"""The 30 deterministic MVP evaluation scenarios.

These are test specifications, not detector rules.  Their injections are handed
only to the simulator by the evaluation runtime; the detector sees transaction
batches generated as a consequence of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import random
from typing import Literal

from backend.schemas import (
    COUNTRY_ISSUING_BANKS,
    COUNTRY_PAYMENT_METHODS,
    InjectionConfig,
)


ExpectedOutcome = Literal["no_alert", "incident", "insufficient_evidence", "optional"]
DEFAULT_LIVE_VOLUME_PER_WINDOW = 1_200


@dataclass(frozen=True)
class CauseExpectation:
    """One expected RCA evidence value, independent of a detector implementation."""

    dimension: str
    value: str


@dataclass(frozen=True)
class ScenarioExpectation:
    """Observable result expected from one scenario."""

    outcome: ExpectedOutcome
    minimum_incidents: int = 0
    causes: tuple[CauseExpectation, ...] = ()
    primary_cause: CauseExpectation | None = None


@dataclass(frozen=True)
class ScenarioDefinition:
    """All deterministic inputs needed to execute one end-to-end evaluation case."""

    scenario_id: int
    name: str
    seed: int
    start_at: datetime
    expectation: ScenarioExpectation
    injections: tuple[InjectionConfig, ...] = ()
    volume_per_window: int = DEFAULT_LIVE_VOLUME_PER_WINDOW
    evaluation_windows: int = 4
    directives: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "seed": self.seed,
            "start_at": self.start_at.isoformat(),
            "expectation": {
                "outcome": self.expectation.outcome,
                "minimum_incidents": self.expectation.minimum_incidents,
                "causes": [cause.__dict__ for cause in self.expectation.causes],
                "primary_cause": (
                    self.expectation.primary_cause.__dict__
                    if self.expectation.primary_cause
                    else None
                ),
            },
            "injections": [
                injection.model_dump(mode="json") for injection in self.injections
            ],
            "volume_per_window": self.volume_per_window,
            "evaluation_windows": self.evaluation_windows,
            "directives": list(self.directives),
            "notes": self.notes,
        }


UTC = timezone.utc


def build_scenarios() -> tuple[ScenarioDefinition, ...]:
    """Return the immutable, seeded MVP scenario catalog in specification order."""

    at = {
        "weekday": datetime(2025, 9, 2, 13, tzinfo=UTC),
        "weekend": datetime(2025, 9, 7, 20, tzinfo=UTC),
        "night": datetime(2025, 9, 3, 3, tzinfo=UTC),
    }
    scenarios = (
        _scenario(1, "Normal weekday Mexico", at["weekday"], _no_alert(), "Rappi", "Mexico"),
        _scenario(2, "Normal weekday Brazil", at["weekday"], _no_alert(), "Carrefour", "Brazil"),
        _scenario(3, "Normal weekday Colombia", at["weekday"], _no_alert(), "Despegar", "Colombia"),
        _scenario(4, "Weekend natural variation", at["weekend"], _no_alert(), "Rappi", "Brazil"),
        _scenario(
            5,
            "Low-volume random noise",
            at["weekday"],
            _no_alert(),
            "Carrefour",
            "Mexico",
            volume_per_window=20,
        ),
        _scenario(
            6,
            "One high-value decline",
            at["weekday"],
            _no_alert(),
            "Despegar",
            "Brazil",
            directives=("single_high_value_decline",),
        ),
        _scenario(7, "Stripe degradation Brazil", at["weekday"], _incident("provider", "Stripe"), "Rappi", "Brazil", provider="Stripe", target=0.50),
        _scenario(8, "Adyen degradation Mexico", at["weekday"], _incident("provider", "Adyen"), "Carrefour", "Mexico", provider="Adyen", target=0.50),
        _scenario(9, "dLocal degradation Colombia", at["weekday"], _incident("provider", "dLocal"), "Despegar", "Colombia", provider="dLocal", target=0.50),
        _scenario(10, "PIX outage Brazil", at["weekday"], _incident("payment_method", "PIX"), "Rappi", "Brazil", payment_method="PIX", target=0.20),
        _scenario(11, "PSE outage Colombia", at["weekday"], _incident("payment_method", "PSE"), "Carrefour", "Colombia", payment_method="PSE", target=0.20),
        _scenario(12, "OXXO outage Mexico", at["weekday"], _incident("payment_method", "OXXO"), "Carrefour", "Mexico", payment_method="OXXO", target=0.20),
        _scenario(13, "BBVA México outage", at["weekday"], _incident("issuing_bank", "BBVA México"), "Rappi", "Mexico", issuing_bank="BBVA México", target=0.20),
        _scenario(14, "Itaú over-declining", at["weekday"], _incident("issuing_bank", "Itaú"), "Despegar", "Brazil", issuing_bank="Itaú", target=0.30),
        _scenario(15, "Bancolombia outage", at["weekday"], _incident("issuing_bank", "Bancolombia"), "Carrefour", "Colombia", issuing_bank="Bancolombia", target=0.25),
        _scenario(16, "Decline code 91 spike", at["weekday"], _incident("decline_code", "91"), "Rappi", "Brazil", decline_code="91", target=0.30),
        _scenario(17, "dLocal × Itaú × Brazil", at["weekday"], _incident("intersection", "dLocal × Itaú"), "Rappi", "Brazil", provider="dLocal", issuing_bank="Itaú", target=0.25),
        _scenario(18, "Stripe × PSE × Colombia", at["weekday"], _incident("intersection", "Stripe × PSE"), "Carrefour", "Colombia", provider="Stripe", payment_method="PSE", target=0.25),
        _scenario(19, "Adyen × BBVA × Mexico", at["weekday"], _incident("intersection", "Adyen × BBVA México"), "Despegar", "Mexico", provider="Adyen", issuing_bank="BBVA México", target=0.25),
        _scenario(20, "Rappi merchant-specific failure", at["weekday"], _incident("merchant", "Rappi"), "Rappi", "Brazil", target=0.35),
        _scenario(21, "Despegar card-only degradation", at["weekday"], _incident("payment_method", "CARD", "merchant", "Despegar"), "Despegar", "Colombia", payment_method="CARD", target=0.35),
        _multi_scenario(
            22,
            "Stripe BR + BBVA MX",
            at["weekday"],
            _incident("provider", "Stripe", "issuing_bank", "BBVA México", minimum_incidents=2),
            (
                _injection("Rappi", "Brazil", provider="Stripe", target=0.30),
                _injection("Carrefour", "Mexico", issuing_bank="BBVA México", target=0.30),
            ),
        ),
        _multi_scenario(
            23,
            "PSE CO + Itaú BR",
            at["weekday"],
            _incident("payment_method", "PSE", "issuing_bank", "Itaú", minimum_incidents=2),
            (
                _injection("Rappi", "Colombia", payment_method="PSE", target=0.30),
                _injection("Despegar", "Brazil", issuing_bank="Itaú", target=0.30),
            ),
        ),
        _multi_scenario(
            24,
            "Two incidents same country/different merchants",
            at["weekday"],
            _incident("provider", "dLocal", "payment_method", "PIX", minimum_incidents=2),
            (
                _injection("Rappi", "Brazil", provider="dLocal", target=0.30),
                _injection("Carrefour", "Brazil", payment_method="PIX", target=0.30),
            ),
        ),
        _multi_scenario(
            25,
            "Critical + mild incident",
            at["weekday"],
            _incident(
                "provider",
                "Stripe",
                "payment_method",
                "OXXO",
                minimum_incidents=2,
                primary_cause=CauseExpectation("provider", "Stripe"),
            ),
            (
                _injection("Rappi", "Brazil", provider="Stripe", target=0.20),
                _injection("Carrefour", "Mexico", payment_method="OXXO", target=0.72),
            ),
        ),
        _scenario(26, "Low-volume suspicious slice", at["weekday"], _insufficient(), "Rappi", "Brazil", provider="Stripe", target=0.15, volume_per_window=20),
        _multi_scenario(
            27,
            "Two equally plausible causes",
            at["weekday"],
            _insufficient(),
            (
                _injection("Rappi", "Brazil", provider="Stripe", target=0.45),
                _injection("Rappi", "Brazil", payment_method="PIX", target=0.45),
            ),
            directives=("ambiguous_root_cause",),
        ),
        _scenario(28, "Natural time-of-day drop", at["night"], _no_alert(), "Rappi", "Brazil", directives=("natural_time_of_day",)),
        _scenario(29, "Repeat previous incident", at["weekday"], _optional(), "Rappi", "Brazil", provider="Stripe", target=0.40, directives=("repeat_previous_incident",)),
        _unseen_slice_scenario(at["weekday"]),
    )
    _validate_catalog(scenarios)
    return scenarios


def _scenario(
    scenario_id: int,
    name: str,
    start_at: datetime,
    expectation: ScenarioExpectation,
    merchant: str,
    country: str,
    *,
    provider: str | None = None,
    payment_method: str | None = None,
    issuing_bank: str | None = None,
    decline_code: str | None = None,
    target: float | None = None,
    volume_per_window: int = DEFAULT_LIVE_VOLUME_PER_WINDOW,
    directives: tuple[str, ...] = (),
) -> ScenarioDefinition:
    injections = ()
    if target is not None:
        injections = (
            _injection(
                merchant,
                country,
                provider=provider,
                payment_method=payment_method,
                issuing_bank=issuing_bank,
                decline_code=decline_code,
                target=target,
            ),
        )
    return ScenarioDefinition(
        scenario_id=scenario_id,
        name=name,
        seed=10_000 + scenario_id,
        start_at=start_at,
        expectation=expectation,
        injections=injections,
        volume_per_window=volume_per_window,
        directives=directives,
    )


def _multi_scenario(
    scenario_id: int,
    name: str,
    start_at: datetime,
    expectation: ScenarioExpectation,
    injections: tuple[InjectionConfig, ...],
    *,
    directives: tuple[str, ...] = (),
) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id=scenario_id,
        name=name,
        seed=10_000 + scenario_id,
        start_at=start_at,
        expectation=expectation,
        injections=injections,
        directives=directives,
    )


def _injection(
    merchant: str,
    country: str,
    *,
    provider: str | None = None,
    payment_method: str | None = None,
    issuing_bank: str | None = None,
    decline_code: str | None = None,
    target: float,
) -> InjectionConfig:
    return InjectionConfig(
        merchant=merchant,
        country=country,
        provider=provider,
        payment_method=payment_method,
        issuing_bank=issuing_bank,
        decline_code=decline_code,
        target_approval_rate=target,
        duration_windows=4,
    )


def _incident(*dimension_value_pairs: str, minimum_incidents: int = 1, primary_cause: CauseExpectation | None = None) -> ScenarioExpectation:
    causes = tuple(
        CauseExpectation(dimension_value_pairs[index], dimension_value_pairs[index + 1])
        for index in range(0, len(dimension_value_pairs), 2)
    )
    return ScenarioExpectation(
        outcome="incident",
        minimum_incidents=minimum_incidents,
        causes=causes,
        primary_cause=primary_cause,
    )


def _no_alert() -> ScenarioExpectation:
    return ScenarioExpectation(outcome="no_alert")


def _insufficient() -> ScenarioExpectation:
    return ScenarioExpectation(outcome="insufficient_evidence")


def _optional() -> ScenarioExpectation:
    return ScenarioExpectation(outcome="optional")


def _unseen_slice_scenario(start_at: datetime) -> ScenarioDefinition:
    rng = random.Random(10_030)
    merchant = rng.choice(("Rappi", "Carrefour", "Despegar"))
    country = rng.choice(("Mexico", "Brazil", "Colombia"))
    provider = rng.choice(("Stripe", "Adyen", "dLocal"))
    payment_method = rng.choice(sorted(COUNTRY_PAYMENT_METHODS[country]))
    issuing_bank = rng.choice(sorted(COUNTRY_ISSUING_BANKS[country]))
    causes = (
        CauseExpectation("provider", provider),
        CauseExpectation("payment_method", payment_method),
        CauseExpectation("issuing_bank", issuing_bank),
    )
    return ScenarioDefinition(
        scenario_id=30,
        name="Random unseen injected slice",
        seed=10_030,
        start_at=start_at,
        expectation=ScenarioExpectation(
            outcome="incident", minimum_incidents=1, causes=causes
        ),
        injections=(
            _injection(
                merchant,
                country,
                provider=provider,
                payment_method=payment_method,
                issuing_bank=issuing_bank,
                target=0.30,
            ),
        ),
        notes="Fields are selected from the frozen catalogs using the scenario seed.",
    )


def _validate_catalog(scenarios: tuple[ScenarioDefinition, ...]) -> None:
    if len(scenarios) != 30:
        raise ValueError("the MVP catalog must contain exactly 30 scenarios")
    if {scenario.scenario_id for scenario in scenarios} != set(range(1, 31)):
        raise ValueError("scenario IDs must be exactly 1 through 30")
    if len({scenario.seed for scenario in scenarios}) != len(scenarios):
        raise ValueError("every scenario must have a unique deterministic seed")


SCENARIOS = build_scenarios()
