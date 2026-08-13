"""Regression guard for the fleet-wide workflow pin-hygiene lint.

Exercises tools/lint_workflow_pins.py against this repo (must be clean) and
against synthetic drift (must be caught). Keeps the vendored lint honest.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LINT_PATH = _REPO_ROOT / "tools" / "lint_workflow_pins.py"

_spec = importlib.util.spec_from_file_location("lint_workflow_pins", _LINT_PATH)
assert _spec and _spec.loader
lint_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_mod)


def test_repo_workflows_are_pin_clean() -> None:
    """Every committed workflow must satisfy pin-hygiene."""
    assert lint_mod.lint() == []


def test_sha_with_comment_passes() -> None:
    text = "      - uses: actions/checkout@" + "a" * 40 + " # v7.0.1\n"
    assert lint_mod.check_pin_hygiene(text, "fake.yml") == []


def test_local_composite_action_passes() -> None:
    text = "      - uses: ./.github/actions/setup\n"
    assert lint_mod.check_pin_hygiene(text, "fake.yml") == []


def test_documented_exception_passes() -> None:
    text = "      - uses: pypa/gh-action-pypi-publish@release/v1 # pin-exempt: trusted publisher\n"
    assert lint_mod.check_pin_hygiene(text, "fake.yml") == []


def test_unpinned_tag_fails() -> None:
    text = "      - uses: actions/checkout@v4\n"
    errors = lint_mod.check_pin_hygiene(text, "fake.yml")
    assert errors and "not a 40-hex" in errors[0]


def test_branch_ref_without_exemption_fails() -> None:
    text = "      - uses: pypa/gh-action-pypi-publish@release/v1\n"
    errors = lint_mod.check_pin_hygiene(text, "fake.yml")
    assert errors and "not a 40-hex" in errors[0]


def test_sha_without_version_comment_fails() -> None:
    text = "      - uses: actions/checkout@" + "b" * 40 + "\n"
    errors = lint_mod.check_pin_hygiene(text, "fake.yml")
    assert errors and "missing the trailing" in errors[0]


def test_pin_exempt_marker_requires_a_reason() -> None:
    # A bare "pin-exempt" with no reason must NOT satisfy the exemption.
    text = "      - uses: pypa/gh-action-pypi-publish@release/v1 # pin-exempt:\n"
    errors = lint_mod.check_pin_hygiene(text, "fake.yml")
    assert errors and "not a 40-hex" in errors[0]
