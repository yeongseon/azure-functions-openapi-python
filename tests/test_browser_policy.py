"""Exercise the browser lane's exit policy through real pytest sessions."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("body", "exit_code"),
    [
        ("def test_case(): pass", 0),
        ("import pytest\ndef test_case(): pytest.skip('unavailable')", 1),
        ("import pytest\npytest.skip('unavailable', allow_module_level=True)", 1),
        ("def test_case(): assert False", 1),
        ("", 5),
    ],
    ids=["pass", "runtime-skip", "collection-skip", "failure", "empty"],
)
def test_browser_lane_exit_status(tmp_path: Path, body: str, exit_code: int) -> None:
    # Given: a standalone suite, independent of the repository's default deselection/coverage.
    suite = tmp_path / "test_case.py"
    suite.write_text(body, encoding="utf-8")

    # When: run the same skip policy used by make test-browser.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tools.browser_policy",
            "-o",
            "addopts=",
            str(suite),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        env={key: value for key, value in os.environ.items() if key != "PYTEST_ADDOPTS"},
    )

    # Then: skipped or empty verification must never report success.
    assert result.returncode == exit_code, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("make") is None, reason="requires Make")
def test_browser_target_fails_when_playwright_is_absent(tmp_path: Path) -> None:
    # Given: an explicitly missing package, even if the user has cached Playwright elsewhere.
    environment = {key: value for key, value in os.environ.items() if key != "PYTEST_ADDOPTS"}

    # When: exercise the actual lane entry point without bootstrapping or downloading anything.
    result = subprocess.run(
        [
            "make",
            "test-browser",
            f"BROWSER_PYTHON={sys.executable}",
            f"PLAYWRIGHT_PACKAGE={tmp_path / 'absent'}",
        ],
        text=True,
        capture_output=True,
        timeout=30,
        env=environment,
    )

    # Then: no browser verification is represented as a successful skipped run.
    assert result.returncode != 0, result.stdout + result.stderr
    assert "8 errors" in result.stdout
