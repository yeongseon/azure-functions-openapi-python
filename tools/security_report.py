"""Allow-listed security evidence: raw scanner output is never persisted."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
import os
from pathlib import Path
import re
from typing import TypeAlias, assert_never

JSON: TypeAlias = "None | bool | int | float | str | list[JSON] | dict[str, JSON]"


class EvidenceError(ValueError):
    """Unusable scanner or policy input; messages never contain the input."""


def mapping(value: JSON) -> dict[str, JSON]:
    if not isinstance(value, dict):
        raise EvidenceError("expected JSON object")
    return value


def sequence(value: JSON) -> list[JSON]:
    if not isinstance(value, list):
        raise EvidenceError("expected JSON array")
    return value


def text(value: JSON) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceError("expected nonempty string")
    return value


def integer(value: JSON) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceError("expected nonnegative integer")
    return value


def load(raw: str) -> dict[str, JSON]:
    parsed: JSON = json.loads(raw)
    return mapping(parsed)


def identifier(value: JSON) -> str:
    candidate = text(value)
    if not re.fullmatch(r"[A-Za-z0-9_.:/@+-]{1,240}", candidate):
        raise EvidenceError("unsafe evidence identifier")
    if candidate.startswith(("/", "http:", "https:")) or ".." in candidate:
        raise EvidenceError("unsafe evidence path")
    return candidate


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    TOOL_ERROR = "TOOL_ERROR"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    file: str = ""
    line: int = 0
    severity: str = "UNKNOWN"
    confidence: str = "UNKNOWN"
    package: str = ""


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    scope: tuple[str, ...]
    status: Status
    exit_status: int | None
    counts: dict[str, int] = field(default_factory=dict)
    suppressions: int = 0
    exceptions_applied: tuple[str, ...] = ()
    tool_versions: dict[str, str] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    message: str = ""

    @property
    def returncode(self) -> int:
        match self.status:
            case Status.PASS:
                return 0
            case Status.FAIL:
                return 1
            case Status.TOOL_ERROR:
                return 2
            case Status.INCOMPLETE:
                return 3
            case unreachable:
                assert_never(unreachable)


def write_report(checks: list[Check], output: Path, summary: Path | None = None) -> int:
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps({"schema_version": 1, "checks": [asdict(c) for c in checks]}, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown = "## Security evidence\n\n| Check | Status | Counts |\n| --- | --- | --- |\n"
    for check in checks:
        markdown += f"| {check.name} | {check.status} | {json.dumps(check.counts)} |\n"
        markdown += f"\n{check.message}\n\n"
    if summary is None and os.environ.get("GITHUB_STEP_SUMMARY"):
        summary = Path(os.environ["GITHUB_STEP_SUMMARY"])
    if summary is not None:
        with summary.open("a", encoding="utf-8") as stream:
            stream.write(markdown)
    for check in checks:
        print(f"{check.name}: {check.status} {json.dumps(check.counts)} {check.message}")
    return max((c.returncode for c in checks), default=3)
