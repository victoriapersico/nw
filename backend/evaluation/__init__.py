"""Deterministic scenario catalog and end-to-end evaluation harness."""

from backend.evaluation.harness import EvaluationHarness, EvaluationReport
from backend.evaluation.scenarios import SCENARIOS, ScenarioDefinition

__all__ = ["EvaluationHarness", "EvaluationReport", "SCENARIOS", "ScenarioDefinition"]
