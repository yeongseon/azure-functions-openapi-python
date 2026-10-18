# tests/test_e2e_marker_contract.py
"""Regression guard for #787: the e2e marker/selector contract.

tests/e2e/test_openapi_e2e.py's six tests carry module-level `pytestmark =
pytest.mark.e2e`. Two things depend on that marker and must keep working
together:

1. The dedicated e2e entry points -- `make e2e-local`/`make e2e-azure`, the
   Hatch `e2e-azure` script (`pytest -v -m e2e --no-cov tests/e2e/`), and the
   e2e-azure.yml release workflow -- select tests with `-m e2e` and must
   collect exactly six, not zero.
2. The default unit-test run (pyproject.toml addopts: "-m 'not e2e and not
   perf'") must deselect those same six at collection time, not merely skip
   them at runtime, so `make test` never attempts real-host HTTP calls.

Before #787, the marker was entirely missing: `pytest --collect-only -m e2e
tests/e2e/` collected zero tests and exited 5, while the default run
accidentally excluded them only through their own per-test
`skipif(not E2E_BASE_URL)`, not through marker-based selection.

This runs real pytest subprocesses against the actual repository collection
(not a synthetic fixture), so it fails immediately if a future change to the
marker, to pyproject.toml's addopts, or to the module's pytestmark silently
breaks either entry point again.
"""

from __future__ import annotations

import os
import subprocess
import sys

_E2E_TEST_NAMES = (
    "test_health_returns_200",
    "test_openapi_json_returns_valid_spec",
    "test_openapi_yaml_returns_valid_spec",
    "test_swagger_ui_returns_html",
    "test_list_items_endpoint",
    "test_deployed_version_matches_candidate",
)


def _run_pytest(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_dedicated_e2e_selector_collects_exactly_six_tests() -> None:
    """Same selector the Hatch 'e2e-azure' script and release workflow use."""
    result = _run_pytest("--collect-only", "-m", "e2e", "--no-cov", "-q", "tests/e2e/")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "tests/e2e/test_openapi_e2e.py: 6" in output, output


def test_dedicated_e2e_selector_collects_every_named_test() -> None:
    """Pins down exact test IDs, so a partially-marked module (some tests
    missing pytestmark) is caught even if the total count happens to match.
    """
    result = _run_pytest("--collect-only", "-m", "e2e", "--no-cov", "tests/e2e/")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    for name in _E2E_TEST_NAMES:
        assert name in output, f"{name!r} missing from '-m e2e' collection:\n{output}"


def test_default_run_deselects_e2e_tests_at_collection_not_runtime() -> None:
    """The regular suite must exclude these at collection time (marker-based
    deselection), not merely skip them individually at runtime -- the two
    report differently, and only the former is what pyproject.toml's addopts
    is meant to guarantee.
    """
    result = _run_pytest("--collect-only", "--no-cov", "tests/e2e/")
    output = result.stdout + result.stderr

    # exit 5 ("no tests collected") is the CORRECT outcome here: every
    # candidate in this path is deselected by the default "not e2e" filter.
    assert result.returncode == 5, output
    assert "6 deselected" in output, output
    for name in _E2E_TEST_NAMES:
        assert name not in output, f"{name!r} was collected despite the default filter:\n{output}"


def test_e2e_azure_env_guard_rejects_an_unconfigured_invocation() -> None:
    """The Hatch `e2e-azure` script is wired to run scripts/require_e2e_env.py
    before pytest (pyproject.toml), specifically to protect the DIRECT
    `hatch run e2e-azure` entry point: #787's Makefile preflight only covers
    `make e2e-local`/`make e2e-azure`, not this one. Before this guard,
    running it with E2E_BASE_URL/E2E_EXPECTED_VERSION unset collected all six
    tests, skipped every one via their own skipif, and exited 0 -- a
    dedicated run that looked successful but certified nothing.
    """
    env = dict(os.environ)
    env.pop("E2E_BASE_URL", None)
    env.pop("E2E_EXPECTED_VERSION", None)

    result = subprocess.run(
        [sys.executable, "scripts/require_e2e_env.py"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "E2E_BASE_URL" in result.stderr
    assert "E2E_EXPECTED_VERSION" in result.stderr


def test_e2e_azure_env_guard_passes_a_fully_configured_invocation() -> None:
    env = dict(os.environ)
    env["E2E_BASE_URL"] = "https://example.invalid"
    env["E2E_EXPECTED_VERSION"] = "0.0.0"

    result = subprocess.run(
        [sys.executable, "scripts/require_e2e_env.py"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
