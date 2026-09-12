"""Regression guard for the hatch-pin / CI-matrix conflict lint.

Origin of the fleet-wide fix: #554 / PR #555 (CI hardening tracked in #559);
fleet deployment audit in #576. This repo is the canonical source for the lint.

Exercises tools/lint_hatch_matrix.py against this repo (must be clean -- the
test matrix runs directly on the interpreter and adds a version guard) and
against synthetic buggy configs (must be caught).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LINT_PATH = _REPO_ROOT / "tools" / "lint_hatch_matrix.py"

_spec = importlib.util.spec_from_file_location("lint_hatch_matrix", _LINT_PATH)
assert _spec and _spec.loader
lint_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_mod)


_PINNED = {"default": "3.10"}

_MATRIX_INLINE = """
jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - run: pip install hatch
      - run: make check-all
"""

_MATRIX_BLOCK = """
jobs:
  test:
    strategy:
      matrix:
        python-version:
          - "3.10"
          - "3.11"
    steps:
      - run: hatch run pytest
"""


def test_repo_is_clean() -> None:
    """This repo's committed workflows must pass -- the fix is in place."""
    assert lint_mod.lint() == []


def test_parses_default_env_pin() -> None:
    text = '[tool.hatch.envs.default]\npython = "3.10"\n'
    assert lint_mod.parse_pinned_hatch_envs(text) == {"default": "3.10"}


def test_matrix_value_is_not_a_pin() -> None:
    # A hatch env whose python is a list/matrix is not a single-interpreter pin.
    text = '[tool.hatch.envs.default]\npython = ["3.10", "3.11"]\n'
    assert lint_mod.parse_pinned_hatch_envs(text) == {}


def test_section_boundary_ends_env_scope() -> None:
    text = '[tool.hatch.envs.default]\n[tool.other]\npython = "3.10"\n'
    assert lint_mod.parse_pinned_hatch_envs(text) == {}


def test_inline_matrix_versions_parsed() -> None:
    assert lint_mod.matrix_python_versions(_MATRIX_INLINE) == ["3.10", "3.11", "3.12"]


def test_block_matrix_versions_parsed() -> None:
    assert lint_mod.matrix_python_versions(_MATRIX_BLOCK) == ["3.10", "3.11"]


def test_matrix_reference_is_not_a_declaration() -> None:
    text = "        python-version: ${{ matrix.python-version }}\n"
    assert lint_mod.matrix_python_versions(text) == []


def test_hatch_run_is_flagged() -> None:
    errors = lint_mod.check_workflow(_MATRIX_BLOCK, "ci.yml", _PINNED)
    assert errors and "runs tests through Hatch" in errors[0]


def test_make_check_all_is_flagged() -> None:
    errors = lint_mod.check_workflow(_MATRIX_INLINE, "ci.yml", _PINNED)
    assert errors and "every matrix cell" in errors[0]


def test_no_pin_is_clean() -> None:
    assert lint_mod.check_workflow(_MATRIX_INLINE, "ci.yml", {}) == []


def test_single_version_matrix_is_clean() -> None:
    text = _MATRIX_INLINE.replace('["3.10", "3.11", "3.12"]', '["3.10"]')
    assert lint_mod.check_workflow(text, "ci.yml", _PINNED) == []


def test_direct_pytest_is_clean() -> None:
    # Runs on the matrix interpreter directly -- no hatch routing, so safe.
    text = """
jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.10", "3.11"]
    steps:
      - run: python -m pip install -e .[dev]
      - run: python -m pytest
"""
    assert lint_mod.check_workflow(text, "ci.yml", _PINNED) == []


def test_interpreter_guard_alone_is_not_enough() -> None:
    # Routes tests through hatch (hatch run pytest) with only a version_info
    # guard. The guard asserts the top-level interpreter, but the tests still
    # run on the pinned hatch env -- so this must be FLAGGED, not cleared.
    text = (
        _MATRIX_BLOCK
        + """
      - name: Assert interpreter matches matrix
        env:
          EXPECTED: ${{ matrix.python-version }}
        run: python -c "import sys; assert '.'.join(map(str, sys.version_info[:2]))"
        # version_info guard tied to matrix.python-version
"""
    )
    errors = lint_mod.check_workflow(text, "ci.yml", _PINNED)
    assert errors and "runs tests through Hatch" in errors[0]
