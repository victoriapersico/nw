from datetime import datetime, timezone

import pandas as pd
import pytest
from pydantic import ValidationError

import backend.data_generator as data_generator
from backend.data_generator import (
    TRANSACTION_COLUMNS,
    expected_approval_rate,
    expected_hourly_volume,
    generate_historical_transactions,
    generate_hourly_transactions,
    persist_historical_dataset,
    split_historical_data,
    validate_transaction_frame,
)


UTC = timezone.utc


def test_hourly_generation_is_reproducible_and_valid() -> None:
    hour = datetime(2025, 1, 6, 12, tzinfo=UTC)

    first = generate_hourly_transactions(seed=123, hour_start=hour)
    second = generate_hourly_transactions(seed=123, hour_start=hour)

    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]
    assert {item.merchant for item in first} == {"Rappi", "Carrefour", "Despegar"}
    assert all(item.timestamp.tzinfo is not None for item in first)


def test_historical_generator_calls_public_normal_behavior(monkeypatch) -> None:
    hour = datetime(2025, 1, 6, 12, tzinfo=UTC)
    volume_calls: list[dict[str, object]] = []
    approval_calls: list[dict[str, object]] = []

    def recording_volume(**context: object) -> float:
        volume_calls.append(context)
        return expected_hourly_volume(**context)

    def always_approved(**context: object) -> float:
        approval_calls.append(context)
        return 1.0

    monkeypatch.setattr(data_generator, "expected_hourly_volume", recording_volume)
    monkeypatch.setattr(data_generator, "expected_approval_rate", always_approved)

    transactions = generate_hourly_transactions(seed=123, hour_start=hour)

    assert len(volume_calls) == 9
    assert len(approval_calls) == len(transactions)
    assert all(transaction.status == "approved" for transaction in transactions)


def test_history_returns_a_dataframe_with_mvp_derived_columns() -> None:
    dataframe = generate_historical_transactions(
        seed=123,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 2, tzinfo=UTC),
    )

    assert isinstance(dataframe, pd.DataFrame)
    assert set(TRANSACTION_COLUMNS).issubset(dataframe.columns)
    assert set(dataframe["split"].unique()) == {"train"}
    assert dataframe["hour_of_week"].between(0, 167).all()
    assert dataframe["decline_code"].isna().any()
    assert validate_transaction_frame(dataframe) == len(dataframe)


def test_frame_validation_normalizes_only_decline_code_nan() -> None:
    dataframe = generate_historical_transactions(
        seed=123,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 1, 1, tzinfo=UTC),
    )
    invalid = dataframe.copy()
    invalid.loc[invalid.index[0], "amount"] = float("nan")

    with pytest.raises(ValidationError):
        validate_transaction_frame(invalid)


def test_split_historical_data_is_chronological() -> None:
    dataframe = pd.DataFrame(
        {
            "timestamp": [
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 5, 1, tzinfo=UTC),
                datetime(2025, 9, 1, tzinfo=UTC),
            ]
        }
    )

    splits = split_historical_data(dataframe)

    assert {name: len(rows) for name, rows in splits.items()} == {
        "train": 1,
        "validation": 1,
        "test": 1,
    }


def test_generator_requires_hour_boundaries() -> None:
    with pytest.raises(ValueError, match="exact UTC hour"):
        generate_historical_transactions(
            seed=123,
            start=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
            end=datetime(2025, 1, 1, 1, tzinfo=UTC),
        )


def test_persist_requires_csv_and_writes_validated_rows(tmp_path) -> None:
    dataframe = generate_historical_transactions(
        seed=123,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 1, 1, tzinfo=UTC),
    )

    output = persist_historical_dataset(dataframe, tmp_path / "history.csv")

    assert output.exists()
    assert output.suffix == ".csv"
