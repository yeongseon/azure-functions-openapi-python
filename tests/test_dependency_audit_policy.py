from __future__ import annotations

from datetime import date
import json

import pytest

from tools.dependency_audit_policy import classify_audit
from tools.security_report import Status

TODAY = date(2026, 10, 22)
POLICY = '{"schema_version": 1, "blocking": "all-known-runtime", "exceptions": []}'


def payload(*, vulnerable: bool = False) -> str:
    return json.dumps(
        {
            "dependencies": [
                {
                    "name": "pydantic",
                    "version": "2.0",
                    "vulns": [{"id": "CVE-2026-12345", "fix_versions": []}] if vulnerable else [],
                }
            ]
        }
    )


@pytest.mark.parametrize("vulnerable,expected", [(False, Status.PASS), (True, Status.FAIL)])
def test_audit_blocks_any_known_runtime_vulnerability(vulnerable: bool, expected: Status) -> None:
    # Given resolved runtime dependencies; When evaluated; Then all advisories block.
    assert (
        classify_audit(
            payload(vulnerable=vulnerable), 1 if vulnerable else 0, policy_raw=POLICY, today=TODAY
        ).status
        == expected
    )


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "invalid",
        "{}",
        '{"dependencies": []}',
        '{"dependencies": [{"name": "x", "skip_reason": "offline"}]}',
    ],
)
def test_audit_tool_errors_never_become_clean_or_vulnerable(raw: str) -> None:
    assert classify_audit(raw, 1, policy_raw=POLICY, today=TODAY).status == Status.TOOL_ERROR


@pytest.mark.parametrize(
    "expires,expected", [("2026-10-21", Status.FAIL), ("2026-11-21", Status.PASS)]
)
def test_exception_expiry_is_enforced(expires: str, expected: Status) -> None:
    # Given an owned, justified exception; When audited; Then only a current exception applies.
    policy = json.loads(POLICY)
    policy["exceptions"] = [
        {
            "id": "CVE-2026-12345",
            "package": "pydantic",
            "reason": "no patched release available",
            "owner": "maintainer",
            "kind": "fix-not-available",
            "added": "2026-10-01",
            "expires": expires,
        }
    ]
    result = classify_audit(payload(vulnerable=True), 1, policy_raw=json.dumps(policy), today=TODAY)
    assert result.status == expected
    assert bool(result.exceptions_applied) == (expected == Status.PASS)


def test_unused_exception_is_reported() -> None:
    policy = json.loads(POLICY)
    policy["exceptions"] = [
        {
            "id": "CVE-2026-12345",
            "package": "pydantic",
            "reason": "reviewed unreachable code",
            "owner": "maintainer",
            "kind": "not-affected",
            "added": "2026-10-01",
            "expires": "2026-11-01",
        }
    ]
    result = classify_audit(payload(), 0, policy_raw=json.dumps(policy), today=TODAY)
    assert result.status == Status.PASS
    assert result.counts["stale_exceptions"] == 1
