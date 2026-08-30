"""OpenAI-assisted prioritization over deterministic routing simulations.

The model may select an eligible option and explain it. All numeric fields in
the public recommendation are copied from the selected SimulationResult.
This module has no approval, execution, provider-credential, or routing tools.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from openai import (
    APIError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAI,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.ai.routing_prompts import (
    ROUTING_RECOMMENDATION_INSTRUCTIONS,
    build_routing_recommendation_input,
)
from backend.config import settings
from backend.schemas import (
    Diagnosis,
    RoutingPolicy,
    RoutingRecommendation,
    SimulationResult,
)


class RoutingRecommendationError(RuntimeError):
    """Raised when OpenAI cannot return a safe, grounded recommendation."""


class _RoutingDecision(BaseModel):
    """Fields OpenAI may author; deterministic metrics are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["recommended", "not_recommended"]
    recommended_option_id: str | None = Field(default=None, max_length=128)
    rationale: str = Field(min_length=1, max_length=1_000)
    abstention_reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "_RoutingDecision":
        if self.status == "recommended":
            if self.recommended_option_id is None:
                raise ValueError("recommended decisions require an option_id")
            if self.abstention_reason is not None:
                raise ValueError("recommended decisions cannot include abstention_reason")
        else:
            if self.recommended_option_id is not None:
                raise ValueError("not_recommended decisions cannot select an option")
            if self.abstention_reason is None:
                raise ValueError("not_recommended decisions require abstention_reason")
        return self


def _validate_model_wording(decision: _RoutingDecision) -> None:
    """Keep model-authored prose qualitative; metrics are rendered locally."""

    wording = " ".join(
        item
        for item in (decision.rationale, decision.abstention_reason)
        if item is not None
    )
    if re.search(r"\d|[$€£]", wording):
        raise RoutingRecommendationError(
            "The model-authored rationale contained a numeric claim; routing "
            "metrics must be copied from SimulationResult by the application."
        )
    unsupported_terms = ("capacity", "fee", "fees", "cost", "costs")
    if any(term in wording.lower().split() for term in unsupported_terms):
        raise RoutingRecommendationError(
            "The model-authored rationale made a capacity or cost claim."
        )


def _eligible_options(
    policy: RoutingPolicy,
    simulations: Sequence[SimulationResult],
) -> list[SimulationResult]:
    """Apply policy again even though simulations should already be validated."""

    seen_ids: set[str] = set()
    eligible: list[SimulationResult] = []
    for simulation in simulations:
        option_id = simulation.option.option_id
        if option_id in seen_ids:
            raise RoutingRecommendationError(
                f"Duplicate simulation option_id: {option_id}."
            )
        seen_ids.add(option_id)
        if (
            simulation.status == "eligible"
            and simulation.option.target_provider
            in policy.eligible_target_providers
            and simulation.option.traffic_shift_pct <= policy.max_traffic_shift_pct
        ):
            eligible.append(simulation)
    return eligible


def _abstain(
    diagnosis: Diagnosis,
    policy: RoutingPolicy,
    simulations: Sequence[SimulationResult],
    *,
    reason: str,
    rationale: str | None = None,
) -> RoutingRecommendation:
    return RoutingRecommendation(
        recommendation_id=f"rec-{diagnosis.incident_id}",
        incident_id=diagnosis.incident_id,
        policy_id=policy.policy_id,
        status="not_recommended",
        alternatives=list(simulations),
        rationale=rationale or f"No routing change is recommended. {reason}",
        confidence=0.0,
        proposed_traffic_cap=None,
        abstention_reason=reason,
    )


def _mock_decision(eligible: Sequence[SimulationResult]) -> _RoutingDecision:
    """Mirror the demo's deterministic confidence-adjusted prioritization."""

    selected = max(
        eligible,
        key=lambda item: (
            item.expected_recovered_value_per_hour * item.confidence,
            -item.option.traffic_shift_pct,
            item.option.target_provider,
        ),
    )
    return _RoutingDecision(
        status="recommended",
        recommended_option_id=selected.option.option_id,
        rationale=(
            f"{selected.option.target_provider} is the strongest policy-eligible "
            "alternative after confidence-adjusted prioritization of the "
            "deterministic simulation results."
        ),
    )


def _openai_decision(
    diagnosis: Diagnosis,
    policy: RoutingPolicy,
    simulations: Sequence[SimulationResult],
) -> _RoutingDecision:
    if settings.openai_api_key is None:
        raise RoutingRecommendationError("OPENAI_API_KEY is missing; use Mock Mode.")

    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=1,
    )
    try:
        response = client.responses.parse(
            model=settings.openai_model,
            instructions=ROUTING_RECOMMENDATION_INSTRUCTIONS,
            input=build_routing_recommendation_input(
                diagnosis,
                policy,
                simulations,
            ),
            text_format=_RoutingDecision,
        )
    except APIError as exc:
        raise RoutingRecommendationError(
            f"OpenAI API request failed: {exc}"
        ) from exc
    except (ContentFilterFinishReasonError, LengthFinishReasonError) as exc:
        raise RoutingRecommendationError(
            f"OpenAI could not complete the structured recommendation: {exc}"
        ) from exc
    except ValidationError as exc:
        raise RoutingRecommendationError(
            "OpenAI returned an invalid routing recommendation."
        ) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise RoutingRecommendationError(
            "OpenAI returned no structured routing recommendation."
        )
    return parsed


def recommend_routing(
    diagnosis: Diagnosis,
    policy: RoutingPolicy,
    simulations: Sequence[SimulationResult],
    *,
    mock_mode: bool | None = None,
) -> RoutingRecommendation:
    """Return a reviewable recommendation without approving or executing it."""

    use_mock = settings.mock_mode if mock_mode is None else mock_mode
    simulations = tuple(simulations)

    if diagnosis.diagnosis_status != "confirmed":
        return _abstain(
            diagnosis,
            policy,
            simulations,
            reason=(
                "The current diagnosis has insufficient evidence; monitor "
                "additional windows before considering a routing change."
            ),
        )
    if not simulations:
        return _abstain(
            diagnosis,
            policy,
            simulations,
            reason=(
                "A deterministic simulation result is required before any "
                "routing action can be proposed."
            ),
        )

    eligible = _eligible_options(policy, simulations)
    if not eligible:
        return _abstain(
            diagnosis,
            policy,
            simulations,
            reason=(
                "All deterministic alternatives are blocked, inconclusive, "
                "or outside the eligible-route policy; continue monitoring."
            ),
        )

    decision = (
        _mock_decision(eligible)
        if use_mock
        else _openai_decision(diagnosis, policy, simulations)
    )
    _validate_model_wording(decision)
    if decision.status == "not_recommended":
        assert decision.abstention_reason is not None
        return _abstain(
            diagnosis,
            policy,
            simulations,
            reason=decision.abstention_reason,
            rationale=decision.rationale,
        )

    by_id = {item.option.option_id: item for item in eligible}
    selected = by_id.get(decision.recommended_option_id or "")
    if selected is None:
        raise RoutingRecommendationError(
            "The recommendation selected an option that is not eligible under "
            "the supplied simulation results and routing policy."
        )

    return RoutingRecommendation(
        recommendation_id=f"rec-{diagnosis.incident_id}",
        incident_id=diagnosis.incident_id,
        policy_id=policy.policy_id,
        status="recommended",
        recommended_option_id=selected.option.option_id,
        alternatives=list(simulations),
        rationale=decision.rationale,
        confidence=selected.confidence,
        proposed_traffic_cap=selected.option.traffic_shift_pct,
        rollback_reference=f"rollback-{diagnosis.incident_id}",
    )
