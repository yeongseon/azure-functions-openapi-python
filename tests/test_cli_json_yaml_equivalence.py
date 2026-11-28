"""Keep the docs/cli.md JSON-versus-YAML equivalence recipe working.

The commands and the comparison script are extracted from the guide itself and
run against the repository's ``report_jobs`` example through the installed
console script. Semantics are compared after parsing, never as text.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_DOC = _ROOT / "docs" / "cli.md"
_HEADING = "## Check that JSON and YAML outputs are equivalent"
_CONSOLE_SCRIPT = Path(sys.executable).parent / "azure-functions-openapi"


def _section() -> str:
    return _DOC.read_text(encoding="utf-8").split(_HEADING, 1)[1].split("\n## ", 1)[0]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    source = _ROOT / "examples" / "report_jobs" / "function_app.py"
    (tmp_path / "function_app.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    script = re.search(r"```python\n(# compare_specs\.py\n.*?)\n```", _section(), re.S)
    assert script is not None
    (tmp_path / "compare_specs.py").write_text(script.group(1) + "\n", encoding="utf-8")
    return tmp_path


def _documented_generate_commands() -> list[list[str]]:
    block = re.search(r"```bash\n(.*?)\n```", _section(), re.S)
    assert block is not None
    commands = [shlex.split(line) for line in block.group(1).splitlines()]
    return [c for c in commands if c[0] == "azure-functions-openapi"]


def _run_documented_generation(project: Path) -> None:
    commands = _documented_generate_commands()
    assert [c[c.index("--format") + 1] for c in commands] == ["json", "yaml"]
    for command in commands:
        result = subprocess.run(
            [str(_CONSOLE_SCRIPT), *command[1:]],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def _compare(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "compare_specs.py"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


def test_documented_commands_produce_equivalent_json_and_yaml(project: Path) -> None:
    _run_documented_generation(project)

    result = _compare(project)

    assert result.returncode == 0, result.stderr
    assert "OK: 3 operations are equivalent" in result.stdout
    from_json = json.loads((project / "openapi.json").read_text(encoding="utf-8"))
    from_yaml = yaml.safe_load((project / "openapi.yaml").read_text(encoding="utf-8"))
    assert from_json == from_yaml
    methods = sorted((p, m) for p, item in from_json["paths"].items() for m in item)
    assert methods == [
        ("/api/reports", "post"),
        ("/api/reports/{job_id}/download", "get"),
        ("/api/reports/{job_id}/status", "get"),
    ]
    assert "BearerAuth" in from_json["components"]["securitySchemes"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda spec: spec["paths"]["/api/reports"]["post"]["responses"].pop("202"),
            "POST /api/reports: responses differ",
        ),
        (lambda spec: spec["components"]["securitySchemes"].pop("BearerAuth"), "security schemes"),
        (lambda spec: spec["paths"].pop("/api/reports"), "paths or methods"),
        (lambda spec: spec["info"].update(title="Drifted"), "outside paths"),
    ],
    ids=["response", "security-scheme", "path", "other"],
)
def test_comparison_detects_drift_in_the_yaml_copy(
    project: Path, mutate: Callable[[dict[str, Any]], object], expected: str
) -> None:
    _run_documented_generation(project)
    yaml_path = project / "openapi.yaml"
    spec = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    mutate(spec)
    yaml_path.write_text(yaml.safe_dump(spec), encoding="utf-8")

    result = _compare(project)

    assert result.returncode != 0
    assert expected in result.stderr


def test_strict_failure_writes_no_file_to_compare(project: Path) -> None:
    (project / "function_app.py").write_text(
        'from azure_functions_openapi import openapi\n\n@openapi(route="x/{id}", method="GET", '
        'parameters=[{"name": "other", "in": "path", "required": True, '
        '"schema": {"type": "string"}}])\ndef h(): pass\n',
        encoding="utf-8",
    )
    command = [*_documented_generate_commands()[0][1:]]
    command[command.index("--app") + 1] = "function_app"

    result = subprocess.run(
        [str(_CONSOLE_SCRIPT), *command],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert not (project / "openapi.json").exists()
