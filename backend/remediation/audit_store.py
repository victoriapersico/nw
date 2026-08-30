"""Small append-only SQLite audit store for the local demo workflow."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from backend.schemas import RemediationAuditEvent


class RemediationAuditStore:
    """Persist audit events without adding an external database dependency."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        configured = database_path or os.getenv("REMEDIATION_AUDIT_DB")
        self._path = Path(configured) if configured else Path(tempfile.gettempdir()) / "nw_remediation_audit.sqlite3"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS remediation_audit_events (
                    event_id TEXT PRIMARY KEY,
                    recommendation_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def append(self, event: RemediationAuditEvent) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO remediation_audit_events (event_id, recommendation_id, payload) VALUES (?, ?, ?)",
                (event.event_id, event.recommendation_id, event.model_dump_json()),
            )

    def events(self, recommendation_id: str | None = None) -> list[RemediationAuditEvent]:
        query = "SELECT payload FROM remediation_audit_events"
        parameters: tuple[str, ...] = ()
        if recommendation_id is not None:
            query += " WHERE recommendation_id = ?"
            parameters = (recommendation_id,)
        query += " ORDER BY rowid"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [RemediationAuditEvent.model_validate_json(row[0]) for row in rows]

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)
