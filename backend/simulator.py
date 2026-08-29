"""Deterministic live payment batches with judge-controlled incident injection."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import random
from typing import Iterable, TypeVar, get_args

from backend.data_generator import (
    BANK_WEIGHTS,
    PAYMENT_METHOD_WEIGHTS,
    PROVIDER_WEIGHTS,
    expected_approval_rate,
    expected_hourly_volume,
)

from backend.schemas import (
    Country,
    DeclineCode,
    InjectionConfig,
    Merchant,
    PaymentMethod,
    Provider,
    Transaction,
    TransactionBatch,
)


DEFAULT_START_TIME = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
DEFAULT_TRANSACTIONS_PER_WINDOW = 1_200
WINDOW_SIZE = timedelta(minutes=5)

# Runtime vocabulary is derived from the frozen schema instead of duplicated here.
MERCHANTS: tuple[Merchant, ...] = get_args(Merchant)
COUNTRIES: tuple[Country, ...] = get_args(Country)
DECLINE_CODES: tuple[DeclineCode, ...] = get_args(DeclineCode)
WeightedValue = TypeVar("WeightedValue")


@dataclass(frozen=True, slots=True)
class TransactionContext:
    """Normal-behavior inputs that can later be shared with the historical model."""

    merchant: Merchant
    country: Country
    provider: Provider
    payment_method: PaymentMethod
    issuing_bank: str
    amount: float
    timestamp: datetime


@dataclass(slots=True)
class ActiveInjection:
    """Simulator-private configuration and duration for one active incident."""

    config: InjectionConfig
    remaining_windows: int | None


class LiveTransactionSimulator:
    """Generate consecutive five-minute transaction batches in simulated time.

    Multiple injections may be active at once and expire independently. If several
    injections match one transaction, the one with the lowest target approval rate
    wins; ties retain activation order. The selected injection also supplies the
    decline code for declines that it causes.

    The simulator never sleeps or manages real-time pacing. Callers decide how
    frequently to call :meth:`next_batch`.
    """

    window_size = WINDOW_SIZE

    def __init__(
        self,
        *,
        start_time: datetime = DEFAULT_START_TIME,
        transactions_per_window: int = DEFAULT_TRANSACTIONS_PER_WINDOW,
        seed: int | str | None = None,
    ) -> None:
        if start_time.tzinfo is None or start_time.utcoffset() is None:
            raise ValueError("start_time must include a timezone offset")
        if (
            isinstance(transactions_per_window, bool)
            or not isinstance(transactions_per_window, int)
            or transactions_per_window <= 0
        ):
            raise ValueError("transactions_per_window must be a positive integer")
        self.current_time = start_time
        self.transactions_per_window = transactions_per_window
        self.active_injections: list[ActiveInjection] = []
        self._random = random.Random(seed)
        self._transaction_sequence = 0

    def normal_approval_probability(self, context: TransactionContext) -> float:
        """Return the same contextual normal rate used by historical generation."""

        return expected_approval_rate(
            merchant=context.merchant,
            country=context.country,
            provider=context.provider,
            payment_method=context.payment_method,
            issuing_bank=context.issuing_bank,
            hour_start=self._utc_hour(context.timestamp),
        )

    def activate_injection(self, config: InjectionConfig) -> None:
        """Apply a validated configuration to future batches only."""

        if not isinstance(config, InjectionConfig):
            raise TypeError("config must be an InjectionConfig")
        config_copy = config.model_copy(deep=True)
        self.active_injections.append(
            ActiveInjection(
                config=config_copy,
                remaining_windows=config_copy.duration_windows,
            )
        )

    def clear_injections(self) -> None:
        """Deactivate every injection, including ones with indefinite duration."""

        self.active_injections.clear()

    def next_batch(self) -> TransactionBatch:
        """Generate one batch, then advance time and injection durations."""

        window_start = self.current_time
        window_end = window_start + self.window_size
        traffic_slices = self._allocate_traffic_slices(window_start)
        self._random.shuffle(traffic_slices)
        transactions = [
            self._generate_transaction(window_start, window_end, merchant, country)
            for merchant, country in traffic_slices
        ]
        batch = TransactionBatch(
            window_start=window_start,
            window_end=window_end,
            transactions=transactions,
        )

        self.current_time = window_end
        self._advance_injections()
        return batch

    def _generate_transaction(
        self,
        window_start: datetime,
        window_end: datetime,
        merchant: Merchant,
        country: Country,
    ) -> Transaction:
        provider = self._weighted_choice(PROVIDER_WEIGHTS[country])
        payment_method = self._weighted_choice(PAYMENT_METHOD_WEIGHTS[country])
        issuing_bank = self._weighted_choice(BANK_WEIGHTS[country])
        amount = round(
            min(1_000_000, max(0.01, self._random.lognormvariate(3.8, 0.7))),
            2,
        )
        timestamp = window_start + timedelta(
            seconds=self._random.random()
            * (window_end - window_start).total_seconds()
        )

        # Draw every stochastic value before applying an injection. This keeps the
        # random stream aligned with an uninjected simulator, so nonmatching traffic
        # is exactly unchanged rather than merely similar in aggregate.
        approval_draw = self._random.random()
        natural_decline_code = self._random.choice(DECLINE_CODES)
        context = TransactionContext(
            merchant=merchant,
            country=country,
            provider=provider,
            payment_method=payment_method,
            issuing_bank=issuing_bank,
            amount=amount,
            timestamp=timestamp,
        )
        normal_probability = self.normal_approval_probability(context)
        if not 0 <= normal_probability <= 1:
            raise ValueError("normal_approval_probability must return a value from 0 to 1")

        selected_injection = self._selected_injection(context)
        effective_probability = (
            selected_injection.config.target_approval_rate
            if selected_injection is not None
            else normal_probability
        )
        naturally_approved = approval_draw < normal_probability
        approved = approval_draw < effective_probability
        injection_caused_decline = naturally_approved and not approved

        if approved:
            status = "approved"
            decline_code = None
        else:
            status = "declined"
            decline_code = natural_decline_code
            if (
                injection_caused_decline
                and selected_injection is not None
                and selected_injection.config.decline_code is not None
            ):
                decline_code = selected_injection.config.decline_code

        self._transaction_sequence += 1
        return Transaction(
            transaction_id=f"txn-live-{self._transaction_sequence:012d}",
            merchant=merchant,
            provider=provider,
            payment_method=payment_method,
            country=country,
            issuing_bank=issuing_bank,
            decline_code=decline_code,
            status=status,
            amount=amount,
            timestamp=timestamp,
        )

    def _allocate_traffic_slices(
        self, window_start: datetime
    ) -> list[tuple[Merchant, Country]]:
        """Scale historical relative volume weights to the configured batch size."""

        hour_start = self._utc_hour(window_start)
        slices = [
            (merchant, country) for merchant in MERCHANTS for country in COUNTRIES
        ]
        weights = [
            expected_hourly_volume(
                merchant=merchant,
                country=country,
                hour_start=hour_start,
            )
            for merchant, country in slices
        ]
        total_weight = sum(weights)
        if total_weight <= 0:
            raise ValueError("expected_hourly_volume must produce positive total weight")

        exact_counts = [
            self.transactions_per_window * weight / total_weight for weight in weights
        ]
        counts = [math.floor(count) for count in exact_counts]
        unallocated = self.transactions_per_window - sum(counts)
        remainder_order = sorted(
            range(len(slices)),
            key=lambda index: (-(exact_counts[index] - counts[index]), index),
        )
        for index in remainder_order[:unallocated]:
            counts[index] += 1

        return [
            traffic_slice
            for traffic_slice, count in zip(slices, counts, strict=True)
            for _ in range(count)
        ]

    def _weighted_choice(
        self, weighted_values: Iterable[tuple[WeightedValue, float]]
    ) -> WeightedValue:
        values, weights = zip(*weighted_values, strict=True)
        return self._random.choices(values, weights=weights, k=1)[0]

    @staticmethod
    def _utc_hour(timestamp: datetime) -> datetime:
        return timestamp.astimezone(timezone.utc).replace(
            minute=0,
            second=0,
            microsecond=0,
        )

    def _selected_injection(
        self, context: TransactionContext
    ) -> ActiveInjection | None:
        matching = [
            injection
            for injection in self.active_injections
            if self._matches(injection.config, context)
        ]
        if not matching:
            return None
        return min(
            matching,
            key=lambda injection: injection.config.target_approval_rate,
        )

    @staticmethod
    def _matches(config: InjectionConfig, context: TransactionContext) -> bool:
        return (
            config.merchant == context.merchant
            and config.country == context.country
            and (config.provider is None or config.provider == context.provider)
            and (
                config.payment_method is None
                or config.payment_method == context.payment_method
            )
            and (
                config.issuing_bank is None
                or config.issuing_bank == context.issuing_bank
            )
        )

    def _advance_injections(self) -> None:
        still_active: list[ActiveInjection] = []
        for injection in self.active_injections:
            if injection.remaining_windows is None:
                still_active.append(injection)
                continue

            injection.remaining_windows -= 1
            if injection.remaining_windows > 0:
                still_active.append(injection)
        self.active_injections = still_active
