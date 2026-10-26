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
