
"""Stateful live Control Tower orchestration for the FastAPI demo."""

from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import cast
from uuid import uuid4

from backend.ai.diagnosis import narrate_diagnosis
from backend.ai.incident_assistant import (
    answer_incident_question as answer_question_from_incident,
)
from backend.evaluation.scenarios import (
    DEFAULT_LIVE_VOLUME_PER_WINDOW,
    ScenarioDefinition,
    ScenarioExpectation,
)
from backend.integration.evaluation_runtime import (
    ControlTowerEvaluationRuntime,
    build_runtime,
)
from backend.incidents.engine import IncidentEngine
from backend.incidents.memory_store import IncidentMemoryStore
from backend.remediation.audit_store import RemediationAuditStore
from backend.schemas import (
    DetectionRequest,
    DiagnosedIncident,
    InjectionConfig,
    LiveTickResponse,
    Merchant,
    PaymentMethod,
    CountryMonitoringMetric,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalRevocationRequest,
    Alert,
    DeclineCode,
    DeclineCodePatternEntry,
    Diagnosis,
    ExecutionRequest,
    ExecutionResult,
    Incident,
    IncidentFingerprint,
    IncidentAssistantRequest,
    IncidentAssistantResponse,
    IncidentMemoryCase,
    IncidentMonitoringOutcome,
    IncidentOutcome,
    MerchantMonitoringResponse,
    MerchantIncidentsResponse,
    RoutingRecommendation,
    RemediationAuditEvent,
    RemediationMonitoringWindow,
    SimulatedChangeRequest,
    SimulatedChangeCompletionRequest,
    SimulatedChangeRollbackRequest,
    SimulatedRoutingChange,
    RoutingWorkflow,
    PostIncidentReport,
    Provider,
    SimilarIncident,
    SimulationRequest,
    TransactionBatch,
)


# A five-minute simulator window needs 8,640 observations to retain 30 days.
# The frontend downsamples this data for rendering, so the API can retain a
# useful monthly operational horizon without creating a huge SVG in the browser.
LIVE_HISTORY_DAYS = 30
LIVE_CHART_WINDOWS = LIVE_HISTORY_DAYS * 24 * 12
ROLLBACK_APPROVAL_RATE = 0.80
ROLLBACK_CONSECUTIVE_WINDOWS = 2
APPROVAL_TTL = timedelta(minutes=30)


class LiveControlTower:
    """Owns the demo runtime and exposes safe merchant-scoped results."""

    def __init__(
        self,
        runtime: ControlTowerEvaluationRuntime,
        initial_scenario: ScenarioDefinition,
        audit_store: RemediationAuditStore | None = None,
        incident_memory_store: IncidentMemoryStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._initial_scenario = initial_scenario
        self._incident_engine = IncidentEngine()
        self._lock = RLock()
        self._incidents: dict[str, DiagnosedIncident] = {}
        self._latest_batch: TransactionBatch | None = None
        self._approval_history: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=LIVE_CHART_WINDOWS)
        )
        self._approval_decisions: dict[str, ApprovalDecision] = {}
        self._execution_results: dict[str, ExecutionResult] = {}
        self._simulated_changes: dict[str, SimulatedRoutingChange] = {}
        self._change_ids_by_key: dict[str, str] = {}
        self._workflows: dict[str, RoutingWorkflow] = {}
        self._audit_events: list[RemediationAuditEvent] = []
        self._audit_store = audit_store or RemediationAuditStore()
        self._incident_memory_store = incident_memory_store or IncidentMemoryStore()
        self.reset()

    def reset(self) -> None:
        """Restore the deterministic initial demo state without stale incidents."""

        with self._lock:
            self._runtime.reset(self._initial_scenario)
            self._incidents.clear()
            self._latest_batch = None
            self._approval_history.clear()
            self._approval_decisions.clear()
            self._execution_results.clear()
            self._simulated_changes.clear()
            self._change_ids_by_key.clear()
            self._workflows.clear()
            self._audit_events.clear()

    def latest_batch(self) -> TransactionBatch | None:
        """Return a defensive copy of the latest real simulator batch."""

        with self._lock:
            return (
                self._latest_batch.model_copy(deep=True)
                if self._latest_batch is not None
                else None
            )

    def inject(self, config: InjectionConfig) -> str:
        """Apply an injection only to the simulator, then advance six
        windows."""

        with self._lock:
            self._runtime.apply_injection(config)

            # The detector requires two consecutive anomalous time windows.
            # Stop once it confirms an incident, while allowing narrower,
            # low-volume slices up to six opportunities to cross the threshold.
            for _ in range(6):
                if self._advance_locked().incidents:
                    break

            return f"inj-{uuid4().hex}"

    def tick(self) -> LiveTickResponse:
        """Advance one simulated five-minute monitoring window."""

        with self._lock:
            return self._advance_locked()

    def incidents_for(self, merchant: Merchant) -> MerchantIncidentsResponse:
        """Return active incidents only for the requested merchant."""

        with self._lock:
            diagnosed_incidents = [
                item
                for item in self._incidents.values()
                if item.incident.merchant == merchant
                and item.incident.status == "active"
            ]
            ordered = self._incident_engine.process(
                [item.incident for item in diagnosed_incidents]
            )
            by_id = {
                item.incident.incident_id: item for item in diagnosed_incidents
            }
            return MerchantIncidentsResponse(
                merchant=merchant,
                incidents=[by_id[incident.incident_id] for incident in ordered],
            )

    def answer_incident_question(
        self,
        incident_id: str,
        request: IncidentAssistantRequest,
    ) -> IncidentAssistantResponse:
        """Answer from one defensive incident snapshot without mutating state."""

        with self._lock:
            item = self._incidents.get(incident_id)
            if item is None:
                raise KeyError(incident_id)
            if item.incident.merchant != request.merchant:
                raise PermissionError(
                    "The requested merchant does not own this incident."
                )
            snapshot = item.model_copy(deep=True)

        # Do not hold the Control Tower lock during a potentially slow model call.
        return answer_question_from_incident(snapshot, request.question)

    def simulate_remediation(self, request: SimulationRequest) -> RoutingRecommendation:
        """Re-evaluate an existing incident in dry-run mode only."""

        with self._lock:
            item = self._incidents.get(request.incident_id)
            if item is None or item.incident.merchant != request.merchant:
                raise KeyError(request.incident_id)
            proposal = self._runtime.propose_remediation(item.incident, item.diagnosis)
            if proposal is None:
                raise RuntimeError("Remediation simulation is unavailable.")
            updated = item.model_copy(update={"remediation": proposal})
            self._incidents[item.incident.incident_id] = updated
            self._persist_case(item.incident.incident_id)
            self._register_recommendation(proposal)
            return proposal

    def record_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Store a human decision; it authorizes no provider action by itself."""

        with self._lock:
            existing = next(
                (
                    decision
                    for decision in self._approval_decisions.values()
                    if decision.idempotency_key == request.idempotency_key
                ),
                None,
            )
            if existing is not None:
                return existing.model_copy(deep=True)
            if request.decision_id in self._approval_decisions:
                raise ValueError(
                    "An approval decision_id cannot be reused with another request."
                )
            recommendation, incident = self._recommendation(request.recommendation_id)
            if request.merchant != incident.merchant:
                raise PermissionError(
                    "The approval merchant does not own this recommendation."
                )
            workflow = self._ensure_workflow(recommendation)
            if workflow.status not in ("pending_approval", "approved", "rejected"):
                raise ValueError("A decision cannot be changed after the simulated rollout starts.")
            selected_simulation = next(
                (
                    item
                    for item in recommendation.alternatives
                    if item.option.option_id == recommendation.recommended_option_id
                ),
                None,
            )
            if request.decision == "approved" and (
                recommendation.status != "recommended"
                or selected_simulation is None
                or selected_simulation.status != "eligible"
            ):
                raise ValueError("Only an eligible recommended simulation can be approved.")
            expires_at = request.expires_at or request.decided_at + APPROVAL_TTL
            status = request.decision
            if request.decision == "approved" and expires_at <= datetime.now(timezone.utc):
                status = "expired"
            approval_payload = request.model_dump()
            approval_payload["expires_at"] = expires_at
            decision = ApprovalDecision(
                **approval_payload,
                incident_id=incident.incident_id,
                simulation_option_id=(
                    selected_simulation.option.option_id if selected_simulation else None
                ),
                reviewed_simulation=selected_simulation,
                reviewed_evidence=(
                    self._incidents[incident.incident_id].diagnosis.evidence
                ),
                status=status,
            )
            self._approval_decisions[decision.decision_id] = decision
            self._transition_workflow(
                recommendation.recommendation_id,
                status,
                f"Human decision recorded: {status}.",
                approval_decision_id=decision.decision_id,
            )
            self._record_audit(
                event_type="approval_recorded",
                recommendation_id=decision.recommendation_id,
                actor=decision.decided_by,
                detail=f"Human decision recorded: {status}.",
            )
            self._persist_case(incident.incident_id, decision=decision)
            if decision.status in ("rejected", "expired"):
                self.generate_post_incident_report(incident.incident_id)
            return decision

    def revoke_approval(
        self, decision_id: str, request: ApprovalRevocationRequest
    ) -> ApprovalDecision:
        """Revoke a still-pending approved decision before a simulation is activated."""

        with self._lock:
            decision = self._approval_decisions.get(decision_id)
            if decision is None:
                raise KeyError(decision_id)
            workflow = self._workflows[decision.recommendation_id]
            if request.merchant != decision.merchant:
                raise PermissionError(
                    "The revocation merchant does not own this approval."
                )
            if decision.status == "revoked":
                return decision.model_copy(deep=True)
            if decision.status != "approved" or workflow.status != "approved":
                raise ValueError("Only a current approved decision can be revoked.")
            revoked = decision.model_copy(update={"status": "revoked"})
            self._approval_decisions[decision_id] = revoked
            self._transition_workflow(
                revoked.recommendation_id,
                "revoked",
                request.reason,
            )
            self._record_audit(
                event_type="approval_revoked",
                recommendation_id=revoked.recommendation_id,
                actor=request.revoked_by,
                detail=request.reason,
            )
            self._persist_case(revoked.incident_id, decision=revoked)
            self.generate_post_incident_report(revoked.incident_id)
            return revoked.model_copy(deep=True)

    def request_execution(self, request: ExecutionRequest) -> ExecutionResult:
        """Return a safe dry-run or denial; POST-01 never contacts providers."""

        with self._lock:
            existing = self._execution_results.get(request.idempotency_key)
            if existing is not None:
                return existing
            decision = self._approval_decisions.get(request.approval_decision_id)
            if decision is None or decision.recommendation_id != request.recommendation_id:
                reason = "Execution denied: an explicit matching approval is required."
                status = "denied"
            elif not self._approval_is_valid(decision):
                reason = "Execution denied: the recorded approval is not current and valid."
                status = "denied"
            elif request.dry_run:
                reason = "Dry-run completed. No provider credentials or routing tools exist in POST-01."
                status = "dry_run"
            else:
                reason = "Execution denied: provider routing is disabled in this recommendation-only MVP."
                status = "denied"
            result = ExecutionResult(
                execution_id=f"exec-{uuid4().hex}",
                recommendation_id=request.recommendation_id,
                idempotency_key=request.idempotency_key,
                status=status,
                reason=reason,
            )
            self._execution_results[request.idempotency_key] = result
            return result

    def apply_simulated_change(self, request: SimulatedChangeRequest) -> SimulatedRoutingChange:
        """Activate an approved route proposal in local state, never at a provider."""

        with self._lock:
            existing_id = self._change_ids_by_key.get(request.idempotency_key)
            if existing_id is not None:
                return self._simulated_changes[existing_id].model_copy(deep=True)
            recommendation, incident = self._recommendation(request.recommendation_id)
            workflow = self._ensure_workflow(recommendation)
            decision = self._approval_decisions.get(request.approval_decision_id)
            if decision is None or decision.recommendation_id != recommendation.recommendation_id:
                raise PermissionError("A matching human approval is required.")
            if not self._approval_is_valid(decision):
                raise PermissionError(
                    "The recorded human approval is expired, revoked, or not approved."
                )
            if workflow.status != "approved":
                raise ValueError("The recommendation is not in an approved workflow state.")
            if recommendation.status != "recommended" or not recommendation.recommended_option_id:
                raise ValueError("This recommendation does not have an eligible selected option.")
            if recommendation.proposed_traffic_cap is None:
                raise ValueError("The recommendation does not include a proposed traffic cap.")
            if request.rollback_reference != recommendation.rollback_reference:
                raise ValueError("The rollback reference does not match the recommendation.")
            simulation = next(
                (
                    item
                    for item in recommendation.alternatives
                    if item.option.option_id == recommendation.recommended_option_id
                    and item.status == "eligible"
                ),
                None,
            )
            if simulation is None:
                raise ValueError("The selected simulation is no longer eligible.")
            if simulation.option.traffic_shift_pct != recommendation.proposed_traffic_cap:
                raise ValueError(
                    "The selected simulation does not match the recommended traffic cap."
                )
            policy = self._runtime.routing_policy(recommendation.policy_id)
            if (
                policy is None
                or policy.merchant != incident.merchant
                or policy.country != incident.country
                or simulation.option.target_provider not in policy.eligible_target_providers
                or simulation.option.traffic_shift_pct > policy.max_traffic_shift_pct
                or not policy.dry_run_only
                or policy.execution_enabled
            ):
                raise ValueError(
                    "The current routing policy does not permit this simulated change."
                )
            change = SimulatedRoutingChange(
                change_id=f"change-{uuid4().hex}",
                recommendation_id=recommendation.recommendation_id,
                approval_decision_id=decision.decision_id,
                idempotency_key=request.idempotency_key,
                merchant=incident.merchant,
                country=incident.country,
                target_provider=simulation.option.target_provider,
                traffic_shift_pct=simulation.option.traffic_shift_pct,
                before_approval_rate=incident.actual_conversion,
                expected_approval_rate=simulation.expected_approval_rate,
                expected_recovered_value_per_hour=(
                    simulation.expected_recovered_value_per_hour
                ),
                status="simulated_active",
                applied_at=datetime.now(timezone.utc),
                rollback_reference=request.rollback_reference,
            )
            self._simulated_changes[change.change_id] = change
            self._change_ids_by_key[request.idempotency_key] = change.change_id
            self._transition_workflow(
                change.recommendation_id,
                "simulated_active",
                "Approved simulated change is active; no provider was contacted.",
                change_id=change.change_id,
            )
            self._record_audit(
                event_type="simulated_change_applied",
                recommendation_id=change.recommendation_id,
                change_id=change.change_id,
                actor=decision.decided_by,
                detail=(
                    f"Simulated {change.traffic_shift_pct:.0%} shift to "
                    f"{change.target_provider}; no provider was contacted."
                ),
            )
            self._persist_case(incident.incident_id, change=change)
            return change.model_copy(deep=True)

    def rollback_simulated_change(
        self, change_id: str, request: SimulatedChangeRollbackRequest
    ) -> SimulatedRoutingChange:
        """Record a human rollback; no external routing is ever changed."""

        with self._lock:
            change = self._simulated_changes.get(change_id)
            if change is None:
                raise KeyError(change_id)
            if change.status == "rolled_back":
                return change.model_copy(deep=True)
            if change.status != "simulated_active":
                raise ValueError("Only an active simulated change can be rolled back.")
            return self._rollback_change(change, request.reason, request.decided_by)

    def complete_simulated_change(
        self, change_id: str, request: SimulatedChangeCompletionRequest
    ) -> SimulatedRoutingChange:
        """Close a healthy local simulation; production routing remains unchanged."""

        with self._lock:
            change = self._simulated_changes.get(change_id)
            if change is None:
                raise KeyError(change_id)
            if change.status != "simulated_active":
                raise ValueError("Only an active simulated change can be completed.")
            completed = change.model_copy(update={"status": "completed"})
            self._simulated_changes[change.change_id] = completed
            self._transition_workflow(
                completed.recommendation_id,
                "completed",
                request.note,
                change_id=completed.change_id,
            )
            self._record_audit(
                event_type="simulated_change_completed",
                recommendation_id=completed.recommendation_id,
                change_id=completed.change_id,
                actor=request.decided_by,
                detail=request.note,
            )
            self._persist_case_for_recommendation(completed.recommendation_id, change=completed)
            self.generate_post_incident_report(
                self._workflows[completed.recommendation_id].incident_id
            )
            return completed.model_copy(deep=True)

    def simulated_change(self, change_id: str) -> SimulatedRoutingChange:
        with self._lock:
            change = self._simulated_changes.get(change_id)
            if change is None:
                raise KeyError(change_id)
            return change.model_copy(deep=True)

    def workflow(self, recommendation_id: str) -> RoutingWorkflow:
        with self._lock:
            workflow = self._workflows.get(recommendation_id)
            if workflow is None:
                recommendation, _ = self._recommendation(recommendation_id)
                workflow = self._ensure_workflow(recommendation)
            return workflow.model_copy(deep=True)

    def remediation_audit(self, recommendation_id: str | None = None) -> list[RemediationAuditEvent]:
        with self._lock:
            return self._audit_store.events(recommendation_id)

    def alerts(self, acknowledged: bool | None = None) -> list[Alert]:
        """Return the durable local notification inbox."""

        with self._lock:
            return self._incident_memory_store.alerts(acknowledged)

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> Alert:
        with self._lock:
            return self._incident_memory_store.acknowledge_alert(alert_id, acknowledged_by)

    def similar_incidents(self, incident_id: str) -> list[SimilarIncident]:
        """Find only exact merchant/country/provider/method/code-pattern matches."""

        with self._lock:
            case = self._incident_memory_store.case(incident_id)
            if case is None:
                raise KeyError(incident_id)
            return [
                self._similar_incident(item)
                for item in self._incident_memory_store.similar_cases(
                    case.fingerprint, exclude_incident_id=incident_id
                )
            ]

    def generate_post_incident_report(self, incident_id: str) -> PostIncidentReport:
        """Persist a deterministic report; no LLM-authored operational facts."""

        with self._lock:
            case = self._incident_memory_store.case(incident_id)
            if case is None:
                raise KeyError(incident_id)
            recommendation_id = (
                case.remediation.recommendation_id if case.remediation else None
            )
            audit_trail = (
                self._audit_store.events(recommendation_id)
                if recommendation_id is not None
                else []
            )
            similar_cases = [
                self._similar_incident(item)
                for item in self._incident_memory_store.similar_cases(
                    case.fingerprint, exclude_incident_id=incident_id
                )
            ]
            outcome = self._case_outcome(case)
            monitoring_outcome = self._monitoring_outcome(case)
            existing = self._incident_memory_store.report(incident_id)
            report = PostIncidentReport(
                report_id=(
                    existing.report_id if existing is not None else f"report-{uuid4().hex}"
                ),
                incident_id=incident_id,
                generated_at=datetime.now(timezone.utc),
                summary=self._report_summary(
                    case,
                    outcome=outcome,
                    monitoring_outcome=monitoring_outcome,
                    similar_case_count=len(similar_cases),
                ),
                incident=case.incident,
                diagnosis=case.diagnosis,
                recommendation=case.remediation,
                evidence=case.diagnosis.evidence,
                decision=case.decision,
                change=case.change,
                outcome=outcome,
                monitoring_outcome=monitoring_outcome,
                recurrence_detected=bool(similar_cases),
                audit_trail=audit_trail,
                similar_cases=similar_cases,
            )
            self._incident_memory_store.save_report(report)
            return report

    def post_incident_report(self, incident_id: str) -> PostIncidentReport:
        with self._lock:
            report = self._incident_memory_store.report(incident_id)
            if report is None:
                raise KeyError(incident_id)
            return report

    def monitoring_for(self, merchant: Merchant) -> MerchantMonitoringResponse:
        """Return measured simulator metrics for the latest live window."""

        with self._lock:
            if self._latest_batch is None:
                self._advance_locked()
            assert self._latest_batch is not None
            batch = self._latest_batch
            countries: list[CountryMonitoringMetric] = []
            total_attempts = 0
            total_approved = 0
            total_expected_approved = 0.0

            for country in ("Mexico", "Brazil", "Colombia"):
                transactions = [
                    transaction
                    for transaction in batch.transactions
                    if transaction.merchant == merchant and transaction.country == country
                ]
                attempts = len(transactions)
                if not attempts:
                    continue
                approved = sum(
                    transaction.status == "approved" for transaction in transactions
                )
                actual_rate = approved / attempts
                expected_rate = self._runtime.expected_approval_rate(
                    merchant, country, batch.window_start
                )
                expected_rate = actual_rate if expected_rate is None else expected_rate
                countries.append(
                    CountryMonitoringMetric(
                        country=country,
                        actual_approval_rate=actual_rate,
                        expected_approval_rate=expected_rate,
                        attempted_transactions=attempts,
                        approval_history=list(self._approval_history[(merchant, country)]),
                    )
                )
                total_attempts += attempts
                total_approved += approved
                total_expected_approved += expected_rate * attempts

            return MerchantMonitoringResponse(
                merchant=merchant,
                window_start=batch.window_start,
                window_end=batch.window_end,
                actual_approval_rate=total_approved / total_attempts,
                expected_approval_rate=total_expected_approved / total_attempts,
                attempted_transactions=total_attempts,
                countries=countries,
            )

    def _advance_locked(self) -> LiveTickResponse:
        batch = self._runtime.next_batch()
        self._latest_batch = batch.model_copy(deep=True)
        self._monitor_simulated_changes(batch)
        for merchant in ("Rappi", "Carrefour", "Despegar"):
            for country in ("Mexico", "Brazil", "Colombia"):
                outcomes = [
                    transaction.status == "approved"
                    for transaction in batch.transactions
                    if transaction.merchant == merchant and transaction.country == country
                ]
                if outcomes:
                    self._approval_history[(merchant, country)].append(
                        sum(outcomes) / len(outcomes)
                    )
        detection = self._runtime.detect(DetectionRequest(batch=batch))

        diagnosed_incidents = []
        for incident in self._incident_engine.process(detection.incidents):
            diagnosis = narrate_diagnosis(self._runtime.diagnose(incident))
            propose_remediation = getattr(self._runtime, "propose_remediation", None)
            remediation = (
                propose_remediation(incident, diagnosis)
                if callable(propose_remediation)
                else None
            )
            diagnosed = DiagnosedIncident(
                incident=incident,
                diagnosis=diagnosis,
                remediation=remediation,
            )
            self._incidents[incident.incident_id] = diagnosed
            self._store_detected_incident(diagnosed, batch)
            self._incident_memory_store.create_alert(
                alert_type="incident_detected",
                dedupe_key=f"incident_detected:{incident.incident_id}",
                incident_id=incident.incident_id,
                payload={
                    "merchant": incident.merchant,
                    "country": incident.country,
                    "severity": incident.severity,
                },
            )
            if remediation is not None:
                self._register_recommendation(remediation)
            diagnosed_incidents.append(diagnosed)

        return LiveTickResponse(
            window_start=batch.window_start,
            window_end=batch.window_end,
            incidents=diagnosed_incidents,
        )

    def _recommendation(
        self, recommendation_id: str
    ) -> tuple[RoutingRecommendation, Incident]:
        for item in self._incidents.values():
            if item.remediation and item.remediation.recommendation_id == recommendation_id:
                return item.remediation, item.incident
        raise KeyError(recommendation_id)

    def _monitor_simulated_changes(self, batch: TransactionBatch) -> None:
        """Observe target-route health and safely close a local simulation if it degrades."""

        for change in list(self._simulated_changes.values()):
            if change.status != "simulated_active":
                continue
            target = [
                transaction
                for transaction in batch.transactions
                if transaction.merchant == change.merchant
                and transaction.country == change.country
                and transaction.provider == change.target_provider
            ]
            attempts = len(target)
            rate = sum(item.status == "approved" for item in target) / attempts if attempts else None
            monitored = RemediationMonitoringWindow(
                window_start=batch.window_start,
                window_end=batch.window_end,
                attempted_transactions=attempts,
                approval_rate=rate,
                error_rate=1 - rate if rate is not None else None,
                below_rollback_threshold=rate is not None and rate < ROLLBACK_APPROVAL_RATE,
            )
            updated = change.model_copy(update={"monitoring": [*change.monitoring, monitored]})
            self._simulated_changes[change.change_id] = updated
            self._persist_case_for_recommendation(change.recommendation_id, change=updated)
            self._record_audit(
                event_type="target_route_monitored",
                recommendation_id=change.recommendation_id,
                change_id=change.change_id,
                actor="system",
                detail=(
                    "Target route monitoring recorded "
                    f"{rate:.1%}." if rate is not None else "No target-route samples in this window."
                ),
            )
            recent = updated.monitoring[-ROLLBACK_CONSECUTIVE_WINDOWS:]
            if (
                len(recent) == ROLLBACK_CONSECUTIVE_WINDOWS
                and all(item.below_rollback_threshold for item in recent)
            ):
                self._rollback_change(
                    updated,
                    "Automatic simulated rollback: target approval rate was below 80% for two consecutive windows.",
                    "system",
                )

    def _rollback_change(
        self, change: SimulatedRoutingChange, reason: str, actor: str
    ) -> SimulatedRoutingChange:
        rolled_back = change.model_copy(
            update={"status": "rolled_back", "rollback_reason": reason}
        )
        self._simulated_changes[change.change_id] = rolled_back
        self._transition_workflow(
            rolled_back.recommendation_id,
            "rolled_back",
            reason,
            change_id=rolled_back.change_id,
        )
        self._record_audit(
            event_type="simulated_change_rolled_back",
            recommendation_id=change.recommendation_id,
            change_id=change.change_id,
            actor=actor,
            detail=reason,
        )
        self._persist_case_for_recommendation(rolled_back.recommendation_id, change=rolled_back)
        self._incident_memory_store.create_alert(
            alert_type="rollback_triggered",
            dedupe_key=f"rollback_triggered:{rolled_back.change_id}",
            incident_id=self._workflows[rolled_back.recommendation_id].incident_id,
            recommendation_id=rolled_back.recommendation_id,
            change_id=rolled_back.change_id,
            payload={"reason": reason, "actor": actor},
        )
        self.generate_post_incident_report(
            self._workflows[rolled_back.recommendation_id].incident_id
        )
        return rolled_back.model_copy(deep=True)

    def _approval_is_valid(self, decision: ApprovalDecision) -> bool:
        if decision.status != "approved":
            return False
        if decision.expires_at is None or decision.expires_at > datetime.now(timezone.utc):
            return True
        expired = decision.model_copy(update={"status": "expired"})
        self._approval_decisions[decision.decision_id] = expired
        self._transition_workflow(
            expired.recommendation_id,
            "expired",
            "Approval expired before the simulated change was activated.",
        )
        self._record_audit(
            event_type="approval_expired",
            recommendation_id=expired.recommendation_id,
            actor="system",
            detail="Approval status changed to expired.",
        )
        self._persist_case(expired.incident_id, decision=expired)
        self.generate_post_incident_report(expired.incident_id)
        return False

    def _ensure_workflow(self, recommendation: RoutingRecommendation) -> RoutingWorkflow:
        """Create the initial state once a recommendation is visible to an operator."""

        if recommendation.status != "recommended" or not recommendation.recommended_option_id:
            raise ValueError("A no-action recommendation cannot enter approval workflow.")
        existing = self._workflows.get(recommendation.recommendation_id)
        if existing is not None:
            return existing
        workflow = RoutingWorkflow(
            recommendation_id=recommendation.recommendation_id,
            incident_id=recommendation.incident_id,
            status="pending_approval",
            updated_at=datetime.now(timezone.utc),
            transition_reason="Recommendation is awaiting merchant-operations approval.",
        )
        self._workflows[recommendation.recommendation_id] = workflow
        return workflow

    def _register_recommendation(
        self, recommendation: RoutingRecommendation
    ) -> RoutingWorkflow | None:
        """Audit every agent result and open approval only for an eligible action."""

        already_audited = any(
            event.event_type == "recommendation_created"
            and event.recommendation_id == recommendation.recommendation_id
            for event in self._audit_events
        )
        if not already_audited:
            self._record_audit(
                event_type="recommendation_created",
                recommendation_id=recommendation.recommendation_id,
                actor="routing-recommendation-agent",
                detail=(
                    "Routing recommendation is ready for human review."
                    if recommendation.status == "recommended"
                    else "The routing agent abstained; monitoring remains active."
                ),
                recommendation=recommendation,
            )
        if recommendation.status != "recommended":
            return None
        workflow = self._ensure_workflow(recommendation)
        self._incident_memory_store.create_alert(
            alert_type="approval_required",
            dedupe_key=f"approval_required:{recommendation.recommendation_id}",
            incident_id=recommendation.incident_id,
            recommendation_id=recommendation.recommendation_id,
            payload={
                "merchant": self._incidents[recommendation.incident_id].incident.merchant,
                "required_approval": recommendation.required_approval,
            },
        )
        return workflow

    def _transition_workflow(
        self,
        recommendation_id: str,
        status: str,
        reason: str,
        *,
        approval_decision_id: str | None = None,
        change_id: str | None = None,
    ) -> RoutingWorkflow:
        current = self._workflows[recommendation_id]
        updated = current.model_copy(
            update={
                "status": status,
                "approval_decision_id": (
                    approval_decision_id
                    if approval_decision_id is not None
                    else current.approval_decision_id
                ),
                "change_id": change_id if change_id is not None else current.change_id,
                "updated_at": datetime.now(timezone.utc),
                "transition_reason": reason,
            }
        )
        self._workflows[recommendation_id] = updated
        return updated

    def _record_audit(
        self,
        *,
        event_type: str,
        recommendation_id: str,
        actor: str,
        detail: str,
        change_id: str | None = None,
        recommendation: RoutingRecommendation | None = None,
    ) -> None:
        event = RemediationAuditEvent(
            event_id=f"audit-{uuid4().hex}",
            occurred_at=datetime.now(timezone.utc),
            event_type=event_type,
            recommendation_id=recommendation_id,
            change_id=change_id,
            actor=actor,
            detail=detail,
            recommendation=recommendation,
        )
        self._audit_events.append(event)
        self._audit_store.append(event)

    def _store_detected_incident(
        self, diagnosed: DiagnosedIncident, batch: TransactionBatch
    ) -> None:
        self._incident_memory_store.upsert_case(
            IncidentMemoryCase(
                incident=diagnosed.incident,
                diagnosis=diagnosed.diagnosis,
                remediation=diagnosed.remediation,
                fingerprint=self._fingerprint(
                    diagnosed.incident, diagnosed.diagnosis, batch
                ),
            )
        )

    def _persist_case(
        self,
        incident_id: str,
        *,
        decision: ApprovalDecision | None = None,
        change: SimulatedRoutingChange | None = None,
    ) -> None:
        current = self._incident_memory_store.case(incident_id)
        live = self._incidents.get(incident_id)
        if current is None or live is None:
            return
        self._incident_memory_store.upsert_case(
            current.model_copy(
                update={
                    "incident": live.incident,
                    "diagnosis": live.diagnosis,
                    "remediation": live.remediation,
                    "decision": decision if decision is not None else current.decision,
                    "change": change if change is not None else current.change,
                }
            )
        )

    def _persist_case_for_recommendation(
        self,
        recommendation_id: str,
        *,
        change: SimulatedRoutingChange | None = None,
    ) -> None:
        _, incident = self._recommendation(recommendation_id)
        self._persist_case(incident.incident_id, change=change)

    @staticmethod
    def _fingerprint(
        incident: Incident, diagnosis: Diagnosis, batch: TransactionBatch
    ) -> IncidentFingerprint:
        declined = [
            transaction
            for transaction in batch.transactions
            if transaction.merchant == incident.merchant
            and transaction.country == incident.country
            and transaction.status == "declined"
        ]
        scopes = Counter((item.provider, item.payment_method) for item in declined)
        if not scopes:
            return IncidentFingerprint(merchant=incident.merchant, country=incident.country)
        fallback_provider, fallback_payment_method = min(
            scopes, key=lambda item: (-scopes[item], item[0], item[1])
        )
        provider = cast(
            Provider,
            next(
                (
                    item.value
                    for item in diagnosis.evidence
                    if item.dimension == "provider"
                    and item.value in ("Stripe", "Adyen", "dLocal")
                ),
                fallback_provider,
            ),
        )
        payment_method = cast(
            PaymentMethod,
            next(
                (
                    item.value
                    for item in diagnosis.evidence
                    if item.dimension == "payment_method"
                    and item.value in ("CARD", "PIX", "PSE", "OXXO")
                ),
                fallback_payment_method,
            ),
        )
        supported_decline_codes = {
            item.value
            for item in diagnosis.evidence
            if item.dimension == "decline_code"
            and item.value in ("05", "51", "54", "57", "61", "91", "96")
        }
        codes = Counter(
            item.decline_code
            for item in declined
            if item.provider == provider and item.payment_method == payment_method
            and item.decline_code in supported_decline_codes
        )
        pattern = [
            DeclineCodePatternEntry(
                code=cast(DeclineCode, code), decline_count=count
            )
            for code, count in sorted(codes.items(), key=lambda item: (-item[1], item[0]))
        ]
        return IncidentFingerprint(
            merchant=incident.merchant,
            country=incident.country,
            provider=provider,
            payment_method=payment_method,
            decline_pattern=pattern,
        )

    @staticmethod
    def _case_outcome(case: IncidentMemoryCase) -> IncidentOutcome:
        if case.change is not None and case.change.status == "rolled_back":
            return "rolled_back"
        if case.change is not None and case.change.status == "completed":
            return "completed"
        if case.decision is not None:
            return case.decision.status
        return "open"

    @staticmethod
    def _monitoring_outcome(case: IncidentMemoryCase) -> IncidentMonitoringOutcome:
        change = case.change
        if change is None:
            return IncidentMonitoringOutcome()
        observed = [
            window
            for window in change.monitoring
            if window.approval_rate is not None and window.attempted_transactions > 0
        ]
        observed_attempts = sum(window.attempted_transactions for window in observed)
        observed_approval_rate = (
            sum(
                window.approval_rate * window.attempted_transactions
                for window in observed
                if window.approval_rate is not None
            )
            / observed_attempts
            if observed_attempts
            else None
        )
        return IncidentMonitoringOutcome(
            status=change.status,
            expected_approval_rate=change.expected_approval_rate,
            observed_approval_rate=observed_approval_rate,
            observed_windows=len(change.monitoring),
            observed_attempts=observed_attempts,
            rollback_reason=change.rollback_reason,
        )

    @staticmethod
    def _report_summary(
        case: IncidentMemoryCase,
        *,
        outcome: IncidentOutcome,
        monitoring_outcome: IncidentMonitoringOutcome,
        similar_case_count: int,
    ) -> str:
        incident = case.incident
        recommendation = case.remediation
        decision = case.decision
        recurrence = (
            f" This exact incident fingerprint occurred {similar_case_count} time(s) before."
            if similar_case_count
            else " No prior exact incident fingerprint was found."
        )
        recommendation_text = (
            f" Recommendation {recommendation.recommendation_id} was "
            f"{recommendation.status}."
            if recommendation is not None
            else " No routing recommendation was recorded."
        )
        decision_text = (
            f" Human decision by {decision.decided_by}: {decision.status}."
            if decision is not None
            else " No human decision was recorded."
        )
        if monitoring_outcome.status == "not_simulated":
            monitoring_text = " No simulated monitoring result was recorded."
        else:
            expected = (
                f"{monitoring_outcome.expected_approval_rate:.1%}"
                if monitoring_outcome.expected_approval_rate is not None
                else "unavailable"
            )
            observed = (
                f"{monitoring_outcome.observed_approval_rate:.1%}"
                if monitoring_outcome.observed_approval_rate is not None
                else "unavailable"
            )
            monitoring_text = (
                f" Simulated monitoring ended as {monitoring_outcome.status} after "
                f"{monitoring_outcome.observed_windows} window(s): expected approval "
                f"{expected}, observed {observed}."
            )
        return (
            f"{incident.severity.title()} incident for {incident.merchant} in "
            f"{incident.country}: approval conversion was "
            f"{incident.actual_conversion:.1%} versus "
            f"{incident.expected_conversion:.1%} expected. Estimated loss was "
            f"{incident.estimated_loss:.2f} in the detected window and "
            f"{incident.estimated_loss_per_hour:.2f} per hour."
            f"{recurrence}{recommendation_text}{decision_text}{monitoring_text} "
            f"Recorded outcome: {outcome}."
        )

    def _similar_incident(self, case: IncidentMemoryCase) -> SimilarIncident:
        return SimilarIncident(
            incident_id=case.incident.incident_id,
            detected_at=case.incident.detected_at,
            severity=case.incident.severity,
            estimated_loss=case.incident.estimated_loss,
            estimated_loss_per_hour=case.incident.estimated_loss_per_hour,
            recommendation=case.remediation,
            decision=case.decision,
            monitoring_outcome=self._monitoring_outcome(case),
            outcome=self._case_outcome(case),
        )


def build_live_control_tower() -> LiveControlTower:
    """Build the default accelerated demo runtime from local history."""

    runtime = build_runtime()
    initial_scenario = ScenarioDefinition(
        scenario_id=0,
        name="Live Control Tower demo",
        seed=20_260,
        start_at=datetime(2025, 9, 2, 13, tzinfo=timezone.utc),
        expectation=ScenarioExpectation(outcome="no_alert"),
        volume_per_window=DEFAULT_LIVE_VOLUME_PER_WINDOW,
    )
    return LiveControlTower(runtime, initial_scenario)
