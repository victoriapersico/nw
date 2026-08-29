"""CLI for running the harness once an MVP-02/05 runtime adapter is available."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from backend.evaluation.harness import EvaluationHarness
from backend.evaluation.scenarios import SCENARIOS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Control Tower synthetic evaluation.")
    parser.add_argument(
        "--runtime",
        default="backend.integration.evaluation_runtime:build_runtime",
        help="Factory path module:function returning an EvaluationRuntime adapter.",
    )
    parser.add_argument("--output", default="artifacts/evaluation")
    parser.add_argument("--scenario", type=int, action="append", dest="scenario_ids")
    parser.add_argument(
        "--list", action="store_true", help="Print the frozen 30-scenario catalog."
    )
    arguments = parser.parse_args()

    selected = tuple(
        scenario
        for scenario in SCENARIOS
        if arguments.scenario_ids is None or scenario.scenario_id in arguments.scenario_ids
    )
    if arguments.list:
        for scenario in selected:
            print(f"{scenario.scenario_id:02d} | seed={scenario.seed} | {scenario.name}")
        return
    if not arguments.runtime:
        parser.error("--runtime is required to execute scenarios; use --list to inspect them")

    runtime = _load_factory(arguments.runtime)()
    report = EvaluationHarness(runtime).run(selected)
    json_path, markdown_path = report.write(Path(arguments.output))
    print(report.to_markdown())
    print(f"Machine-readable: {json_path}")
    print(f"Human-readable: {markdown_path}")


def _load_factory(path: str):
    module_name, separator, factory_name = path.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("runtime must use module:function syntax")
    return getattr(importlib.import_module(module_name), factory_name)


if __name__ == "__main__":
    main()
