#!/usr/bin/env python3
"""Lint Mermaid diagrams embedded in Markdown for label-hygiene issues.

Some Mermaid renderers mishandle literal ``\\n`` newline escapes inside node
labels (e.g. ``NODE["a\\nb"]``), which silently breaks rendering. This linter
scans Markdown files for ```mermaid``` fenced blocks and flags any literal
``\\n`` sequence, steering authors toward ``<br/>`` or short labels instead.

Exit code 0 when clean, 1 when any violation is found.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Files/globs to scan, relative to the repository root.
TARGET_GLOBS = ("README*.md", "DESIGN.md", "docs/**/*.md")

FENCE_START = "```mermaid"
FENCE_END = "```"
BAD_TOKEN = "\\n"


def _iter_targets(root: Path) -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in TARGET_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                files.append(path)
    return files


def _lint_file(path: Path) -> list[str]:
    violations: list[str] = []
    in_block = False
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not in_block:
            if stripped.startswith(FENCE_START):
                in_block = True
            continue
        if stripped == FENCE_END:
            in_block = False
            continue
        if BAD_TOKEN in raw:
            violations.append(
                f"{path}:{lineno}: literal '\\n' in Mermaid label; use '<br/>' or a shorter label"
            )
    return violations


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    all_violations: list[str] = []
    for path in _iter_targets(root):
        all_violations.extend(_lint_file(path))

    if all_violations:
        print("Mermaid label lint failed:")
        for violation in all_violations:
            print(f"  {violation}")
        return 1

    print("Mermaid label lint passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
