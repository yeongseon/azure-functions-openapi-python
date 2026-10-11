from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark_spec_generation import main


@pytest.mark.parametrize("argument", ["--operations", "--models"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_benchmark_rejects_non_positive_scenario_size(argument: str, value: str) -> None:
    # Given
    arguments = ["--operations", "1", "--models", "1"]
    arguments[arguments.index(argument) + 1] = value

    # When / Then
    with pytest.raises(SystemExit) as raised:
        main(arguments)

    assert raised.value.code == 2


def test_benchmark_smallest_scenario_writes_json(tmp_path: Path) -> None:
    # Given
    output = tmp_path / "benchmark.json"

    # When
    result = main(
        [
            "--operations",
            "1",
            "--models",
            "1",
            "--repeats",
            "1",
            "--json",
            str(output),
        ]
    )

    # Then
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert payload["results"][0]["operations"] == 1
    assert payload["results"][0]["models"] == 1
    assert payload["results"][0]["median_seconds"] > 0
    assert payload["results"][0]["peak_bytes"] > 0


@pytest.mark.perf
def test_spec_generation_stays_within_committed_budgets() -> None:
    # Given / When
    result = main(["--check"])

    # Then
    assert result == 0
