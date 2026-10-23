"""Audit an isolated wheel environment; distinguish advisory findings from tool failures."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import BadZipFile

from tools.candidate_inventory import Inventory, package, verified_inventory
from tools.security_exceptions import parse_exceptions
from tools.security_report import (
    Check,
    EvidenceError,
    Finding,
    Status,
    identifier,
    load,
    mapping,
    sequence,
    text,
    write_report,
)


def classify_audit(raw: str, exit_status: int, *, policy_raw: str, today: date) -> Check:
    result = Check("pip-audit", ("resolved-runtime-wheel",), Status.TOOL_ERROR, exit_status)
    try:
        policy = load(policy_raw)
        if policy["schema_version"] != 1 or policy["blocking"] != "all-known-runtime":
            raise EvidenceError("unsupported policy")
        rules = parse_exceptions(policy["exceptions"], today)
        if any(r.file or r.line or not r.package or r.kind == "reviewed-static" for r in rules):
            raise EvidenceError("invalid dependency exception")
        dependencies = sequence(load(raw)["dependencies"])
        if not dependencies or exit_status not in {0, 1}:
            raise EvidenceError("empty audit or tool crash")
        findings: list[Finding] = []
        applied: set[str] = set()
        blocking = 0
        packages = 0
        for dependency in dependencies:
            item = mapping(dependency)
            package = identifier(item["name"]).lower().replace("_", "-")
            text(item["version"])
            if "skip_reason" in item:
                raise EvidenceError("dependency could not be audited")
            packages += 1
            for advisory in sequence(item["vulns"]):
                vuln = mapping(advisory)
                advisory_id = identifier(vuln["id"])
                severity = identifier(vuln.get("severity", "UNKNOWN"))
                findings.append(Finding(advisory_id, severity=severity, package=package))
                matches = [
                    r
                    for r in rules
                    if r.id == advisory_id
                    and r.package.lower().replace("_", "-") == package
                    and r.expires >= today
                ]
                if matches and (
                    matches[0].kind != "fix-not-available" or not sequence(vuln["fix_versions"])
                ):
                    applied.add(f"{package}:{advisory_id}")
                else:
                    blocking += 1
        if bool(findings) != (exit_status == 1):
            raise EvidenceError("exit status disagrees with findings")
        expired = sum(r.expires < today for r in rules)
        return replace(
            result,
            status=Status.FAIL if blocking or expired else Status.PASS,
            counts={
                "packages": packages,
                "findings": len(findings),
                "blocking": blocking,
                "expired_exceptions": expired,
                "stale_exceptions": len(rules) - len(applied),
            },
            findings=tuple(findings),
            exceptions_applied=tuple(sorted(applied)),
            message="All known advisories block unless a current, applicable exception exists.",
        )
    except (ValueError, KeyError, TypeError):
        return replace(result, message="Audit/tool/policy incomplete or invalid; release blocked.")


def verify_audited_inventory(raw: str, inventory: Inventory) -> None:
    audited = tuple(
        package(text(item["name"]), text(item["version"]))
        for value in sequence(load(raw)["dependencies"])
        for item in (mapping(value),)
    )
    third_party = tuple(p for p in audited if p.name != inventory.candidate.name)
    candidates = tuple(p for p in audited if p.name == inventory.candidate.name)
    if candidates not in ((), (inventory.candidate,)) or (
        len(third_party) != len(inventory.dependencies)
        or set(third_party) != set(inventory.dependencies)
    ):
        raise EvidenceError("audit differs from verified inventory")


def run_audit(site_packages: Path, policy: Path, candidate: Path | None = None) -> Check:
    try:
        if candidate is None:
            raise EvidenceError("candidate wheel required")
        inventory = verified_inventory(site_packages, candidate)
    except (OSError, ValueError, KeyError, TypeError, BadZipFile):
        return Check(
            "pip-audit",
            ("resolved-runtime-wheel",),
            Status.INCOMPLETE,
            None,
            message="Candidate identity or third-party inventory incomplete; release blocked.",
        )
    try:
        with tempfile.TemporaryDirectory(prefix="openapi-audit-") as temporary:
            requirements = Path(temporary) / "requirements.txt"
            requirements.write_text(inventory.requirements(), encoding="utf-8")
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip_audit",
                    "--requirement",
                    str(requirements),
                    "--no-deps",
                    "--disable-pip",
                    "--format",
                    "json",
                    "--desc",
                    "off",
                    "--progress-spinner",
                    "off",
                    "--timeout",
                    "30",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        verify_audited_inventory(process.stdout, inventory)
        result = classify_audit(
            process.stdout,
            process.returncode,
            policy_raw=policy.read_text(encoding="utf-8"),
            today=date.today(),
        )
        return replace(result, tool_versions={"pip-audit": version("pip-audit")})
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return Check(
            "pip-audit",
            ("resolved-runtime-wheel",),
            Status.TOOL_ERROR,
            None,
            message="Audit execution failed; release blocked.",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--candidate-wheel", type=Path, required=True)
    parser.add_argument(
        "--policy", type=Path, default=Path("security/dependency-audit-policy.json")
    )
    parser.add_argument("--output", type=Path, default=Path("security-results"))
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    check = run_audit(args.site_packages, args.policy, args.candidate_wheel)
    if args.development:
        check = replace(check, name="pip-audit-development", scope=("runtime-and-development",))
    return write_report([check], args.output)


if __name__ == "__main__":
    raise SystemExit(main())
