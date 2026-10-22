"""Offline contracts for the saved verification evidence boundary."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


def test_report_renders_saved_json_without_running_a_lane(tmp_path: Path) -> None:
    # Given no results and an isolated working directory.
    runner = Path(__file__).resolve().parents[1] / "tools" / "verification.py"
    # When requesting a report, no test process should be started.
    result = subprocess.run(
        [sys.executable, str(runner), "report"], cwd=tmp_path, capture_output=True, text=True
    )
    # Then absence of saved evidence is explicit and non-successful.
    assert result.returncode == 1
    assert "No saved" in result.stdout
    assert not (tmp_path / "test-results").exists()


@pytest.mark.parametrize(
    ("cases", "exit_code", "status"),
    [
        ("", 0, "INCOMPLETE"),
        ("<testcase><skipped/></testcase>", 0, "INCOMPLETE"),
        ("<testcase><failure/></testcase>", 1, "FAIL"),
        ("<testcase/>", 0, "PASS"),
    ],
)
def test_junit_classifies_execution_fail_closed(
    tmp_path: Path, cases: str, exit_code: int, status: str
) -> None:
    from tools.verification_evidence import collect

    # Given actual JUnit cases, not an optimistic process exit alone.
    (tmp_path / "junit.xml").write_text(f"<testsuite>{cases}</testsuite>")
    # When collecting evidence.
    summary = collect(tmp_path, ["pytest"], exit_code)
    # Then zero/all-skipped cases cannot pass.
    assert summary.status == status


@pytest.mark.parametrize(
    "secret",
    [
        "AccountKey=VERYSECRET;",
        "SharedAccessSignature=VERYSECRET;",
        "code=VERYSECRET&x=1",
        "x-functions-key: VERYSECRET",
        "Authorization: Bearer VERYSECRET",
        "password=VERYSECRET",
        "token=VERYSECRET",
        "AzureWebJobsStorage=VERYSECRET",
    ],
)
def test_secrets_are_redacted_from_persisted_evidence(tmp_path: Path, secret: str) -> None:
    from tools.verification_evidence import collect, save

    # Given secret-bearing logs and XML attributes/text.
    (tmp_path / "junit.xml").write_text(
        "<testsuite><testcase><system-out>"
        + secret.replace("&", "&amp;")
        + "</system-out></testcase></testsuite>"
    )
    (tmp_path / "output.log").write_text(secret)
    # When saving all evidence.
    save(tmp_path, collect(tmp_path, ["pytest", secret], 0))
    # Then persisted evidence contains no credential value.
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert "VERYSECRET" not in path.read_text()


def test_saved_summary_has_versioned_schema_and_supporting_paths(tmp_path: Path) -> None:
    from tools.verification_evidence import collect, save

    # Given one executed test and coverage.
    (tmp_path / "junit.xml").write_text("<testsuite><testcase/></testsuite>")
    (tmp_path / "coverage.xml").write_text('<coverage line-rate="0.99"/>')
    # When saving a lane.
    save(tmp_path, collect(tmp_path, ["pytest"], 0))
    data = json.loads((tmp_path / "summary.json").read_text())
    # Then consumers can identify the contract and its proof.
    assert data["schema_version"] == 1
    assert (data["selected"], data["passed"], data["failed"], data["skipped"]) == (1, 1, 0, 0)
    assert data["coverage"] == 0.99
    assert str(tmp_path / "junit.xml") in data["supporting_files"]
    assert (tmp_path / "environment.json").exists()


def test_redaction_preserves_json_syntax(tmp_path: Path) -> None:
    from tools.verification_evidence import Summary, save

    summary = Summary(1, "test", ("Authorization: Bearer VERYSECRET",), 1, 1, 0, 0, "PASS", 0)
    save(tmp_path, summary)
    data = json.loads((tmp_path / "summary.json").read_text())
    assert "VERYSECRET" not in str(data)
