"""Wiring of the release verification jobs (#904).

The scripts under test are the ``run`` blocks of the real workflow files, extracted from the YAML
and executed in bash with a fake ``python3`` on ``PATH``, so the exit codes and job summaries are
the ones GitHub would produce. Nothing touches the network.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
NEW_JOBS = {"verify-release-tag", "verify-pypi", "report-unpublished"}


def load(name: str) -> dict[Any, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def script(workflow: str, job: str, step: str) -> str:
    steps: list[dict[str, Any]] = load(workflow)["jobs"][job]["steps"]
    found = next(s for s in steps if s["name"] == step)
    run = found["run"]
    assert isinstance(run, str)
    return run


def shell_of(workflow: str, job: str, step: str) -> list[str]:
    steps: list[dict[str, Any]] = load(workflow)["jobs"][job]["steps"]
    found = next(s for s in steps if s["name"] == step)
    if found.get("shell") == "bash":
        return ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c"]
    return ["bash", "-e", "-c"]


class Outcome:
    def __init__(self, result: subprocess.CompletedProcess[str], summary: str, args: str) -> None:
        self.result = result
        self.summary = summary
        self.args = args


def execute(
    tmp_path: Path,
    workflow: str,
    job: str,
    step: str,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    **env: str,
) -> Outcome:
    """Run a workflow step's script with ``python3`` swapped for an argument-recording stub."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "args.txt"
    stub = bin_dir / "python3"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{args_file}"\n'
        f"printf '%s' {stdout!r}\n"
        f"printf '%s' {stderr!r} >&2\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    result = subprocess.run(
        [*shell_of(workflow, job, step), script(workflow, job, step)],
        cwd=tmp_path,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_STEP_SUMMARY": str(summary),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    args = args_file.read_text(encoding="utf-8") if args_file.exists() else ""
    return Outcome(result, summary.read_text(encoding="utf-8"), args)


# ------------------------------------------------------------ release-please.yml


CHECK_TAG = (
    "release-please.yml",
    "verify-release-tag",
    "Check the tagged source, mainline history and changelog",
)


def test_a_sound_tag_passes_quietly(tmp_path: Path) -> None:
    out = execute(tmp_path, *CHECK_TAG, RELEASE_TAG="v1.2.3")
    assert out.result.returncode == 0
    assert out.summary == ""
    assert out.args.strip() == "-m tools.release_audit check-tag v1.2.3 --wait-seconds 60"


@pytest.mark.parametrize("code", [1, 2])
def test_an_unsound_tag_or_a_tool_failure_fails_the_run_and_explains(
    tmp_path: Path, code: int
) -> None:
    problem = "v1.2.3: source at a25b33f declares version '0.15.1', not '1.2.3'"
    out = execute(tmp_path, *CHECK_TAG, exit_code=code, stderr=problem, RELEASE_TAG="v1.2.3")
    assert out.result.returncode == 1  # fail closed whatever the tool's own exit code was
    assert problem in out.result.stderr
    assert "### Release tag `v1.2.3` failed validation" in out.summary
    assert f"- {problem}" in out.summary
    assert "Do not move or delete the tag" in out.summary


def test_the_tag_check_is_read_only_and_cannot_block_anything() -> None:
    job = load("release-please.yml")["jobs"]["verify-release-tag"]
    assert job["permissions"] == {"contents": "read"}
    assert job["needs"] == "release-please"
    assert job["if"] == "needs.release-please.outputs.release_created == 'true'"
    assert "continue-on-error" not in job  # a failure must be visible
    for name, other in load("release-please.yml")["jobs"].items():
        assert "verify-release-tag" not in _needs(other), name


# ------------------------------------------------------------ publish-pypi.yml


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def test_pypi_is_read_back_after_the_upload_job() -> None:
    job = load("publish-pypi.yml")["jobs"]["verify-pypi"]
    assert _needs(job) == ["build", "publish"]
    assert job["permissions"] == {"contents": "read"}
    run = next(s["run"] for s in job["steps"] if "run" in s)
    assert 'check-published "$RELEASE_TAG" --wait-minutes 10' in run


def test_the_new_publish_jobs_gate_nothing_and_publish_keeps_every_gate() -> None:
    jobs = load("publish-pypi.yml")["jobs"]
    for name, job in jobs.items():
        assert not NEW_JOBS & set(_needs(job)) or name == "report-unpublished", name
    assert {"build", "lib-tests", "cookbook-smoke", "cookbook-host-smoke", "azure-e2e"} <= set(
        _needs(jobs["publish"])
    )
    assert jobs["notify-cookbook"]["needs"] == ["build", "publish"]


def test_an_unpublished_candidate_is_reported_whenever_publish_did_not_succeed() -> None:
    job = load("publish-pypi.yml")["jobs"]["report-unpublished"]
    assert job["if"] == "${{ !cancelled() && needs.publish.result != 'success' }}"
    assert "publish" in _needs(job)
    assert set(_needs(load("publish-pypi.yml")["jobs"]["publish"])) <= set(_needs(job))
    assert job["permissions"] == {}


def test_the_unpublished_report_names_the_tag_and_the_recovery(tmp_path: Path) -> None:
    out = execute(
        tmp_path,
        "publish-pypi.yml",
        "report-unpublished",
        "Write the recovery steps to the job summary",
        RELEASE_TAG="v1.2.3",
    )
    assert out.result.returncode == 0
    assert "::error::This run did not publish v1.2.3 to PyPI" in out.result.stdout
    assert "### This run did not publish `v1.2.3` to PyPI" in out.summary
    assert "gh workflow run publish-pypi.yml --ref v1.2.3" in out.summary
    assert "not proof of publication" in out.summary
    assert "Never move or reuse a tag" in out.summary


# ------------------------------------------------------------ release-audit.yml


AUDIT = ("release-audit.yml", "audit", "Audit tags, GitHub Releases, CHANGELOG and PyPI")


def test_the_scheduled_audit_is_weekly_manual_and_read_only() -> None:
    workflow = load("release-audit.yml")
    triggers = workflow[True]  # PyYAML reads the bare key ``on`` as a boolean
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert len(triggers["schedule"]) == 1
    assert workflow["permissions"] == {"contents": "read"}
    text = (WORKFLOWS / "release-audit.yml").read_text(encoding="utf-8")
    assert re.search(r":\s*write\b", text) is None


def test_a_clean_audit_passes_and_is_summarised(tmp_path: Path) -> None:
    out = execute(tmp_path, *AUDIT, stdout="RESULT: OK\n")
    assert out.result.returncode == 0
    assert out.args.strip() == "-m tools.release_audit audit"
    assert out.summary.startswith("```text\n") and "RESULT: OK" in out.summary


@pytest.mark.parametrize("code", [1, 2])
def test_a_discrepancy_or_a_tool_failure_fails_the_audit_run(tmp_path: Path, code: int) -> None:
    out = execute(
        tmp_path, *AUDIT, exit_code=code, stdout="RESULT: DISCREPANCIES FOUND\n", stderr="boom\n"
    )
    assert out.result.returncode == code
    assert "DISCREPANCIES FOUND" in out.summary and "boom" in out.summary
    assert "DISCREPANCIES FOUND" in out.result.stdout
