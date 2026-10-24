"""Run Bandit over the declared executable surfaces, or record Semgrep action evidence."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys

from tools.security_exceptions import parse_exceptions
from tools.security_report import (
    Check,
    EvidenceError,
    Finding,
    Status,
    identifier,
    integer,
    load,
    mapping,
    sequence,
    text,
    write_report,
)

SCOPE = ("src", "examples", "demo", "scripts", "tools")
FILE_FLOOR = 40


def classify_bandit(raw: str, exit_status: int, *, floor: int = FILE_FLOOR) -> Check:
    result = Check("bandit", SCOPE, Status.TOOL_ERROR, exit_status)
    try:
        data = load(raw)
        metrics = mapping(data["metrics"])
        totals = mapping(metrics["_totals"])
        files = tuple(identifier(f.removeprefix("./")) for f in metrics if f != "_totals")
        findings: list[Finding] = []
        counts = {
            "files": len(files),
            "loc": integer(totals.get("loc", 0)),
            "errors": len(sequence(data["errors"])),
        }
        for entry in sequence(data["results"]):
            item = mapping(entry)
            severity = text(item["issue_severity"])
            confidence = text(item["issue_confidence"])
            if severity not in {"LOW", "MEDIUM", "HIGH", "UNDEFINED"} or confidence not in {
                "LOW",
                "MEDIUM",
                "HIGH",
                "UNDEFINED",
            }:
                raise EvidenceError("invalid finding classification")
            findings.append(
                Finding(
                    identifier(item["test_id"]),
                    identifier(text(item["filename"]).removeprefix("./")),
                    integer(item["line_number"]),
                    severity,
                    confidence,
                )
            )
            for key in (f"severity.{severity}", f"confidence.{confidence}"):
                counts[key] = counts.get(key, 0) + 1
        suppressions = integer(totals.get("nosec", 0)) + integer(totals.get("skipped_tests", 0))
        result = replace(result, counts=counts, suppressions=suppressions, findings=tuple(findings))
        if exit_status not in {0, 1} or counts["errors"]:
            return replace(
                result, message="Scanner failure or skipped/error files; scan is unusable."
            )
        if len(files) < floor or counts["loc"] == 0 or suppressions:
            return replace(
                result,
                status=Status.INCOMPLETE,
                message="Scan below expected file/LOC floor or unapproved inline suppressions.",
            )
        if bool(findings) != (exit_status == 1):
            return replace(result, message="Scanner exit status disagrees with findings.")
        return replace(result, status=Status.FAIL if findings else Status.PASS)
    except (ValueError, KeyError, TypeError):
        return replace(
            result, message="Missing or invalid Bandit JSON; no raw diagnostics retained."
        )


def apply_bandit_policy(check: Check, policy_raw: str, today: date) -> Check:
    if check.status not in {Status.PASS, Status.FAIL}:
        return check
    try:
        rules = parse_exceptions(load(policy_raw)["exceptions"], today)
        if any(
            r.expires < today
            or not r.file
            or not r.line
            or r.package
            or r.kind != "reviewed-static"
            for r in rules
        ):
            return replace(
                check, status=Status.FAIL, message="Expired or invalid static exception."
            )
        applied: list[str] = []
        blocking = 0
        for finding in check.findings:
            matches = [
                r
                for r in rules
                if (r.id, r.file, r.line) == (finding.id, finding.file, finding.line)
            ]
            if matches:
                applied.append(f"{finding.id}:{finding.file}:{finding.line}")
            else:
                blocking += 1
        return replace(
            check,
            status=Status.FAIL if blocking else Status.PASS,
            exceptions_applied=tuple(applied),
            counts={
                **check.counts,
                "blocking": blocking,
                "stale_exceptions": len(rules) - len(set(applied)),
            },
        )
    except (ValueError, KeyError, TypeError):
        return replace(check, status=Status.TOOL_ERROR, message="Invalid Bandit exception policy.")


def run_bandit() -> Check:
    try:
        process = subprocess.run(
            [sys.executable, "-m", "bandit", "-r", *SCOPE, "-f", "json", "-q"],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        result = classify_bandit(process.stdout, process.returncode)
        expected = {p.as_posix() for surface in SCOPE for p in Path(surface).rglob("*.py")}
        scanned = set(mapping(load(process.stdout)["metrics"])) - {"_totals"}
        if {p.removeprefix("./") for p in scanned} != expected:
            result = replace(
                result,
                status=Status.INCOMPLETE,
                message="Scanned file inventory differs from declared surfaces.",
            )
        result = apply_bandit_policy(
            result, Path("security/bandit-policy.json").read_text(encoding="utf-8"), date.today()
        )
        return replace(result, tool_versions={"bandit": version("bandit")})
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return Check(
            "bandit",
            SCOPE,
            Status.TOOL_ERROR,
            None,
            message="Bandit execution or evidence collection failed.",
        )


def semgrep_evidence(outcome: str) -> Check:
    code: int | None
    match outcome:
        case "success":
            status, code = Status.INCOMPLETE, 0
        case "failure":
            status, code = Status.TOOL_ERROR, 1
        case _:
            status, code = Status.INCOMPLETE, None
    return Check(
        "semgrep",
        ("p/python",),
        status,
        code,
        tool_versions={"action": "713efdd345f3035192eaa63f56867b88e63e4e5d"},
        message=(
            "action outcome only; findings and analysed inventory unavailable. "
            "Failure may include findings."
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=("bandit", "semgrep"))
    parser.add_argument("--outcome", default="")
    parser.add_argument("--output", type=Path, default=Path("security-results"))
    args = parser.parse_args()
    check = run_bandit() if args.check == "bandit" else semgrep_evidence(args.outcome)
    return write_report([check], args.output)


if __name__ == "__main__":
    raise SystemExit(main())
