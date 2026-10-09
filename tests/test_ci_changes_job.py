from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-test.yml"
FULL_MATRIX = {
    "docs_only": "false",
    "docs_changed": "true",
    "full_required": "true",
}


def changes_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    script = workflow["jobs"]["changes"]["steps"][1]["run"]
    assert isinstance(script, str)
    return script


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True, text=True)


def run_changes(repo: Path, event: dict[str, str]) -> dict[str, str]:
    output = repo / "github-output"
    result = subprocess.run(
        ["bash", "-c", changes_script()],
        cwd=repo,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            **event,
            "GITHUB_OUTPUT": str(output),
        },
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in output.read_text().splitlines())


def initialized_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "--initial-branch=main", cwd=repo)
    git("config", "user.name", "CI Test", cwd=repo)
    git("config", "user.email", "ci@example.invalid", cwd=repo)
    tools = repo / "tools"
    tools.mkdir()
    shutil.copy2(REPO_ROOT / "tools" / "ci_classify_changes.sh", tools)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-m", "base", cwd=repo)
    return repo


def pull_event(sha: str) -> dict[str, str]:
    return {
        "EVENT_NAME": "pull_request",
        "BASE_SHA": sha,
        "HEAD_SHA": sha,
        "HEAD_REPOSITORY": "owner/repo",
        "REPOSITORY": "owner/repo",
        "PR_NUMBER": "1",
        "BEFORE_SHA": "",
        "SHA": "",
    }


def push_event(before_sha: str, sha: str) -> dict[str, str]:
    return {
        "EVENT_NAME": "push",
        "BASE_SHA": "",
        "HEAD_SHA": "",
        "HEAD_REPOSITORY": "",
        "REPOSITORY": "owner/repo",
        "PR_NUMBER": "",
        "BEFORE_SHA": before_sha,
        "SHA": sha,
    }


def test_fork_modified_classifier_cannot_influence_result(tmp_path: Path) -> None:
    repo = initialized_repo(tmp_path)
    base_sha = git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    origin = tmp_path / "origin.git"
    git("clone", "--bare", str(repo), str(origin), cwd=tmp_path)
    git("remote", "add", "origin", str(origin), cwd=repo)
    fork = tmp_path / "fork"
    git("clone", str(origin), str(fork), cwd=tmp_path)
    git("config", "user.name", "Fork Test", cwd=fork)
    git("config", "user.email", "fork@example.invalid", cwd=fork)
    (fork / "tools" / "ci_classify_changes.sh").write_text(
        "#!/usr/bin/env bash\n"
        "printf 'docs_only=true\\ndocs_changed=false\\nfull_required=false\\n'\n",
        encoding="utf-8",
    )
    (fork / "README.md").write_text("fork\n", encoding="utf-8")
    git("add", ".", cwd=fork)
    git("commit", "-m", "malicious classifier", cwd=fork)
    head_sha = git("rev-parse", "HEAD", cwd=fork).stdout.strip()
    git("push", "origin", "HEAD:refs/pull/1/head", cwd=fork)
    event = pull_event(head_sha)
    event.update(
        BASE_SHA=base_sha,
        HEAD_REPOSITORY="attacker/fork",
    )

    assert run_changes(repo, event) == FULL_MATRIX


@pytest.mark.parametrize("event_name", ["pull_request", "push"])
def test_failing_git_diff_fails_safe(event_name: str, tmp_path: Path) -> None:
    repo = initialized_repo(tmp_path)
    sha = git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None
    (bin_dir / "git").write_text(
        f'#!/usr/bin/env bash\nif [ "$1" = diff ]; then exit 1; fi\nexec "{real_git}" "$@"\n',
        encoding="utf-8",
    )
    (bin_dir / "git").chmod(0o755)
    event = pull_event(sha) if event_name == "pull_request" else push_event(sha, sha)
    event["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

    assert run_changes(repo, event) == FULL_MATRIX


def test_divergent_push_fails_safe(tmp_path: Path) -> None:
    repo = initialized_repo(tmp_path)
    base_sha = git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "README.md").write_text("first branch\n", encoding="utf-8")
    git("commit", "-am", "first branch", cwd=repo)
    before_sha = git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    git("checkout", "--detach", base_sha, cwd=repo)
    (repo / "README.md").write_text("divergent branch\n", encoding="utf-8")
    git("commit", "-am", "divergent branch", cwd=repo)
    sha = git("rev-parse", "HEAD", cwd=repo).stdout.strip()

    assert run_changes(repo, push_event(before_sha, sha)) == FULL_MATRIX
