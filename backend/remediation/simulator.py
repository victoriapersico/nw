"""Counterfactual traffic-shift estimates built from observed transaction data.

This module deliberately has no provider credentials or execution capability.
It produces a small, bounded set of alternatives for an operator to approve.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import sqrt

from backend.schemas import (
    Diagnosis,
    Incident,
    PaymentMethod,
    Provider,
    RemediationOption,
    RemediationProposal,
    RemediationSimulation,
    RoutingPolicy,
    Transaction,
    TransactionBatch,
)


ALL_PROVIDERS: tuple[Provider, ...] = ("Stripe", "Adyen", "dLocal")
SHIFT_PCTS: tuple[float, ...] = (0.25, 0.50)
MINIMUM_TARGET_SAMPLE = 50
MINIMUM_LIVE_TARGET_SAMPLE = 10
MINIMUM_CONFIDENCE = 0.65


class RemediationSimulator:
    """Evaluate approved demo alternatives using only historical/live evidence."""

    def __init__(
        self,
        historical_transactions: Iterable[Transaction],
        policies: Iterable[RoutingPolicy] | None = None,
    ) -> None:
        self._history = tuple(historical_transactions)
        self._policies = tuple(policies or _default_policies())

    def propose(
        self,
        incident: Incident,
        diagnosis: Diagnosis,
        recent_batches: Sequence[TransactionBatch],
    ) -> RemediationProposal:
        """Return a recommendation only when a provider route is supported by RCA."""

        if diagnosis.diagnosis_status != "confirmed":
            return self._not_recommended(
                incident,
                "No routing change is simulated because RCA did not confirm a supported cause.",
            )

        affected_provider = _evidence_value(diagnosis, "provider", ALL_PROVIDERS)
        if affected_provider is None:
            return self._not_recommended(
                incident,
                "No provider-level cause was isolated, so routing alternatives are unsafe to recommend.",
            )
        affected_method = _evidence_value(
            diagnosis, "payment_method", ("CARD", "PIX", "PSE", "OXXO")
        )
        policy = self._policy_for(incident, affected_method)
        if policy is None:
            return self._not_recommended(
                incident,
                "No eligible routing policy exists for this merchant and country.",
            )
        source = _source_transactions(
            incident, recent_batches, affected_provider, affected_method
        )
        if not source:
            return self._not_recommended(
                incident,
                "Recent live transactions do not support a route-level simulation.",
            )

        window_minutes = _window_minutes(recent_batches)
        if window_minutes <= 0:
            return self._not_recommended(incident, "The live-window duration is unavailable.")

        alternatives = []
        for target in policy.eligible_target_providers:
            if target == affected_provider:
                continue
            for shift_pct in SHIFT_PCTS:
                if shift_pct > policy.max_traffic_shift_pct:
                    continue
                alternatives.append(
                    self._simulate_option(
                        incident=incident,
                        source=source,
                        recent_batches=recent_batches,
                        window_minutes=window_minutes,
                        target_provider=target,
                        payment_method=affected_method,
                        shift_pct=shift_pct,
                    )
                )

        eligible = [item for item in alternatives if item.status == "eligible"]
        if not eligible:
            return RemediationProposal(
                recommendation_id=f"rec-{incident.incident_id}",
                incident_id=incident.incident_id,
                policy_id=policy.policy_id,
                status="not_recommended",
                alternatives=alternatives,
                rationale="No eligible alternative has enough healthy historical evidence.",
            )

        best = max(
            eligible,
            key=lambda item: (
                item.expected_recovered_value_per_hour * item.confidence,
                -item.option.traffic_shift_pct,
                item.option.target_provider,
            ),
        )
        return RemediationProposal(
            recommendation_id=f"rec-{incident.incident_id}",
            incident_id=incident.incident_id,
            policy_id=policy.policy_id,
            status="recommended",
            recommended_option_id=best.option.option_id,
            alternatives=alternatives,
            rationale=(
                f"{best.option.target_provider} has the strongest eligible historical "
                "approval estimate after confidence adjustment."
            ),
            rollback_condition=(
                "Do not execute automatically. If approved, roll back the temporary "
                "change when target-route approval falls below 80% for two consecutive "
                "five-minute windows."
            ),
            rollback_reference=f"rollback-{incident.incident_id}",
        )

    def policy_for_id(self, policy_id: str) -> RoutingPolicy | None:
        """Expose the frozen policy for a final activation-time guardrail check."""

        return next((policy for policy in self._policies if policy.policy_id == policy_id), None)

    def _policy_for(
        self, incident: Incident, payment_method: str | None
    ) -> RoutingPolicy | None:
        candidates = [
            policy
            for policy in self._policies
            if policy.merchant == incident.merchant
            and policy.country == incident.country
            and (policy.payment_method is None or policy.payment_method == payment_method)
        ]
        return next(
            (policy for policy in candidates if policy.payment_method == payment_method),
            next((policy for policy in candidates if policy.payment_method is None), None),
        )

    def _simulate_option(
        self,
        *,
        incident: Incident,
        source: Sequence[Transaction],
        recent_batches: Sequence[TransactionBatch],
        window_minutes: float,
        target_provider: Provider,
        payment_method: str | None,
        shift_pct: float,
    ) -> RemediationSimulation:
        option = RemediationOption(
            option_id=f"{incident.incident_id}:{target_provider}:{int(shift_pct * 100)}",
            target_provider=target_provider,
            traffic_shift_pct=shift_pct,
        )
        history = [
            item
            for item in self._history
            if item.merchant == incident.merchant
            and item.country == incident.country
            and item.provider == target_provider
            and (payment_method is None or item.payment_method == payment_method)
        ]
        if len(history) < MINIMUM_TARGET_SAMPLE:
            return _blocked(
                option,
                "inconclusive",
                "The target route has insufficient historical sample size.",
            )

        target_live = [
            item
            for batch in recent_batches
            for item in batch.transactions
            if item.merchant == incident.merchant
            and item.country == incident.country
            and item.provider == target_provider
            and (payment_method is None or item.payment_method == payment_method)
        ]
        if len(target_live) >= MINIMUM_LIVE_TARGET_SAMPLE and _approval_rate(target_live) < 0.75:
            return _blocked(
                option,
                "blocked",
                "The target route is currently unhealthy in the observed live windows.",
            )

        target_rate = _approval_rate(history)
        source_rate = _approval_rate(source)
        average_amount = sum(item.amount for item in source) / len(source)
        attempts_per_hour = len(source) * 60 / window_minutes
        recovered = max(
            0.0,
            attempts_per_hour * shift_pct * (target_rate - source_rate) * average_amount,
        )
        confidence = _confidence(history, target_rate)
        if confidence < MINIMUM_CONFIDENCE:
            return _blocked(
                option,
                "inconclusive",
                "The target route estimate does not meet the minimum confidence threshold.",
            )
        if recovered <= 0:
            return _blocked(
                option,
                "blocked",
                "The target route does not improve the observed approval rate.",
            )
        method_note = payment_method or "all affected payment methods"
        return RemediationSimulation(
            option=option,
            status="eligible",
            expected_approval_rate=target_rate,
            expected_recovered_value_per_hour=recovered,
            expected_incremental_cost_per_hour=0.0,
            confidence=confidence,
            assumptions=[
                f"Historical {method_note} performance represents the target route.",
                "No provider fee or capacity data is available in this MVP estimate.",
            ],
            risks=[
                "Recommendation only; merchant approval is required.",
                "Historical performance may not match a live provider outage.",
            ],
        )

    @staticmethod
    def _not_recommended(incident: Incident, rationale: str) -> RemediationProposal:
        return RemediationProposal(
            recommendation_id=f"rec-{incident.incident_id}",
            incident_id=incident.incident_id,
            policy_id="no-eligible-policy",
            status="not_recommended",
            alternatives=[],
            rationale=rationale,
        )


def _evidence_value(
    diagnosis: Diagnosis, dimension: str, allowed: Sequence[str]
) -> str | None:
    """Read a direct or intersection value without trusting free-form narration."""

    for item in diagnosis.evidence:
        if item.dimension == dimension and item.value in allowed:
            return item.value
    for item in diagnosis.evidence:
        if item.dimension == "intersection":
            values = item.value.split(" × ")
            for value in values:
                if value in allowed:
                    return value
    return None


def _source_transactions(
    incident: Incident,
    batches: Sequence[TransactionBatch],
    provider: str,
    payment_method: str | None,
) -> list[Transaction]:
    return [
        item
        for batch in batches
        for item in batch.transactions
        if item.merchant == incident.merchant
        and item.country == incident.country
        and item.provider == provider
        and (payment_method is None or item.payment_method == payment_method)
    ]


def _window_minutes(batches: Sequence[TransactionBatch]) -> float:
    return sum(
        (batch.window_end - batch.window_start).total_seconds() / 60 for batch in batches
    )


def _approval_rate(transactions: Sequence[Transaction]) -> float:
    return sum(item.status == "approved" for item in transactions) / len(transactions)


def _confidence(history: Sequence[Transaction], target_rate: float) -> float:
    sample_support = min(1.0, sqrt(len(history) / 200))
    stability = 1.0 - min(1.0, (target_rate * (1 - target_rate)) / 0.25)
    return min(0.95, 0.45 + 0.40 * sample_support + 0.15 * stability)


def _blocked(
    option: RemediationOption, status: str, reason: str
) -> RemediationSimulation:
    return RemediationSimulation(
        option=option,
        status=status,
        expected_recovered_value_per_hour=0.0,
        expected_incremental_cost_per_hour=0.0,
        confidence=0.0,
        rejection_reason=reason,
    )


def _default_policies() -> tuple[RoutingPolicy, ...]:
    """Demo defaults: only 25%/50% dry-runs, never provider execution."""

    return tuple(
        RoutingPolicy(
            policy_id=f"default-{merchant.lower()}-{country.lower()}",
            merchant=merchant,
            country=country,
            eligible_target_providers=list(ALL_PROVIDERS),
            max_traffic_shift_pct=0.50,
            dry_run_only=True,
            execution_enabled=False,
        )
        for merchant in ("Rappi", "Carrefour", "Despegar")
        for country in ("Mexico", "Brazil", "Colombia")
    )
