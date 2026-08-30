"""Shared Judge Lab controls for one statistically observable injection slice."""

from dataclasses import dataclass
from typing import Literal, cast

import streamlit as st

from backend.schemas import COUNTRY_ISSUING_BANKS, COUNTRY_PAYMENT_METHODS, Country


InjectionScope = Literal[
    "All traffic",
    "Provider",
    "Payment method",
    "Issuing bank",
]

ALL_TRAFFIC: InjectionScope = "All traffic"
SCOPE_OPTIONS: tuple[InjectionScope, ...] = (
    ALL_TRAFFIC,
    "Provider",
    "Payment method",
    "Issuing bank",
)


@dataclass(frozen=True)
class InjectionSlice:
    """The optional slice fields exposed by the supported Judge Lab policy."""

    provider: str | None = None
    payment_method: str | None = None
    issuing_bank: str | None = None


def render_scope_selector(*, key_prefix: str) -> InjectionScope:
    """Render the single-select scope control outside the submission form."""

    selected = st.segmented_control(
        "Anomaly scope",
        SCOPE_OPTIONS,
        default=ALL_TRAFFIC,
        required=True,
        key=f"{key_prefix}_scope",
        width="stretch",
        help="Choose all traffic or exactly one optional payment dimension.",
    )
    return cast(InjectionScope, selected or ALL_TRAFFIC)


def render_scope_filter(
    *, country: Country, scope: InjectionScope, key_prefix: str
) -> InjectionSlice:
    """Render only the filter selected by the scope control."""

    if scope == "Provider":
        return InjectionSlice(
            provider=st.selectbox(
                "Provider",
                ["Stripe", "Adyen", "dLocal"],
                key=f"{key_prefix}_provider",
            )
        )
    if scope == "Payment method":
        return InjectionSlice(
            payment_method=st.selectbox(
                "Payment method",
                sorted(COUNTRY_PAYMENT_METHODS[country]),
                key=f"{key_prefix}_payment_method",
            )
        )
    if scope == "Issuing bank":
        return InjectionSlice(
            issuing_bank=st.selectbox(
                "Issuing bank",
                sorted(COUNTRY_ISSUING_BANKS[country]),
                key=f"{key_prefix}_issuing_bank",
            )
        )
    return InjectionSlice()


def clear_scope_state(*, key_prefix: str) -> None:
    """Return one Judge Lab form to its safe all-traffic default."""

    for suffix in ("scope", "provider", "payment_method", "issuing_bank"):
        st.session_state.pop(f"{key_prefix}_{suffix}", None)
