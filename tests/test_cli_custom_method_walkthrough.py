"""Keep the docs/cli.md custom-method strict-validation walkthrough working.

The two example projects are extracted from the guide itself and run through
the installed console script, so a stale snippet or changed gate fails here.
Assertions use exit codes, output-file presence and stable message fragments,
never tracebacks.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

_DOC = Path(__file__).resolve().parent.parent / "docs" / "cli.md"
_HEADING = "## Walkthrough: strict validation of custom HTTP methods"
_CONSOLE_SCRIPT = Path(sys.executable).parent / "azure-functions-openapi"
_GATES = ["--strict", "--fail-on-warnings"]


def _walkthrough() -> str:
    return _DOC.read_text(encoding="utf-8").split(_HEADING, 1)[1].split("\n## ", 1)[0]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    blocks = re.findall(r"```python\n(.*?)\n```", _walkthrough(), re.S)
    assert len(blocks) == 2
    for block in blocks:
        name = block.splitlines()[0].removeprefix("# ").strip()
        (tmp_path / name).write_text(block + "\n", encoding="utf-8")
    assert {p.name for p in tmp_path.glob("*.py")} == {"ok_methods.py", "bad_methods.py"}
    return tmp_path


def _generate(
    project: Path, module: str, version: str, *flags: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    output = project / f"{module}-{version}.json"
    result = subprocess.run(
        [
            str(_CONSOLE_SCRIPT),
            "generate",
            "--app",
            module,
            "--openapi-version",
            version,
            *flags,
            "--output",
            str(output),
        ],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, output


def test_guide_lists_the_commands_it_documents() -> None:
    text = _walkthrough()
    assert "generate --app ok_methods --openapi-version 3.2" in text
    assert "generate --app bad_methods --openapi-version 3.2" in text
    assert "--strict --fail-on-warnings" in text
    assert "does not add\n    authentication" in text
    usage = (_DOC.parent / "usage.md").read_text(encoding="utf-8")
    assert "cli.md#walkthrough-strict-validation-of-custom-http-methods" in usage


def test_valid_custom_method_passes_both_gates(project: Path) -> None:
    result, output = _generate(project, "ok_methods", "3.2", *_GATES)

    assert result.returncode == 0, result.stderr
    spec = json.loads(output.read_text(encoding="utf-8"))
    assert "PROPFIND" in spec["paths"]["/api/files/{id}"]["additionalOperations"]


def test_invalid_path_parameter_is_rejected_and_not_written(project: Path) -> None:
    result, output = _generate(project, "bad_methods", "3.2", *_GATES)

    assert result.returncode == 1
    assert not output.exists()
    assert "Strict mode: generated spec has validation errors:" in result.stderr
    assert "Path parameter 'file' in PROPFIND /api/files/{id}" in result.stderr


def test_without_gates_the_invalid_document_is_still_written(project: Path) -> None:
    result, output = _generate(project, "bad_methods", "3.2")

    assert result.returncode == 0
    assert output.exists()
    assert "Path parameter 'file'" in result.stderr


@pytest.mark.parametrize(("flag", "code"), [("--strict", 1), ("--fail-on-warnings", 2)])
def test_each_gate_alone_blocks_output(project: Path, flag: str, code: int) -> None:
    result, output = _generate(project, "bad_methods", "3.2", flag)

    assert result.returncode == code
    assert not output.exists()


def test_custom_method_requires_openapi_3_2(project: Path) -> None:
    result, output = _generate(project, "ok_methods", "3.1", *_GATES)

    assert result.returncode == 1
    assert not output.exists()
    assert "requires OpenAPI 3.2" in result.stderr
