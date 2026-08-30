"""Pydantic contracts shared by every Control Tower track and the API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Frozen MVP-00 domain vocabulary.  Other modules must import these values rather
# than defining their own spellings or country/method mappings.
Merchant = Literal["Rappi", "Carrefour", "Despegar"]
Country = Literal["Mexico", "Brazil", "Colombia"]
Provider = Literal["Stripe", "Adyen", "dLocal"]
PaymentMethod = Literal["CARD", "PIX", "PSE", "OXXO"]
DeclineCode = Literal["05", "51", "54", "57", "61", "91", "96"]
TransactionStatus = Literal["approved", "declined"]
Severity = Literal["low", "medium", "high", "critical"]
IncidentStatus = Literal["active", "resolved"]
DiagnosisStatus = Literal["confirmed", "insufficient_evidence"]
AlertType = Literal["incident_detected", "approval_required", "rollback_triggered"]
IncidentOutcome = Literal[
    "open",
    "approved",
    "rejected",
    "expired",
    "revoked",
    "rolled_back",
    "completed",
]
EvidenceDimension = Literal[
    "merchant",
    "country",
    "provider",
    "payment_method",
    "issuing_bank",
    "decline_code",
    "intersection",
]


COUNTRY_PAYMENT_METHODS: dict[str, frozenset[str]] = {
    "Mexico": frozenset({"CARD", "OXXO"}),
    "Brazil": frozenset({"CARD", "PIX"}),
    "Colombia": frozenset({"CARD", "PSE"}),
}

COUNTRY_ISSUING_BANKS: dict[str, frozenset[str]] = {
    "Mexico": frozenset(
        {"BBVA México", "Banorte", "Santander México", "Citibanamex"}
    ),
    "Brazil": frozenset({"Itaú", "Bradesco", "Banco do Brasil", "Nubank"}),
    "Colombia": frozenset(
        {"Bancolombia", "Davivienda", "Banco de Bogotá", "BBVA Colombia"}
    ),
}


class Transaction(BaseModel):
    """One attempted payment, the sole input delivered to the detector."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1, max_length=128)
    merchant: Merchant
    provider: Provider
    payment_method: PaymentMethod
    country: Country
    issuing_bank: str = Field(min_length=1, max_length=128)
    decline_code: DeclineCode | None = None
    status: TransactionStatus
    amount: float = Field(gt=0, le=1_000_000)
    timestamp: datetime

    @model_validator(mode="after")
    def validate_payment_domain(self) -> "Transaction":
        if self.payment_method not in COUNTRY_PAYMENT_METHODS[self.country]:
            raise ValueError(
                f"payment_method '{self.payment_method}' is not valid for {self.country}"
            )
        if self.issuing_bank not in COUNTRY_ISSUING_BANKS[self.country]:
            raise ValueError(
                f"issuing_bank '{self.issuing_bank}' is not valid for {self.country}"
            )
        if self.status == "approved" and self.decline_code is not None:
            raise ValueError("approved transactions must have decline_code = null")
        if self.status == "declined" and self.decline_code is None:
            raise ValueError("declined transactions must include a decline_code")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a timezone offset")
        return self


class Incident(BaseModel):
    """A detected conversion degradation for one merchant and country."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1, max_length=128)
    merchant: Merchant
    country: Country
    detected_at: datetime
    expected_conversion: float = Field(ge=0, le=1)
    actual_conversion: float = Field(ge=0, le=1)
    conversion_drop_pp: float = Field(ge=0, le=100)
    affected_volume: int = Field(ge=0)
    estimated_loss: float = Field(default=0, ge=0)
    estimated_loss_per_hour: float = Field(default=0, ge=0)
    severity: Severity
    anomaly_score: float
    status: IncidentStatus = "active"


class EvidenceItem(BaseModel):
    """One deterministic slice comparison supplied to the diagnosis layer."""

    model_config = ConfigDict(extra="forbid")

    dimension: EvidenceDimension
    value: str = Field(min_length=1, max_length=256)
    baseline_metric: float = Field(ge=0, le=1)
    live_metric: float = Field(ge=0, le=1)
    delta: float
    sample_size: int = Field(ge=0)
    explained_loss_share: float = Field(ge=0, le=1)


class Diagnosis(BaseModel):
    """Structured diagnosis: calculated evidence first, language generation second."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1, max_length=128)
    root_cause_dimensions: list[EvidenceDimension] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    diagnosis_status: DiagnosisStatus
    explanation: str = Field(min_length=1, max_length=2_000)
    recommended_action: str = Field(min_length=1, max_length=1_000)


class InjectionConfig(BaseModel):
    """Judge-controlled change applied only to future generated transactions."""

    model_config = ConfigDict(extra="forbid")

    merchant: Merchant
    country: Country
    provider: Provider | None = None
    payment_method: PaymentMethod | None = None
    issuing_bank: str | None = Field(default=None, min_length=1, max_length=128)
    decline_code: DeclineCode | None = None
    target_approval_rate: float = Field(ge=0, le=1)
    duration_windows: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_injection_filters(self) -> "InjectionConfig":
        if (
            self.payment_method is not None
            and self.payment_method not in COUNTRY_PAYMENT_METHODS[self.country]
        ):
            raise ValueError(
                f"payment_method '{self.payment_method}' is not valid for {self.country}"
            )
        if (
            self.issuing_bank is not None
            and self.issuing_bank not in COUNTRY_ISSUING_BANKS[self.country]
        ):
            raise ValueError(
                f"issuing_bank '{self.issuing_bank}' is not valid for {self.country}"
            )
        return self


class TransactionBatch(BaseModel):
    """The simulator-to-detector payload; it intentionally excludes InjectionConfig."""

    model_config = ConfigDict(extra="forbid")

    window_start: datetime
    window_end: datetime
    transactions: list[Transaction] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_window(self) -> "TransactionBatch":
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


class CreateInjectionRequest(BaseModel):
    """API payload used to ask the simulator to start an injection."""

    model_config = ConfigDict(extra="forbid")

    config: InjectionConfig


class CreateInjectionResponse(BaseModel):
    """Acknowledgement returned by the simulator without exposing it to the detector."""

    model_config = ConfigDict(extra="forbid")

    injection_id: str = Field(min_length=1, max_length=128)
    status: Literal["scheduled", "active"]


class DetectionRequest(BaseModel):
    """API payload handed to the detector; configuration never crosses this boundary."""

    model_config = ConfigDict(extra="forbid")

    batch: TransactionBatch


class DetectionResponse(BaseModel):
    """Deterministic detector output for one simulated transaction batch."""

    model_config = ConfigDict(extra="forbid")

    incidents: list[Incident] = Field(default_factory=list)


class DiagnosisResponse(BaseModel):
    """API response after root-cause analysis of an incident."""

    model_config = ConfigDict(extra="forbid")

    diagnosis: Diagnosis


class RoutingPolicy(BaseModel):
    """Explicit per-merchant limits used before any recommendation is produced."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1, max_length=128)
    merchant: Merchant
    country: Country
    payment_method: PaymentMethod | None = None
    eligible_target_providers: list[Provider] = Field(min_length=1)
    max_traffic_shift_pct: float = Field(gt=0, le=1, default=0.50)
    dry_run_only: bool = True
    execution_enabled: bool = False


class RemediationOption(BaseModel):
    """A bounded, human-approvable traffic-shift alternative."""

    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=128)
    target_provider: Provider
    traffic_shift_pct: float = Field(gt=0, le=1)


class SimulationRequest(BaseModel):
    """Ask to re-evaluate an already-detected incident; no raw route controls."""

    model_config = ConfigDict(extra="forbid")

    merchant: Merchant
    incident_id: str = Field(min_length=1, max_length=128)
    dry_run: Literal[True] = True
    idempotency_key: str = Field(min_length=8, max_length=128)


class SimulationResult(BaseModel):
    """Deterministic estimate for one possible remediation; never an execution."""

    model_config = ConfigDict(extra="forbid")

    option: RemediationOption
    status: Literal["eligible", "blocked", "inconclusive"]
    expected_approval_rate: float | None = Field(default=None, ge=0, le=1)
    expected_recovered_value_per_hour: float = Field(ge=0)
    expected_incremental_cost_per_hour: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    rejection_reason: str | None = Field(default=None, max_length=500)


class RoutingRecommendation(BaseModel):
    """Read-only recommendation produced from deterministic simulations."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(min_length=1, max_length=128)
    incident_id: str = Field(min_length=1, max_length=128)
    policy_id: str = Field(min_length=1, max_length=128)
    status: Literal["recommended", "not_recommended"]
    recommended_option_id: str | None = Field(default=None, max_length=128)
    alternatives: list[SimulationResult] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(default=0.0, ge=0, le=1)
    proposed_traffic_cap: float | None = Field(default=None, gt=0, le=1)
    abstention_reason: str | None = Field(default=None, max_length=1_000)
    rollback_condition: str | None = Field(default=None, max_length=1_000)
    rollback_reference: str | None = Field(default=None, max_length=128)
    required_approval: Literal["merchant_operations"] = "merchant_operations"
    dry_run: Literal[True] = True


class ApprovalRequest(BaseModel):
    """Human input for a recommendation; linked evidence is derived server-side."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1, max_length=128)
    recommendation_id: str = Field(min_length=1, max_length=128)
    merchant: Merchant
    decision: Literal["approved", "rejected"]
    decided_by: str = Field(min_length=1, max_length=128)
    decided_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=128)
    expires_at: datetime | None = None
    note: str | None = Field(default=None, max_length=1_000)


class ApprovalDecision(ApprovalRequest):
    """Immutable approval record with the reviewed evidence snapshot."""

    merchant: Merchant
    incident_id: str = Field(min_length=1, max_length=128)
    simulation_option_id: str | None = Field(default=None, max_length=128)
    reviewed_simulation: SimulationResult | None = None
    reviewed_evidence: list[EvidenceItem] = Field(default_factory=list)
    status: Literal["approved", "rejected", "expired", "revoked"]


class ApprovalRevocationRequest(BaseModel):
    """Human revocation before a simulated change has started."""

    model_config = ConfigDict(extra="forbid")

    revoked_by: str = Field(min_length=1, max_length=128)
    merchant: Merchant
    reason: str = Field(min_length=1, max_length=1_000)


class ExecutionRequest(BaseModel):
    """Contract only: this MVP has no provider execution capability."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(min_length=1, max_length=128)
    approval_decision_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    rollback_reference: str = Field(min_length=1, max_length=128)
    dry_run: bool = True


class ExecutionResult(BaseModel):
    """Always denied or dry-run in POST-01; no provider action is performed."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1, max_length=128)
    recommendation_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    status: Literal["denied", "dry_run"]
    executed: Literal[False] = False
    reason: str = Field(min_length=1, max_length=1_000)


class SimulatedChangeRequest(BaseModel):
    """Activate an approved recommendation in the local simulator only."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(min_length=1, max_length=128)
    approval_decision_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    rollback_reference: str = Field(min_length=1, max_length=128)


class RemediationMonitoringWindow(BaseModel):
    """Observed health of the proposed target route in one simulator window."""

    model_config = ConfigDict(extra="forbid")

    window_start: datetime
    window_end: datetime
    attempted_transactions: int = Field(ge=0)
    approval_rate: float | None = Field(default=None, ge=0, le=1)
    error_rate: float | None = Field(default=None, ge=0, le=1)
    below_rollback_threshold: bool = False


class SimulatedRoutingChange(BaseModel):
    """An auditable, non-provider-routing representation of an approved change."""

    model_config = ConfigDict(extra="forbid")

    change_id: str = Field(min_length=1, max_length=128)
    recommendation_id: str = Field(min_length=1, max_length=128)
    approval_decision_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    merchant: Merchant
    country: Country
    target_provider: Provider
    traffic_shift_pct: float = Field(gt=0, le=1)
    before_approval_rate: float = Field(ge=0, le=1)
    expected_approval_rate: float | None = Field(default=None, ge=0, le=1)
    expected_recovered_value_per_hour: float = Field(ge=0)
    status: Literal["simulated_active", "rolled_back", "completed"]
    applied_at: datetime
    rollback_reference: str = Field(min_length=1, max_length=128)
    rollback_reason: str | None = Field(default=None, max_length=1_000)
    monitoring: list[RemediationMonitoringWindow] = Field(default_factory=list)
    simulated: Literal[True] = True


class SimulatedChangeRollbackRequest(BaseModel):
    """Human-initiated rollback for a simulated routing change."""

    model_config = ConfigDict(extra="forbid")

    decided_by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1_000)


class SimulatedChangeCompletionRequest(BaseModel):
    """Human closes a healthy simulated rollout without any provider action."""

    model_config = ConfigDict(extra="forbid")

    decided_by: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1, max_length=1_000)


class RoutingWorkflow(BaseModel):
    """Single source of truth for the human-approved remediation lifecycle."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(min_length=1, max_length=128)
    incident_id: str = Field(min_length=1, max_length=128)
    status: Literal[
        "pending_approval",
        "approved",
        "rejected",
        "expired",
        "revoked",
        "simulated_active",
        "rolled_back",
        "completed",
    ]
    approval_decision_id: str | None = Field(default=None, max_length=128)
    change_id: str | None = Field(default=None, max_length=128)
    updated_at: datetime
    transition_reason: str = Field(min_length=1, max_length=1_000)


class RemediationAuditEvent(BaseModel):
    """Append-only in-memory audit entry for the safe demo workflow."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    event_type: Literal[
        "recommendation_created",
        "approval_recorded",
        "approval_revoked",
        "approval_expired",
        "simulated_change_applied",
        "target_route_monitored",
        "simulated_change_rolled_back",
        "simulated_change_completed",
    ]
    recommendation_id: str = Field(min_length=1, max_length=128)
    change_id: str | None = Field(default=None, max_length=128)
    actor: str = Field(min_length=1, max_length=128)
    detail: str = Field(min_length=1, max_length=1_000)
    recommendation: RoutingRecommendation | None = None


# Backward-compatible names used by the first POST-01 implementation.
RemediationSimulation = SimulationResult
RemediationProposal = RoutingRecommendation


class DiagnosedIncident(BaseModel):
    """One detected incident paired with its RCA and AI narration."""

    model_config = ConfigDict(extra="forbid")

    incident: Incident
    diagnosis: Diagnosis
    remediation: RoutingRecommendation | None = None


class IncidentAssistantRequest(BaseModel):
    """One evidence-scoped operator question about an existing incident."""

    model_config = ConfigDict(extra="forbid")

    merchant: Merchant
    question: str = Field(min_length=1, max_length=1_000)

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class IncidentAssistantEvidence(BaseModel):
    """One deterministic fact cited by the incident assistant."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=1_000)


class IncidentAssistantResponse(BaseModel):
    """Grounded assistance that cannot approve or apply routing changes."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1, max_length=128)
    answer: str = Field(min_length=1, max_length=2_000)
    answerable: bool
    evidence: list[IncidentAssistantEvidence] = Field(default_factory=list)
    mode: Literal["mock", "openai", "fallback"]


class DeclineCodePatternEntry(BaseModel):
    """One code in a normalized, deterministic decline pattern."""

    model_config = ConfigDict(extra="forbid")

    code: DeclineCode
    decline_count: int = Field(ge=1)


class IncidentFingerprint(BaseModel):
    """Exact-match key used for the local incident memory; never embeddings."""

    model_config = ConfigDict(extra="forbid")

    merchant: Merchant
    country: Country
    provider: Provider | None = None
    payment_method: PaymentMethod | None = None
    decline_pattern: list[DeclineCodePatternEntry] = Field(default_factory=list)


class IncidentMemoryCase(BaseModel):
    """Persistent evidence and outcome snapshots for one detected incident."""

    model_config = ConfigDict(extra="forbid")

    incident: Incident
    diagnosis: Diagnosis
    remediation: RoutingRecommendation | None = None
    fingerprint: IncidentFingerprint
    decision: ApprovalDecision | None = None
    change: SimulatedRoutingChange | None = None


class IncidentMonitoringOutcome(BaseModel):
    """Expected versus observed result persisted for a simulated response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "not_simulated", "simulated_active", "rolled_back", "completed"
    ] = "not_simulated"
    expected_approval_rate: float | None = Field(default=None, ge=0, le=1)
    observed_approval_rate: float | None = Field(default=None, ge=0, le=1)
    observed_windows: int = Field(default=0, ge=0)
    observed_attempts: int = Field(default=0, ge=0)
    rollback_reason: str | None = Field(default=None, max_length=1_000)


class SimilarIncident(BaseModel):
    """A prior exact match with the facts needed for operator context."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1, max_length=128)
    detected_at: datetime
    severity: Severity
    estimated_loss: float = Field(ge=0)
    estimated_loss_per_hour: float = Field(ge=0)
    recommendation: RoutingRecommendation | None = None
    decision: ApprovalDecision | None = None
    monitoring_outcome: IncidentMonitoringOutcome = Field(
        default_factory=IncidentMonitoringOutcome
    )
    outcome: IncidentOutcome


class Alert(BaseModel):
    """A local operator notification; delivery integrations are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str = Field(min_length=1, max_length=128)
    type: AlertType
    created_at: datetime
    incident_id: str | None = Field(default=None, max_length=128)
    recommendation_id: str | None = Field(default=None, max_length=128)
    change_id: str | None = Field(default=None, max_length=128)
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = Field(default=None, max_length=128)
    payload: dict[str, object] = Field(default_factory=dict)


class AlertAcknowledgeRequest(BaseModel):
    """Human acknowledgement for a local inbox item."""

    model_config = ConfigDict(extra="forbid")

    acknowledged_by: str = Field(min_length=1, max_length=128)


class PostIncidentReport(BaseModel):
    """Evidence-bound report assembled entirely from persisted snapshots."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1, max_length=128)
    incident_id: str = Field(min_length=1, max_length=128)
    generated_at: datetime
    summary: str = Field(min_length=1, max_length=2_000)
    incident: Incident | None = None
    diagnosis: Diagnosis | None = None
    recommendation: RoutingRecommendation | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    decision: ApprovalDecision | None = None
    change: SimulatedRoutingChange | None = None
    outcome: IncidentOutcome = "open"
    monitoring_outcome: IncidentMonitoringOutcome = Field(
        default_factory=IncidentMonitoringOutcome
    )
    recurrence_detected: bool = False
    audit_trail: list[RemediationAuditEvent] = Field(default_factory=list)
    similar_cases: list[SimilarIncident] = Field(default_factory=list)


class MerchantIncidentsResponse(BaseModel):
    """Active incidents visible within one merchant context only."""

    model_config = ConfigDict(extra="forbid")

    merchant: Merchant
    incidents: list[DiagnosedIncident] = Field(default_factory=list)


class LiveTickResponse(BaseModel):
    """Result of advancing one simulated monitoring window."""

    model_config = ConfigDict(extra="forbid")

    window_start: datetime
    window_end: datetime
    incidents: list[DiagnosedIncident] = Field(default_factory=list)


class CountryMonitoringMetric(BaseModel):
    """Observed and expected approval metrics for one live merchant-country window."""

    model_config = ConfigDict(extra="forbid")

    country: Country
    actual_approval_rate: float = Field(ge=0, le=1)
    expected_approval_rate: float = Field(ge=0, le=1)
    attempted_transactions: int = Field(ge=0)
    approval_history: list[float] = Field(default_factory=list)


class MerchantMonitoringResponse(BaseModel):
    """Live simulator metrics isolated to one merchant context."""

    model_config = ConfigDict(extra="forbid")

    merchant: Merchant
    window_start: datetime
    window_end: datetime
    actual_approval_rate: float = Field(ge=0, le=1)
    expected_approval_rate: float = Field(ge=0, le=1)
    attempted_transactions: int = Field(ge=0)
    countries: list[CountryMonitoringMetric] = Field(default_factory=list)

class HealthResponse(BaseModel):
    status: Literal["ok"]


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_text: str = Field(
        min_length=1,
        max_length=5_000,
        description="The user's question, context, or challenge data.",
    )
    record_id: str = Field(
        default="REC-001",
        min_length=1,
        max_length=64,
        description="A sample record identifier used by the demo tools.",
    )

    @field_validator("input_text", "record_id")
    @classmethod
    def reject_whitespace_only_values(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


# CHANGE THIS AFTER CHALLENGE REVEAL
class AnalysisResponse(BaseModel):
    """Structured result returned by both OpenAI mode and mock mode."""

    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=100)
    reasoning_summary: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str = Field(min_length=1, max_length=500)
    tools_used: list[str]
    mode: Literal["mock", "openai"]
