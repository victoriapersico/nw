"""Deterministic, seasonal transaction history for the Control Tower MVP."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import math
from pathlib import Path
import random
from typing import Iterable

import pandas as pd

from backend.schemas import (
    COUNTRY_ISSUING_BANKS,
    Transaction,
)


TRANSACTION_COLUMNS = (
    "transaction_id",
    "merchant",
    "provider",
    "payment_method",
    "country",
    "issuing_bank",
    "decline_code",
    "status",
    "amount",
    "timestamp",
)

MERCHANTS = ("Rappi", "Carrefour", "Despegar")
COUNTRIES = ("Mexico", "Brazil", "Colombia")

# The smallest merchant/country/hour slice has enough train observations after
# Jan-Apr (roughly 17 occurrences of a given hour_of_week) for the MVP baseline.
MIN_TRANSACTIONS_PER_HOUR = 3

BASE_HOURLY_VOLUME = {
    "Rappi": 7.0,
    "Carrefour": 6.0,
    "Despegar": 4.0,
}

COUNTRY_VOLUME_MULTIPLIER = {"Mexico": 1.0, "Brazil": 1.1, "Colombia": 0.85}

BASE_APPROVAL_RATE = {
    "Rappi": {"Mexico": 0.91, "Brazil": 0.92, "Colombia": 0.90},
    "Carrefour": {"Mexico": 0.93, "Brazil": 0.94, "Colombia": 0.92},
    "Despegar": {"Mexico": 0.89, "Brazil": 0.90, "Colombia": 0.88},
}

PROVIDER_WEIGHTS = {
    "Mexico": (("Stripe", 0.46), ("Adyen", 0.35), ("dLocal", 0.19)),
    "Brazil": (("Stripe", 0.27), ("Adyen", 0.31), ("dLocal", 0.42)),
    "Colombia": (("Stripe", 0.30), ("Adyen", 0.26), ("dLocal", 0.44)),
}

PAYMENT_METHOD_WEIGHTS = {
    "Mexico": (("CARD", 0.72), ("OXXO", 0.28)),
    "Brazil": (("CARD", 0.45), ("PIX", 0.55)),
    "Colombia": (("CARD", 0.58), ("PSE", 0.42)),
}

BANK_WEIGHTS = {
    country: tuple((bank, 1.0) for bank in sorted(banks))
    for country, banks in COUNTRY_ISSUING_BANKS.items()
}

PROVIDER_APPROVAL_ADJUSTMENT = {"Stripe": 0.008, "Adyen": 0.005, "dLocal": -0.004}
PAYMENT_METHOD_APPROVAL_ADJUSTMENT = {
    "CARD": 0.0,
    "PIX": 0.008,
    "PSE": -0.004,
    "OXXO": -0.006,
}

BANK_APPROVAL_ADJUSTMENT = {
    "BBVA México": 0.003,
    "Banorte": -0.002,
    "Santander México": 0.001,
    "Citibanamex": -0.001,
    "Itaú": 0.003,
    "Bradesco": 0.0,
    "Banco do Brasil": -0.002,
    "Nubank": 0.002,
    "Bancolombia": 0.002,
    "Davivienda": -0.001,
    "Banco de Bogotá": -0.002,
    "BBVA Colombia": 0.001,
}

AMOUNT_PROFILE = {
    # median amount, lognormal spread, hard cap; the currency is intentionally
    # abstract for MVP because Transaction has no currency field.
    "Rappi": (22.0, 0.55, 180.0),
    "Carrefour": (62.0, 0.65, 850.0),
    "Despegar": (320.0, 0.85, 5_000.0),
}

COUNTRY_AMOUNT_MULTIPLIER = {"Mexico": 1.0, "Brazil": 0.92, "Colombia": 0.82}

CARD_DECLINE_WEIGHTS = (
    ("05", 0.35),
    ("51", 0.25),
    ("54", 0.10),
    ("57", 0.06),
    ("61", 0.08),
    ("91", 0.08),
    ("96", 0.08),
)
ALTERNATIVE_METHOD_DECLINE_WEIGHTS = (
    ("05", 0.27),
    ("51", 0.22),
    ("54", 0.02),
    ("57", 0.09),
    ("61", 0.10),
    ("91", 0.18),
    ("96", 0.12),
)


def generate_one_year(seed: int = 42, year: int = 2025) -> pd.DataFrame:
    """Generate the canonical Jan-Dec historical dataset as a DataFrame.

    The year is a calendar year because the train/validation/test contract is
    month-based. No incidents are injected into this baseline history.
    """

    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return generate_historical_transactions(seed=seed, start=start, end=end)


def generate_historical_transactions(
    *, seed: int, start: datetime, end: datetime
) -> pd.DataFrame:
    """Generate validated transactions for a UTC-aligned hourly interval.

    The random stream for each hour is derived from ``seed`` and its timestamp.
    Consequently, the rows for an hour are identical whether it is generated on
    its own or as part of a full year. This makes debugging and fixtures stable.
    """

    start_utc = _validated_hour_boundary(start, field_name="start")
    end_utc = _validated_hour_boundary(end, field_name="end")
    if end_utc <= start_utc:
        raise ValueError("end must be later than start")

    rows: list[dict[str, object]] = []
    current_hour = start_utc
    while current_hour < end_utc:
        rows.extend(
            transaction.model_dump()
            for transaction in generate_hourly_transactions(
                seed=seed, hour_start=current_hour
            )
        )
        current_hour += timedelta(hours=1)

    frame = pd.DataFrame(rows, columns=TRANSACTION_COLUMNS)
    if frame.empty:
        return _add_derived_columns(frame)

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame.sort_values("timestamp", inplace=True, kind="stable")
    frame.reset_index(drop=True, inplace=True)
    return _add_derived_columns(frame)


def generate_hourly_transactions(*, seed: int, hour_start: datetime) -> list[Transaction]:
    """Generate one independently reproducible normal hour for every merchant/country."""

    hour_start = _validated_hour_boundary(hour_start, field_name="hour_start")
    rng = random.Random(_hour_seed(seed=seed, hour_start=hour_start))
    transactions: list[Transaction] = []

    for merchant in MERCHANTS:
        for country in COUNTRIES:
            expected_volume = _expected_hourly_volume(
                merchant=merchant, country=country, hour_start=hour_start
            )
            transaction_count = max(
                MIN_TRANSACTIONS_PER_HOUR,
                int(round(rng.gauss(expected_volume, math.sqrt(expected_volume)))),
            )

            for position in range(transaction_count):
                provider = _weighted_choice(rng, PROVIDER_WEIGHTS[country])
                payment_method = _weighted_choice(rng, PAYMENT_METHOD_WEIGHTS[country])
                issuing_bank = _weighted_choice(rng, BANK_WEIGHTS[country])
                approval_rate = _expected_approval_rate(
                    merchant=merchant,
                    country=country,
                    provider=provider,
                    payment_method=payment_method,
                    issuing_bank=issuing_bank,
                    hour_start=hour_start,
                )
                approved = rng.random() < approval_rate
                status = "approved" if approved else "declined"
                decline_code = (
                    None
                    if approved
                    else _weighted_choice(
                        rng,
                        CARD_DECLINE_WEIGHTS
                        if payment_method == "CARD"
                        else ALTERNATIVE_METHOD_DECLINE_WEIGHTS,
                    )
                )
                timestamp = hour_start + timedelta(seconds=rng.randrange(3_600))

                transactions.append(
                    Transaction(
                        transaction_id=(
                            f"txn-{hour_start:%Y%m%d%H}-{merchant[:3].lower()}-"
                            f"{country[:2].lower()}-{position:03d}"
                        ),
                        merchant=merchant,
                        provider=provider,
                        payment_method=payment_method,
                        country=country,
                        issuing_bank=issuing_bank,
                        decline_code=decline_code,
                        status=status,
                        amount=_generate_amount(rng, merchant, country),
                        timestamp=timestamp,
                    )
                )

    return transactions


def split_historical_data(dataframe: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return chronological train/validation/test DataFrames using the MVP split."""

    frame = _add_derived_columns(dataframe)
    return {
        split: frame.loc[frame["split"] == split].copy()
        for split in ("train", "validation", "test")
    }


def validate_transaction_frame(dataframe: pd.DataFrame) -> int:
    """Validate every transaction-shaped row and return the validated row count."""

    missing_columns = set(TRANSACTION_COLUMNS) - set(dataframe.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"dataframe is missing transaction columns: {missing}")

    for row in dataframe.loc[:, TRANSACTION_COLUMNS].to_dict(orient="records"):
        Transaction.model_validate(row)
    return len(dataframe)


def persist_historical_dataset(dataframe: pd.DataFrame, output_path: str | Path) -> Path:
    """Validate and save history locally as CSV, returning the absolute path."""

    validate_transaction_frame(dataframe)
    path = Path(output_path).resolve()
    if path.suffix.lower() != ".csv":
        raise ValueError("output_path must have a .csv extension")
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    return path


def _validated_hour_boundary(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    normalized = value.astimezone(timezone.utc)
    if normalized.minute or normalized.second or normalized.microsecond:
        raise ValueError(f"{field_name} must be aligned to an exact UTC hour")
    return normalized


def _hour_seed(*, seed: int, hour_start: datetime) -> int:
    material = f"{seed}:{hour_start.isoformat()}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _expected_hourly_volume(*, merchant: str, country: str, hour_start: datetime) -> float:
    return (
        BASE_HOURLY_VOLUME[merchant]
        * COUNTRY_VOLUME_MULTIPLIER[country]
        * _merchant_hour_volume_multiplier(merchant, hour_start.hour)
        * _merchant_weekday_volume_multiplier(merchant, hour_start.weekday())
        * _merchant_month_volume_multiplier(merchant, hour_start.month)
    )


def _merchant_hour_volume_multiplier(merchant: str, hour: int) -> float:
    if merchant == "Rappi":
        if 11 <= hour <= 14:
            return 1.8
        if 18 <= hour <= 22:
            return 2.2
        if 0 <= hour <= 5:
            return 0.35
        if hour == 6:
            return 0.6
        if 7 <= hour <= 10:
            return 1.1
        if hour == 23:
            return 1.1
        return 0.85
    if merchant == "Carrefour":
        if 9 <= hour <= 13:
            return 1.6
        if 14 <= hour <= 18:
            return 1.35
        if 19 <= hour <= 21:
            return 1.1
        if 0 <= hour <= 7:
            return 0.2
        if hour == 8:
            return 0.6
        return 0.55
    if 10 <= hour <= 17:
        return 1.2
    if 7 <= hour <= 9 or 18 <= hour <= 22:
        return 1.0
    if 0 <= hour <= 6:
        return 0.7
    return 0.85


def _merchant_weekday_volume_multiplier(merchant: str, weekday: int) -> float:
    if merchant == "Rappi":
        return (0.9, 0.95, 1.0, 1.08, 1.3, 1.28, 1.18)[weekday]
    if merchant == "Carrefour":
        return (0.92, 0.96, 1.0, 1.05, 1.14, 1.45, 1.3)[weekday]
    return (1.0, 1.0, 1.02, 1.06, 1.2, 0.98, 0.92)[weekday]


def _merchant_month_volume_multiplier(merchant: str, month: int) -> float:
    if merchant == "Rappi":
        return 1.18 if month == 12 else 1.08 if month == 7 else 1.0
    if merchant == "Carrefour":
        return 1.45 if month == 12 else 1.18 if month == 11 else 1.0
    return 1.28 if month == 7 else 1.25 if month == 12 else 1.2 if month == 1 else 1.0


def _expected_approval_rate(
    *,
    merchant: str,
    country: str,
    provider: str,
    payment_method: str,
    issuing_bank: str,
    hour_start: datetime,
) -> float:
    rate = (
        BASE_APPROVAL_RATE[merchant][country]
        + PROVIDER_APPROVAL_ADJUSTMENT[provider]
        + PAYMENT_METHOD_APPROVAL_ADJUSTMENT[payment_method]
        + BANK_APPROVAL_ADJUSTMENT[issuing_bank]
    )
    if merchant == "Rappi" and 0 <= hour_start.hour <= 6:
        rate -= 0.010
    elif merchant == "Carrefour" and 0 <= hour_start.hour <= 7:
        rate -= 0.006
    elif merchant == "Despegar" and 10 <= hour_start.hour <= 17:
        rate += 0.004
    rate += 0.003 * math.sin(2 * math.pi * hour_start.timetuple().tm_yday / 365)
    return min(0.98, max(0.78, rate))


def _generate_amount(rng: random.Random, merchant: str, country: str) -> float:
    median, spread, cap = AMOUNT_PROFILE[merchant]
    amount = math.exp(rng.gauss(math.log(median), spread))
    amount *= COUNTRY_AMOUNT_MULTIPLIER[country]
    return round(min(cap, max(1.0, amount)), 2)


def _weighted_choice(rng: random.Random, weighted_values: Iterable[tuple[str, float]]) -> str:
    values, weights = zip(*weighted_values, strict=True)
    return rng.choices(values, weights=weights, k=1)[0]


def _add_derived_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    frame = dataframe.copy()
    if "timestamp" not in frame.columns:
        return frame
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    frame["timestamp"] = timestamps
    frame["hour_of_week"] = timestamps.dt.weekday * 24 + timestamps.dt.hour
    frame["split"] = pd.cut(
        timestamps.dt.month,
        bins=[0, 4, 8, 12],
        labels=["train", "validation", "test"],
    ).astype("string")
    return frame
