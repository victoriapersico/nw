"""Prompt construction for simulation-backed routing recommendations."""

import json
from collections.abc import Sequence

from backend.schemas import Diagnosis, RoutingPolicy, SimulationResult


ROUTING_RECOMMENDATION_INSTRUCTIONS = """
You are a payment-operations routing recommendation assistant.
Use only the supplied deterministic Diagnosis, RoutingPolicy, and
SimulationResult objects. The application has already selected the route in
deterministic_selection using policy gates and deterministic ranking. You do
not choose, replace, or return an option_id. Explain why that selected route is
operationally preferable and compare it qualitatively with the supplied
alternatives. Never recalculate or invent recovery, cost, capacity, confidence,
traffic percentage, provider health, or payment metrics. Do not execute,
approve, or claim that a routing change has occurred.

Return a concise operational rationale. If the evidence does not support a
routing change, return not_recommended and a concrete abstention reason that
recommends monitoring. Do not include numeric estimates in the rationale; the
application renders verified values from SimulationResult.
""".strip()


def build_routing_recommendation_input(
    diagnosis: Diagnosis,
    policy: RoutingPolicy,
    simulations: Sequence[SimulationResult],
    selected: SimulationResult,
) -> str:
    """Serialize the allowed contracts and application-selected simulation."""

    payload = {
        "diagnosis": diagnosis.model_dump(mode="json"),
        "eligible_route_policy": policy.model_dump(mode="json"),
        "simulation_results": [
            simulation.model_dump(mode="json") for simulation in simulations
        ],
        "deterministic_selection": selected.model_dump(mode="json"),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
