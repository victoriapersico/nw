"""Small, deterministic view helpers for real Control Tower batches."""

from dataclasses import dataclass

from backend.schemas import (
    Country,
    DiagnosisStatus,
    DiagnosedIncident,
    Merchant,
    Transaction,
    TransactionBatch,
)


COUNTRIES: tuple[Country, ...] = ("Mexico", "Brazil", "Colombia")


@dataclass(frozen=True)
class CountrySnapshot:
    transaction_count: int
    approval_rate: float
    status: str


@dataclass(frozen=True)
class MerchantSnapshot:
    transaction_count: int
    approval_rate: float
    countries: dict[Country, CountrySnapshot]
    recent_transactions: tuple[Transaction, ...]


@dataclass(frozen=True)
class DiagnosisPresentation:
    heading: str
    evidence_heading: str


def diagnosis_presentation(status: DiagnosisStatus) -> DiagnosisPresentation:
    """Return wording that cannot turn an RCA abstention into a claim."""

    if status == "confirmed":
        return DiagnosisPresentation(
            heading="Confirmed root cause",
            evidence_heading="Confirmed supporting evidence",
        )
    return DiagnosisPresentation(
        heading="Insufficient evidence to isolate a single root cause.",
        evidence_heading="Observed evidence — not sufficient for confirmation",
    )


def build_merchant_snapshot(
    batch: TransactionBatch,
    merchant: Merchant,
    incidents: list[DiagnosedIncident],
) -> MerchantSnapshot:
    """Aggregate only values measured in the latest simulator batch."""

    merchant_transactions = [
        transaction
        for transaction in batch.transactions
        if transaction.merchant == merchant
    ]
    active_severity = {
        item.incident.country: item.incident.severity
        for item in incidents
        if item.incident.merchant == merchant and item.incident.status == "active"
    }
    countries: dict[Country, CountrySnapshot] = {}
    for country in COUNTRIES:
        transactions = [
            transaction
            for transaction in merchant_transactions
            if transaction.country == country
        ]
        rate = _approval_rate(transactions)
        severity = active_severity.get(country)
        status = (
            "Critical"
            if severity in {"high", "critical"}
            else "Attention"
            if severity in {"low", "medium"}
            else "No active incident"
        )
        countries[country] = CountrySnapshot(
            transaction_count=len(transactions),
            approval_rate=rate,
            status=status,
        )

    recent = tuple(
        sorted(
            merchant_transactions,
            key=lambda transaction: transaction.timestamp,
            reverse=True,
        )[:8]
    )
    return MerchantSnapshot(
        transaction_count=len(merchant_transactions),
        approval_rate=_approval_rate(merchant_transactions),
        countries=countries,
        recent_transactions=recent,
    )


def _approval_rate(transactions: list[Transaction]) -> float:
    if not transactions:
        return 0.0
    approved = sum(transaction.status == "approved" for transaction in transactions)
    return approved / len(transactions)
