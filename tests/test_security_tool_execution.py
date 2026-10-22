from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools import browser_integrity, dependency_audit_policy, security_evidence
from tools.security_evidence import apply_bandit_policy, classify_bandit, semgrep_evidence
from tools.security_report import Check, Status


def scanner_result(raw: str, code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["scanner"], code, stdout=raw, stderr="secret")


def test_bandit_runner_checks_inventory_and_preserves_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = {
        p.as_posix(): {"loc": 1}
        for surface in security_evidence.SCOPE
        for p in Path(surface).rglob("*.py")
    }
    metrics["_totals"] = {"loc": len(metrics)}
    raw = json.dumps({"errors": [], "metrics": metrics, "results": []})

    def complete(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return scanner_result(raw)

    monkeypatch.setattr(subprocess, "run", complete)
    result = security_evidence.run_bandit()
    assert result.status == Status.PASS
    assert result.tool_versions["bandit"] == "1.9.4"
    del metrics[next(iter(metrics))]
    raw = json.dumps({"errors": [], "metrics": metrics, "results": []})
    assert security_evidence.run_bandit().status == Status.INCOMPLETE


def test_audit_runner_uses_only_target_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text('{"schema_version":1,"blocking":"all-known-runtime","exceptions":[]}')

    def complete(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[command.index("--path") + 1] == str(tmp_path)
        return scanner_result('{"dependencies":[{"name":"example","version":"1","vulns":[]}]}')

    monkeypatch.setattr(subprocess, "run", complete)
    monkeypatch.setattr(dependency_audit_policy, "version", lambda name: "2.10.1")
    assert dependency_audit_policy.run_audit(tmp_path, policy).status == Status.PASS


def test_browser_network_exit_is_not_a_hash_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(["curl"], 22, stdout=b"error page", stderr=b"secret")

    monkeypatch.setattr(subprocess, "run", failed)
    assert all(c.status == Status.TOOL_ERROR for c in browser_integrity.verify_assets())


def test_browser_success_with_wrong_bytes_fails_integrity(monkeypatch: pytest.MonkeyPatch) -> None:
    def complete(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(["curl"], 0, stdout=b"modified", stderr=b"")

    monkeypatch.setattr(subprocess, "run", complete)
    assert all(c.status == Status.FAIL for c in browser_integrity.verify_assets())


@pytest.mark.parametrize("development", [False, True])
@pytest.mark.parametrize(
    "status,code", [(Status.FAIL, 1), (Status.TOOL_ERROR, 2), (Status.INCOMPLETE, 3)]
)
def test_audit_cli_preserves_failure_codes_in_both_lanes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, development: bool, status: Status, code: int
) -> None:
    args = ["audit", "--site-packages", str(tmp_path), "--output", str(tmp_path)]
    if development:
        args.append("--development")
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(
        dependency_audit_policy, "run_audit", lambda path, policy: Check("pip-audit", (), status, 1)
    )
    assert dependency_audit_policy.main() == code
    assert json.loads((tmp_path / "summary.json").read_text())["checks"][0]["status"] == status


def test_browser_cli_writes_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["sri", "--output", str(tmp_path)])
    monkeypatch.setattr(
        browser_integrity, "verify_assets", lambda: [Check("sri", (), Status.FAIL, 0)]
    )
    assert browser_integrity.main() == 1


def test_bandit_cli_writes_classified_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "argv", ["security", "bandit", "--output", str(tmp_path)])
    monkeypatch.setattr(
        security_evidence, "run_bandit", lambda: Check("bandit", (), Status.INCOMPLETE, 0)
    )
    assert security_evidence.main() == 3


@pytest.mark.parametrize(
    "severity,exit_code,expected",
    [
        ("INVALID", 1, Status.TOOL_ERROR),
        ("LOW", 0, Status.TOOL_ERROR),
    ],
)
def test_bandit_rejects_invalid_classification_or_inconsistent_exit(
    severity: str, exit_code: int, expected: Status
) -> None:
    raw = json.dumps(
        {
            "errors": [],
            "metrics": {"_totals": {"loc": 1}, "src/x.py": {}},
            "results": [
                {
                    "test_id": "B404",
                    "filename": "src/x.py",
                    "line_number": 1,
                    "issue_severity": severity,
                    "issue_confidence": "HIGH",
                }
            ],
        }
    )
    assert classify_bandit(raw, exit_code, floor=1).status == expected


def test_static_unmatched_finding_remains_blocking() -> None:
    check = classify_bandit(
        json.dumps(
            {
                "errors": [],
                "metrics": {"_totals": {"loc": 1}, "src/x.py": {}},
                "results": [
                    {
                        "test_id": "B404",
                        "filename": "src/x.py",
                        "line_number": 1,
                        "issue_severity": "LOW",
                        "issue_confidence": "HIGH",
                    }
                ],
            }
        ),
        1,
        floor=1,
    )
    result = apply_bandit_policy(check, '{"exceptions":[]}', date(2026, 10, 22))
    assert result.status == Status.FAIL
    assert result.counts["blocking"] == 1


@pytest.mark.parametrize(
    "outcome,status",
    [("success", Status.PASS), ("failure", Status.TOOL_ERROR), ("skipped", Status.INCOMPLETE)],
)
def test_semgrep_records_action_outcome(outcome: str, status: Status) -> None:
    assert semgrep_evidence(outcome).status == status


def test_evidence_cli_executes_without_package_dependencies(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.security_evidence",
            "semgrep",
            "--outcome",
            "success",
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads((tmp_path / "summary.json").read_text())["checks"][0]["name"] == "semgrep"


@pytest.mark.parametrize("failure", [OSError(), subprocess.TimeoutExpired("scanner", 1)])
def test_external_tool_failures_are_classified(
    monkeypatch: pytest.MonkeyPatch, failure: OSError | subprocess.TimeoutExpired, tmp_path: Path
) -> None:
    def fail(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    assert security_evidence.run_bandit().status == Status.TOOL_ERROR
    assert dependency_audit_policy.run_audit(tmp_path, tmp_path).status == Status.TOOL_ERROR
    assert all(c.status == Status.TOOL_ERROR for c in browser_integrity.verify_assets())


def test_static_exceptions_match_exact_file_line_and_id() -> None:
    check = classify_bandit(
        json.dumps(
            {
                "errors": [],
                "metrics": {"_totals": {"loc": 1}, "tools/example.py": {}},
                "results": [
                    {
                        "test_id": "B404",
                        "filename": "tools/example.py",
                        "line_number": 1,
                        "issue_severity": "LOW",
                        "issue_confidence": "HIGH",
                    }
                ],
            }
        ),
        1,
        floor=1,
    )
    policy = {
        "exceptions": [
            {
                "id": "B404",
                "file": "tools/example.py",
                "line": 1,
                "kind": "reviewed-static",
                "reason": "fixed shell-free command",
                "owner": "maintainer",
                "added": "2026-10-01",
                "expires": "2026-11-01",
            }
        ]
    }
    assert apply_bandit_policy(check, json.dumps(policy), date(2026, 10, 22)).status == Status.PASS
    assert apply_bandit_policy(check, json.dumps(policy), date(2026, 11, 2)).status == Status.FAIL
    assert apply_bandit_policy(check, "invalid", date(2026, 10, 22)).status == Status.TOOL_ERROR


def test_incomplete_static_scan_cannot_be_excepted() -> None:
    check = Check("bandit", (), Status.INCOMPLETE, 0)
    assert apply_bandit_policy(check, '{"exceptions": []}', date(2026, 10, 22)) == check
