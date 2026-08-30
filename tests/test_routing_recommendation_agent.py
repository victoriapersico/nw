"""Safety and grounding tests for the POST-MVP-04 routing agent."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import backend.ai.routing_recommendation as recommendation_module
from backend.ai.routing_prompts import build_routing_recommendation_input
from backend.ai.routing_recommendation import (
    RoutingRecommendationError,
    recommend_routing,
)
from backend.schemas import (
    Diagnosis,
    EvidenceItem,
    RemediationOption,
    RoutingPolicy,
    SimulationResult,
)


def _diagnosis(*, confirmed: bool = True) -> Diagnosis:
    return Diagnosis(
        incident_id="inc-rappi-brazil-dlocal-pix",
        diagnosis_status="confirmed" if confirmed else "insufficient_evidence",
        confidence=0.91 if confirmed else 0.2,
        root_cause_dimensions=["provider", "payment_method"] if confirmed else [],
        evidence=(
            [
                EvidenceItem(
                    dimension="intersection",
                    value="dLocal × PIX",
                    baseline_metric=0.92,
                    live_metric=0.40,
                    delta=-0.52,
                    sample_size=100,
                    explained_loss_share=0.88,
                )
            ]
            if confirmed
            else []
        ),
        explanation="Deterministic RCA output.",
        recommended_action="Investigate dLocal PIX.",
    )


def _policy(*, cap: float = 0.50) -> RoutingPolicy:
    return RoutingPolicy(
        policy_id="rappi-brazil-pix",
        merchant="Rappi",
        country="Brazil",
        payment_method="PIX",
        eligible_target_providers=["Stripe", "Adyen"],
        max_traffic_shift_pct=cap,
    )


def _simulation(
    option_id: str,
    provider: str,
    shift: float,
    *,
    status: str = "eligible",
    recovered: float = 1_000.0,
    confidence: float = 0.8,
) -> SimulationResult:
    return SimulationResult(
        option=RemediationOption(
            option_id=option_id,
            target_provider=provider,
            traffic_shift_pct=shift,
        ),
        status=status,
        expected_approval_rate=0.90 if status == "eligible" else None,
        expected_recovered_value_per_hour=recovered if status == "eligible" else 0,
        expected_incremental_cost_per_hour=20 if status == "eligible" else 0,
        confidence=confidence if status == "eligible" else 0,
        rejection_reason=(
            None if status == "eligible" else "Insufficient deterministic evidence."
        ),
    )


def test_mock_mode_prioritizes_and_copies_deterministic_metrics(monkeypatch) -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("OpenAI must not run in Mock Mode")

    monkeypatch.setattr(recommendation_module, "OpenAI", fail_if_called)
    simulations = [
        _simulation("stripe-25", "Stripe", 0.25, recovered=900, confidence=0.9),
        _simulation("adyen-25", "Adyen", 0.25, recovered=1_200, confidence=0.85),
    ]

    recommendation = recommend_routing(
        _diagnosis(),
        _policy(),
        simulations,
        mock_mode=True,
    )

    assert recommendation.status == "recommended"
    assert recommendation.recommended_option_id == "adyen-25"
    assert recommendation.confidence == simulations[1].confidence
    assert (
        recommendation.proposed_traffic_cap
        == simulations[1].option.traffic_shift_pct
    )
    assert recommendation.alternatives == simulations
    assert recommendation.required_approval == "merchant_operations"
    assert recommendation.dry_run is True


@pytest.mark.parametrize(
    ("diagnosis", "simulations", "reason_fragment"),
    [
        (_diagnosis(), [], "simulation result is required"),
        (
            _diagnosis(confirmed=False),
            [_simulation("stripe-25", "Stripe", 0.25)],
            "insufficient evidence",
        ),
        (
            _diagnosis(),
            [_simulation("stripe-25", "Stripe", 0.25, status="inconclusive")],
            "inconclusive",
        ),
    ],
)
def test_unsafe_or_inconclusive_inputs_abstain_without_openai(
    monkeypatch,
    diagnosis: Diagnosis,
    simulations: list[SimulationResult],
    reason_fragment: str,
) -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("OpenAI must not run for a deterministic abstention")

    monkeypatch.setattr(recommendation_module, "OpenAI", fail_if_called)

    recommendation = recommend_routing(
        diagnosis,
        _policy(),
        simulations,
        mock_mode=False,
    )

    assert recommendation.status == "not_recommended"
    assert recommendation.recommended_option_id is None
    assert recommendation.proposed_traffic_cap is None
    assert recommendation.confidence == 0
    assert reason_fragment in recommendation.abstention_reason.lower()


def test_policy_rejects_an_eligible_result_above_traffic_cap() -> None:
    recommendation = recommend_routing(
        _diagnosis(),
        _policy(cap=0.25),
        [_simulation("adyen-50", "Adyen", 0.50)],
        mock_mode=True,
    )

    assert recommendation.status == "not_recommended"
    assert recommendation.proposed_traffic_cap is None
    assert "outside the eligible-route policy" in recommendation.abstention_reason


def test_openai_explains_the_deterministic_selection_without_choosing_it(
    monkeypatch,
) -> None:
    parsed = recommendation_module._RoutingExplanation(
        status="recommended",
        rationale="The selected route has the strongest grounded evidence.",
    )
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_kwargs: SimpleNamespace(output_parsed=parsed)
        )
    )
    monkeypatch.setattr(recommendation_module, "OpenAI", lambda **_kwargs: fake_client)
    monkeypatch.setattr(
        recommendation_module,
        "settings",
        SimpleNamespace(
            openai_api_key="test-key",
            openai_timeout_seconds=1,
            openai_model="test-model",
            mock_mode=False,
        ),
    )

    simulations = [
        _simulation("stripe-25", "Stripe", 0.25, recovered=900, confidence=0.9),
        _simulation("adyen-25", "Adyen", 0.25, recovered=1_200, confidence=0.85),
    ]
    recommendation = recommend_routing(
        _diagnosis(),
        _policy(),
        simulations,
        mock_mode=False,
    )

    assert "recommended_option_id" not in recommendation_module._RoutingExplanation.model_fields
    assert recommendation.recommended_option_id == "adyen-25"
    assert recommendation.confidence == simulations[1].confidence


def test_structured_explanation_rejects_a_model_authored_option_id() -> None:
    with pytest.raises(ValidationError, match="recommended_option_id"):
        recommendation_module._RoutingExplanation.model_validate(
            {
                "status": "recommended",
                "recommended_option_id": "invented-provider-100",
                "rationale": "Use an invented option.",
            }
        )


def test_openai_explanation_can_abstain_after_deterministic_selection(
    monkeypatch,
) -> None:
    parsed = recommendation_module._RoutingExplanation(
        status="not_recommended",
        rationale="The evidence does not yet support an operational change.",
        abstention_reason="Continue monitoring until the evidence is conclusive.",
    )
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_kwargs: SimpleNamespace(output_parsed=parsed)
        )
    )
    monkeypatch.setattr(recommendation_module, "OpenAI", lambda **_kwargs: fake_client)
    monkeypatch.setattr(
        recommendation_module,
        "settings",
        SimpleNamespace(
            openai_api_key="test-key",
            openai_timeout_seconds=1,
            openai_model="test-model",
            mock_mode=False,
        ),
    )

    recommendation = recommend_routing(
        _diagnosis(),
        _policy(),
        [_simulation("stripe-25", "Stripe", 0.25)],
        mock_mode=False,
    )

    assert recommendation.status == "not_recommended"
    assert recommendation.recommended_option_id is None
    assert recommendation.proposed_traffic_cap is None
    assert recommendation.abstention_reason == parsed.abstention_reason


def test_model_authored_numeric_claim_triggers_safe_deterministic_fallback(
    monkeypatch,
) -> None:
    parsed = recommendation_module._RoutingExplanation(
        status="recommended",
        rationale="This route will recover $999999 per hour.",
    )
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_kwargs: SimpleNamespace(output_parsed=parsed)
        )
    )
    monkeypatch.setattr(recommendation_module, "OpenAI", lambda **_kwargs: fake_client)
    monkeypatch.setattr(
        recommendation_module,
        "settings",
        SimpleNamespace(
            openai_api_key="test-key",
            openai_timeout_seconds=1,
            openai_model="test-model",
            mock_mode=False,
        ),
    )

    recommendation = recommend_routing(
        _diagnosis(),
        _policy(),
        [_simulation("stripe-25", "Stripe", 0.25)],
        mock_mode=False,
    )

    assert recommendation.status == "recommended"
    assert recommendation.recommended_option_id == "stripe-25"
    assert "$999999" not in recommendation.rationale
    assert "deterministic" in recommendation.rationale


def test_model_input_contains_only_allowed_contracts() -> None:
    selected = _simulation("stripe-25", "Stripe", 0.25)
    payload = json.loads(
        build_routing_recommendation_input(
            _diagnosis(),
            _policy(),
            [selected],
            selected,
        )
    )

    assert set(payload) == {
        "diagnosis",
        "deterministic_selection",
        "eligible_route_policy",
        "simulation_results",
    }
    assert payload["deterministic_selection"]["option"]["option_id"] == "stripe-25"
    serialized = json.dumps(payload)
    assert "transaction_id" not in serialized
    assert "api_key" not in serialized
    assert "approval_decision_id" not in serialized
    assert "idempotency_key" not in serialized
