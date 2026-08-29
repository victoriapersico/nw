"""Monetary impact calculations for detected conversion degradation."""

from dataclasses import dataclass
from typing import Iterable

from backend.schemas import Transaction


@dataclass(frozen=True)
class MoneyImpact:
    total_attempted_amount: float
    expected_approved_amount: float
    actual_approved_amount: float
    estimated_loss: float
    estimated_loss_per_hour: float


def calculate_money_impact(
    transactions: Iterable[Transaction],
    expected_conversion: float,
    window_minutes: int,
) -> MoneyImpact:
    """Estimate lost approved value against the seasonal expected
    conversion."""

    if not 0 <= expected_conversion <= 1:
        raise ValueError("expected_conversion must be between 0 and 1")

    if window_minutes <= 0:
        raise ValueError("window_minutes must be greater than zero")

    transaction_list = list(transactions)

    total_attempted_amount = sum(
        transaction.amount for transaction in transaction_list
    )
    actual_approved_amount = sum(
        transaction.amount
        for transaction in transaction_list
        if transaction.status == "approved"
    )

    expected_approved_amount = total_attempted_amount * expected_conversion
    estimated_loss = max(
        0.0,
        expected_approved_amount - actual_approved_amount,
    )
    estimated_loss_per_hour = estimated_loss * (60 / window_minutes)

    return MoneyImpact(
        total_attempted_amount=total_attempted_amount,
        expected_approved_amount=expected_approved_amount,
        actual_approved_amount=actual_approved_amount,
        estimated_loss=estimated_loss,
        estimated_loss_per_hour=estimated_loss_per_hour,
    )