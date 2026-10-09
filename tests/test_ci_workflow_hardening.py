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


def test_fork_pull_requests_run_the_trusted_base_classifier() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert "github.event.pull_request.base.sha" in workflow_text
    assert "refs/pull/${PR_NUMBER}/head" in workflow_text
    assert "Fork pull request: refusing to execute classifier" not in workflow_text


def test_force_pushes_fail_safe_before_diffing() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    ancestor_check = 'git merge-base --is-ancestor "$BEFORE_SHA" "$SHA"'
    diff = 'git diff --name-only --no-renames "$BEFORE_SHA" "$SHA"'

    assert ancestor_check in workflow_text
    assert workflow_text.index(ancestor_check) < workflow_text.index(diff)
