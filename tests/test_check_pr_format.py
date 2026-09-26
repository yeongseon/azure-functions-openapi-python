from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tools import check_pr_format


def test_checks_changed_python_files_with_spaces_and_renames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "new name.py").touch()
    (tmp_path / "renamed.py").touch()
    (tmp_path / "notes.md").touch()
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        if args[0] == "git":
            assert kwargs == {"check": True, "capture_output": True}
            return subprocess.CompletedProcess(args, 0, b"new name.py\0renamed.py\0notes.md\0")
        assert kwargs == {"check": False}
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert check_pr_format.main("base", "head") == 0
    assert calls == [
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "-z", "base...head", "--"],
        ["ruff", "format", "--check", "--", "new name.py", "renamed.py"],
    ]


def test_formatter_failure_is_propagated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "unformatted.py").touch()

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if args[0] == "git":
            return subprocess.CompletedProcess(args, 0, b"unformatted.py\0")
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(subprocess, "run", run)
    assert check_pr_format.main("base", "head") == 1


def test_non_python_or_deleted_files_skip_formatter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.md").touch()
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, b"notes.md\0removed.py\0")

    monkeypatch.setattr(subprocess, "run", run)
    assert check_pr_format.main("base", "head") == 0
    assert len(calls) == 1


def test_git_diff_failure_does_not_skip_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", run)
    try:
        check_pr_format.main("missing-base", "head")
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError("An unavailable PR base must fail the gate")
