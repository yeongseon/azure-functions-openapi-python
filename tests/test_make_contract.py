"""Contract of the Makefile targets that set up and check a checkout (#811).

``make -n`` prints recipes without running them. The behavior cases run the real recipes in a
scratch directory whose ``PATH`` holds only stub programs that log their arguments, so nothing is
installed, no network is used and no real tool can run.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tomllib

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("make") is None,
    reason="runs the real Makefile recipes through /bin/sh",
)

ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make") or "make"
_PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
HATCH_SCRIPTS: dict[str, str] = _PYPROJECT["tool"]["hatch"]["envs"]["default"]["scripts"]


def script_runs(commands: str, name: str) -> int:
    """Count the runs of Hatch script ``name``, following scripts that run other scripts.

    Hatch's ``lint`` script runs ``style`` and ``typecheck``, so a second type check can hide
    inside a target that ``make -n`` shows as one ``hatch run lint``.
    """
    called = re.findall(r"\bhatch run ([\w-]+)", commands)
    return sum((s == name) + script_runs(HATCH_SCRIPTS.get(s, ""), name) for s in called)


def run_make(
    cwd: Path, path: str, *arguments: str, **environment: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [MAKE, "--no-print-directory", *arguments],
        cwd=cwd,
        env={"PATH": path, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def plan(*arguments: str) -> str:
    """Return the commands ``make -n`` prints for this repository's own Makefile."""
    result = run_make(ROOT, os.environ["PATH"], "-n", *arguments)
    assert result.returncode == 0, result.stderr
    return result.stdout


def installs_hatch(call: str) -> bool:
    words = call.split()
    return words[:2] == ["pip", "install"] and words[-1] == "hatch" and "--upgrade" not in words


@dataclass(frozen=True)
class Sandbox:
    """A scratch copy of the Makefile, run with ``PATH`` limited to stubs that log their calls."""

    root: Path

    @property
    def venv(self) -> Path:
        return self.root / "venv"

    @property
    def calls(self) -> list[str]:
        log = self.root / "calls.log"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def tool(self, name: str, directory: Path | None = None, body: str = "") -> Path:
        """Create a stub that logs ``<name> <arguments>`` and then runs ``body``."""
        path = (directory or self.root / "bin") / name
        path.parent.mkdir(parents=True, exist_ok=True)
        log = shlex.quote(str(self.root / "calls.log"))
        line = f'printf "%s\\n" "{name} $*" >> {log}\n'  # printf: `echo` would expand backslashes
        path.write_text(f"#!/bin/sh\n{line}{body}exit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def pip(self, directory: Path) -> None:
        """Add a ``pip`` whose ``install ... hatch`` puts a logging ``hatch`` beside it."""
        template = self.tool("hatch", self.root / "templates")  # `cp` keeps its executable bit
        install = f'for last; do :; done\n[ "$last" = hatch ] && cp {template} "${{0%/*}}/hatch"\n'
        self.tool("pip", directory, install)

    def interpreter(self, name: str, version: tuple[int, int] = (3, 12)) -> Path:
        """Add a Python stub that reports ``version`` to the probes the Makefile runs."""
        major, minor = version
        probe = f"import sys; sys.version_info = ({major}, {minor}, 0); exec(sys.argv[1])"
        body = (
            f'[ "$1" = --version ] && echo "Python {major}.{minor}.0"\n'
            f'[ "$1" = -c ] && exec {shlex.quote(sys.executable)} -c "{probe}" "$2"\n'
        )
        return self.tool(name, body=body)

    def doctor_tools(self, missing: Iterable[str] = ()) -> None:
        """Provide every tool ``make doctor`` looks for, except the ``missing`` ones."""
        if "python" not in missing:
            self.interpreter("python3.12")
        for name in {"hatch", "func", "azurite"} - set(missing):
            self.tool(name, self.venv / "bin" if name == "hatch" else None)

    def make(self, *arguments: str, **environment: str) -> subprocess.CompletedProcess[str]:
        arguments = (f"VENV_DIR={self.venv}", *arguments)
        return run_make(self.root, str(self.root / "bin"), *arguments, **environment)


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "cp").symlink_to(shutil.which("cp") or "cp")  # the one real program
    return Sandbox(tmp_path)


@pytest.mark.parametrize(("target", "tests"), [("check", 0), ("check-all", 1)])
def test_each_check_runs_once(target: str, tests: int) -> None:
    runs = [script_runs(plan(target), name) for name in ("style", "typecheck", "test")]

    assert runs == [1, 1, tests]


def test_check_all_keeps_every_gate_it_had() -> None:
    gates = ("lint_release_workflows", "lint_workflow_pins", "lint_hatch_matrix", "bandit")

    assert [plan("check-all").count(gate) for gate in gates] == [1, 1, 1, 1]


def test_makefile_never_upgrades_pip() -> None:
    # Also covers `docs`: its recipe line contains $(MAKE), so `make -n` would run it for real.
    assert "--upgrade" not in (ROOT / "Makefile").read_text(encoding="utf-8")


def test_bootstrap_installs_hatch_once_and_only_while_it_is_missing(sandbox: Sandbox) -> None:
    sandbox.pip(sandbox.venv / "bin")

    for _ in range(2):
        assert sandbox.make("bootstrap").returncode == 0

    (call,) = sandbox.calls  # the second run finds the Hatch the first run installed
    assert installs_hatch(call)


@pytest.mark.parametrize("kind", ["directory", "non-executable file"])
def test_only_an_executable_regular_file_counts_as_hatch(sandbox: Sandbox, kind: str) -> None:
    sandbox.doctor_tools(missing={"hatch"})
    sandbox.pip(sandbox.venv / "bin")
    hatch = sandbox.venv / "bin" / "hatch"
    if kind == "directory":
        hatch.mkdir()
    else:
        hatch.write_text("#!/bin/sh\n", encoding="utf-8")  # created without the executable bit

    doctor = sandbox.make("doctor")
    bootstrap = sandbox.make("bootstrap")

    assert doctor.returncode != 0
    assert f"MISSING  {hatch} (required" in doctor.stdout
    assert bootstrap.returncode == 0, bootstrap.stderr
    (call,) = (call for call in sandbox.calls if call.startswith("pip "))
    assert installs_hatch(call)


def test_the_selected_interpreter_creates_the_virtual_environment() -> None:
    assert "python3 -m venv" in plan("bootstrap")
    assert "sentinel -m venv" in plan("bootstrap", "PYTHON=sentinel")


@pytest.mark.parametrize(("version", "installs"), [((3, 10), False), ((3, 11), True)])
def test_install_ci_installs_into_the_selected_interpreter_from_python_311(
    sandbox: Sandbox, version: tuple[int, int], installs: bool
) -> None:
    python = sandbox.interpreter("sentinel", version)  # no Hatch and no pip on PATH

    result = sandbox.make("install-ci", f"PYTHON={python}")

    assert any(call.startswith("sentinel -c ") for call in sandbox.calls)  # the version guard ran
    assert (result.returncode == 0) is installs
    assert ("sentinel -m pip install -e .[dev]" in sandbox.calls) is installs


@pytest.mark.parametrize(
    ("environment", "build"),
    [({}, "hatch run mkdocs build --strict"), ({"CI": "1"}, "mkdocs build --strict")],
    ids=["local", "ci"],
)
def test_docs_builds_strictly(sandbox: Sandbox, environment: dict[str, str], build: str) -> None:
    for name in ("pip", "mkdocs"):
        sandbox.tool(name)
    sandbox.tool("hatch", sandbox.venv / "bin")

    result = sandbox.make("docs", **environment)

    assert result.returncode == 0, result.stderr
    assert sandbox.calls[-1] == build
    installs = [call for call in sandbox.calls if call.startswith("pip install")]
    assert all(call.endswith("-e .[docs]") for call in installs)  # the CI gate's extra, not pins
    assert bool(installs) is bool(environment)


@pytest.mark.parametrize("environment", [{}, {"CI": "1"}], ids=["local", "ci"])
def test_docs_fails_when_the_build_fails(sandbox: Sandbox, environment: dict[str, str]) -> None:
    sandbox.tool("pip")
    sandbox.tool("mkdocs", body="exit 1\n")
    sandbox.tool("hatch", sandbox.venv / "bin", "exit 1\n")

    assert sandbox.make("docs", **environment).returncode != 0


def test_docs_shows_a_failed_install_and_does_not_build_after_it(sandbox: Sandbox) -> None:
    sandbox.tool("pip", body='echo "ERROR: no matching distribution" >&2\nexit 1\n')
    sandbox.tool("mkdocs")

    result = sandbox.make("docs", CI="1")

    assert result.returncode != 0
    assert "ERROR: no matching distribution" in result.stderr
    assert "mkdocs build --strict" not in sandbox.calls


@pytest.mark.parametrize("absent", [(), ("func", "azurite")], ids=["all tools", "optional absent"])
def test_doctor_passes_when_the_required_tools_exist(
    sandbox: Sandbox, absent: tuple[str, ...]
) -> None:
    sandbox.doctor_tools(missing=absent)

    result = sandbox.make("doctor")

    assert result.returncode == 0, result.stdout
    assert "MISSING" not in result.stdout
    assert all(f"missing  {tool} (optional" in result.stdout for tool in absent)


@pytest.mark.parametrize("tool", ["python", "hatch"])
def test_doctor_fails_naming_the_one_required_tool_that_is_missing(
    sandbox: Sandbox, tool: str
) -> None:
    sandbox.doctor_tools(missing={tool})

    result = sandbox.make("doctor")

    assert result.returncode != 0
    assert result.stdout.count("MISSING  ") == 1
    assert ("python >= 3.11" if tool == "python" else str(sandbox.venv)) in result.stdout


def test_doctor_rejects_a_python_older_than_311(sandbox: Sandbox) -> None:
    sandbox.doctor_tools(missing={"python"})
    sandbox.interpreter("python3", (3, 10))

    result = sandbox.make("doctor")

    assert result.returncode != 0
    assert "MISSING  python >= 3.11" in result.stdout


def test_doctor_neither_installs_nor_writes(sandbox: Sandbox) -> None:
    sandbox.pip(sandbox.venv / "bin")  # a stub pip and no Hatch: bootstrap would install here
    before = sorted(sandbox.root.rglob("*"))

    result = sandbox.make("doctor")

    assert result.returncode != 0
    assert sandbox.calls == []
    assert sorted(sandbox.root.rglob("*")) == before
