from __future__ import annotations

import os
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
        ["git", "diff", "--name-only", "--diff-filter=d", "-z", "base...head", "--"],
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


@pytest.mark.parametrize(
    ("base", "head"), [("", ""), ("", "head"), ("base", ""), ("   ", "head"), ("base", "   ")]
)
def test_blank_revision_fails_without_running_git(
    monkeypatch: pytest.MonkeyPatch, base: str, head: str
) -> None:
    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError(f"git/ruff must not run for a blank revision: {args}")

    monkeypatch.setattr(subprocess, "run", run)
    assert check_pr_format.main(base, head) != 0


def test_type_changed_python_path_is_detected_against_real_git(tmp_path: Path) -> None:
    """A mocked diff cannot catch a filter regression, so drive real Git here.

    Replacing a Python-named symlink with a regular file is reported by Git as
    ``T`` and nothing else. An ``ACMR`` allow-list returns an empty list for
    that change, so this test fails if the filter is ever narrowed again.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")

    (repo / "target.txt").write_text("x\n")
    (repo / "mod.py").symlink_to("target.txt")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    (repo / "mod.py").unlink()
    (repo / "mod.py").write_text("def f( a ):  return a\n")
    git("add", "-A")
    git("commit", "-qm", "swap")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    status = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-status", f"{base}...{head}", "--"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status.startswith("T\t"), f"expected a type change, got {status!r}"

    monkey_cwd = Path.cwd()
    try:
        os.chdir(repo)
        assert check_pr_format.changed_python_files(base, head) == ["mod.py"]
    finally:
        os.chdir(monkey_cwd)
