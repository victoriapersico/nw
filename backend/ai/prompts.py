"""Prompt construction for evidence-bound diagnosis narration."""

import json

from backend.schemas import Diagnosis


NARRATION_INSTRUCTIONS = """
You are an operations communications assistant for payment incidents.
Use only the deterministic diagnosis and evidence supplied in the input.
Do not invent providers, banks, payment methods, decline codes, metrics, causes,
or remediation outcomes. Do not recalculate statistics. Do not execute actions.

Return a concise explanation and a recommendation. If diagnosis_status is
insufficient_evidence, explicitly preserve that abstention and recommend
monitoring or collecting additional evidence rather than naming a cause.
""".strip()


def build_evidence_input(diagnosis: Diagnosis) -> str:
    """Serialize only deterministic RCA output; raw transactions are excluded."""

    payload = {
        "incident_id": diagnosis.incident_id,
        "diagnosis_status": diagnosis.diagnosis_status,
        "root_cause_dimensions": diagnosis.root_cause_dimensions,
        "confidence": diagnosis.confidence,
        "deterministic_explanation": diagnosis.explanation,
        "deterministic_recommendation": diagnosis.recommended_action,
        "evidence": [item.model_dump(mode="json") for item in diagnosis.evidence],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
