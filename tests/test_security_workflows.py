from __future__ import annotations

from pathlib import Path

import yaml

from tools.lint_release_workflows import check_pins, check_publish_needs
from tools.security_evidence import SCOPE

ROOT = Path(__file__).resolve().parents[1]


def test_release_security_gate_preserves_all_existing_tiers() -> None:
    text = (ROOT / ".github/workflows/publish-pypi.yml").read_text()
    jobs = yaml.safe_load(text)["jobs"]
    assert check_publish_needs(text, "publish-pypi.yml") == []
    assert "runtime-dependency-audit" in jobs["publish"]["needs"]
    gate = jobs["runtime-dependency-audit"]
    assert gate["permissions"] == {"contents": "read"}
    assert gate["needs"] == "build"
    assert gate["strategy"]["matrix"]["interpreter"] == ["3.11", "3.12", "3.13", "3.14"]
    assert not gate.get("continue-on-error")
    assert all(not step.get("continue-on-error") for step in gate["steps"])
    downloads = [s for s in gate["steps"] if "download-artifact@" in s.get("uses", "")]
    assert downloads[0]["with"]["name"] == "dist"
    commands = "\n".join(s.get("run", "") for s in gate["steps"])
    assert "pip-audit==2.10.1" in commands
    assert "--without-pip" in commands
    assert "tools.dependency_audit_policy" in commands
    assert 'candidate/bin/python" -m tools.browser_integrity' in commands


def test_security_workflows_preserve_evidence_even_on_failure() -> None:
    for filename in ("security.yml", "dependency-audit.yml", "publish-pypi.yml"):
        text = (ROOT / ".github/workflows" / filename).read_text()
        workflow = yaml.safe_load(text)
        assert workflow["permissions"] == {"contents": "read"}
        assert check_pins(text, filename) == []
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if "upload-artifact@" in step.get("uses", "") and step.get("with", {}).get(
                    "path", ""
                ).startswith("security-results"):
                    assert step["if"] == "always()"
                    assert step["with"]["if-no-files-found"] == "error"


def test_security_scan_declares_all_executable_surfaces() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/security.yml").read_text())
    assert SCOPE == ("src", "examples", "demo", "scripts", "tools")
    commands = [s.get("run", "") for s in workflow["jobs"]["bandit"]["steps"]]
    assert "python -m tools.security_evidence bandit" in commands
    semgrep = workflow["jobs"]["semgrep"]["steps"]
    action = next(s for s in semgrep if "semgrep/semgrep-action@" in s.get("uses", ""))
    assert action["with"]["config"] == "p/python"
    assert not action.get("continue-on-error")


def test_scheduled_dependency_lane_uses_shared_reporting_policy() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/dependency-audit.yml").read_text())
    job = workflow["jobs"]["pip-audit"]
    assert job["continue-on-error"] is True
    commands = "\n".join(s.get("run", "") for s in job["steps"])
    assert commands.count("tools.dependency_audit_policy") == 2
    assert "--development" in commands
    assert "tools.browser_integrity" in commands
