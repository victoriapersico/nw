from pathlib import Path
from unittest.mock import Mock, patch

import requests
from streamlit.testing.v1 import AppTest


JUDGE_LAB_PAGE = (
    Path(__file__).resolve().parents[1] / "frontend" / "pages" / "1_Judge_Lab.py"
)
DASHBOARD_APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


def _widget_with_label(widgets, label: str):
    return next(widget for widget in widgets if widget.label == label)


def test_bank_scope_submits_only_the_selected_bank() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"injection_id": "inj-bank-test", "status": "active"}

    with patch("requests.post", return_value=response) as post:
        app = AppTest.from_file(str(JUDGE_LAB_PAGE)).run(timeout=20)

        expected_filter_by_scope = {
            "All traffic": set(),
            "Provider": {"Provider"},
            "Payment method": {"Payment method"},
            "Issuing bank": {"Issuing bank"},
        }
        optional_labels = {"Provider", "Payment method", "Issuing bank"}
        for selected_scope, expected_labels in expected_filter_by_scope.items():
            scope = _widget_with_label(app.segmented_control, "Anomaly scope")
            scope.select(selected_scope).run(timeout=20)
            labels = {widget.label for widget in app.selectbox}
            assert labels & optional_labels == expected_labels

        labels = {widget.label for widget in app.selectbox}
        assert "Issuing bank" in labels
        assert "Provider" not in labels
        assert "Payment method" not in labels

        bank = _widget_with_label(app.selectbox, "Issuing bank")
        bank.select("BBVA México")
        _widget_with_label(app.button, "Inject incident").click().run(timeout=20)

        payload = post.call_args_list[0].kwargs["json"]["config"]
        assert payload["provider"] is None
        assert payload["payment_method"] is None
        assert payload["issuing_bank"] == "BBVA México"

        _widget_with_label(app.button, "Reset demo").click().run(timeout=20)

        reset_scope = _widget_with_label(app.segmented_control, "Anomaly scope")
        assert reset_scope.value == "All traffic"
        assert post.call_args_list[1].args[0].endswith("/monitor/reset")


def test_dashboard_bank_scope_hides_other_optional_filters() -> None:
    offline = requests.ConnectionError("offline dashboard test")
    with (
        patch("requests.get", side_effect=offline),
        patch("requests.post", side_effect=offline),
    ):
        app = AppTest.from_file(str(DASHBOARD_APP)).run(timeout=20)
        assert not app.exception

        scope = _widget_with_label(app.segmented_control, "Anomaly scope")
        scope.select("Issuing bank").run(timeout=20)

    labels = {widget.label for widget in app.selectbox}
    assert "Issuing bank" in labels
    assert "Provider" not in labels
    assert "Payment method" not in labels
