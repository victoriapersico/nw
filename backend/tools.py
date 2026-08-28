"""Small, deterministic Python tools backed by the sample CSV file."""

import csv
from pathlib import Path
from typing import Any, Callable


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "sample_data.csv"


class RecordNotFoundError(LookupError):
    """Raised when a requested demo record does not exist."""


def _read_record(record_id: str) -> dict[str, Any]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Sample data file not found at {DATA_PATH}. Restore data/sample_data.csv."
        )

    with DATA_PATH.open(newline="", encoding="utf-8") as csv_file:
        for row in csv.DictReader(csv_file):
            if row["record_id"] == record_id:
                return {
                    "record_id": row["record_id"],
                    "category": row["category"],
                    "status": row["status"],
                    "current_value": float(row["current_value"]),
                    "target_value": float(row["target_value"]),
                    "priority": row["priority"],
                    "owner": row["owner"],
                }

    raise RecordNotFoundError(
        f"Record '{record_id}' was not found. Try REC-001, REC-002, or REC-003."
    )


# CHANGE THIS AFTER CHALLENGE REVEAL
def get_record_details(record_id: str) -> dict[str, Any]:
    """Return one record from the fake dataset."""

    return _read_record(record_id)


# CHANGE THIS AFTER CHALLENGE REVEAL
def calculate_metric(record_id: str) -> dict[str, Any]:
    """Calculate target attainment and the remaining gap for a record."""

    record = _read_record(record_id)
    target = record["target_value"]
    if target <= 0:
        raise ValueError(f"Record '{record_id}' has a non-positive target value.")

    attainment = round((record["current_value"] / target) * 100, 1)
    gap = round(target - record["current_value"], 2)
    return {
        "record_id": record_id,
        "attainment_percent": attainment,
        "gap_to_target": gap,
        "needs_attention": attainment < 90,
    }


# CHANGE THIS AFTER CHALLENGE REVEAL
def recommend_action(record_id: str) -> dict[str, Any]:
    """Return a deterministic example action based on sample record values."""

    record = _read_record(record_id)
    metric = calculate_metric(record_id)

    if metric["needs_attention"] and record["priority"] == "high":
        urgency = "high"
        action = "Escalate to the owner and create a same-day recovery plan."
    elif metric["needs_attention"]:
        urgency = "medium"
        action = "Review the gap with the owner and schedule a follow-up."
    else:
        urgency = "low"
        action = "Keep monitoring the record; no immediate intervention is needed."

    return {"record_id": record_id, "urgency": urgency, "action": action}


# OpenAI function definitions. Keep schemas strict so tool arguments are predictable.
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_record_details",
        "description": "Get the full sample record for a record ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {
                    "type": "string",
                    "description": "A sample ID such as REC-001.",
                }
            },
            "required": ["record_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "calculate_metric",
        "description": "Calculate attainment and gap-to-target for a sample record.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {
                    "type": "string",
                    "description": "A sample ID such as REC-001.",
                }
            },
            "required": ["record_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "recommend_action",
        "description": "Recommend a generic next action for a sample record.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {
                    "type": "string",
                    "description": "A sample ID such as REC-001.",
                }
            },
            "required": ["record_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_record_details": get_record_details,
    "calculate_metric": calculate_metric,
    "recommend_action": recommend_action,
}


def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route a model tool call to a known local Python function."""

    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        raise ValueError(f"Unknown tool requested: {name}")
    return function(**arguments)
