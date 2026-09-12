#!/usr/bin/env python3
"""Guard against the fleet-wide "hatch default-env pin hides the CI matrix" bug.

Origin of the fleet-wide fix: #554 / PR #555 (CI hardening tracked in #559);
fleet deployment audit in #576. This repo is the canonical source for the lint.

The failure mode this lint catches: a repo pins its Hatch *default* env to a
single interpreter --

    [tool.hatch.envs.default]
    python = "3.10"

-- while its CI declares a *multi-version* ``python-version`` matrix that then
installs and runs the test suite **through Hatch** (``hatch run ...`` directly,
or ``make install`` / ``make check-all`` targets that route through Hatch).
Because ``hatch run`` re-resolves to the pinned interpreter regardless of what
``actions/setup-python`` provisioned, *every* matrix cell secretly executes on
the pinned version. The per-version status/coverage badges are then false: the
matrix looks green across 3.11/3.12/3.13 but nothing ever ran there.

Rule -- a workflow is flagged when ALL of the following hold:

1. ``pyproject.toml`` pins at least one Hatch env to a single ``python``
   version (``[tool.hatch.envs.<name>] python = "X.Y"``); and
2. the workflow declares a ``python-version`` matrix with 2+ distinct
   versions; and
3. that workflow routes the test run through Hatch (``hatch run`` or a
   ``make`` target known to wrap Hatch: ``install`` / ``check-all`` /
   ``check`` / ``test`` / ``coverage``); and
4. the workflow does NOT run its tests directly on the matrix interpreter --
   i.e. there is no un-Hatched ``pytest`` / ``python -m pytest`` invocation.
   A ``sys.version_info`` guard is NOT sufficient on its own: it asserts the
   top-level interpreter, but a subsequent ``hatch run pytest`` still
   re-resolves to the pinned env, so the guard cannot prove where the tests
   actually ran. Only a direct pytest invocation on the matrix interpreter
   makes the workflow safe.

Stdlib-only on purpose (mirrors ``tools/lint_workflow_pins.py``): the lint must
not itself depend on a package that can drift. Exit code 0 = clean, 1 = drift.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

WORKFLOWS_DIR = ".github/workflows"
PYPROJECT = "pyproject.toml"

# ``make`` targets that (in this fleet's Makefiles) execute through ``hatch run``.
_HATCH_MAKE_TARGETS = ("check-all", "install", "check", "test", "coverage")

# [tool.hatch.envs.<name>] section header.
_HATCH_ENV_HEADER_RE = re.compile(r"^\s*\[tool\.hatch\.envs\.(?P<name>[^\].]+)\]\s*$")
# A single pinned interpreter: python = "3.10". A matrix/list value is not a pin.
_PYTHON_PIN_RE = re.compile(r"""^\s*python\s*=\s*["'](?P<ver>\d+\.\d+)["']\s*$""")
# Any other section header ends the current section.
_SECTION_RE = re.compile(r"^\s*\[")

# Routes tests through Hatch: a bare ``hatch run`` or a Hatch-wrapping make target.
_HATCH_RUN_RE = re.compile(r"\bhatch\s+run\b")
_HATCH_MAKE_RE = re.compile(r"\bmake\s+(?:" + "|".join(_HATCH_MAKE_TARGETS) + r")\b")

# A direct pytest invocation (``python -m pytest`` / ``pytest ...``) that is not
# routed through Hatch proves the tests run on the matrix interpreter itself.
_DIRECT_PYTEST_RE = re.compile(r"\bpytest\b")

# Inline matrix list: python-version: ["3.10", "3.11"].
_MATRIX_INLINE_RE = re.compile(r"""python-version:\s*\[(?P<body>[^\]]*)\]""")
# Block matrix key: python-version:  (followed by "- x.y" items on later lines).
_MATRIX_BLOCK_KEY_RE = re.compile(r"""^(?P<indent>\s*)python-version:\s*$""")
_QUOTED_VER_RE = re.compile(r"""["'](?P<ver>\d+(?:\.\d+)+)["']""")
_DASH_VER_RE = re.compile(r"""^\s*-\s*["']?(?P<ver>\d+(?:\.\d+)+)["']?\s*$""")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def parse_pinned_hatch_envs(pyproject_text: str) -> dict[str, str]:
    """Return ``{env_name: version}`` for every Hatch env pinned to one interpreter."""
    pinned: dict[str, str] = {}
    current: str | None = None
    for line in pyproject_text.splitlines():
        header = _HATCH_ENV_HEADER_RE.match(line)
        if header:
            current = header.group("name")
            continue
        if _SECTION_RE.match(line):
            # Some other TOML table began; leave the hatch-env context.
            current = None
            continue
        if current is not None:
            pin = _PYTHON_PIN_RE.match(line)
            if pin:
                pinned[current] = pin.group("ver")
    return pinned


def matrix_python_versions(workflow_text: str) -> list[str]:
    """Return the distinct interpreter versions declared in a ``python-version`` matrix.

    Recognizes both inline (``["3.10", "3.11"]``) and block (``- "3.10"``) forms.
    ``${{ matrix.python-version }}`` *references* are ignored -- only declarations
    of an actual version list count.
    """
    versions: list[str] = []
    lines = workflow_text.splitlines()
    for idx, line in enumerate(lines):
        inline = _MATRIX_INLINE_RE.search(line)
        if inline:
            versions.extend(m.group("ver") for m in _QUOTED_VER_RE.finditer(inline.group("body")))
            continue
        block = _MATRIX_BLOCK_KEY_RE.match(line)
        if block:
            base_indent = len(block.group("indent"))
            for follow in lines[idx + 1 :]:
                if not follow.strip():
                    continue
                indent = len(follow) - len(follow.lstrip())
                dash = _DASH_VER_RE.match(follow)
                if dash and indent > base_indent:
                    versions.append(dash.group("ver"))
                    continue
                # Dedent or a non-item line closes the block list.
                if indent <= base_indent or not follow.lstrip().startswith("-"):
                    break
    # Distinct, order-preserving.
    seen: set[str] = set()
    distinct: list[str] = []
    for ver in versions:
        if ver not in seen:
            seen.add(ver)
            distinct.append(ver)
    return distinct


def routes_tests_through_hatch(workflow_text: str) -> bool:
    """True when the workflow runs tests via ``hatch run`` or a Hatch-wrapping make target."""
    return bool(_HATCH_RUN_RE.search(workflow_text) or _HATCH_MAKE_RE.search(workflow_text))


def runs_tests_directly_on_matrix(workflow_text: str) -> bool:
    """True when the workflow invokes pytest directly (not through ``hatch run``).

    The interpreter provisioned by ``actions/setup-python`` is then the one that
    executes the tests, so the matrix cell is genuinely exercised. A mere
    ``sys.version_info`` guard is NOT sufficient: it asserts the *top-level*
    interpreter but a subsequent ``hatch run pytest`` still re-resolves to the
    pinned Hatch env, so the guard cannot prove where the tests actually ran.
    """
    for raw in workflow_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _DIRECT_PYTEST_RE.search(line) and "hatch" not in line and "make " not in line:
            return True
    return False


def check_workflow(workflow_text: str, rel_path: str, pinned: dict[str, str]) -> list[str]:
    """Flag a workflow whose multi-version matrix is silently forced by a Hatch pin."""
    if not pinned:
        return []
    versions = matrix_python_versions(workflow_text)
    if len(versions) < 2:
        return []
    if not routes_tests_through_hatch(workflow_text):
        return []
    if runs_tests_directly_on_matrix(workflow_text):
        # Hatch may still run interpreter-agnostic linters, but the test suite
        # executes via a direct pytest invocation on the matrix interpreter, so
        # every cell is genuinely exercised.
        return []
    env_desc = ", ".join(f"{name}={ver}" for name, ver in sorted(pinned.items()))
    return [
        f"{rel_path}: python-version matrix {versions} runs tests through Hatch, "
        f"but [tool.hatch.envs] pins the interpreter ({env_desc}); every matrix "
        f"cell would execute on the pinned version. Run tests directly on the "
        f"matrix interpreter (python -m pytest) or add a sys.version_info guard "
        f"asserting it equals matrix.python-version."
    ]


def lint(root: Path | None = None) -> list[str]:
    """Run the hatch-pin/matrix conflict check; return human-readable violations."""
    root = root or _repo_root()
    pyproject = root / PYPROJECT
    if not pyproject.is_file():
        return [f"{PYPROJECT}: expected pyproject.toml is missing"]
    pinned = parse_pinned_hatch_envs(pyproject.read_text(encoding="utf-8"))
    errors: list[str] = []
    workflows = root / WORKFLOWS_DIR
    if not workflows.is_dir():
        return errors
    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        errors.extend(check_workflow(path.read_text(encoding="utf-8"), rel, pinned))
    return errors


def main() -> int:
    errors = lint()
    if errors:
        print("Hatch default-env pin vs. CI matrix conflict detected:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("Hatch/matrix hygiene: no multi-version matrix is silently forced by a Hatch env pin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
