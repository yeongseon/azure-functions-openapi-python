from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from tools.dependency_audit_policy import run_audit
from tools.security_report import JSON, Status


def candidate_environment(root: Path) -> tuple[Path, Path, Path]:
    site = root / "site"
    for name, version in (("unpublished-probe", "9876.1"), ("idna", "3.11")):
        info = site / f"{name.replace('-', '_')}-{version}.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    wheel = root / "probe.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(
            "unpublished_probe-9876.1.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: unpublished-probe\nVersion: 9876.1\n",
        )
    policy = root / "policy.json"
    policy.write_text('{"schema_version":1,"blocking":"all-known-runtime","exceptions":[]}')
    return site, wheel, policy


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("clean", Status.PASS),
        ("advisory", Status.FAIL),
        ("skip", Status.TOOL_ERROR),
        ("omitted", Status.TOOL_ERROR),
        ("candidate-mismatch", Status.TOOL_ERROR),
    ],
)
def test_unpublished_candidate_audits_exact_third_party_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, expected: Status
) -> None:
    site, wheel, policy = candidate_environment(tmp_path)

    def audit(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        requirements = Path(command[command.index("--requirement") + 1]).read_text()
        assert requirements == "idna==3.11\n"
        assert "--no-deps" in command and "--disable-pip" in command
        dependency: dict[str, JSON] = {"name": "idna", "version": "3.11", "vulns": []}
        dependencies = [dependency]
        if scenario == "skip":
            dependencies = [{"name": "idna", "skip_reason": "unavailable"}]
        elif scenario == "advisory":
            dependency["vulns"] = [{"id": "CVE-2026-12345", "fix_versions": []}]
        elif scenario == "omitted":
            dependencies = [{"name": "other", "version": "1", "vulns": []}]
        elif scenario == "candidate-mismatch":
            dependencies.append({"name": "unpublished-probe", "version": "9876.2", "vulns": []})
        return subprocess.CompletedProcess(
            command, int(scenario == "advisory"), json.dumps({"dependencies": dependencies})
        )

    monkeypatch.setattr(subprocess, "run", audit)
    monkeypatch.setattr("tools.dependency_audit_policy.version", lambda _: "2.10.1")
    assert run_audit(site, policy, wheel).status == expected


@pytest.mark.parametrize("condition", ["mismatch", "absent", "empty"])
def test_unverified_or_empty_candidate_inventory_never_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    site, wheel, policy = candidate_environment(tmp_path)
    if condition == "mismatch":
        (site / "unpublished_probe-9876.1.dist-info/METADATA").write_text(
            "Name: unpublished-probe\nVersion: 9876.2\n"
        )
    elif condition == "absent":
        (site / "unpublished_probe-9876.1.dist-info/METADATA").unlink()
    else:
        (site / "idna-3.11.dist-info/METADATA").unlink()
    scanner = Mock()
    monkeypatch.setattr(subprocess, "run", scanner)
    assert run_audit(site, policy, wheel).status == Status.INCOMPLETE
    scanner.assert_not_called()
