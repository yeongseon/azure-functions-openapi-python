from collections.abc import Callable, Iterator
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from azure_functions_openapi import clear_openapi_registry, register_openapi_metadata
from azure_functions_openapi.cli import main

RunCLI = Callable[[list[str], str | None], tuple[int, str, str]]
SETTING = "AzureFunctionsJobHost__extensions__http__routePrefix"


@pytest.fixture
def run_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Iterator[RunCLI]:
    monkeypatch.delenv(SETTING, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "prefix_app", raising=False)
    clear_openapi_registry()
    (tmp_path / "prefix_app.py").write_text(
        "import azure.functions as func\n"
        "from azure_functions_openapi import openapi\n"
        "app = func.FunctionApp()\n"
        "@app.route(route='widgets', methods=['GET'])\n"
        "@openapi(summary='Widgets')\n"
        "def list_widgets(req: func.HttpRequest) -> func.HttpResponse:\n"
        "    return func.HttpResponse('[]')\n",
        encoding="utf-8",
    )

    def run(options: list[str], host: str | None) -> tuple[int, str, str]:
        if host is not None:
            (tmp_path / "host.json").write_text(host, encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            ["azure-functions-openapi", "generate", "--app", "prefix_app:app", *options],
        )
        code = main()
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    try:
        yield run
    finally:
        sys.modules.pop("prefix_app", None)
        clear_openapi_registry()


@pytest.mark.parametrize("prefix", ["v1", ""])
def test_auto_uses_host_prefix(run_cli: RunCLI, prefix: str) -> None:
    # Given
    host = json.dumps({"extensions": {"http": {"routePrefix": prefix}}})
    # When
    code, output, error = run_cli(["--route-prefix", "auto", "--fail-on-warnings"], host)
    # Then
    assert code == 0
    assert set(json.loads(output)["paths"]) == {f"/{prefix}/widgets" if prefix else "/widgets"}
    assert error == ""


@pytest.mark.parametrize("options", [[], ["--route-prefix", "/api"]])
def test_mismatch_is_structured_warning(run_cli: RunCLI, options: list[str]) -> None:
    # Given
    host = '{"extensions":{"http":{"routePrefix":"v1"}}}'
    # When
    code, output, error = run_cli(options, host)
    # Then
    assert code == 0
    assert set(json.loads(output)["paths"]) == {"/api/widgets"}
    warning = json.loads(error)
    assert warning["code"] == "route-prefix-mismatch"
    assert all(
        value in warning["message"] for value in ["/api", "/v1", "--route-prefix /v1", "auto"]
    )


def test_mismatch_gates_output(run_cli: RunCLI) -> None:
    # Given
    host = '{"extensions":{"http":{"routePrefix":"v1"}}}'
    # When
    code, output, error = run_cli(["--fail-on-warnings", "--output", "blocked.json"], host)
    # Then
    assert code == 2
    assert output == ""
    assert not Path("blocked.json").exists()
    assert json.loads(error)["code"] == "route-prefix-mismatch"


@pytest.mark.parametrize(
    "case",
    [
        (["--route-prefix", "/v1/"], '{"extensions":{"http":{"routePrefix":"v1"}}}', "/v1"),
        ([], None, "/api"),
        ([], "{}", "/api"),
        ([], "{", "/api"),
        ([], '{"extensions":{"http":{"routePrefix":17}}}', "/api"),
        (["--route-prefix", ""], '{"extensions":{"http":{"routePrefix":""}}}', ""),
        (["--route-prefix", "/auto"], '{"extensions":{"http":{"routePrefix":"auto"}}}', "/auto"),
    ],
)
def test_matching_or_absent_prefix_does_not_warn(
    run_cli: RunCLI, case: tuple[list[str], str | None, str]
) -> None:
    # Given
    options, host, prefix = case
    # When
    code, output, error = run_cli([*options, "--fail-on-warnings"], host)
    # Then
    assert code == 0
    assert set(json.loads(output)["paths"]) == {f"{prefix}/widgets"}
    assert error == ""


def test_mismatch_ignores_environment(run_cli: RunCLI, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    monkeypatch.setenv(SETTING, "api")
    # When
    code, _, error = run_cli([], '{"extensions":{"http":{"routePrefix":"v1"}}}')
    # Then
    assert code == 0
    assert json.loads(error)["code"] == "route-prefix-mismatch"


def test_auto_honors_environment(run_cli: RunCLI, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    monkeypatch.setenv(SETTING, "override")
    # When
    code, output, error = run_cli(
        ["--route-prefix", "auto"], '{"extensions":{"http":{"routePrefix":"v1"}}}'
    )
    # Then
    assert code == 0
    assert set(json.loads(output)["paths"]) == {"/override/widgets"}
    assert error == ""


def test_auto_looks_beside_module_not_cwd(run_cli: RunCLI, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    caller = Path("caller")
    caller.mkdir()
    (Path.cwd() / "host.json").write_text(
        '{"extensions":{"http":{"routePrefix":"v1"}}}', encoding="utf-8"
    )
    monkeypatch.chdir(caller)
    Path("host.json").write_text(
        '{"extensions":{"http":{"routePrefix":"wrong"}}}', encoding="utf-8"
    )
    # When
    code, output, error = run_cli(["--route-prefix", "auto"], None)
    # Then
    assert code == 0
    assert set(json.loads(output)["paths"]) == {"/v1/widgets"}
    assert error == ""


@pytest.mark.parametrize("app", [None, "fileless_prefix_app"])
def test_auto_falls_back_to_cwd(
    run_cli: RunCLI, monkeypatch: pytest.MonkeyPatch, app: str | None
) -> None:
    # Given
    Path("host.json").write_text(
        '{"extensions":{"http":{"routePrefix":"local"}}}', encoding="utf-8"
    )
    register_openapi_metadata(path="widgets", method="get")
    if app is not None:
        monkeypatch.setitem(sys.modules, app, ModuleType(app))
    options = [] if app is None else ["--app", app]
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli", "generate", "--route-prefix", "auto", "--output", "result.json", *options],
    )
    # When
    code = main()
    # Then
    assert code == 0
    assert set(json.loads(Path("result.json").read_text())["paths"]) == {"/local/widgets"}
