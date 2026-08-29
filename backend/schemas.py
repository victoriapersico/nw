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
    estimated_loss: float = Field(ge=0)
    estimated_loss_per_hour: float = Field(ge=0)
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

class DiagnosedIncident(BaseModel):
    """One detected incident paired with its RCA and AI narration."""

    model_config = ConfigDict(extra="forbid")

    incident: Incident
    diagnosis: Diagnosis


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
