"""Deterministic ordering rules for concurrent incidents."""

from backend.schemas import Incident


SEVERITY_RANK: dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def incident_priority_key(incident: Incident) -> tuple[float, ...]:
    """Return a descending-sort key for business incident priority."""

    return (
        SEVERITY_RANK[incident.severity],
        incident.estimated_loss,
        incident.anomaly_score,
        incident.conversion_drop_pp,
    )


def prioritize_incidents(incidents: list[Incident]) -> list[Incident]:
    """Return incidents ordered from highest to lowest priority."""

    return sorted(
        incidents,
        key=incident_priority_key,
        reverse=True,
    )