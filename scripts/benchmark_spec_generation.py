"""Measure OpenAPI spec generation against committed regression budgets."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from statistics import median
import time
import tracemalloc
from typing import Any, TypedDict

from pydantic import BaseModel, create_model

from azure_functions_openapi.decorator import register_openapi_metadata
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import generate_openapi_spec

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUDGET_PATH = _REPO_ROOT / "benchmarks" / "spec_generation_budgets.json"
DEFAULT_SCENARIOS = ((10, 5), (50, 25), (200, 100), (500, 100))


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


class ScenarioBudget(TypedDict):
    operations: int
    models: int
    max_median_seconds: float
    max_peak_bytes: int


class ScalingBudget(TypedDict):
    from_operations: int
    to_operations: int
    max_time_ratio: float


class BudgetFile(TypedDict):
    scenarios: list[ScenarioBudget]
    scaling: ScalingBudget


class BenchmarkDetail(BaseModel):
    code: str
    score: float | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    operations: int
    models: int
    median_seconds: float
    peak_bytes: int


def _build_models(count: int) -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for index in range(count):
        model = create_model(
            f"BenchmarkPayload{index}",
            identifier=(int, ...),
            detail=(BenchmarkDetail, ...),
            related=(list[BenchmarkDetail], ...),
            labels=(list[str], ...),
        )
        models.append(model)
    return models


def _build_registry(operation_count: int, model_count: int) -> OpenAPIRegistry:
    registry = OpenAPIRegistry()
    models = _build_models(model_count)
    for index in range(operation_count):
        model = models[index % model_count]
        register_openapi_metadata(
            path=f"/benchmark/resources/{index}",
            method="POST",
            operation_id=f"benchmarkResource{index}",
            summary=f"Benchmark resource {index}",
            request_model=model,
            response_model=model,
            registry=registry,
        )
    return registry


def _measure_once(generate: Callable[[], dict[str, Any]]) -> tuple[float, int]:
    tracemalloc.start()
    started = time.perf_counter()
    spec = generate()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if not spec["paths"]:
        raise RuntimeError("synthetic registry produced no OpenAPI paths")
    return elapsed, peak


def benchmark_scenario(operation_count: int, model_count: int, repeats: int) -> BenchmarkResult:
    registry = _build_registry(operation_count, model_count)

    def generate() -> dict[str, Any]:
        return generate_openapi_spec(title="Benchmark API", registry=registry)

    generate()
    samples = [_measure_once(generate) for _ in range(repeats)]
    return BenchmarkResult(
        operations=operation_count,
        models=model_count,
        median_seconds=median(sample[0] for sample in samples),
        peak_bytes=max(sample[1] for sample in samples),
    )


def _load_budgets(path: Path) -> BudgetFile:
    with path.open(encoding="utf-8") as stream:
        payload: BudgetFile = json.load(stream)
    return payload


def _check_results(results: Sequence[BenchmarkResult], budgets: BudgetFile) -> list[str]:
    failures: list[str] = []
    by_size = {(result.operations, result.models): result for result in results}
    for budget in budgets["scenarios"]:
        key = (budget["operations"], budget["models"])
        result = by_size[key]
        if result.median_seconds > budget["max_median_seconds"]:
            failures.append(
                f"{key}: median {result.median_seconds:.6f}s exceeds "
                f"{budget['max_median_seconds']:.6f}s"
            )
        if result.peak_bytes > budget["max_peak_bytes"]:
            failures.append(
                f"{key}: peak {result.peak_bytes} bytes exceeds {budget['max_peak_bytes']} bytes"
            )

    scaling = budgets["scaling"]
    by_operations = {result.operations: result for result in results}
    start = by_operations[scaling["from_operations"]]
    end = by_operations[scaling["to_operations"]]
    ratio = end.median_seconds / start.median_seconds
    if ratio > scaling["max_time_ratio"]:
        failures.append(
            f"{start.operations}->{end.operations} operations: time ratio {ratio:.2f} "
            f"exceeds {scaling['max_time_ratio']:.2f}"
        )
    return failures


def _print_results(results: Sequence[BenchmarkResult]) -> None:
    print("operations  models  median_ms  peak_mib")
    for result in results:
        print(
            f"{result.operations:>10}  {result.models:>6}  "
            f"{result.median_seconds * 1000:>9.2f}  {result.peak_bytes / 1024 / 1024:>8.2f}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operations", type=_positive_int)
    parser.add_argument("--models", type=_positive_int)
    parser.add_argument("--repeats", type=_positive_int, default=5)
    parser.add_argument("--json", type=Path, dest="json_path")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--budgets", type=Path, default=DEFAULT_BUDGET_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if (args.operations is None) != (args.models is None):
        parser.error("--operations and --models must be provided together")
    budgets = _load_budgets(args.budgets) if args.check else None
    if budgets is not None:
        scenarios = [(budget["operations"], budget["models"]) for budget in budgets["scenarios"]]
    elif args.operations is not None and args.models is not None:
        scenarios = [(args.operations, args.models)]
    else:
        scenarios = list(DEFAULT_SCENARIOS)

    results = [
        benchmark_scenario(operations, models, args.repeats) for operations, models in scenarios
    ]
    _print_results(results)
    if args.json_path is not None:
        args.json_path.write_text(
            json.dumps({"results": [asdict(result) for result in results]}, indent=2) + "\n",
            encoding="utf-8",
        )
    if budgets is None:
        return 0

    failures = _check_results(results, budgets)
    if failures:
        print("Spec-generation budget check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Spec-generation budgets passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
