from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci-test.yml"
FULL_JOBS = (
    "quality",
    "test",
    "minimum-dependencies",
    "artifact-build",
    "artifact-python310-negative",
    "artifact-python311",
    "azure-functions-2x",
    "host-smoke",
)


def gate_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    script = workflow["jobs"]["ci-required"]["steps"][0]["run"]
    assert isinstance(script, str)
    return script


def needs(
    *, docs_changed: str = "true", full_required: str = "false"
) -> dict[str, dict[str, str | dict[str, str]]]:
    jobs: dict[str, dict[str, str | dict[str, str]]] = {
        "changes": {
            "result": "success",
            "outputs": {"docs_changed": docs_changed, "full_required": full_required},
        },
        "docs-check": {"result": "success" if docs_changed == "true" else "skipped", "outputs": {}},
    }
    jobs.update(
        {
            name: {"result": "success" if full_required == "true" else "skipped", "outputs": {}}
            for name in FULL_JOBS
        }
    )
    return jobs


def run_gate(jobs: dict[str, dict[str, str | dict[str, str]]]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", gate_script()],
        capture_output=True,
        check=False,
        env={**os.environ, "NEEDS_JSON": json.dumps(jobs)},
        text=True,
    )


@pytest.mark.parametrize("value", ["", "yes", "TRUE"])
@pytest.mark.parametrize("output", ["docs_changed", "full_required"])
def test_gate_rejects_missing_or_invalid_classifier_outputs(output: str, value: str) -> None:
    jobs = needs()
    outputs = jobs["changes"]["outputs"]
    assert isinstance(outputs, dict)
    outputs[output] = value

    assert run_gate(jobs).returncode != 0


def test_gate_rejects_classifier_success_without_outputs() -> None:
    jobs = needs()
    jobs["changes"]["outputs"] = {}

    assert run_gate(jobs).returncode != 0


def test_gate_rejects_impossible_no_work_classification() -> None:
    assert run_gate(needs(docs_changed="false", full_required="false")).returncode != 0


@pytest.mark.parametrize("result", ["failure", "skipped", "cancelled"])
def test_gate_requires_unknown_dependencies_to_succeed(result: str) -> None:
    jobs = needs()
    jobs["future-job"] = {"result": result, "outputs": {}}

    assert run_gate(jobs).returncode != 0


def test_gate_accepts_a_successful_unknown_dependency() -> None:
    jobs = needs()
    jobs["future-job"] = {"result": "success", "outputs": {}}

    assert run_gate(jobs).returncode == 0
