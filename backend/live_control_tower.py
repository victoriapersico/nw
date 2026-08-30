
"""Stateful live Control Tower orchestration for the FastAPI demo."""

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from backend.ai.diagnosis import narrate_diagnosis
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
from backend.remediation.audit_store import RemediationAuditStore
from backend.schemas import (
    DetectionRequest,
    DiagnosedIncident,
    InjectionConfig,
    LiveTickResponse,
    Merchant,
    CountryMonitoringMetric,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalRevocationRequest,
    ExecutionRequest,
    ExecutionResult,
    Incident,
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
    SimulationRequest,
    TransactionBatch,
)


LIVE_CHART_WINDOWS = 24
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
        """Apply an injection only to the simulator, then advance two
        windows."""

        with self._lock:
            self._runtime.apply_injection(config)

            # The detector requires two consecutive anomalous time windows.
            self._advance_locked()
            self._advance_locked()

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
            self._ensure_workflow(proposal)
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
                raise ValueError("An approval decision_id cannot be reused with another request.")
            recommendation, incident = self._recommendation(request.recommendation_id)
            if request.merchant != incident.merchant:
                raise PermissionError("The approval merchant does not own this recommendation.")
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
                reviewed_evidence=self._incidents[incident.incident_id].diagnosis.evidence,
                status=status,
            )
            self._approval_decisions[decision.decision_id] = decision
            self._transition_workflow(
                recommendation.recommendation_id,
                status,
                f"Human decision recorded: {status}.",
            )
            self._record_audit(
                event_type="approval_recorded",
                recommendation_id=decision.recommendation_id,
                actor=decision.decided_by,
                detail=f"Human decision recorded: {status}.",
            )
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
                raise PermissionError("The revocation merchant does not own this approval.")
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
                raise PermissionError("The recorded human approval is expired, revoked, or not approved.")
            if workflow.status != "approved":
                raise ValueError("The recommendation is not in an approved workflow state.")
            if recommendation.status != "recommended" or not recommendation.recommended_option_id:
                raise ValueError("This recommendation does not have an eligible selected option.")
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
                raise ValueError("The current routing policy does not permit this simulated change.")
            change = SimulatedRoutingChange(
                change_id=f"change-{uuid4().hex}",
                recommendation_id=recommendation.recommendation_id,
                approval_decision_id=decision.decision_id,
                idempotency_key=request.idempotency_key,
                merchant=incident.merchant,
                country=incident.country,
                target_provider=simulation.option.target_provider,
                traffic_shift_pct=simulation.option.traffic_shift_pct,
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
            if remediation is not None:
                self._ensure_workflow(remediation)
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
                below_rollback_threshold=rate is not None and rate < ROLLBACK_APPROVAL_RATE,
            )
            updated = change.model_copy(update={"monitoring": [*change.monitoring, monitored]})
            self._simulated_changes[change.change_id] = updated
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
        return False

    def _ensure_workflow(self, recommendation: RoutingRecommendation) -> RoutingWorkflow:
        """Create the initial state once a recommendation is visible to an operator."""

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

    def _transition_workflow(
        self,
        recommendation_id: str,
        status: str,
        reason: str,
        *,
        change_id: str | None = None,
    ) -> RoutingWorkflow:
        current = self._workflows[recommendation_id]
        updated = current.model_copy(
            update={
                "status": status,
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
    ) -> None:
        event = RemediationAuditEvent(
                event_id=f"audit-{uuid4().hex}",
                occurred_at=datetime.now(timezone.utc),
                event_type=event_type,
                recommendation_id=recommendation_id,
                change_id=change_id,
                actor=actor,
                detail=detail,
        )
        self._audit_events.append(event)
        self._audit_store.append(event)


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
