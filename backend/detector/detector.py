"""Interpretable seasonal anomaly detector."""

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt
from typing import Iterable

from backend.baseline.seasonal import SeasonalBaseline
from backend.detector.config import DetectorConfig
from backend.detector.impact import calculate_money_impact
from backend.schemas import Incident, Transaction, TransactionBatch


@dataclass(frozen=True)
class WindowMetrics:
    """Aggregated live behavior for one merchant-country slice."""

    merchant: str
    country: str
    transaction_count: int
    actual_conversion: float
    expected_conversion: float
    conversion_drop_pp: float
    z_score: float


class AnomalyDetector:
    """Detect persistent merchant-country conversion degradation."""

    def __init__(
        self,
        baseline: SeasonalBaseline,
        config: DetectorConfig,
        window_minutes: int,
    ) -> None:
        if window_minutes <= 0:
            raise ValueError("window_minutes must be greater than zero")

        self.baseline = baseline
        self.config = config
        self.window_minutes = window_minutes
        self._consecutive_matches: dict[tuple[str, str], int] = defaultdict(int)

    @staticmethod
    def _group_transactions(
        transactions: Iterable[Transaction],
    ) -> dict[tuple[str, str], list[Transaction]]:
        """Group a live window into independent merchant-country slices."""

        groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)

        for transaction in transactions:
            key = (transaction.merchant, transaction.country)
            groups[key].append(transaction)

        return dict(groups)

    def _calculate_metrics(
        self,
        merchant: str,
        country: str,
        transactions: list[Transaction],
        batch: TransactionBatch,
    ) -> WindowMetrics | None:
        """Compare one live merchant-country group with its seasonal
        baseline."""

        baseline_metric = self.baseline.expected_for(
            merchant=merchant,
            country=country,
            timestamp=batch.window_start,
        )

        if baseline_metric is None:
            return None

        transaction_count = len(transactions)
        actual_conversion = (
            sum(
                transaction.status == "approved"
                for transaction in transactions
            )
            / transaction_count
        )
        expected_conversion = baseline_metric.approval_rate
        conversion_drop_pp = (
            expected_conversion - actual_conversion
        ) * 100

        variance = max(baseline_metric.variance, 1e-6)
        standard_error = sqrt(variance / transaction_count)
        z_score = (
            actual_conversion - expected_conversion
        ) / standard_error

        return WindowMetrics(
            merchant=merchant,
            country=country,
            transaction_count=transaction_count,
            actual_conversion=actual_conversion,
            expected_conversion=expected_conversion,
            conversion_drop_pp=conversion_drop_pp,
            z_score=z_score,
        )

    def _meets_anomaly_thresholds(
        self,
        metrics: WindowMetrics,
    ) -> bool:
        """Return whether one live group is statistically anomalous."""

        return (
            metrics.transaction_count >= self.config.minimum_volume
            and (
                metrics.conversion_drop_pp / 100
                >= self.config.minimum_absolute_drop
            )
            and metrics.z_score <= self.config.z_score_threshold
        )

    def _is_persistent(
        self,
        metrics: WindowMetrics,
        is_anomaly: bool,
    ) -> bool:
        """Track consecutive anomalous windows for one merchant-country
        group."""

        key = (metrics.merchant, metrics.country)

        if not is_anomaly:
            self._consecutive_matches[key] = 0
            return False

        self._consecutive_matches[key] += 1

        return (
            self._consecutive_matches[key] == self.config.consecutive_windows
        )

    @staticmethod
    def _severity_for(conversion_drop_pp: float) -> str:
        """Assign an initial severity from the measured conversion drop."""

        if conversion_drop_pp >= 30:
            return "critical"

        if conversion_drop_pp >= 20:
            return "high"

        if conversion_drop_pp >= 12:
            return "medium"

        return "low"
    
    def detect(self, batch: TransactionBatch) -> list[Incident]:
        """Return newly confirmed incidents for one live transaction batch."""

        incidents: list[Incident] = []

        for (merchant, country), transactions in self._group_transactions(
            batch.transactions
        ).items():
            metrics = self._calculate_metrics(
                merchant=merchant,
                country=country,
                transactions=transactions,
                batch=batch,
            )

            if metrics is None:
                self._consecutive_matches[(merchant, country)] = 0
                continue

            is_anomaly = self._meets_anomaly_thresholds(metrics)

            if not self._is_persistent(metrics, is_anomaly):
                continue

            impact = calculate_money_impact(
                transactions=transactions,
                expected_conversion=metrics.expected_conversion,
                window_minutes=self.window_minutes,
            )

            incident_id = (
                f"inc-{merchant.lower()}-{country.lower()}-"
                f"{batch.window_end.strftime('%Y%m%dT%H%M%S')}"
            )

            incidents.append(
                Incident(
                    incident_id=incident_id,
                    merchant=merchant,
                    country=country,
                    detected_at=batch.window_end,
                    expected_conversion=metrics.expected_conversion,
                    actual_conversion=metrics.actual_conversion,
                    conversion_drop_pp=metrics.conversion_drop_pp,
                    affected_volume=metrics.transaction_count,
                    estimated_loss=impact.estimated_loss,
                    estimated_loss_per_hour=impact.estimated_loss_per_hour,
                    severity=self._severity_for(metrics.conversion_drop_pp),
                    anomaly_score=abs(metrics.z_score),
                )
            )

        return incidents