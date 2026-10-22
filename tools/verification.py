"""Canonical stdlib-only verification CLI. Run via make or python -m tools.verification."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.verification_environment import clean, doctor
from tools.verification_evidence import Status, Summary, collect, publish, report, save
from tools.verification_host import host_smoke
from tools.verification_process import run


def pytest_command(lane: str, extra: list[str]) -> list[str]:
    directory = Path("test-results") / lane
    command = [sys.executable, "-m", "pytest"]
    if lane == "test":
        command += [
            "tests/",
            "-m",
            "not e2e and not perf",
            "--ignore=tests/e2e",
            "--cov-report=xml:" + str(directory / "coverage.xml"),
        ]
    else:
        command += ["tests/e2e/", "-m", "e2e", "--no-cov"]
    return command + ["--junitxml=" + str(directory / "junit.xml"), *extra]


def execute(lane: str, extra: list[str]) -> int:
    directory = Path("test-results") / lane
    if directory.exists():
        shutil.rmtree(directory)
    (directory / "logs").mkdir(parents=True)
    command = pytest_command(lane, extra)
    reason = ""
    code = 0
    blocked = False
    try:
        if lane in {"azure-e2e", "local-e2e"}:
            missing = [
                key for key in ("E2E_BASE_URL", "E2E_EXPECTED_VERSION") if not os.environ.get(key)
            ]
            if missing:
                blocked, code, reason = True, 2, "Missing prerequisites: " + ", ".join(missing)
        if lane == "integration":
            command = ["func", "start", "(managed host smoke)"]
            if doctor(live=True):
                blocked, code, reason = True, 2, "Missing required integration tools"
            else:
                code = host_smoke(directory)
        elif not blocked:
            code = run(command, directory / "logs/runner.log")
    except KeyboardInterrupt:
        code, reason = 130, "Interrupted; owned child processes terminated"
    except (OSError, ET.ParseError, ValueError) as error:
        code, reason = 2, str(error)
    try:
        summary = collect(directory, command, code)
    except (ET.ParseError, ValueError) as error:
        summary = Summary(
            1,
            lane,
            tuple(command),
            0,
            0,
            0,
            0,
            "INCOMPLETE",
            2,
            reason=f"Invalid evidence: {error}",
        )
    if blocked:
        summary = replace(summary, status="INCOMPLETE")
        destination = directory / "junit.xml"
        suite = ET.Element("testsuite", name=lane, tests="0")
        ET.ElementTree(suite).write(destination, encoding="unicode")
    summary = replace(summary, reason=reason or summary.reason)
    summary = save(directory, summary)
    publish(summary)
    return code if code > 0 else (0 if summary.status == "PASS" else 1)


def verify() -> int:
    directory = Path("test-results/verify")
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    outcomes: list[Summary] = []
    for target in ("check", "test", "integration", "perf", "wheel-smoke", "docs"):
        code = run(["make", target], directory / "logs" / f"{target}.log", 1200)
        path = Path("test-results") / target / "summary.json"
        if target in {"test", "integration"} and path.exists():
            summary = Summary(**json.loads(path.read_text()))
            if code and summary.status == "PASS":
                summary = replace(summary, status="FAIL", exit_code=code)
        elif target in {"test", "integration"}:
            summary = Summary(
                1,
                target,
                ("make", target),
                0,
                0,
                0,
                0,
                "INCOMPLETE",
                code or 1,
                reason="Required lane summary missing",
            )
        else:
            summary = Summary(
                1,
                target,
                ("make", target),
                1,
                int(code == 0),
                int(code != 0),
                0,
                "PASS" if code == 0 else "FAIL",
                code,
            )
        outcomes.append(summary)
    status: Status = "FAIL" if any(item.status == "FAIL" for item in outcomes) else "PASS"
    if status == "PASS" and any(item.status != "PASS" for item in outcomes):
        status = "INCOMPLETE"
    aggregate = Summary(
        1,
        "verify",
        ("make", "verify"),
        sum(s.selected for s in outcomes),
        sum(s.passed for s in outcomes),
        sum(s.failed for s in outcomes),
        sum(s.skipped for s in outcomes),
        status,
        0 if status == "PASS" else 1,
        reason="; ".join(f"{item.lane}={item.status}" for item in outcomes),
    )
    (directory / "lanes.json").write_text(json.dumps([asdict(s) for s in outcomes], indent=2))
    publish(save(directory, aggregate))
    return aggregate.exit_code


def focused(lane: str, command: list[str]) -> int:
    directory = Path("test-results") / lane
    if directory.exists():
        shutil.rmtree(directory)
    code = run(command, directory / "logs/runner.log", 1200)
    summary = Summary(
        1,
        lane,
        tuple(command),
        1,
        int(code == 0),
        int(code != 0),
        0,
        "PASS" if code == 0 else "FAIL",
        code,
    )
    publish(save(directory, summary))
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "lane",
        choices=(
            "test",
            "integration",
            "verify",
            "azure-e2e",
            "local-e2e",
            "report",
            "doctor",
            "clean",
            "focused",
        ),
    )
    args, extra = parser.parse_known_args()
    if tuple(sys.version_info[:2]) < (3, 11):
        parser.error("Python >=3.11 is required")
    match args.lane:
        case "report":
            return report(Path("test-results"))
        case "doctor":
            return doctor()
        case "clean":
            clean(Path.cwd())
            return 0
        case "verify":
            return verify()
        case "focused":
            return focused(extra[0], [sys.executable, *extra[1:]])
        case _:
            return execute(args.lane, extra)


if __name__ == "__main__":
    raise SystemExit(main())
