"""Persistence checks for the local append-only remediation audit."""

from datetime import datetime, timezone

from backend.remediation.audit_store import RemediationAuditStore
from backend.schemas import RemediationAuditEvent


def test_audit_events_survive_a_new_store_instance(tmp_path) -> None:
    database_path = tmp_path / "remediation-audit.sqlite3"
    event = RemediationAuditEvent(
        event_id="audit-persistence-001",
        occurred_at=datetime.now(timezone.utc),
        event_type="approval_recorded",
        recommendation_id="rec-persistence-001",
        actor="merchant-operator",
        detail="Approval was recorded for persistence verification.",
    )

    RemediationAuditStore(database_path).append(event)
    persisted = RemediationAuditStore(database_path).events("rec-persistence-001")

    assert persisted == [event]
