from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.verification_environment import clean, doctor
from tools.verification_process import run

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    "install",
    "install-ci",
    "doctor",
    "format",
    "format-check",
    "check",
    "test",
    "integration",
    "verify",
    "e2e-azure",
    "report",
    "clean",
)


def test_process_propagates_exit_code(tmp_path: Path) -> None:
    assert run([sys.executable, "-c", "raise SystemExit(7)"], tmp_path / "log") == 7


def test_missing_process_is_non_successful(tmp_path: Path) -> None:
    assert run(["/nonexistent/openapi-command"], tmp_path / "log") == 127


def test_owned_child_is_reaped_on_interruption(tmp_path: Path) -> None:
    from tools.verification_process import child

    with (
        pytest.raises(KeyboardInterrupt),
        child([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path / "log") as process,
    ):
        raise KeyboardInterrupt
    assert process.poll() is not None


def test_verify_runs_every_required_lane_even_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.verification import verify

    commands: list[list[str]] = []

    def fake_run(command: list[str], log: Path, timeout: float = 600) -> int:
        from tools.verification_evidence import Summary, save

        commands.append(command)
        if command[1] in {"test", "integration"}:
            failed = command[1] == "integration"
            save(
                Path("test-results") / command[1],
                Summary(
                    1,
                    command[1],
                    tuple(command),
                    1,
                    int(not failed),
                    int(failed),
                    0,
                    "FAIL" if failed else "PASS",
                    int(failed),
                ),
            )
        return 1 if command == ["make", "integration"] else 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("tools.verification.run", fake_run)
    assert verify() == 1
    assert [command[1] for command in commands] == [
        "check",
        "test",
        "integration",
        "perf",
        "wheel-smoke",
        "docs",
    ]
    summary = json.loads((tmp_path / "test-results/verify/summary.json").read_text())
    assert summary["status"] == "FAIL"
    assert (tmp_path / "test-results/verify/environment.json").exists()


def test_integration_missing_tools_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.verification import execute

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("tools.verification_environment.shutil.which", lambda _: None)
    assert execute("integration", []) != 0
    data = json.loads((tmp_path / "test-results/integration/summary.json").read_text())
    assert data["status"] == "INCOMPLETE"


def test_host_readiness_fails_when_child_exits(tmp_path: Path) -> None:
    from tools.verification_host import wait_ready

    with subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"], text=True) as child:
        child.wait()
        with pytest.raises(RuntimeError, match="before readiness"):
            wait_ready(child, "http://127.0.0.1:1")


def test_live_lane_rejects_partially_skipped_results(tmp_path: Path) -> None:
    from tools.verification_evidence import collect

    (tmp_path / "junit.xml").write_text(
        "<testsuite><testcase/><testcase><skipped/></testcase></testsuite>"
    )
    assert collect(tmp_path, ["pytest"], 0).status == "INCOMPLETE"


def test_process_times_out_and_redacts_output(tmp_path: Path) -> None:
    code = run(
        [sys.executable, "-u", "-c", "import time; print('password=SECRET'); time.sleep(30)"],
        tmp_path / "log",
        1,
    )
    assert code == 124
    assert "SECRET" not in (tmp_path / "log").read_text()


def test_clean_preserves_venvs_sources_and_shared_emulator_data(tmp_path: Path) -> None:
    for directory in (".venv", "src", "shared-azurite", "test-results", "dist", "build"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "keep").touch()
    clean(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [".venv", "shared-azurite", "src"]


def test_clean_unlinks_artifact_symlink_without_following_it(tmp_path: Path) -> None:
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared/keep").touch()
    (tmp_path / "test-results").symlink_to(tmp_path / "shared", target_is_directory=True)
    clean(tmp_path)
    assert (tmp_path / "shared/keep").exists()


def test_doctor_fails_when_required_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.verification_environment.importlib.util.find_spec", lambda _: None)
    assert doctor() == 1


def test_azure_missing_prerequisites_saves_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.verification import execute

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("E2E_BASE_URL", raising=False)
    monkeypatch.delenv("E2E_EXPECTED_VERSION", raising=False)
    assert execute("azure-e2e", []) != 0
    data = json.loads((tmp_path / "test-results/azure-e2e/summary.json").read_text())
    assert data["status"] == "INCOMPLETE"
    assert data["selected"] == 0


@pytest.mark.parametrize("target", CONTRACT)
def test_make_contract_is_install_free_on_routine_runs(target: str) -> None:
    result = subprocess.run(["make", "-n", target], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "install --upgrade pip" not in result.stdout
    if target not in {"install", "install-ci"}:
        assert "pip install hatch" not in result.stdout


def test_check_runs_typechecking_once_without_test_execution() -> None:
    result = subprocess.run(
        ["make", "-n", "check-commands"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.count("-m mypy") == 1
    assert "-m pytest" not in result.stdout


def test_report_uses_saved_counts_and_job_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.verification_evidence import Summary, report, save

    directory = tmp_path / "test-results/test"
    summary = Summary(1, "test", ("not-a-real-command",), 3, 2, 0, 1, "PASS", 0)
    save(directory, summary)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "job-summary"))
    assert report(tmp_path / "test-results") == 0
    assert "passed=2" in (tmp_path / "job-summary").read_text()
