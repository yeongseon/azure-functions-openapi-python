"""Regression contracts for review findings on verification commands."""

from __future__ import annotations

from contextlib import nullcontext
from http.client import HTTPException
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError(), OSError(), HTTPException()])
def test_readiness_retries_transient_failure(
    error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a live process and one transient request failure followed by success.
    from tools.verification_host import wait_ready

    request = Mock(side_effect=[error, nullcontext(Mock(status=200))])
    monkeypatch.setattr("tools.verification_host.urlopen", request)
    monkeypatch.setattr("tools.verification_host.time.sleep", lambda _: None)
    # When waiting for host readiness.
    wait_ready(Mock(poll=Mock(return_value=None)), "http://localhost/api")
    # Then startup is retried rather than aborted.
    assert request.call_count == 2


@pytest.mark.parametrize("failure", [False, True])
def test_check_saves_prerequisite_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    # Given a real Makefile and deterministic quality prerequisites.
    makefile = (ROOT / "Makefile").read_text()
    start = makefile.index("check-commands:")
    end = makefile.index(".PHONY: lint-workflows", start)
    makefile = (
        makefile[:start]
        + (
            "check-commands: review-prerequisite\n\t@true\n"
            "review-prerequisite:\n"
            + ("\t@echo 'password=CANARY_quality'; exit 7\n\n" if failure else "\t@true\n\n")
        )
        + makefile[end:]
    )
    (tmp_path / "Makefile").write_text(makefile)
    shutil.copytree(ROOT / "tools", tmp_path / "tools")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "job-summary"))
    # When executing the public quality gate including failing prerequisites.
    result = subprocess.run(
        [
            "make",
            "check",
            "CI=1",
            f"PYTHON={sys.executable}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Then logs and machine-readable failure status survive the make failure.
    summary = json.loads((tmp_path / "test-results/check/summary.json").read_text())
    assert summary["status"] == ("FAIL" if failure else "PASS")
    assert bool(result.returncode) == failure
    assert "CANARY_quality" not in (tmp_path / "test-results/check/logs/runner.log").read_text()
    assert f"check: {summary['status']}" in (tmp_path / "job-summary").read_text()


@pytest.mark.parametrize("target", ["doctor", "report", "clean"])
def test_maintenance_never_bootstraps_hatch(tmp_path: Path, target: str) -> None:
    # Given a fresh checkout mirror and empty Hatch data directory, with CI unset.
    shutil.copy(ROOT / "Makefile", tmp_path)
    shutil.copy(ROOT / "pyproject.toml", tmp_path)
    shutil.copytree(ROOT / "tools", tmp_path / "tools")
    environment = dict(os.environ, HATCH_DATA_DIR=str(tmp_path / "hatch-data"))
    environment.pop("CI", None)
    environment.pop("VIRTUAL_ENV", None)
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(tmp_path / ".venv")], check=True
    )
    # When running a maintenance command without any development environment.
    result = subprocess.run(
        ["make", target], cwd=tmp_path, env=environment, capture_output=True, text=True
    )
    # Then no environment or dependency synchronization occurs.
    assert "Creating environment" not in result.stderr
    assert not list((tmp_path / "hatch-data").rglob("pyvenv.cfg"))
    if target == "doctor":
        assert result.returncode != 0
        assert "development environment not created: run make install" in result.stdout


def test_verification_tests_leave_outer_summary_untouched(tmp_path: Path) -> None:
    outer = tmp_path / "outer-summary"
    outer.write_text("real job evidence\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_verification_commands.py",
            "-k",
            "verify_runs_every_required_lane or azure_missing_prerequisites",
            "--no-cov",
            "-q",
        ],
        cwd=ROOT,
        env=dict(os.environ, GITHUB_STEP_SUMMARY=str(outer)),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert outer.read_text() == "real job evidence\n"
