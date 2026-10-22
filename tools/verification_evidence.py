"""Versioned evidence shared by local commands and CI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Literal
import xml.etree.ElementTree as ET

Status = Literal["PASS", "FAIL", "INCOMPLETE", "NOT_APPLICABLE"]


def read_xml_root(path: Path) -> ET.Element:
    """Parse a locally generated report, refusing entity declarations."""
    data = path.read_bytes()
    if b"<!ENTITY" in data.upper():
        raise ValueError("XML reports must not declare entities")
    return ET.fromstring(data)


@dataclass(frozen=True, slots=True)
class Summary:
    schema_version: int
    lane: str
    command: tuple[str, ...]
    selected: int
    passed: int
    failed: int
    skipped: int
    status: Status
    exit_code: int
    supporting_files: tuple[str, ...] = ()
    coverage: float | None = None
    reason: str = ""


def redact(text: str) -> str:
    # Redact entire authorization values, including the scheme and whitespace.
    text = re.sub(r"(?im)(authorization[\"']?\s*[:=]\s*)[^\r\n<\"]+", r"\1[REDACTED]", text)
    text = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", text)
    text = re.sub(
        r"(?i)(?<![\w-])((?:[\w-]*(?:token|password|secret|connectionstring)|AccountKey|"
        r"SharedAccessSignature|AzureWebJobsStorage|x-functions-key|code|sig)"
        r"[\"']?\s*[:=]\s*[\"']?)[^\s;&<\"']+",
        r"\1[REDACTED]",
        text,
    )
    for key, value in os.environ.items():
        if len(value) >= 6 and re.search(
            r"(?i)secret|token|password|connection|string|accountkey|functions.key", key
        ):
            text = text.replace(value, "[REDACTED]")
    return text


def environment(live: bool = False) -> dict[str, str]:
    metadata = {
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "runtime": platform.python_implementation(),
    }
    for package in ("azure-functions", "azure-functions-openapi", "pydantic", "hatch"):
        try:
            metadata[package] = version(package)
        except PackageNotFoundError:
            metadata[package] = "not installed"
    for key in ("E2E_BASE_URL", "E2E_EXPECTED_VERSION", "GITHUB_SHA"):
        if key in os.environ:
            metadata[key] = redact(os.environ[key])
    for tool in ("func", "azurite") if live else ():
        try:
            result = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=10)
            metadata[tool] = redact(result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            metadata[tool] = "unavailable"
    return metadata


def collect(directory: Path, command: list[str], exit_code: int) -> Summary:
    cases: list[ET.Element] = []
    for path in directory.rglob("*.xml"):
        if "junit" in path.name:
            cases.extend(read_xml_root(path).iter("testcase"))
    skipped = sum(case.find("skipped") is not None for case in cases)
    failed = sum(
        case.find("failure") is not None or case.find("error") is not None for case in cases
    )
    passed = len(cases) - skipped - failed
    status: Status = "PASS"
    if exit_code or failed:
        status = "FAIL"
    elif not cases or not passed or (directory.name != "test" and skipped):
        status = "INCOMPLETE"
    coverage_path = directory / "coverage.xml"
    coverage = None
    if coverage_path.exists():
        coverage = float(read_xml_root(coverage_path).get("line-rate", "0"))
    return Summary(
        1,
        directory.name,
        tuple(command),
        len(cases),
        passed,
        failed,
        skipped,
        status,
        exit_code,
        coverage=coverage,
    )


def render(summary: Summary) -> str:
    return (
        f"{summary.lane}: {summary.status} | selected={summary.selected} "
        f"passed={summary.passed} failed={summary.failed} skipped={summary.skipped} "
        f"exit={summary.exit_code}" + (f" | {summary.reason}" if summary.reason else "")
    )


def publish(summary: Summary) -> None:
    text = render(summary)
    print(text)
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(f"\n- {text}\n")


def save(directory: Path, summary: Summary) -> Summary:
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.rglob("*"):
        if path.is_file():
            path.write_text(redact(path.read_text(encoding="utf-8")), encoding="utf-8")
    (directory / "environment.json").write_text(
        redact(json.dumps(environment(live=directory.name == "integration"), indent=2)) + "\n",
        encoding="utf-8",
    )
    summary = replace(
        summary,
        supporting_files=tuple(
            str(path)
            for path in sorted(directory.rglob("*"))
            if path.is_file() and path.name != "summary.json"
        ),
    )
    path = directory / "summary.json"
    path.write_text(redact(json.dumps(asdict(summary), indent=2)) + "\n", encoding="utf-8")
    return summary


def report(root: Path) -> int:
    paths = sorted(root.glob("*/summary.json"))
    if not paths:
        print("No saved verification results")
        return 1
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        publish(Summary(**data))
    return 0
