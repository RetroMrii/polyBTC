import argparse
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class PipelineStep:
    name: str
    command: list[str]
    optional: bool = False


def run_step(step: PipelineStep) -> dict[str, object]:
    print(f"\n=== {step.name} ===")
    result = subprocess.run(step.command, check=False)
    status = "ok" if result.returncode == 0 else "failed_optional" if step.optional else "failed"
    print(f"=== {step.name}: {status} exit={result.returncode} ===")
    return {
        "name": step.name,
        "command": step.command,
        "returncode": result.returncode,
        "optional": step.optional,
        "status": status,
    }


def build_steps(skip_training: bool) -> list[PipelineStep]:
    python = sys.executable
    steps = [
        PipelineStep("build_trade_quality_dataset", [python, "build_trade_quality_dataset.py"]),
    ]

    if not skip_training:
        steps.extend(
            [
                PipelineStep("train_lightgbm_trade_quality", [python, "train_lightgbm_trade_quality.py"], optional=True),
                PipelineStep("train_xgboost_trade_quality", [python, "train_xgboost_trade_quality.py"], optional=True),
            ]
        )

    steps.extend(
        [
            PipelineStep("score_trade_quality", [python, "score_trade_quality.py"]),
            PipelineStep("evaluate_trade_quality_models", [python, "evaluate_trade_quality_models.py"]),
            PipelineStep("kronos_adapter", [python, "kronos_adapter.py"]),
            PipelineStep("timesfm_adapter", [python, "timesfm_adapter.py"]),
            PipelineStep("chronos_adapter", [python, "chronos_adapter.py"]),
            PipelineStep("combine_diagnostics", [python, "combine_diagnostics.py"]),
            PipelineStep("research_darts_forecasts", [python, "research_darts_forecasts.py"]),
            PipelineStep("research_neuralforecast_forecasts", [python, "research_neuralforecast_forecasts.py"]),
            PipelineStep("tradingagents_daily_review", [python, "tradingagents_daily_review.py"]),
        ]
    )
    return steps


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate offline BTC5M research and diagnostic artifacts.")
    parser.add_argument(
        "--skip-training",
        action="store_true",
        help="Skip LightGBM/XGBoost training attempts. Useful until enough labeled rows exist.",
    )
    args = parser.parse_args(argv)

    results = [run_step(step) for step in build_steps(skip_training=args.skip_training)]
    failed_required = [result for result in results if result["status"] == "failed"]

    print("\n=== PIPELINE SUMMARY ===")
    for result in results:
        print(f"{result['status']}: {result['name']} exit={result['returncode']}")

    return 1 if failed_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
