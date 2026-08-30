"""SQLite persistence for local alerts, incident memory, and reports."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.schemas import (
    Alert,
    AlertType,
    IncidentFingerprint,
    IncidentMemoryCase,
    PostIncidentReport,
)


class IncidentMemoryStore:
    """Small durable store with exact-match incident retrieval only."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        configured = database_path or os.getenv("INCIDENT_MEMORY_DB")
        self._path = (
            Path(configured)
            if configured
            else Path(tempfile.gettempdir()) / "nw_incident_memory.sqlite3"
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS incident_memory_cases (
                    incident_id TEXT PRIMARY KEY,
                    merchant TEXT NOT NULL,
                    country TEXT NOT NULL,
                    provider TEXT,
                    payment_method TEXT,
                    decline_pattern TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS incident_memory_exact_match
                ON incident_memory_cases (
                    merchant, country, provider, payment_method, decline_pattern
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    acknowledged INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS post_incident_reports (
                    incident_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                """
            )

    def upsert_case(self, case: IncidentMemoryCase) -> None:
        fingerprint = case.fingerprint
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO incident_memory_cases (
                    incident_id, merchant, country, provider, payment_method,
                    decline_pattern, detected_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    merchant = excluded.merchant,
                    country = excluded.country,
                    provider = excluded.provider,
                    payment_method = excluded.payment_method,
                    decline_pattern = excluded.decline_pattern,
                    detected_at = excluded.detected_at,
                    payload = excluded.payload
                """,
                (
                    case.incident.incident_id,
                    fingerprint.merchant,
                    fingerprint.country,
                    fingerprint.provider,
                    fingerprint.payment_method,
                    self._pattern_key(fingerprint),
                    case.incident.detected_at.isoformat(),
                    case.model_dump_json(),
                ),
            )

    def case(self, incident_id: str) -> IncidentMemoryCase | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM incident_memory_cases WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
        return IncidentMemoryCase.model_validate_json(row[0]) if row else None

    def similar_cases(
        self, fingerprint: IncidentFingerprint, *, exclude_incident_id: str
    ) -> list[IncidentMemoryCase]:
        """Return exact fingerprint matches, ordered from newest to oldest."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM incident_memory_cases
                WHERE merchant = ? AND country = ?
                  AND provider IS ? AND payment_method IS ?
                  AND decline_pattern = ? AND incident_id != ?
                ORDER BY detected_at DESC
                """,
                (
                    fingerprint.merchant,
                    fingerprint.country,
                    fingerprint.provider,
                    fingerprint.payment_method,
                    self._pattern_key(fingerprint),
                    exclude_incident_id,
                ),
            ).fetchall()
        return [IncidentMemoryCase.model_validate_json(row[0]) for row in rows]

    def create_alert(
        self,
        *,
        alert_type: AlertType,
        dedupe_key: str,
        incident_id: str | None = None,
        recommendation_id: str | None = None,
        change_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> Alert:
        """Create at most one inbox item for a domain event."""

        alert = Alert(
            alert_id=f"alert-{uuid4().hex}",
            type=alert_type,
            created_at=datetime.now(timezone.utc),
            incident_id=incident_id,
            recommendation_id=recommendation_id,
            change_id=change_id,
            payload=payload or {},
        )
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO alerts (alert_id, dedupe_key, acknowledged, payload) "
                "VALUES (?, ?, ?, ?)",
                (alert.alert_id, dedupe_key, 0, alert.model_dump_json()),
            )
            row = connection.execute(
                "SELECT payload FROM alerts WHERE dedupe_key = ?", (dedupe_key,)
            ).fetchone()
        assert row is not None
        return Alert.model_validate_json(row[0])

    def alerts(self, acknowledged: bool | None = None) -> list[Alert]:
        query = "SELECT payload FROM alerts"
        parameters: tuple[int, ...] = ()
        if acknowledged is not None:
            query += " WHERE acknowledged = ?"
            parameters = (int(acknowledged),)
        query += " ORDER BY rowid DESC"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [Alert.model_validate_json(row[0]) for row in rows]

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> Alert:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM alerts WHERE alert_id = ?", (alert_id,)
            ).fetchone()
            if row is None:
                raise KeyError(alert_id)
            current = Alert.model_validate_json(row[0])
            if current.acknowledged:
                return current
            updated = current.model_copy(
                update={
                    "acknowledged": True,
                    "acknowledged_at": datetime.now(timezone.utc),
                    "acknowledged_by": acknowledged_by,
                }
            )
            connection.execute(
                "UPDATE alerts SET acknowledged = 1, payload = ? WHERE alert_id = ?",
                (updated.model_dump_json(), alert_id),
            )
        return updated

    def save_report(self, report: PostIncidentReport) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO post_incident_reports (incident_id, payload) VALUES (?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET payload = excluded.payload
                """,
                (report.incident_id, report.model_dump_json()),
            )

    def report(self, incident_id: str) -> PostIncidentReport | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM post_incident_reports WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
        return PostIncidentReport.model_validate_json(row[0]) if row else None

    @staticmethod
    def _pattern_key(fingerprint: IncidentFingerprint) -> str:
        return json.dumps(
            [entry.code for entry in fingerprint.decline_pattern],
            separators=(",", ":"),
            sort_keys=True,
        )

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)
