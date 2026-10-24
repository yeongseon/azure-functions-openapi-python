from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.security_evidence import SCOPE, classify_bandit, run_bandit
from tools.security_report import Check, Status, write_report


def bandit_payload() -> str:
    return json.dumps(
        {
            "errors": [],
            "metrics": {
                "_totals": {"loc": 10, "nosec": 0, "skipped_tests": 0},
                "src/example.py": {"loc": 10},
            },
            "results": [],
        }
    )


@pytest.mark.parametrize(
    ("raw", "exit_status", "expected"),
    [
        ("", 2, Status.TOOL_ERROR),
        ("invalid", 0, Status.TOOL_ERROR),
        ('{"errors": [], "metrics": {"_totals": {}}, "results": []}', 0, Status.INCOMPLETE),
    ],
)
def test_bandit_fails_closed_when_evidence_is_missing(
    raw: str, exit_status: int, expected: Status
) -> None:
    # Given incomplete scanner output; When classified; Then it cannot pass.
    assert classify_bandit(raw, exit_status, floor=1).status == expected


def test_bandit_passes_when_scan_is_complete() -> None:
    # Given one scanned file; When classified; Then counts reflect the scan.
    result = classify_bandit(bandit_payload(), 0, floor=1)
    assert result.status == Status.PASS
    assert result.counts["files"] == 1
    assert result.counts["loc"] == 10


def write_scan_surfaces(root: Path, file_count: int) -> None:
    for index in range(file_count):
        surface = root / SCOPE[index % len(SCOPE)]
        surface.mkdir(exist_ok=True)
        (surface / f"module_{index:03d}.py").write_text(f"VALUE = {index}\n", encoding="utf-8")
    policy = root / "security" / "bandit-policy.json"
    policy.parent.mkdir()
    policy.write_text('{"exceptions": []}\n', encoding="utf-8")


@pytest.mark.parametrize(
    "file_count",
    [
        pytest.param(49, id="below-bandit-progress-threshold"),
        pytest.param(51, id="above-bandit-progress-threshold"),
    ],
)
def test_real_bandit_scan_passes_on_either_side_of_the_progress_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, file_count: int
) -> None:
    # Given harmless files on every declared surface, on either side of the 50-file
    # threshold above which Bandit prints a "Working..." progress bar before its JSON;
    # When the real scanner is run through the evidence collector;
    # Then its JSON still parses and the scan passes instead of reporting TOOL_ERROR.
    write_scan_surfaces(tmp_path, file_count)
    monkeypatch.chdir(tmp_path)
    result = run_bandit()
    assert result.status == Status.PASS
    assert result.counts["files"] == file_count


@pytest.mark.parametrize("field", ["nosec", "skipped_tests"])
def test_bandit_rejects_unapproved_suppressions(field: str) -> None:
    # Given an unapproved suppression; When classified; Then scan is incomplete.
    data = json.loads(bandit_payload())
    data["metrics"]["_totals"][field] = 1
    assert classify_bandit(json.dumps(data), 0, floor=1).status == Status.INCOMPLETE


def test_bandit_rejects_errors_and_crashes() -> None:
    # Given valid JSON with an error; When classified; Then tool failure is distinct.
    data = json.loads(bandit_payload())
    data["errors"] = [{"filename": "src/broken.py", "reason": "secret"}]
    assert classify_bandit(json.dumps(data), 0, floor=1).status == Status.TOOL_ERROR
    assert classify_bandit(bandit_payload(), 2, floor=1).status == Status.TOOL_ERROR


@pytest.mark.parametrize("severity", ["LOW", "MEDIUM", "HIGH"])
def test_bandit_reports_findings_without_source_or_secret(severity: str) -> None:
    # Given a finding containing sensitive source; When classified; Then only metadata survives.
    data = json.loads(bandit_payload())
    data["results"] = [
        {
            "test_id": "B105",
            "filename": "src/example.py",
            "line_number": 3,
            "issue_severity": severity,
            "issue_confidence": "HIGH",
            "code": "Authorization: Bearer secret",
            "issue_text": "AccountKey=secret",
        }
    ]
    result = classify_bandit(json.dumps(data), 1, floor=1)
    assert result.status == Status.FAIL
    assert result.counts[f"severity.{severity}"] == 1
    assert result.counts["confidence.HIGH"] == 1


def test_summary_has_versioned_schema_and_redacts_raw_diagnostics(tmp_path: Path) -> None:
    # Given secret-bearing scanner diagnostics; When rendered; Then neither report leaks them.
    data = json.loads(bandit_payload())
    data["errors"] = ["Authorization: Bearer canary;AccountKey=canary"]
    check = classify_bandit(json.dumps(data), 2, floor=1)
    summary = tmp_path / "job-summary.md"
    write_report([check], tmp_path / "results", summary)
    saved = (tmp_path / "results" / "summary.json").read_text()
    assert json.loads(saved)["schema_version"] == 1
    assert json.loads(saved)["checks"][0]["status"] == "TOOL_ERROR"
    assert "canary" not in saved + summary.read_text()
    assert set(json.loads(saved)["checks"][0]) >= {
        "name",
        "scope",
        "status",
        "exit_status",
        "counts",
        "suppressions",
        "exceptions_applied",
        "tool_versions",
    }


@pytest.mark.parametrize(
    "status,code",
    [(Status.PASS, 0), (Status.FAIL, 1), (Status.TOOL_ERROR, 2), (Status.INCOMPLETE, 3)],
)
def test_status_exit_codes_are_distinct(status: Status, code: int) -> None:
    assert Check("test", (), status, 0).returncode == code
