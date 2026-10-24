"""Contract of the Makefile targets that set up and check a checkout (#811).

``make -n`` prints recipes without running them, so the expansion cases need no network, Hatch or
virtual environment. The behavior cases run the real recipes in a scratch directory whose ``PATH``
holds only stub programs that log their arguments: nothing is installed, no network is used and no
real tool can run.
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


def plan(*arguments: str) -> str:
    """Return the commands ``make -n`` prints for this repository's own Makefile."""
    result = subprocess.run(
        [MAKE, "--no-print-directory", "-n", *arguments],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
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
        """Add a Python stub that reports ``version`` and whose ``-m venv DIR`` holds a stub pip."""
        self.pip(self.root / "templates")
        pip = self.root / "templates" / "pip"
        probe = f"import sys; sys.version_info = ({version[0]}, {version[1]}, 0); exec(sys.argv[1])"
        body = (
            f'[ "$1" = --version ] && echo "Python {version[0]}.{version[1]}.0"\n'
            f'[ "$1" = -c ] && exec {shlex.quote(sys.executable)} -c "{probe}" "$2"\n'
            f'[ "$1 $2" = "-m venv" ] && mkdir -p "$3/bin" && cp {pip} "$3/bin/pip"\n'
        )
        return self.tool(name, body=body)

    def doctor_tools(self, missing: Iterable[str] = ()) -> None:
        """Provide every tool ``make doctor`` looks for, except the ``missing`` ones."""
        if "python" not in missing:
            self.interpreter("python3.12")
        for name in {"hatch", "func", "azurite"} - set(missing):
            self.tool(name, self.venv / "bin" if name == "hatch" else None)

    def make(self, *arguments: str, **environment: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [MAKE, "--no-print-directory", f"VENV_DIR={self.venv}", *arguments],
            cwd=self.root,
            env={"PATH": str(self.root / "bin"), **environment},
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / "bin").mkdir()
    for program in ("cp", "mkdir"):  # the only real programs the stubs run
        (tmp_path / "bin" / program).symlink_to(shutil.which(program) or program)
    return Sandbox(tmp_path)


@pytest.mark.parametrize(
    ("target", "style", "typecheck", "test"), [("check", 1, 1, 0), ("check-all", 1, 1, 1)]
)
def test_each_check_runs_once(target: str, style: int, typecheck: int, test: int) -> None:
    # Given the commands the target would run
    commands = plan(target)

    # Then style, the type check and the tests run the expected number of times
    runs = [script_runs(commands, name) for name in ("style", "typecheck", "test")]
    assert runs == [style, typecheck, test]


def test_check_all_keeps_every_gate_it_had() -> None:
    # Given the commands `make check-all` would run
    commands = plan("check-all")

    # Then each workflow lint and the Bandit evidence run once
    gates = ("lint_release_workflows", "lint_workflow_pins", "lint_hatch_matrix", "bandit")
    assert [commands.count(gate) for gate in gates] == [1, 1, 1, 1]


def test_makefile_never_upgrades_pip() -> None:
    # Also covers `docs`: its recipe line contains $(MAKE), so `make -n` would run it for real.
    assert "--upgrade" not in (ROOT / "Makefile").read_text(encoding="utf-8")


def test_bootstrap_installs_hatch_once_and_only_while_it_is_missing(sandbox: Sandbox) -> None:
    # Given a virtual environment that has pip but no Hatch
    sandbox.pip(sandbox.venv / "bin")

    # When bootstrap runs twice
    for _ in range(2):
        assert sandbox.make("bootstrap").returncode == 0

    # Then one pip call across both runs installed Hatch, without --upgrade
    (call,) = sandbox.calls
    assert installs_hatch(call)


def test_bootstrap_leaves_an_installed_hatch_alone(sandbox: Sandbox) -> None:
    # Given a virtual environment that already holds Hatch
    sandbox.pip(sandbox.venv / "bin")
    sandbox.tool("hatch", sandbox.venv / "bin")

    # When bootstrap runs
    result = sandbox.make("bootstrap")

    # Then pip is never called
    assert result.returncode == 0, result.stderr
    assert sandbox.calls == []


@pytest.mark.parametrize("kind", ["directory", "non-executable file"])
def test_only_an_executable_regular_file_counts_as_hatch(sandbox: Sandbox, kind: str) -> None:
    # Given something at the Hatch path that `test -x` or `command -v` alone would accept
    sandbox.doctor_tools(missing={"hatch"})
    sandbox.pip(sandbox.venv / "bin")
    hatch = sandbox.venv / "bin" / "hatch"
    if kind == "directory":
        hatch.mkdir()
    else:
        hatch.write_text("#!/bin/sh\n", encoding="utf-8")  # created without the executable bit

    # When doctor and bootstrap run
    doctor = sandbox.make("doctor")
    bootstrap = sandbox.make("bootstrap")

    # Then doctor reports Hatch missing and bootstrap installs it
    assert doctor.returncode != 0
    assert f"MISSING  {hatch} (required" in doctor.stdout
    assert bootstrap.returncode == 0, bootstrap.stderr
    (call,) = (call for call in sandbox.calls if call.startswith("pip "))
    assert installs_hatch(call)


def test_a_fresh_checkout_gets_one_venv_from_the_selected_interpreter(sandbox: Sandbox) -> None:
    # Given no virtual environment and a selected interpreter
    python = sandbox.interpreter("sentinel")

    # When bootstrap runs
    result = sandbox.make("bootstrap", f"PYTHON={python}")

    # Then that interpreter creates the environment and Hatch is the only thing installed
    assert result.returncode == 0, result.stderr
    venv_call, pip_call = sandbox.calls
    assert venv_call == f"sentinel -m venv {sandbox.venv}"
    assert installs_hatch(pip_call)


def test_install_ci_installs_into_the_selected_interpreter_and_not_through_hatch() -> None:
    # Given the commands `make install-ci PYTHON=python3.12` would run
    commands = plan("install-ci", "PYTHON=python3.12")

    # Then the matrix interpreter receives the install, so a cell keeps its own Python
    assert 'python3.12 -m pip install -e ".[dev]"' in commands
    assert "hatch" not in commands


@pytest.mark.parametrize(("version", "installs"), [((3, 10), False), ((3, 11), True)])
def test_install_ci_needs_python_311(
    sandbox: Sandbox, version: tuple[int, int], installs: bool
) -> None:
    # Given an interpreter of the given version
    python = sandbox.interpreter("sentinel", version)

    # When install-ci runs
    result = sandbox.make("install-ci", f"PYTHON={python}")

    # Then the version guard ran, and pip runs only for Python 3.11 or newer
    assert any(call.startswith("sentinel -c ") for call in sandbox.calls)
    assert (result.returncode == 0) is installs
    assert ("sentinel -m pip install -e .[dev]" in sandbox.calls) is installs


@pytest.mark.parametrize(
    ("environment", "build"),
    [({}, "hatch run mkdocs build --strict"), ({"CI": "1"}, "mkdocs build --strict")],
    ids=["local", "ci"],
)
def test_docs_builds_strictly(sandbox: Sandbox, environment: dict[str, str], build: str) -> None:
    # Given Hatch, pip and MkDocs stubs
    sandbox.tool("hatch", sandbox.venv / "bin")
    sandbox.tool("pip")
    sandbox.tool("mkdocs")

    # When docs runs locally and under CI
    result = sandbox.make("docs", **environment)

    # Then MkDocs ran in strict mode
    assert result.returncode == 0, result.stderr
    assert build in sandbox.calls


def test_docs_under_ci_installs_the_docs_extra_the_ci_gate_installs(sandbox: Sandbox) -> None:
    # Given pip and MkDocs stubs
    sandbox.tool("pip")
    sandbox.tool("mkdocs")

    # When docs runs under CI
    result = sandbox.make("docs", CI="1")

    # Then the dependencies come from pyproject.toml, not from pins kept in the Makefile
    assert result.returncode == 0, result.stderr
    assert any(
        call.startswith("pip install") and call.endswith("-e .[docs]") for call in sandbox.calls
    )


@pytest.mark.parametrize("environment", [{}, {"CI": "1"}], ids=["local", "ci"])
def test_docs_fails_when_the_build_fails(sandbox: Sandbox, environment: dict[str, str]) -> None:
    # Given a MkDocs build that fails
    sandbox.tool("hatch", sandbox.venv / "bin", "exit 1\n")
    sandbox.tool("pip")
    sandbox.tool("mkdocs", body="exit 1\n")

    # When docs runs
    result = sandbox.make("docs", **environment)

    # Then make fails
    assert result.returncode != 0


def test_docs_shows_a_failed_install_and_does_not_build_after_it(sandbox: Sandbox) -> None:
    # Given a pip that fails with a message
    sandbox.tool("pip", body='echo "ERROR: no matching distribution" >&2\nexit 1\n')
    sandbox.tool("mkdocs")

    # When docs runs under CI
    result = sandbox.make("docs", CI="1")

    # Then the error is visible and MkDocs never ran
    assert result.returncode != 0
    assert "ERROR: no matching distribution" in result.stderr
    assert "mkdocs build --strict" not in sandbox.calls


@pytest.mark.parametrize("absent", [(), ("func", "azurite")], ids=["all tools", "optional absent"])
def test_doctor_passes_when_every_required_tool_exists(
    sandbox: Sandbox, absent: tuple[str, ...]
) -> None:
    # Given Python 3.11 or newer and Hatch, with or without the Functions host tools
    sandbox.doctor_tools(missing=absent)

    # When doctor runs
    result = sandbox.make("doctor")

    # Then it passes and lists each absent optional tool
    assert result.returncode == 0, result.stdout
    assert "MISSING" not in result.stdout
    for tool in absent:
        assert f"missing  {tool} (optional" in result.stdout


@pytest.mark.parametrize(
    ("tool", "line"), [("python", "MISSING  python >= 3.11 (required)"), ("hatch", "MISSING  ")]
)
def test_doctor_fails_when_a_required_tool_is_missing(
    sandbox: Sandbox, tool: str, line: str
) -> None:
    # Given every tool except one required one
    sandbox.doctor_tools(missing={tool})

    # When doctor runs
    result = sandbox.make("doctor")

    # Then it fails and names only that tool
    assert result.returncode != 0
    assert line in result.stdout
    assert result.stdout.count("MISSING  ") == 1


def test_doctor_rejects_a_python_older_than_311(sandbox: Sandbox) -> None:
    # Given Hatch and a Python 3.10 as the only interpreter
    sandbox.doctor_tools(missing={"python"})
    sandbox.interpreter("python3", (3, 10))

    # When doctor runs
    result = sandbox.make("doctor")

    # Then Python counts as missing
    assert result.returncode != 0
    assert "MISSING  python >= 3.11 (required)" in result.stdout


def test_doctor_neither_installs_nor_writes(sandbox: Sandbox) -> None:
    # Given a stub pip and no Hatch, where bootstrap would install
    sandbox.pip(sandbox.venv / "bin")
    before = sorted(sandbox.root.rglob("*"))

    # When doctor runs
    result = sandbox.make("doctor")

    # Then it fails, calls nothing and leaves the directory as it was
    assert result.returncode != 0
    assert sandbox.calls == []
    assert sorted(sandbox.root.rglob("*")) == before
