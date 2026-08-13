#!/usr/bin/env python3
"""Fleet-wide pin-hygiene lint for GitHub Actions workflows.

Part of the DX Toolkit CI hardening work
(follow-up to yeongseon/azure-functions-validation-python#319, umbrella #308).

Unlike ``tools/lint_release_workflows.py`` -- which enforces a single *canonical*
SHA per action for the two release-gate workflows -- this lint applies a lighter
**pin-hygiene** rule to *every* workflow file. It does not care *which* version an
action is pinned to (that is Renovate's domain, #320); it only insists the pin is
a real, immutable commit SHA (or an explicitly justified exception).

Rule -- every external ``uses:`` reference MUST be one of:

1. Pinned to a full 40-hex commit SHA **and** carry a trailing ``#`` version
   comment (e.g. ``uses: actions/checkout@<sha> # v7.0.1``); or
2. A local composite action (``uses: ./...``); or
3. An explicitly documented exception flagged with an inline ``# pin-exempt:``
   comment at the call site, stating why the SHA pin is skipped (e.g. the PyPA
   ``gh-action-pypi-publish`` trusted-publisher action, or a distributed
   copy-paste template file).

Enforcing pin *hygiene* rather than a canonical SHA keeps non-gate workflows free
to be bumped by Renovate/Dependabot without fighting a frozen central version.

Stdlib-only on purpose: the lint must not itself depend on a package that can
drift. Exit code 0 = clean, 1 = drift detected.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

WORKFLOWS_DIR = ".github/workflows"

# owner/name@ref, with an optional trailing "# comment".
_USES_RE = re.compile(
    r"""uses:\s*(?P<ref>\S+)          # the action reference (owner/name@x or ./local)
        (?:\s+\#\s*(?P<comment>.*\S))?  # optional trailing # comment
        \s*$
    """,
    re.VERBOSE,
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Marker that justifies skipping a SHA pin. Must carry a reason after the colon.
_EXEMPT_RE = re.compile(r"pin-exempt:\s*\S")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _split_ref(ref: str) -> tuple[str, str | None]:
    """Split ``owner/name@gitref`` into (action, gitref). Local actions have no @."""
    if "@" not in ref:
        return ref, None
    action, _, gitref = ref.partition("@")
    return action, gitref


def check_pin_hygiene(text: str, rel_path: str) -> list[str]:
    """Assert every external ``uses:`` is SHA-pinned, local, or documented-exempt."""
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _USES_RE.search(line)
        if not m:
            continue
        ref = m.group("ref")
        comment = m.group("comment")

        # (2) Local composite actions are always allowed.
        if ref.startswith("./") or ref.startswith("."):
            continue

        action, gitref = _split_ref(ref)

        # (3) Explicitly documented exception, e.g. the PyPA publish action.
        if comment and _EXEMPT_RE.search(comment):
            continue

        if gitref is None:
            errors.append(
                f"{rel_path}:{lineno}: '{ref}' is not pinned "
                f"(no @ref); pin to a 40-hex SHA or mark '# pin-exempt: <reason>'"
            )
            continue

        # (1) Full commit SHA + trailing version comment.
        if _SHA_RE.match(gitref):
            if not comment:
                errors.append(
                    f"{rel_path}:{lineno}: {action}@{gitref} is SHA-pinned but "
                    f"missing the trailing '# <version>' comment"
                )
            continue

        errors.append(
            f"{rel_path}:{lineno}: {action} is pinned to '{gitref}', not a 40-hex "
            f"commit SHA; pin to a SHA (with a version comment) or mark "
            f"'# pin-exempt: <reason>'"
        )
    return errors


def lint(root: Path | None = None) -> list[str]:
    """Run pin-hygiene over every workflow file; return human-readable violations."""
    root = root or _repo_root()
    errors: list[str] = []
    workflows = root / WORKFLOWS_DIR
    if not workflows.is_dir():
        return [f"{WORKFLOWS_DIR}: expected workflows directory is missing"]
    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        errors.extend(check_pin_hygiene(path.read_text(encoding="utf-8"), rel))
    return errors


def main() -> int:
    errors = lint()
    if errors:
        print("Workflow pin-hygiene drift detected:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("Workflow pin-hygiene: every action is SHA-pinned, local, or documented-exempt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
