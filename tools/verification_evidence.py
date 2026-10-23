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


_REDACTED = "[REDACTED]"
_QUOTED = r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'"
_AUTHORIZATION = re.compile(
    r"(?im)(?P<key>(?:proxy-)?authorization[\"']?\s*[:=]\s*)(?P<value>" + _QUOTED + r"|[^\r\n\"<]+)"
)
_URL_CREDENTIALS = re.compile(r"(https?://)[^/@\s\"']+:[^/@\s\"']+@")
_SECRET_FIELD = re.compile(
    r"(?i)(?<![\w-])(?P<key>(?:[\w.-]*(?:token|password|passwd|secret|api[_-]?key|"
    r"connection[_-]?string)|AccountKey|SharedAccessKey|SharedAccessSignature|"
    r"AzureWebJobsStorage|InstrumentationKey|x-functions-key|code|sig)"
    r"[\"']?\s*[:=]\s*)(?P<value>" + _QUOTED + r"|[^\s;&<>\"',]+)"
)
_SECRET_ENV_NAME = re.compile(
    r"(?i)secret|token|password|connection|string|accountkey|functions.key|api.?key|sas"
)
_TEXT_SUFFIXES = frozenset({".log", ".txt", ".xml", ".json", ".md"})


def _mask(match: re.Match[str]) -> str:
    value = match.group("value")
    quote = value[0] if value[:1] in {'"', "'"} else ""
    return f"{match.group('key')}{quote}{_REDACTED}{quote}"


def _known_secrets() -> list[str]:
    values = {
        value
        for key, value in os.environ.items()
        if len(value) >= 6 and _SECRET_ENV_NAME.search(key)
    }
    # Longest first so a secret that contains another secret is replaced whole, and the JSON
    # string-escaped spelling is covered because saved logs often embed serialized JSON.
    escaped = {json.dumps(value)[1:-1] for value in values}
    return sorted(values | escaped, key=len, reverse=True)


def redact(text: str) -> str:
    """Mask credentials in free text without changing its surrounding syntax.

    Complete known secrets are replaced first so a partial pattern match cannot change a
    value before the exact-match pass sees it. Quoted values are consumed whole (including
    whitespace and escaped quotes) and keep their quotes, so JSON and XML stay well formed.
    """
    for value in _known_secrets():
        text = text.replace(value, _REDACTED)
    text = _AUTHORIZATION.sub(_mask, text)
    text = _URL_CREDENTIALS.sub(r"\1" + _REDACTED + "@", text)
    return _SECRET_FIELD.sub(_mask, text)


def redact_json(value: object) -> object:
    """Redact every string leaf of a JSON-compatible value, leaving its structure intact."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (list, tuple)):
        return [redact_json(item) for item in value]
    if isinstance(value, dict):
        return {redact(str(key)): redact_json(item) for key, item in value.items()}
    return value


def dump_json(value: object) -> str:
    """Serialize redacted JSON so credentials never reach disk and the file always parses."""
    return json.dumps(redact_json(value), indent=2) + "\n"


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


def _redact_file_text(suffix: str, text: str) -> str:
    if suffix == ".json":
        try:
            return dump_json(json.loads(text))
        except ValueError:
            pass
    return redact(text)


def save(directory: Path, summary: Summary) -> Summary:
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.rglob("*"):
        # Only textual evidence is rewritten: binary assets stay byte-for-byte, and symlinks are
        # never followed out of the evidence tree.
        if path.is_symlink() or not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        redacted = _redact_file_text(path.suffix, original)
        if redacted != original:
            path.write_text(redacted, encoding="utf-8")
    (directory / "environment.json").write_text(
        dump_json(environment(live=directory.name == "integration")), encoding="utf-8"
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
    path.write_text(dump_json(asdict(summary)), encoding="utf-8")
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
