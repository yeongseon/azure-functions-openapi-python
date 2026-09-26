from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def changed_python_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "-z", f"{base}...{head}", "--"],
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
    paths = changed_python_files(base, head)
    if not paths:
        print("No changed Python files to format-check.")
        return 0
    return subprocess.run(["ruff", "format", "--check", "--", *paths], check=False).returncode


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python tools/check_pr_format.py <base> <head>")
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
