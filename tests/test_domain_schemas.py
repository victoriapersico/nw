from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.schemas import InjectionConfig, Transaction, TransactionBatch


def valid_transaction(**overrides: object) -> Transaction:
    payload = {
        "transaction_id": "txn-001",
        "merchant": "Rappi",
        "provider": "dLocal",
        "payment_method": "PIX",
        "country": "Brazil",
        "issuing_bank": "Itaú",
        "decline_code": None,
        "status": "approved",
        "amount": 42.5,
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return Transaction.model_validate(payload)


def test_transaction_accepts_a_valid_payment() -> None:
    assert valid_transaction().payment_method == "PIX"


@pytest.mark.parametrize(
    "overrides",
    [
        {"payment_method": "PSE"},
        {"issuing_bank": "Banorte"},
        {"decline_code": "91"},
        {"status": "declined", "decline_code": None},
    ],
)
def test_transaction_rejects_invalid_domain_combinations(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        valid_transaction(**overrides)


def test_injection_uses_the_same_country_filter_constraints() -> None:
    with pytest.raises(ValidationError):
        InjectionConfig(
            merchant="Rappi",
            country="Brazil",
            payment_method="OXXO",
            target_approval_rate=0.35,
        )


def test_detector_batch_has_no_injection_configuration() -> None:
    transaction = valid_transaction()
    batch = TransactionBatch(
        window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        transactions=[transaction],
    )

    assert batch.transactions == [transaction]

    with pytest.raises(ValidationError):
        TransactionBatch.model_validate(
            {
                **batch.model_dump(mode="json"),
                "injection_config": {
                    "merchant": "Rappi",
                    "country": "Brazil",
                    "target_approval_rate": 0.35,
                },
            }
        )
