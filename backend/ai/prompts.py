"""Prompt construction for evidence-bound diagnosis narration."""

import json

from backend.schemas import Diagnosis, NarrativeLanguage, NarrativeTone


NARRATION_INSTRUCTIONS = """
You are an operations communications assistant for payment incidents.
Use only the deterministic diagnosis and evidence supplied in the input.
Do not invent providers, banks, payment methods, decline codes, metrics, causes,
or remediation outcomes. Do not recalculate statistics. Do not execute actions.

Return evidence-bound statements using only the supplied evidence IDs. Every
factual statement must cite at least one supplied evidence ID. Return an
operator summary, an executive one-liner, and a safe recommended action. If diagnosis_status is
insufficient_evidence, explicitly preserve that abstention and recommend
monitoring or collecting additional evidence rather than naming a cause.
Each statement must name the value of every evidence item it cites.
""".strip()


def build_evidence_input(
    diagnosis: Diagnosis,
    *,
    language: NarrativeLanguage = "en",
    tone: NarrativeTone = "operations",
) -> str:
    """Serialize only deterministic RCA output; raw transactions are excluded."""

    payload = {
        "incident_id": diagnosis.incident_id,
        "diagnosis_status": diagnosis.diagnosis_status,
        "language": language,
        "tone": tone,
        "root_cause_dimensions": diagnosis.root_cause_dimensions,
        "confidence": diagnosis.confidence,
        "deterministic_explanation": diagnosis.explanation,
        "deterministic_recommendation": diagnosis.recommended_action,
        "evidence": [
            {"evidence_id": f"evidence-{index}", **item.model_dump(mode="json")}
            for index, item in enumerate(diagnosis.evidence, start=1)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
