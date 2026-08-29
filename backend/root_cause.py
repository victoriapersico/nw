"""Deterministic root-cause analysis for detected payment incidents."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import ceil, sqrt
from typing import Iterable, Sequence

from backend.baseline.seasonal import TRAINING_MONTHS, SeasonalBaseline
from backend.detector.impact import calculate_money_impact
from backend.schemas import Diagnosis, EvidenceItem, Incident, Transaction, TransactionBatch


DimensionTuple = tuple[str, ...]
ValueTuple = tuple[str, ...]

SINGLE_DIMENSIONS: tuple[DimensionTuple, ...] = (
    ("provider",),
    ("payment_method",),
    ("issuing_bank",),
)
INTERSECTION_DIMENSIONS: tuple[DimensionTuple, ...] = (
    ("provider", "payment_method"),
    ("provider", "issuing_bank"),
    ("provider", "payment_method", "issuing_bank"),
)
HISTORICAL_GROUPINGS: tuple[DimensionTuple, ...] = (
    (),
    *SINGLE_DIMENSIONS,
    *INTERSECTION_DIMENSIONS,
)
DIMENSION_ORDER = {"provider": 0, "payment_method": 1, "issuing_bank": 2}


@dataclass(frozen=True, slots=True)
class RootCauseConfig:
    """Small, explicit evidence thresholds used by the MVP RCA."""

    minimum_historical_sample: int = 50
    minimum_live_sample: int = 10
    minimum_live_parent_share: float = 0.05
    minimum_approval_drop: float = 0.08
    z_score_threshold: float = -3.0
    minimum_explained_loss_share: float = 0.50
    minimum_family_dominance: float = 0.60
    specificity_retention: float = 0.80
    minimum_competing_loss_share: float = 0.10
    minimum_confidence: float = 0.65
    minimum_historical_declines: int = 20
    minimum_live_declines: int = 10
    minimum_decline_share_increase: float = 0.10
    minimum_decline_code_explained_share: float = 0.20
    decline_code_z_threshold: float = 3.0

    def __post_init__(self) -> None:
        positive_integers = (
            self.minimum_historical_sample,
            self.minimum_live_sample,
            self.minimum_historical_declines,
            self.minimum_live_declines,
        )
        if any(value <= 0 for value in positive_integers):
            raise ValueError("RCA sample thresholds must be greater than zero")
        probabilities = (
            self.minimum_live_parent_share,
            self.minimum_approval_drop,
            self.minimum_explained_loss_share,
            self.minimum_family_dominance,
            self.specificity_retention,
            self.minimum_competing_loss_share,
            self.minimum_confidence,
            self.minimum_decline_share_increase,
            self.minimum_decline_code_explained_share,
        )
        if any(not 0 < value <= 1 for value in probabilities):
            raise ValueError("RCA probability thresholds must be in (0, 1]")
        if self.z_score_threshold >= 0:
            raise ValueError("z_score_threshold must be negative")
        if self.decline_code_z_threshold <= 0:
            raise ValueError("decline_code_z_threshold must be positive")


@dataclass(slots=True)
class _HistoricalAggregate:
    attempts: int = 0
    approvals: int = 0
    decline_count: int = 0
    decline_code_counts: dict[str, int] = field(default_factory=dict)

    def add(self, transaction: Transaction) -> None:
        self.attempts += 1
        if transaction.status == "approved":
            self.approvals += 1
            return
        self.decline_count += 1
        code = transaction.decline_code
        if code is None:  # Transaction validation normally makes this unreachable.
            return
        self.decline_code_counts[code] = self.decline_code_counts.get(code, 0) + 1

    @property
    def approval_rate(self) -> float:
        return self.approvals / self.attempts


@dataclass(frozen=True, slots=True)
class _HistoricalComparison:
    expected_rate: float
    sample_size: int
    source: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    dimensions: DimensionTuple
    values: ValueTuple
    baseline_rate: float
    live_rate: float
    sample_size: int
    historical_sample_size: int
    approval_drop: float
    z_score: float
    excess_failures: float
    excess_loss: float
    explained_loss_share: float
    historical_source: str
    eligible: bool

    @property
    def label(self) -> str:
        return " × ".join(self.values)

    def to_evidence(self) -> EvidenceItem:
        dimension = self.dimensions[0] if len(self.dimensions) == 1 else "intersection"
        return EvidenceItem(
            dimension=dimension,
            value=self.label,
            baseline_metric=self.baseline_rate,
            live_metric=self.live_rate,
            delta=self.live_rate - self.baseline_rate,
            sample_size=self.sample_size,
            explained_loss_share=self.explained_loss_share,
        )


@dataclass(frozen=True, slots=True)
class _CodeCandidate:
    code: str
    baseline_share: float
    live_share: float
    sample_size: int
    z_score: float
    explained_loss_share: float

    def to_evidence(self) -> EvidenceItem:
        return EvidenceItem(
            dimension="decline_code",
            value=self.code,
            baseline_metric=self.baseline_share,
            live_metric=self.live_share,
            delta=self.live_share - self.baseline_share,
            sample_size=self.sample_size,
            explained_loss_share=self.explained_loss_share,
        )


class RootCauseAnalyzer:
    """Fit normal slice behavior once, then diagnose incidents from live windows."""

    def __init__(
        self,
        historical_transactions: Iterable[Transaction],
        config: RootCauseConfig | None = None,
    ) -> None:
        self.config = config or RootCauseConfig()
        self._seasonal: dict[
            tuple[str, str, int, DimensionTuple, ValueTuple], _HistoricalAggregate
        ] = defaultdict(_HistoricalAggregate)
        self._global: dict[
            tuple[str, str, DimensionTuple, ValueTuple], _HistoricalAggregate
        ] = defaultdict(_HistoricalAggregate)
        self._fit(historical_transactions)

    def diagnose(
        self,
        incident: Incident,
        recent_batches: Sequence[TransactionBatch],
    ) -> Diagnosis:
        """Return deterministic evidence from up to two incident-context windows."""

        context = self._incident_context(incident, recent_batches)
        if not context:
            return self._insufficient(
                incident,
                explanation="Recent live windows for this incident are unavailable.",
            )

        live_transactions = tuple(
            transaction
            for batch in context
            for transaction in batch.transactions
            if transaction.merchant == incident.merchant
            and transaction.country == incident.country
        )
        if not live_transactions:
            return self._insufficient(
                incident,
                explanation="No live transactions match the incident scope.",
            )

        window_minutes = sum(
            (batch.window_end - batch.window_start).total_seconds() / 60
            for batch in context
        )
        parent_impact = calculate_money_impact(
            live_transactions,
            expected_conversion=incident.expected_conversion,
            window_minutes=window_minutes,
        )
        if parent_impact.estimated_loss <= 0:
            return self._insufficient(
                incident,
                explanation="The available live context has no measurable excess loss.",
            )

        hour_of_week = SeasonalBaseline.hour_of_week(context[-1].window_start)
        evaluated = self._evaluate_candidates(
            incident=incident,
            live_transactions=live_transactions,
            hour_of_week=hour_of_week,
            window_minutes=window_minutes,
            parent_loss=parent_impact.estimated_loss,
        )

        primary: _Candidate | None = None
        family_dominance = 0.0
        selection_reason = "No supported candidate root cause was found."
        merchant_wide = self._is_uniform_merchant_degradation(evaluated)
        if not merchant_wide:
            primary, family_dominance, selection_reason = self._select_primary(evaluated)

        code_filters = (
            (primary.dimensions, primary.values) if primary is not None else ((), ())
        )
        code_candidate = self._decline_code_candidate(
            incident=incident,
            live_transactions=live_transactions,
            dimensions=code_filters[0],
            values=code_filters[1],
            hour_of_week=hour_of_week,
            parent_loss=parent_impact.estimated_loss,
        )

        if merchant_wide:
            parent_candidate = self._parent_candidate(
                incident,
                live_transactions,
                parent_impact.estimated_loss,
            )
            confidence = self._candidate_confidence(parent_candidate, 1.0)
            evidence = [parent_candidate.to_evidence()]
            dimensions = ["merchant"]
            if code_candidate is not None:
                evidence.append(code_candidate.to_evidence())
                dimensions.append("decline_code")
                confidence = max(confidence, self._code_confidence(code_candidate))
            if confidence >= self.config.minimum_confidence:
                return self._confirmed(
                    incident,
                    dimensions=dimensions,
                    evidence=evidence,
                    confidence=confidence,
                    label=incident.merchant,
                    code_candidate=code_candidate,
                    merchant_wide=True,
                )

        if primary is not None:
            confidence = self._candidate_confidence(primary, family_dominance)
            evidence = self._supporting_evidence(primary, evaluated)
            evidence.append(
                self._parent_candidate(
                    incident,
                    live_transactions,
                    parent_impact.estimated_loss,
                ).to_evidence()
            )
            dimensions = list(primary.dimensions)
            if code_candidate is not None:
                evidence.append(code_candidate.to_evidence())
                dimensions.append("decline_code")
                confidence = max(confidence, self._code_confidence(code_candidate))
            if confidence >= self.config.minimum_confidence:
                return self._confirmed(
                    incident,
                    dimensions=dimensions,
                    evidence=evidence,
                    confidence=confidence,
                    label=primary.label,
                    code_candidate=code_candidate,
                )

        if code_candidate is not None:
            code_confidence = self._code_confidence(code_candidate)
            if (
                code_candidate.explained_loss_share
                >= self.config.minimum_explained_loss_share
                and code_confidence >= self.config.minimum_confidence
            ):
                return self._confirmed(
                    incident,
                    dimensions=["decline_code"],
                    evidence=[code_candidate.to_evidence()],
                    confidence=code_confidence,
                    label=f"decline code {code_candidate.code}",
                    code_candidate=code_candidate,
                )

        ambiguous_evidence = [
            candidate.to_evidence()
            for candidate in sorted(evaluated, key=self._candidate_sort_key)
            if candidate.eligible
        ][:5]
        if code_candidate is not None:
            ambiguous_evidence.append(code_candidate.to_evidence())
        return self._insufficient(
            incident,
            evidence=ambiguous_evidence,
            confidence=min(
                self.config.minimum_confidence - 0.01,
                max(
                    [0.0]
                    + [
                        self._candidate_confidence(candidate, 0.0)
                        for candidate in evaluated
                        if candidate.eligible
                    ]
                ),
            ),
            explanation=selection_reason,
        )

    def _fit(self, historical_transactions: Iterable[Transaction]) -> None:
        for transaction in historical_transactions:
            if not isinstance(transaction, Transaction):
                raise TypeError("historical_transactions must contain Transaction objects")
            if transaction.timestamp.month not in TRAINING_MONTHS:
                continue
            hour_of_week = SeasonalBaseline.hour_of_week(transaction.timestamp)
            for dimensions in HISTORICAL_GROUPINGS:
                values = self._values_for(transaction, dimensions)
                self._global[
                    (transaction.merchant, transaction.country, dimensions, values)
                ].add(transaction)
                self._seasonal[
                    (
                        transaction.merchant,
                        transaction.country,
                        hour_of_week,
                        dimensions,
                        values,
                    )
                ].add(transaction)

    def _evaluate_candidates(
        self,
        *,
        incident: Incident,
        live_transactions: tuple[Transaction, ...],
        hour_of_week: int,
        window_minutes: float,
        parent_loss: float,
    ) -> list[_Candidate]:
        minimum_live = max(
            self.config.minimum_live_sample,
            ceil(len(live_transactions) * self.config.minimum_live_parent_share),
        )
        candidates: list[_Candidate] = []
        for dimensions in (*SINGLE_DIMENSIONS, *INTERSECTION_DIMENSIONS):
            groups: dict[ValueTuple, list[Transaction]] = defaultdict(list)
            for transaction in live_transactions:
                groups[self._values_for(transaction, dimensions)].append(transaction)
            for values, transactions in sorted(groups.items()):
                if len(transactions) < minimum_live:
                    continue
                historical = self._historical_approval(
                    incident,
                    dimensions,
                    values,
                    hour_of_week,
                )
                if historical is None:
                    continue
                live_rate = sum(
                    transaction.status == "approved" for transaction in transactions
                ) / len(transactions)
                approval_drop = historical.expected_rate - live_rate
                variance = max(
                    historical.expected_rate * (1 - historical.expected_rate), 1e-6
                )
                z_score = (live_rate - historical.expected_rate) / sqrt(
                    variance / len(transactions)
                )
                impact = calculate_money_impact(
                    transactions,
                    expected_conversion=historical.expected_rate,
                    window_minutes=window_minutes,
                )
                explained_share = min(1.0, impact.estimated_loss / parent_loss)
                eligible = (
                    approval_drop >= self.config.minimum_approval_drop
                    and z_score <= self.config.z_score_threshold
                )
                candidates.append(
                    _Candidate(
                        dimensions=dimensions,
                        values=values,
                        baseline_rate=historical.expected_rate,
                        live_rate=live_rate,
                        sample_size=len(transactions),
                        historical_sample_size=historical.sample_size,
                        approval_drop=approval_drop,
                        z_score=z_score,
                        excess_failures=max(0.0, approval_drop * len(transactions)),
                        excess_loss=impact.estimated_loss,
                        explained_loss_share=explained_share,
                        historical_source=historical.source,
                        eligible=eligible,
                    )
                )
        return candidates

    def _historical_approval(
        self,
        incident: Incident,
        dimensions: DimensionTuple,
        values: ValueTuple,
        hour_of_week: int,
    ) -> _HistoricalComparison | None:
        seasonal_parent = self._seasonal.get(
            (incident.merchant, incident.country, hour_of_week, (), ())
        )
        seasonal_slice = self._seasonal.get(
            (incident.merchant, incident.country, hour_of_week, dimensions, values)
        )
        minimum = self.config.minimum_historical_sample
        if (
            seasonal_parent is not None
            and seasonal_slice is not None
            and seasonal_parent.attempts >= minimum
            and seasonal_slice.attempts >= minimum
        ):
            expected = self._contextual_expected_rate(
                incident.expected_conversion,
                seasonal_slice.approval_rate,
                seasonal_parent.approval_rate,
            )
            return _HistoricalComparison(expected, seasonal_slice.attempts, "hour_of_week")

        global_parent = self._global.get(
            (incident.merchant, incident.country, (), ())
        )
        global_slice = self._global.get(
            (incident.merchant, incident.country, dimensions, values)
        )
        if (
            global_parent is None
            or global_slice is None
            or global_parent.attempts < minimum
            or global_slice.attempts < minimum
        ):
            return None
        expected = self._contextual_expected_rate(
            incident.expected_conversion,
            global_slice.approval_rate,
            global_parent.approval_rate,
        )
        return _HistoricalComparison(expected, global_slice.attempts, "jan_apr_global")

    @staticmethod
    def _contextual_expected_rate(
        incident_expected: float,
        historical_slice_rate: float,
        historical_parent_rate: float,
    ) -> float:
        return min(
            1.0,
            max(
                0.0,
                incident_expected + historical_slice_rate - historical_parent_rate,
            ),
        )

    def _select_primary(
        self, candidates: list[_Candidate]
    ) -> tuple[_Candidate | None, float, str]:
        hypotheses: list[tuple[_Candidate, float]] = []
        for dimensions in SINGLE_DIMENSIONS:
            family = [candidate for candidate in candidates if candidate.dimensions == dimensions]
            if not family:
                continue
            family_loss = sum(candidate.excess_loss for candidate in family)
            if family_loss <= 0:
                continue
            strongest = max(family, key=lambda candidate: candidate.excess_loss)
            dominance = strongest.excess_loss / family_loss
            if strongest.eligible and dominance >= self.config.minimum_family_dominance:
                hypotheses.append((strongest, dominance))

        if not hypotheses:
            return None, 0.0, "No candidate slice dominates its peer group."

        hypotheses.sort(key=lambda item: self._candidate_sort_key(item[0]))
        if len(hypotheses) > 1:
            unified = self._unifying_candidate(hypotheses, candidates)
            if unified is None:
                return (
                    None,
                    0.0,
                    "Multiple candidate causes are plausible and no supported "
                    "intersection isolates one.",
                )
            primary = unified
            dominance = min(item[1] for item in hypotheses)
        else:
            primary, dominance = hypotheses[0]
            refinements = [
                candidate
                for candidate in candidates
                if candidate.eligible
                and self._extends(candidate, primary)
                and candidate.excess_loss
                >= primary.excess_loss * self.config.specificity_retention
            ]
            if refinements:
                primary = sorted(
                    refinements,
                    key=lambda candidate: (
                        -len(candidate.dimensions),
                        *self._candidate_sort_key(candidate),
                    ),
                )[0]

        if (
            primary.explained_loss_share
            < self.config.minimum_explained_loss_share
        ):
            return (
                None,
                dominance,
                "The strongest candidate explains too little of the incident loss.",
            )
        if self._has_competing_candidate(primary, candidates):
            return (
                None,
                dominance,
                "A material degraded slice remains outside the leading candidate cause.",
            )
        return primary, dominance, "A supported root cause was isolated."

    def _unifying_candidate(
        self,
        hypotheses: list[tuple[_Candidate, float]],
        candidates: list[_Candidate],
    ) -> _Candidate | None:
        filters: dict[str, str] = {}
        for hypothesis, _ in hypotheses:
            for dimension, value in zip(
                hypothesis.dimensions, hypothesis.values, strict=True
            ):
                existing = filters.get(dimension)
                if existing is not None and existing != value:
                    return None
                filters[dimension] = value
        dimensions = tuple(sorted(filters, key=DIMENSION_ORDER.__getitem__))
        values = tuple(filters[dimension] for dimension in dimensions)
        matches = [
            candidate
            for candidate in candidates
            if candidate.dimensions == dimensions
            and candidate.values == values
            and candidate.eligible
            and all(
                candidate.excess_loss
                >= hypothesis.excess_loss * self.config.specificity_retention
                for hypothesis, _ in hypotheses
            )
        ]
        return sorted(matches, key=self._candidate_sort_key)[0] if matches else None

    def _is_uniform_merchant_degradation(self, candidates: list[_Candidate]) -> bool:
        for dimensions in SINGLE_DIMENSIONS:
            family = [candidate for candidate in candidates if candidate.dimensions == dimensions]
            if len(family) < 2 or not all(candidate.eligible for candidate in family):
                return False
        return True

    def _has_competing_candidate(
        self,
        primary: _Candidate,
        candidates: list[_Candidate],
    ) -> bool:
        primary_filters = dict(zip(primary.dimensions, primary.values, strict=True))
        for candidate in candidates:
            if not candidate.eligible or candidate == primary:
                continue
            if (
                candidate.explained_loss_share
                < self.config.minimum_competing_loss_share
            ):
                continue
            candidate_filters = dict(
                zip(candidate.dimensions, candidate.values, strict=True)
            )
            if any(
                dimension in candidate_filters
                and candidate_filters[dimension] != value
                for dimension, value in primary_filters.items()
            ):
                return True
        return False

    def _decline_code_candidate(
        self,
        *,
        incident: Incident,
        live_transactions: tuple[Transaction, ...],
        dimensions: DimensionTuple,
        values: ValueTuple,
        hour_of_week: int,
        parent_loss: float,
    ) -> _CodeCandidate | None:
        filtered = [
            transaction
            for transaction in live_transactions
            if all(
                getattr(transaction, dimension) == value
                for dimension, value in zip(dimensions, values, strict=True)
            )
        ]
        declines = [transaction for transaction in filtered if transaction.status == "declined"]
        if len(declines) < self.config.minimum_live_declines:
            return None

        historical = self._historical_declines(
            incident,
            dimensions,
            values,
            hour_of_week,
        )
        if historical is None:
            return None

        total_declined_amount = sum(transaction.amount for transaction in declines)
        candidates: list[_CodeCandidate] = []
        codes = sorted(
            {
                transaction.decline_code
                for transaction in declines
                if transaction.decline_code
            }
        )
        for code in codes:
            baseline_share = historical.decline_code_counts.get(code, 0) / historical.decline_count
            matching = [transaction for transaction in declines if transaction.decline_code == code]
            live_share = len(matching) / len(declines)
            delta = live_share - baseline_share
            variance = max(baseline_share * (1 - baseline_share), 1e-6)
            z_score = delta / sqrt(variance / len(declines))
            excess_amount = max(
                0.0,
                sum(transaction.amount for transaction in matching)
                - baseline_share * total_declined_amount,
            )
            explained_share = min(1.0, excess_amount / parent_loss)
            if (
                delta >= self.config.minimum_decline_share_increase
                and z_score >= self.config.decline_code_z_threshold
                and explained_share
                >= self.config.minimum_decline_code_explained_share
            ):
                candidates.append(
                    _CodeCandidate(
                        code=code,
                        baseline_share=baseline_share,
                        live_share=live_share,
                        sample_size=len(declines),
                        z_score=z_score,
                        explained_loss_share=explained_share,
                    )
                )
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda candidate: (
                -candidate.explained_loss_share,
                -(candidate.live_share - candidate.baseline_share),
                -candidate.z_score,
                candidate.code,
            ),
        )[0]

    def _historical_declines(
        self,
        incident: Incident,
        dimensions: DimensionTuple,
        values: ValueTuple,
        hour_of_week: int,
    ) -> _HistoricalAggregate | None:
        seasonal = self._seasonal.get(
            (incident.merchant, incident.country, hour_of_week, dimensions, values)
        )
        if (
            seasonal is not None
            and seasonal.decline_count >= self.config.minimum_historical_declines
        ):
            return seasonal
        broad = self._global.get(
            (incident.merchant, incident.country, dimensions, values)
        )
        if (
            broad is not None
            and broad.decline_count >= self.config.minimum_historical_declines
        ):
            return broad
        return None

    def _parent_candidate(
        self,
        incident: Incident,
        live_transactions: tuple[Transaction, ...],
        parent_loss: float,
    ) -> _Candidate:
        live_rate = sum(
            transaction.status == "approved" for transaction in live_transactions
        ) / len(live_transactions)
        variance = max(
            incident.expected_conversion * (1 - incident.expected_conversion), 1e-6
        )
        z_score = (live_rate - incident.expected_conversion) / sqrt(
            variance / len(live_transactions)
        )
        return _Candidate(
            dimensions=("merchant",),
            values=(incident.merchant,),
            baseline_rate=incident.expected_conversion,
            live_rate=live_rate,
            sample_size=len(live_transactions),
            historical_sample_size=0,
            approval_drop=incident.expected_conversion - live_rate,
            z_score=z_score,
            excess_failures=max(
                0.0,
                (incident.expected_conversion - live_rate) * len(live_transactions),
            ),
            excess_loss=parent_loss,
            explained_loss_share=1.0,
            historical_source="incident",
            eligible=True,
        )

    def _supporting_evidence(
        self, primary: _Candidate, candidates: list[_Candidate]
    ) -> list[EvidenceItem]:
        supporting = [
            candidate
            for candidate in candidates
            if candidate.eligible
            and (
                candidate == primary
                or self._extends(primary, candidate)
            )
        ]
        supporting.sort(
            key=lambda candidate: (
                candidate != primary,
                -len(candidate.dimensions),
                *self._candidate_sort_key(candidate),
            )
        )
        return [candidate.to_evidence() for candidate in supporting[:8]]

    @staticmethod
    def _extends(child: _Candidate, parent: _Candidate) -> bool:
        if len(child.dimensions) <= len(parent.dimensions):
            return False
        child_filters = dict(zip(child.dimensions, child.values, strict=True))
        return all(
            child_filters.get(dimension) == value
            for dimension, value in zip(parent.dimensions, parent.values, strict=True)
        )

    @staticmethod
    def _candidate_sort_key(candidate: _Candidate) -> tuple[float, float, int, str]:
        return (
            -candidate.explained_loss_share,
            candidate.z_score,
            -len(candidate.dimensions),
            candidate.label,
        )

    def _candidate_confidence(self, candidate: _Candidate, dominance: float) -> float:
        statistical_strength = min(1.0, abs(candidate.z_score) / 6)
        return min(
            1.0,
            0.50 * candidate.explained_loss_share
            + 0.25 * statistical_strength
            + 0.25 * dominance,
        )

    def _code_confidence(self, candidate: _CodeCandidate) -> float:
        statistical_strength = min(1.0, candidate.z_score / 6)
        support = min(1.0, candidate.sample_size / 50)
        return min(
            1.0,
            0.55 * candidate.explained_loss_share
            + 0.30 * statistical_strength
            + 0.15 * support,
        )

    @staticmethod
    def _incident_context(
        incident: Incident,
        recent_batches: Sequence[TransactionBatch],
    ) -> tuple[TransactionBatch, ...]:
        by_end = {batch.window_end: batch for batch in recent_batches}
        current = by_end.get(incident.detected_at)
        if current is None:
            return ()
        previous = by_end.get(current.window_start)
        return (previous, current) if previous is not None else (current,)

    @staticmethod
    def _values_for(
        transaction: Transaction, dimensions: DimensionTuple
    ) -> ValueTuple:
        return tuple(str(getattr(transaction, dimension)) for dimension in dimensions)

    @staticmethod
    def _confirmed(
        incident: Incident,
        *,
        dimensions: list[str],
        evidence: list[EvidenceItem],
        confidence: float,
        label: str,
        code_candidate: _CodeCandidate | None,
        merchant_wide: bool = False,
    ) -> Diagnosis:
        if merchant_wide:
            explanation = f"Approval degradation is broad across {label} traffic."
        else:
            explanation = f"Approval degradation is concentrated in {label}."
        if code_candidate is not None:
            explanation = (
                f"{explanation[:-1]}; decline code {code_candidate.code} increased."
            )
        return Diagnosis(
            incident_id=incident.incident_id,
            root_cause_dimensions=dimensions,
            evidence=evidence,
            confidence=confidence,
            diagnosis_status="confirmed",
            explanation=explanation,
            recommended_action="Investigate the affected payment route.",
        )

    @staticmethod
    def _insufficient(
        incident: Incident,
        *,
        evidence: Sequence[EvidenceItem] = (),
        confidence: float = 0.0,
        explanation: str,
    ) -> Diagnosis:
        return Diagnosis(
            incident_id=incident.incident_id,
            root_cause_dimensions=[],
            evidence=list(evidence),
            confidence=max(0.0, min(confidence, 1.0)),
            diagnosis_status="insufficient_evidence",
            explanation=explanation,
            recommended_action="Investigate the affected payment route.",
        )
