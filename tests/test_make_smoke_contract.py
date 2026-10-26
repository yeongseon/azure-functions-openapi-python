"""Local smoke targets remain discoverable, ordered and fail-fast (#811)."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make") or "make"
LANES = ("check", "test", "integration", "docs", "wheel-smoke")
pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="requires make")


def test_verify_recipe_lists_lanes_in_order() -> None:
    # Read the recipe instead of running `make -n verify`: make executes any recipe line that
    # contains $(MAKE) even under -n, and `docs` would then really run `pip install -e` in CI.
    # Given
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    # When
    match = re.search(r"^verify:[^\n]*\n((?:\t[^\n]*\n)+)", makefile, flags=re.MULTILINE)
    # Then
    assert match is not None, "verify target not found"
    recipe = [line.strip() for line in match.group(1).splitlines()]
    assert recipe == [f"@$(MAKE) {lane}" for lane in LANES]


def test_smoke_targets_are_phony_and_visible_in_help() -> None:
    # Given
    targets = {"integration", "wheel-smoke", "verify"}
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    # When
    phony = {
        target
        for line in makefile.splitlines()
        if line.startswith(".PHONY:")
        for target in line.partition(":")[2].split()
    }
    result = subprocess.run(
        [MAKE, "--no-print-directory", "help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    # Then
    assert targets <= phony
    assert all(f"make {target}" in result.stdout for target in targets)


@pytest.mark.parametrize("failed_lane", LANES)
def test_verify_stops_at_the_first_failed_lane(tmp_path: Path, failed_lane: str) -> None:
    # Given: real make recursion, replacing only the expensive lane recipes.
    source = (ROOT / "Makefile").read_text(encoding="utf-8")
    source = re.sub(r"^(check|test|wheel-smoke):.*$", r"\1:", source, flags=re.MULTILINE)
    (tmp_path / "Makefile").write_text(source, encoding="utf-8")
    with (tmp_path / "Makefile").open("a", encoding="utf-8") as makefile:
        makefile.write("\nensure-hatch: ; @:\nbootstrap: ; @:\n")
        makefile.write(
            "".join(f"{lane}: ; @echo {lane}; exit {int(lane == failed_lane)}\n" for lane in LANES)
        )
    # When
    result = subprocess.run(
        [MAKE, "--no-print-directory", "verify", "MAKE=make"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={key: value for key, value in os.environ.items() if not key.startswith("MAKE")},
    )
    # Then
    assert result.returncode != 0
    assert result.stdout.splitlines() == list(LANES[: LANES.index(failed_lane) + 1]), result.stderr


SMOKE_SCRIPT = ROOT / "scripts" / "local-smoke.sh"


def test_smoke_script_checks_azurite_before_and_after_the_route_tests() -> None:
    # The routes are HTTP-only, so a dead Azurite would not fail them. The script must check its
    # liveness itself, both before running them and after (#811 review).
    # Given
    lines = SMOKE_SCRIPT.read_text(encoding="utf-8").splitlines()
    checks = [
        i for i, line in enumerate(lines) if 'kill -0 "$azurite_pid"' in line and "fail" in line
    ]
    pytest_run = next(i for i, line in enumerate(lines) if "-m pytest tests/host_smoke" in line)
    # Then
    assert any(i < pytest_run for i in checks), "no Azurite liveness check before the route tests"
    assert any(i > pytest_run for i in checks), "no Azurite liveness check after the route tests"


@pytest.mark.skipif(os.name != "posix", reason="process groups")
def test_term_during_a_blocking_command_cleans_up_promptly(tmp_path: Path) -> None:
    # Under job control a foreground command sits in its own process group, so Bash would defer
    # the TERM trap until it finished. A hung Hatch must not block cancellation or leak its
    # scratch directory.
    # Given: a `hatch` that hangs, and a private TMPDIR so only this run's scratch dir is seen.
    import signal
    import sys
    import time

    hatch = tmp_path / "hatch"
    hatch.write_text("#!/bin/sh\nexec sleep 300\n", encoding="utf-8")
    hatch.chmod(0o755)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    env = {**os.environ, "PYTHON": sys.executable, "HATCH": str(hatch), "TMPDIR": str(scratch)}
    # When
    proc = subprocess.Popen(  # noqa: S603
        ["bash", str(SMOKE_SCRIPT), "wheel-smoke"],  # noqa: S607
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not any(scratch.glob("openapi-smoke.*")):
            time.sleep(0.1)
        time.sleep(0.5)  # let the blocking command start
        proc.send_signal(signal.SIGTERM)
        # Then
        assert proc.wait(timeout=10) == 143
        assert not list(scratch.glob("openapi-smoke.*")), "scratch directory was not removed"
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
