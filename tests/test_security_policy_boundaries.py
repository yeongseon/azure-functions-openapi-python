from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from tools.dependency_audit_policy import classify_audit
from tools.security_exceptions import parse_exceptions
from tools.security_report import (
    Check,
    EvidenceError,
    Status,
    identifier,
    integer,
    load,
    sequence,
    text,
    write_report,
)


@pytest.mark.parametrize("raw", ["null", "[]", '"text"', "true"])
def test_json_boundary_requires_object(raw: str) -> None:
    with pytest.raises(EvidenceError):
        load(raw)


@pytest.mark.parametrize("value", [None, 0, True, ""])
def test_text_boundary_rejects_nonempty_string_violations(value: None | int | str) -> None:
    with pytest.raises(EvidenceError):
        text(value)


@pytest.mark.parametrize("value", [None, True, -1, "1"])
def test_count_boundary_rejects_invalid_counts(value: None | int | str) -> None:
    with pytest.raises(EvidenceError):
        integer(value)


@pytest.mark.parametrize("value", [None, "[]", 0])
def test_array_boundary_rejects_nonarrays(value: None | str | int) -> None:
    with pytest.raises(EvidenceError):
        sequence(value)


@pytest.mark.parametrize(
    "value",
    [
        "/tmp/file.py",
        "../secret",
        "https://example.com",
        "Authorization: Bearer canary",
        "file.py?code=canary",
    ],
)
def test_identifiers_reject_sensitive_or_external_metadata(value: str) -> None:
    with pytest.raises(EvidenceError):
        identifier(value)


@pytest.mark.parametrize(
    "patch",
    [
        {"expires": "2027-10-22"},
        {"added": "2026-11-01"},
        {"expires": "invalid"},
        {"kind": "ignore-all"},
        {"line": -1},
        {"line": True},
        {"owner": ""},
        {"reason": ""},
    ],
)
def test_exception_boundary_rejects_invalid_policy(patch: dict[str, str | int]) -> None:
    rule = {
        "id": "CVE-2026-12345",
        "package": "example",
        "kind": "not-affected",
        "reason": "reviewed unreachable path",
        "owner": "maintainer",
        "added": "2026-10-01",
        "expires": "2026-11-01",
        **patch,
    }
    parsed = load(json.dumps({"exceptions": [rule]}))
    with pytest.raises((EvidenceError, ValueError)):
        parse_exceptions(parsed["exceptions"], date(2026, 10, 22))


def test_duplicate_exception_is_rejected() -> None:
    rule = {
        "id": "CVE-2026-12345",
        "package": "example",
        "kind": "not-affected",
        "reason": "reviewed unreachable path",
        "owner": "maintainer",
        "added": "2026-10-01",
        "expires": "2026-11-01",
    }
    parsed = load(json.dumps({"exceptions": [rule, rule]}))
    with pytest.raises(EvidenceError):
        parse_exceptions(parsed["exceptions"], date(2026, 10, 22))


@pytest.mark.parametrize(
    "policy",
    [
        "{}",
        "invalid",
        '{"schema_version":2,"blocking":"all-known-runtime","exceptions":[]}',
        '{"schema_version":1,"blocking":"high-only","exceptions":[]}',
    ],
)
def test_audit_rejects_unsupported_policy(policy: str) -> None:
    assert (
        classify_audit(
            '{"dependencies":[{"name":"example","version":"1","vulns":[]}]}',
            0,
            policy_raw=policy,
            today=date(2026, 10, 22),
        ).status
        == Status.TOOL_ERROR
    )


@pytest.mark.parametrize("exit_status", [0, 2])
def test_audit_rejects_exit_status_inconsistent_with_findings(exit_status: int) -> None:
    raw = '{"dependencies":[{"name":"example","version":"1","vulns":[{"id":"CVE-1"}]}]}'
    policy = '{"schema_version":1,"blocking":"all-known-runtime","exceptions":[]}'
    assert (
        classify_audit(raw, exit_status, policy_raw=policy, today=date(2026, 10, 22)).status
        == Status.TOOL_ERROR
    )


def test_fix_not_available_exception_stops_applying_when_patch_exists() -> None:
    policy = {
        "schema_version": 1,
        "blocking": "all-known-runtime",
        "exceptions": [
            {
                "id": "CVE-1",
                "package": "example",
                "kind": "fix-not-available",
                "reason": "no fix",
                "owner": "maintainer",
                "added": "2026-10-01",
                "expires": "2026-11-01",
            }
        ],
    }
    raw = (
        '{"dependencies":[{"name":"example","version":"1",'
        '"vulns":[{"id":"CVE-1","fix_versions":["2"]}]}]}'
    )
    assert (
        classify_audit(raw, 1, policy_raw=json.dumps(policy), today=date(2026, 10, 22)).status
        == Status.FAIL
    )


def test_summary_appends_to_github_summary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("existing\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert write_report([Check("scanner", (), Status.PASS, 0)], tmp_path / "output") == 0
    assert summary.read_text().startswith("existing\n")


def test_skipped_dependency_is_tool_error_even_with_version() -> None:
    raw = (
        '{"dependencies":[{"name":"example","version":"1",'
        '"skip_reason":"index unavailable","vulns":[]}]}'
    )
    policy = '{"schema_version":1,"blocking":"all-known-runtime","exceptions":[]}'
    assert (
        classify_audit(raw, 0, policy_raw=policy, today=date(2026, 10, 22)).status
        == Status.TOOL_ERROR
    )
