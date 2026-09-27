from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def changed_python_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        # Exclude deletions rather than allow-listing statuses: an allow-list of
        # ACMR silently drops T (type changed), so swapping a Python-named
        # symlink for a real .py file would skip the format check entirely.
        ["git", "diff", "--name-only", "--diff-filter=d", "-z", f"{base}...{head}", "--"],
        check=True,
        capture_output=True,
    )
    return [
        path
        for raw_path in result.stdout.split(b"\0")
        if raw_path
        if (path := os.fsdecode(raw_path)).endswith(".py") and Path(path).is_file()
    ]


def main(base: str, head: str) -> int:
    if not base.strip() or not head.strip():
        print(
            "Missing PR base/head revision; refusing to report success.",
            file=sys.stderr,
        )
        return 2
    paths = changed_python_files(base, head)
    if not paths:
        print("No changed Python files to format-check.")
        return 0
    return subprocess.run(["ruff", "format", "--check", "--", *paths], check=False).returncode


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python tools/check_pr_format.py <base> <head>")
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
