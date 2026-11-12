"""Pin the CLI route-prefix troubleshooting recipe in docs/troubleshooting.md.

Each scenario runs the documented command through the installed console script
against a local app, so the documented outcomes cannot drift from the CLI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DOC = (_ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
_SCRIPT = Path(sys.executable).parent / "azure-functions-openapi"
_SETTING = "AzureFunctionsJobHost__extensions__http__routePrefix"
_APP = (
    "import azure.functions as func\n"
    "from azure_functions_openapi import openapi\n"
    "app = func.FunctionApp()\n"
    "@app.route(route='widgets', methods=['GET'])\n"
    "@openapi(summary='Widgets')\n"
    "def list_widgets(req: func.HttpRequest) -> func.HttpResponse:\n"
    "    return func.HttpResponse('[]')\n"
)


def _run(cwd: Path, *options: str, setting: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != _SETTING}
    if setting is not None:
        env[_SETTING] = setting
    return subprocess.run(
        [str(_SCRIPT), "generate", "--app", "function_app:app", "--format", "json", *options],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "function_app.py").write_text(_APP, encoding="utf-8")
    (tmp_path / "host.json").write_text(
        '{"version": "2.0", "extensions": {"http": {"routePrefix": "v1"}}}', encoding="utf-8"
    )
    return tmp_path


def _paths(result: subprocess.CompletedProcess[str]) -> list[str]:
    return sorted(json.loads(result.stdout)["paths"])


def test_doc_lists_the_commands_it_documents() -> None:
    for fragment in (
        "generate --app function_app:app --format json --fail-on-warnings",
        "--route-prefix auto --format json",
        "--route-prefix /v1 --format json",
        _SETTING + "=gw",
        "route-prefix-mismatch",
        "[Route Prefix Policy](route-prefix.md)",
    ):
        assert fragment in _DOC


def test_default_prefix_mismatch_exits_2_without_output(project: Path) -> None:
    result = _run(project, "--fail-on-warnings")
    assert result.returncode == 2
    assert result.stdout == ""
    warning = json.loads(result.stderr.strip().splitlines()[-1])
    assert warning["code"] == "route-prefix-mismatch"
    assert "'/api'" in warning["message"] and "'/v1'" in warning["message"]


@pytest.mark.parametrize("prefix", ["auto", "/v1"])
def test_auto_and_explicit_prefix_match_host(project: Path, prefix: str) -> None:
    result = _run(project, "--route-prefix", prefix, "--fail-on-warnings")
    assert result.returncode == 0
    assert result.stderr == ""
    assert _paths(result) == ["/v1/widgets"]


def test_host_json_is_read_beside_the_app_module_not_cwd(
    project: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    (elsewhere / "host.json").write_text('{"extensions": {"http": {"routePrefix": "other"}}}')
    env = {**os.environ, "PYTHONPATH": str(project)}
    env.pop(_SETTING, None)
    result = subprocess.run(
        [str(_SCRIPT), "generate", "--app", "function_app:app", "--format", "json"]
        + ["--route-prefix", "auto"],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert _paths(result) == ["/v1/widgets"]


def test_environment_override_wins_in_auto_mode_only(project: Path) -> None:
    auto = _run(project, "--route-prefix", "auto", setting="gw")
    assert _paths(auto) == ["/gw/widgets"]
    explicit = _run(project, "--route-prefix", "/v1", "--fail-on-warnings", setting="gw")
    assert explicit.returncode == 0
    assert _paths(explicit) == ["/v1/widgets"]


def test_unreadable_host_json_is_an_error_in_auto_mode(project: Path) -> None:
    (project / "host.json").write_text("{", encoding="utf-8")
    result = _run(project, "--route-prefix", "auto")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "for --route-prefix auto:" in result.stderr
    assert "Fix the file or pass --route-prefix explicitly." in result.stderr
