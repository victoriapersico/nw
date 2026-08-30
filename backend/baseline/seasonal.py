"""Interpretable merchant/country/hour-of-week approval baseline."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from backend.schemas import Transaction


TRAINING_MONTHS = frozenset({1, 2, 3, 4})
DEFAULT_SHRINKAGE_STRENGTH = 50.0


@dataclass(frozen=True)
class BaselineMetric:
    """Expected approval behavior for one supported seasonal bucket."""

    merchant: str
    country: str
    hour_of_week: int
    sample_size: int
    approval_rate: float
    variance: float


class SeasonalBaseline:
    """Fits only Jan-Apr transactions and answers expected conversion queries."""

    def __init__(
        self,
        minimum_volume: int,
        shrinkage_strength: float = DEFAULT_SHRINKAGE_STRENGTH,
    ) -> None:
        if minimum_volume <= 0:
            raise ValueError("minimum_volume must be greater than zero")
        if shrinkage_strength < 0:
            raise ValueError("shrinkage_strength must be non-negative")
        self.minimum_volume = minimum_volume
        self.shrinkage_strength = shrinkage_strength
        self._metrics: dict[tuple[str, str, int], BaselineMetric] = {}

    @staticmethod
    def hour_of_week(timestamp: datetime) -> int:
        """Return Monday 00:00 as 0 and Sunday 23:00 as 167."""

        return timestamp.weekday() * 24 + timestamp.hour

    def fit(self, transactions: Iterable[Transaction]) -> "SeasonalBaseline":
        """Fit from the TRAIN split only, ignoring all non-training months."""

        buckets: dict[tuple[str, str, int], list[int]] = defaultdict(list)
        parent_buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
        for transaction in transactions:
            if transaction.timestamp.month not in TRAINING_MONTHS:
                continue
            outcome = int(transaction.status == "approved")
            key = (
                transaction.merchant,
                transaction.country,
                self.hour_of_week(transaction.timestamp),
            )
            buckets[key].append(outcome)
            parent_buckets[(transaction.merchant, transaction.country)].append(outcome)

        metrics: dict[tuple[str, str, int], BaselineMetric] = {}
        for key, outcomes in buckets.items():
            if len(outcomes) < self.minimum_volume:
                continue
            parent_outcomes = parent_buckets[(key[0], key[1])]
            parent_rate = sum(parent_outcomes) / len(parent_outcomes)
            approval_rate = (
                sum(outcomes) + self.shrinkage_strength * parent_rate
            ) / (len(outcomes) + self.shrinkage_strength)
            metrics[key] = BaselineMetric(
                merchant=key[0],
                country=key[1],
                hour_of_week=key[2],
                sample_size=len(outcomes),
                approval_rate=approval_rate,
                variance=approval_rate * (1 - approval_rate),
            )
        self._metrics = metrics
        return self

    def expected_for(
        self, merchant: str, country: str, timestamp: datetime
    ) -> BaselineMetric | None:
        """Return None when a bucket lacks the agreed minimum support."""

        return self._metrics.get(
            (merchant, country, self.hour_of_week(timestamp))
        )

    @property
    def metrics(self) -> tuple[BaselineMetric, ...]:
        return tuple(self._metrics.values())
