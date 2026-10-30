from collections.abc import Callable, Iterator
import json
from pathlib import Path
import re
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


@pytest.mark.parametrize(
    "case",
    [
        ("{", "Expecting property name"),
        ("{// comment\n}", "Expecting property name"),
        ("{/* comment */}", "Expecting property name"),
        ('{"version":"2.0",}', "Expecting property name|Illegal trailing comma"),
        ('{"extensions":{"http":{"routePrefix":17}}}', "must be a string"),
        ('{"extensions":{"http":{"routePrefix":null}}}', "must be a string"),
        ('{"extensions":{"http":{"routePrefix":[]}}}', "must be a string"),
    ],
)
def test_auto_rejects_unusable_host_json(run_cli: RunCLI, case: tuple[str, str]) -> None:
    # Given
    host, reason = case
    path = Path.cwd() / "host.json"
    # When
    code, output, error = run_cli(["--route-prefix", "auto", "--output", "blocked.json"], host)
    # Then
    assert code == 1
    assert output == ""
    assert not Path("blocked.json").exists()
    assert f"Cannot use {path} for --route-prefix auto:" in error
    assert re.search(reason, error)
    assert "Fix the file or pass --route-prefix explicitly." in error
    assert len(error.splitlines()) == 1
    assert "Traceback" not in error


def test_auto_rejects_directory_host_json(run_cli: RunCLI) -> None:
    # Given
    path = Path.cwd() / "host.json"
    path.mkdir()
    # When
    code, output, error = run_cli(
        ["--route-prefix", "auto", "--fail-on-warnings", "--output", "blocked.json"], None
    )
    # Then
    assert code == 1
    assert output == ""
    assert not Path("blocked.json").exists()
    assert f"Cannot use {path} for --route-prefix auto:" in error
    assert "Is a directory" in error
    assert len(error.splitlines()) == 1
    assert "Traceback" not in error


def test_auto_failure_leaves_an_existing_output_file_untouched(run_cli: RunCLI) -> None:
    # Given
    target = Path("existing.json")
    target.write_text("previous", encoding="utf-8")
    # When
    code, output, error = run_cli(["--route-prefix", "auto", "--output", "existing.json"], "{")
    # Then
    assert code == 1
    assert output == ""
    assert "Cannot use" in error
    assert target.read_text(encoding="utf-8") == "previous"


@pytest.mark.parametrize("host", [None, "{}", '{"extensions":{"http":{}}}'])
def test_auto_silently_defaults_when_configuration_is_absent(
    run_cli: RunCLI, host: str | None
) -> None:
    # Given
    options = ["--route-prefix", "auto", "--fail-on-warnings"]
    # When
    code, output, error = run_cli(options, host)
    # Then
    assert code == 0
    assert set(json.loads(output)["paths"]) == {"/api/widgets"}
    assert error == ""


@pytest.mark.parametrize("prefix", ["override", ""])
def test_auto_environment_bypasses_unusable_file(
    run_cli: RunCLI, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    # Given
    Path("host.json").mkdir()
    monkeypatch.setenv(SETTING, prefix)
    # When
    code, output, error = run_cli(["--route-prefix", "auto", "--fail-on-warnings"], None)
    # Then
    assert code == 0
    assert set(json.loads(output)["paths"]) == {"/override/widgets" if prefix else "/widgets"}
    assert error == ""


@pytest.mark.parametrize(
    ("setting", "expected"), [("override", "/override/widgets"), ("", "/widgets")]
)
def test_auto_environment_is_resolved_before_the_file_is_read(
    run_cli: RunCLI, monkeypatch: pytest.MonkeyPatch, setting: str, expected: str
) -> None:
    # Given
    def fail(path: Path) -> tuple[str | None, str | None]:
        raise AssertionError(f"{path} was read although the app setting is present")

    monkeypatch.setattr("azure_functions_openapi._cli_route_prefix._read_route_prefix", fail)
    monkeypatch.setenv(SETTING, setting)
    # When
    code, output, error = run_cli(["--route-prefix", "auto", "--fail-on-warnings"], "{")
    # Then
    assert code == 0
    assert set(json.loads(output)["paths"]) == {expected}
    assert error == ""


@pytest.mark.parametrize("options", [[], ["--route-prefix", "/gateway"]])
def test_literal_prefix_ignores_unreadable_file(run_cli: RunCLI, options: list[str]) -> None:
    # Given
    Path("host.json").mkdir()
    # When
    code, output, error = run_cli([*options, "--fail-on-warnings"], None)
    # Then
    assert code == 0
    assert set(json.loads(output)["paths"]) == {"/gateway/widgets" if options else "/api/widgets"}
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
