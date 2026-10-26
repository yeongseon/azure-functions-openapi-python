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


def test_host_smoke_job_runs_the_real_host_tests() -> None:
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["host-smoke"]["steps"]
    script = "\n".join(step.get("run", "") for step in steps)

    assert "HOST_SMOKE_BASE_URL=" in script
    assert "-m host_smoke" in script
    assert 'exit "$pytest_status"' in script


def test_matrix_retains_only_junit_and_coverage_xml_when_tests_fail() -> None:
    # Given the matrix job, including its coverage and compatibility cells.
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test"]["steps"]

    # When selecting every artifact upload in that job.
    uploads = [
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")
    ]

    # Then uploads run after failure and allow only the two generated XML reports.
    assert len(uploads) == 1
    upload = uploads[0]
    assert upload["if"] == "always()"
    assert upload["uses"] == "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"
    assert upload["with"]["name"] == (
        "test-evidence-py${{ matrix.python-version }}-af${{ matrix.azure-functions-version }}"
    )
    assert upload["with"]["path"].splitlines() == [
        "test-results/junit/py${{ matrix.python-version }}"
        "-af${{ matrix.azure-functions-version }}.xml",
        "${{ matrix.python-version == '3.11' && matrix.azure-functions-version == 'latest' "
        "&& 'coverage.xml' || '' }}",
    ]
    assert upload["with"]["if-no-files-found"] == "warn"
    assert upload["with"]["retention-days"] == 7


def test_matrix_writes_cell_unique_junit_without_changing_coverage_gate() -> None:
    # Given the matrix test command.
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test"]["steps"]
    step = next(step for step in steps if step["name"] == "Run tests on the matrix interpreter")

    # When inspecting the report destination and both pytest branches.
    script = step["run"]

    # Then every cell writes JUnit, with coverage still gated only on 3.11 x latest.
    assert step["env"]["JUNIT_XML"] == (
        "test-results/junit/py${{ matrix.python-version }}"
        "-af${{ matrix.azure-functions-version }}.xml"
    )
    assert step["env"]["IS_COVERAGE_CELL"] == (
        "${{ matrix.python-version == '3.11' && matrix.azure-functions-version == 'latest' }}"
    )
    assert 'pytest tests/ --junitxml="$JUNIT_XML"\n' in script
    assert 'pytest tests/ --no-cov --junitxml="$JUNIT_XML"\n' in script


def test_coverage_summary_is_nonblocking_and_runs_when_tests_fail(tmp_path: Path) -> None:
    # Given the coverage summary step and a cell without coverage data (e.g. install failure).
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test"]["steps"]
    step = next(step for step in steps if step["name"] == "Summarize coverage")
    summary = tmp_path / "summary.md"

    # When executing the summary script without a .coverage file.
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_STEP_SUMMARY": str(summary)},
        capture_output=True,
        text=True,
        check=False,
    )

    # Then missing data is harmless and summary failures cannot change the coverage gate.
    assert result.returncode == 0
    assert not summary.exists()
    assert step["if"] == (
        "always() && matrix.python-version == '3.11' && matrix.azure-functions-version == 'latest'"
    )
    assert step["continue-on-error"] is True
    assert (
        'python -m coverage report --format=markdown --fail-under=0 >> "$GITHUB_STEP_SUMMARY"'
        in (step["run"])
    )
