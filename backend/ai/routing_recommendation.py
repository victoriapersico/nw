"""OpenAI-assisted explanation of a deterministic routing selection.

Application rules rank and select the eligible option before the model runs.
The model may explain that selection or abstain, but cannot select a route. All
numeric fields in the public recommendation are copied from the deterministically
selected SimulationResult. This module has no approval, execution,
provider-credential, or routing tools.
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


class _RoutingExplanation(BaseModel):
    """Qualitative fields OpenAI may author after deterministic selection."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["recommended", "not_recommended"]
    rationale: str = Field(min_length=1, max_length=1_000)
    abstention_reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_explanation_shape(self) -> "_RoutingExplanation":
        if self.status == "recommended":
            if self.abstention_reason is not None:
                raise ValueError(
                    "recommended explanations cannot include abstention_reason"
                )
        else:
            if self.abstention_reason is None:
                raise ValueError(
                    "not_recommended explanations require abstention_reason"
                )
        return self


def _validate_model_wording(explanation: _RoutingExplanation) -> None:
    """Keep model-authored prose qualitative; metrics are rendered locally."""

    wording = " ".join(
        item
        for item in (explanation.rationale, explanation.abstention_reason)
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


def _rank_eligible_options(
    eligible: Sequence[SimulationResult],
) -> list[SimulationResult]:
    """Rank eligible options using stable application-owned rules."""

    return sorted(
        eligible,
        key=lambda item: (
            -(item.expected_recovered_value_per_hour * item.confidence),
            item.option.traffic_shift_pct,
            item.option.target_provider,
            item.option.option_id,
        ),
    )


def _mock_explanation(selected: SimulationResult) -> _RoutingExplanation:
    """Explain the deterministic selection without invoking OpenAI."""

    return _RoutingExplanation(
        status="recommended",
        rationale=(
            f"{selected.option.target_provider} is the strongest policy-eligible "
            "alternative under the deterministic confidence-adjusted ranking."
        ),
    )


def _openai_explanation(
    diagnosis: Diagnosis,
    policy: RoutingPolicy,
    simulations: Sequence[SimulationResult],
    selected: SimulationResult,
) -> _RoutingExplanation:
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
                selected,
            ),
            text_format=_RoutingExplanation,
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

    selected = _rank_eligible_options(eligible)[0]
    explanation = (
        _mock_explanation(selected)
        if use_mock
        else _openai_explanation(diagnosis, policy, simulations, selected)
    )
    _validate_model_wording(explanation)
    if explanation.status == "not_recommended":
        assert explanation.abstention_reason is not None
        return _abstain(
            diagnosis,
            policy,
            simulations,
            reason=explanation.abstention_reason,
            rationale=explanation.rationale,
        )

    return RoutingRecommendation(
        recommendation_id=f"rec-{diagnosis.incident_id}",
        incident_id=diagnosis.incident_id,
        policy_id=policy.policy_id,
        status="recommended",
        recommended_option_id=selected.option.option_id,
        alternatives=list(simulations),
        rationale=explanation.rationale,
        confidence=selected.confidence,
        proposed_traffic_cap=selected.option.traffic_shift_pct,
        rollback_reference=f"rollback-{diagnosis.incident_id}",
    )
