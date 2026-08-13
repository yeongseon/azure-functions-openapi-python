#!/usr/bin/env python3
"""Drift-lint for the release-gate GitHub Actions workflows.

Part of the DX Toolkit tiered pre-publish verification gate
(umbrella: yeongseon/azure-functions-validation-python#306).

This guards two invariants in ``publish-pypi.yml`` and ``e2e-azure.yml`` so the
release gate cannot silently regress:

1. **Pinned-action consistency.** Every shared action is pinned to the canonical
   40-hex commit SHA *and* carries the canonical ``# vX`` annotation. The SHA is
   the real security boundary; the annotation is human-readable evidence for
   reviewers. Both are asserted.

2. **Publish-gate wiring.** The ``publish`` job's ``needs`` must always include
   ``build``, ``lib-tests`` and ``verify-azure-certification``, plus this repo's
   required runtime tier(s). The gate must never regress to publishing on
   ``build`` + ``lib-tests`` alone.

The ``publish.needs`` list legitimately varies across three repo families
(cookbook / runtime-gate / minimal); this repo's family is configured below, so
the lint tolerates that variation while still enforcing the universal invariant.

Vendored per-repo by design (there is no shared workflow repo). Keep the
``CANONICAL_ACTIONS`` table and the ``REPO_FAMILY`` / ``REQUIRED_RUNTIME_TIERS``
config in sync across the fleet when they change.

Stdlib-only on purpose: the lint must not itself depend on a package that can
drift. Exit code 0 = clean, 1 = drift detected.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

# --- Fleet-wide canonical pins (action -> (sha, annotation)) ------------------
CANONICAL_ACTIONS: dict[str, tuple[str, str]] = {
    # renovate: datasource=github-tags depName=actions/checkout versioning=github-tags
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    # renovate: datasource=github-tags depName=actions/setup-python versioning=github-tags
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
    # renovate: datasource=github-tags depName=azure/login versioning=github-tags
    "azure/login": ("f5d393ae46f8fde4be8b75f32e3fc50e654ad0ca", "v3.0.1"),
    # renovate: datasource=github-tags depName=actions/upload-artifact versioning=github-tags
    "actions/upload-artifact": ("ea165f8d65b6e75b540449e92b4886f43607fa02", "v4"),
    # renovate: datasource=github-tags depName=actions/download-artifact versioning=github-tags
    "actions/download-artifact": ("d3f86a106a0bac45b974a628896c90dbdf5c8093", "v4"),
}

# --- Per-repo configuration ---------------------------------------------------
# Family is set explicitly (never inferred from the repo name): silent
# misclassification would be worse than this one-line duplication.
#   "cookbook"     -> requires cookbook-smoke + cookbook-host-smoke
#   "runtime-gate" -> requires the package-specific <pkg>-runtime-gate job
#   "minimal"      -> verify-azure-certification is itself the runtime proof
REPO_FAMILY = "cookbook"
REQUIRED_RUNTIME_TIERS: tuple[str, ...] = ("cookbook-smoke", "cookbook-host-smoke")

# Universal invariant across every repo, regardless of family.
UNIVERSAL_REQUIRED_NEEDS = ("build", "lib-tests", "verify-azure-certification")

GATE_WORKFLOWS = (
    ".github/workflows/publish-pypi.yml",
    ".github/workflows/e2e-azure.yml",
)

_USES_RE = re.compile(
    r"""uses:\s*(?P<action>[\w.\-]+/[\w.\-]+)@(?P<ref>\S+?)      # owner/name@ref
        (?:\s+\#\s*(?P<annotation>\S+))?\s*$                     # optional # annotation
    """,
    re.VERBOSE,
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check_pins(text: str, rel_path: str) -> list[str]:
    """Assert every canonical action is pinned to its canonical SHA + annotation."""
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _USES_RE.search(line)
        if not m:
            continue
        action = m.group("action")
        if action not in CANONICAL_ACTIONS:
            continue
        ref = m.group("ref")
        annotation = m.group("annotation")
        want_sha, want_ann = CANONICAL_ACTIONS[action]
        if not _SHA_RE.match(ref):
            errors.append(
                f"{rel_path}:{lineno}: {action} is not pinned to a 40-hex SHA "
                f"(found '{ref}'); expected {want_sha} # {want_ann}"
            )
            continue
        if ref != want_sha:
            errors.append(
                f"{rel_path}:{lineno}: {action} pinned to {ref} # {annotation}; "
                f"expected canonical {want_sha} # {want_ann}"
            )
        elif annotation != want_ann:
            errors.append(
                f"{rel_path}:{lineno}: {action}@{ref} annotation is "
                f"'# {annotation}'; expected '# {want_ann}'"
            )
    return errors


def _extract_publish_needs(text: str) -> list[str] | None:
    """Return the ``publish`` job's ``needs`` list, or None if not found.

    Scans the block under the 2-space-indented ``publish:`` job header until the
    next job header, then reads the ``needs:`` value. Handles both flow style
    (``needs: [a, b]``) and block style (``needs:\\n    - a``).
    """
    lines = text.splitlines()
    in_publish = False
    for i, line in enumerate(lines):
        if re.match(r"^  publish:\s*$", line):
            in_publish = True
            continue
        if in_publish and re.match(r"^  \w[\w-]*:\s*$", line):
            break  # next job header -> left the publish block
        if not in_publish:
            continue
        flow = re.match(r"^\s+needs:\s*\[(?P<items>.*)\]\s*$", line)
        if flow:
            return [x.strip() for x in flow.group("items").split(",") if x.strip()]
        block = re.match(r"^\s+needs:\s*$", line)
        if block:
            items: list[str] = []
            for follow in lines[i + 1 :]:
                item = re.match(r"^\s+-\s*(?P<name>\S+)\s*$", follow)
                if not item:
                    break
                items.append(item.group("name"))
            return items
    return None


def check_publish_needs(text: str, rel_path: str) -> list[str]:
    """Assert the publish gate keeps the universal + family-required tiers."""
    errors: list[str] = []
    needs = _extract_publish_needs(text)
    if needs is None:
        return [f"{rel_path}: could not locate the 'publish' job's 'needs' list"]
    needs_set = set(needs)

    for required in UNIVERSAL_REQUIRED_NEEDS:
        if required not in needs_set:
            errors.append(
                f"{rel_path}: publish.needs is missing required gate '{required}' "
                f"(found {sorted(needs_set)})"
            )
    for tier in REQUIRED_RUNTIME_TIERS:
        if tier not in needs_set:
            errors.append(
                f"{rel_path}: publish.needs is missing '{tier}' runtime tier "
                f"required for the '{REPO_FAMILY}' family (found {sorted(needs_set)})"
            )
    if needs_set == {"build", "lib-tests"}:
        errors.append(
            f"{rel_path}: publish.needs regressed to build+lib-tests only; "
            f"a runtime verification tier is mandatory"
        )
    return errors


def lint(root: Path | None = None) -> list[str]:
    """Run all checks; return a flat list of human-readable violations."""
    root = root or _repo_root()
    errors: list[str] = []
    for rel in GATE_WORKFLOWS:
        path = root / rel
        if not path.exists():
            errors.append(f"{rel}: expected release-gate workflow is missing")
            continue
        text = path.read_text(encoding="utf-8")
        errors.extend(check_pins(text, rel))
        if rel.endswith("publish-pypi.yml"):
            errors.extend(check_publish_needs(text, rel))
    return errors


def main() -> int:
    errors = lint()
    if errors:
        print("Release-workflow drift detected:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("Release-gate workflows: pins and publish gate are canonical.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
