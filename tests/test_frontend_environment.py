"""Regression tests for dashboard environment precedence."""

from __future__ import annotations

import ast
import os
from pathlib import Path

from dotenv import load_dotenv as real_load_dotenv


CLIENT_PAGE = Path(__file__).parents[1] / "frontend" / "pages" / "0_Client.py"


def _client_load_dotenv_call() -> ast.Call:
    module = ast.parse(CLIENT_PAGE.read_text(encoding="utf-8"))
    for statement in module.body:
        if not isinstance(statement, ast.Expr) or not isinstance(
            statement.value, ast.Call
        ):
            continue
        function = statement.value.func
        if isinstance(function, ast.Name) and function.id == "load_dotenv":
            return statement.value
    raise AssertionError("The client dashboard does not load its environment.")


def test_client_dashboard_preserves_process_api_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "CONTROL_TOWER_API_URL=http://127.0.0.1:8000\n",
        encoding="utf-8",
    )
    process_url = "http://127.0.0.1:8011"
    monkeypatch.setenv("CONTROL_TOWER_API_URL", process_url)

    def load_isolated_dotenv(*_args: object, **kwargs: object) -> bool:
        return real_load_dotenv(dotenv_path=dotenv_file, **kwargs)

    expression = ast.Expression(body=_client_load_dotenv_call())
    exec(
        compile(expression, str(CLIENT_PAGE), "eval"),
        {"load_dotenv": load_isolated_dotenv},
    )

    assert os.environ["CONTROL_TOWER_API_URL"] == process_url
