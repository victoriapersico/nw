from datetime import datetime, timezone

import pandas as pd

from backend.integration.evaluation_runtime import _load_baseline


UTC = timezone.utc


def test_runtime_loads_blank_decline_codes_from_persisted_csv(tmp_path) -> None:
    path = tmp_path / "history.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "approved",
                "merchant": "Rappi",
                "provider": "Stripe",
                "payment_method": "CARD",
                "country": "Mexico",
                "issuing_bank": "Banorte",
                "decline_code": None,
                "status": "approved",
                "amount": 10.0,
                "timestamp": datetime(2025, 1, 6, 9, tzinfo=UTC),
            },
            {
                "transaction_id": "declined",
                "merchant": "Rappi",
                "provider": "Stripe",
                "payment_method": "CARD",
                "country": "Mexico",
                "issuing_bank": "Banorte",
                "decline_code": "05",
                "status": "declined",
                "amount": 10.0,
                "timestamp": datetime(2025, 1, 6, 9, tzinfo=UTC),
            },
        ]
    ).to_csv(path, index=False)

    baseline = _load_baseline(str(path.resolve()), minimum_volume=1)

    metric = baseline.expected_for("Rappi", "Mexico", datetime(2025, 1, 6, 9, tzinfo=UTC))
    assert metric is not None
    assert metric.approval_rate == 0.5
