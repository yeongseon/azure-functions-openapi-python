from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import subprocess
import sys

import azure.functions as func
import pytest
import yaml

from azure_functions_openapi import (
    WarningCode,
    clear_openapi_registry,
    generate_openapi_report,
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
    openapi,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def test_spec_uses_binding_route_when_openapi_is_outermost() -> None:
    # Given: @openapi can inspect the builder returned by @app.route.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(summary="outer")
    @app.route(route="things/{id}", methods=["PATCH"])
    def outer_handler(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: binding metadata is reconciled and the spec is generated.
    spec = generate_openapi_spec(app=app)

    # Then: the binding route, method, and route parameter are documented.
    operation = spec["paths"]["/api/things/{id}"]["patch"]
    assert operation["parameters"] == [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    ]


def test_spec_uses_binding_route_when_openapi_is_innermost() -> None:
    # Given: @openapi runs before @app.route and cannot inspect its binding yet.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.function_name(name="custom_name")
    @app.route(route="items/{item_id:int}", methods=["GET", "DELETE"])
    @openapi(summary="inner")
    def inner_handler(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: binding metadata is reconciled with a custom host route prefix.
    spec = generate_openapi_spec(app=app, route_prefix="/v1")

    # Then: neither the Python nor registered function name becomes the path.
    path_item = spec["paths"]["/v1/items/{item_id}"]
    assert set(path_item) == {"get", "delete"}
    assert path_item["get"]["parameters"] == [
        {
            "name": "item_id",
            "in": "path",
            "required": True,
            "schema": {"type": "integer"},
        }
    ]
    assert "/v1/inner_handler" not in spec["paths"]
    assert "/v1/custom_name" not in spec["paths"]


def test_json_uses_binding_route_when_openapi_is_innermost() -> None:
    # Given: @openapi runs before the route binding exists.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="json-items", methods=["GET"])
    @openapi(summary="JSON items")
    def json_items(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: the package-root JSON facade receives the completed app.
    document = json.loads(get_openapi_json(app=app))

    # Then: it scans the binding before serializing the spec.
    assert set(document["paths"]) == {"/api/json-items"}


def test_yaml_uses_binding_route_when_openapi_is_innermost() -> None:
    # Given: @openapi runs before the route binding exists.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="yaml-items", methods=["POST"])
    @openapi(summary="YAML items")
    def yaml_items(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: the package-root YAML facade receives the completed app.
    document = yaml.safe_load(get_openapi_yaml(app=app))

    # Then: it scans the binding before serializing the spec.
    assert set(document["paths"]) == {"/api/yaml-items"}


def test_report_uses_binding_route_when_openapi_is_innermost() -> None:
    # Given: @openapi runs before the route binding exists.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="report-items", methods=["GET"])
    @openapi(summary="Report items")
    def report_items(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: the package-root report facade receives the completed app.
    report = generate_openapi_report(app=app)

    # Then: it scans the binding before compiling and reports no unresolved route.
    assert set(report.spec["paths"]) == {"/api/report-items"}
    assert not report.warnings


def test_report_warns_when_route_has_no_binding_evidence() -> None:
    # Given: a bare decorator has neither an explicit route nor a visible builder.
    @openapi(summary="Unresolved")
    def unresolved(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: a report is generated without scanning an app.
    with pytest.warns(RuntimeWarning, match="unresolved"):
        report = generate_openapi_report()

    # Then: the function-name fallback is machine-readable.
    assert [(warning.code, warning.function_name) for warning in report.warnings] == [
        (WarningCode.UNRESOLVED_ROUTE, "unresolved")
    ]


def test_strict_generation_raises_when_route_has_no_binding_evidence() -> None:
    # Given: a bare decorator has no evidence for its runtime route.
    @openapi(summary="Unresolved")
    def unresolved(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When/Then: strict generation refuses the silent function-name fallback.
    with pytest.raises(OpenAPISpecConfigError, match="unresolved"):
        generate_openapi_spec(strict=True)


def test_cli_app_variable_uses_binding_route_for_innermost_openapi(tmp_path: Path) -> None:
    # Given: an importable app uses the innermost decorator order.
    (tmp_path / "function_app.py").write_text(
        "import azure.functions as func\n"
        "from azure_functions_openapi import openapi\n"
        "app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)\n"
        "@app.route(route='cli-items', methods=['GET'])\n"
        "@openapi(summary='CLI items')\n"
        "def cli_items(req: func.HttpRequest): return func.HttpResponse('OK')\n",
        encoding="utf-8",
    )
    output = tmp_path / "openapi.json"

    # When: the CLI resolves and scans the completed FunctionApp.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "azure_functions_openapi.cli",
            "generate",
            "--app",
            "function_app:app",
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then: the generated path comes from the binding.
    assert result.returncode == 0, result.stderr
    assert set(json.loads(output.read_text(encoding="utf-8"))["paths"]) == {"/api/cli-items"}


def test_cli_module_warns_for_innermost_openapi_without_scan(tmp_path: Path) -> None:
    # Given: a module-only import registers metadata before its route is visible.
    (tmp_path / "function_app.py").write_text(
        "import azure.functions as func\n"
        "from azure_functions_openapi import openapi\n"
        "app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)\n"
        "@app.route(route='cli-items', methods=['GET'])\n"
        "@openapi(summary='CLI items')\n"
        "def cli_items(req: func.HttpRequest): return func.HttpResponse('OK')\n",
        encoding="utf-8",
    )

    # When: the CLI imports only the module and cannot scan the app binding.
    result = subprocess.run(
        [sys.executable, "-m", "azure_functions_openapi.cli", "generate", "--app", "function_app"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then: generation succeeds for compatibility but exposes the unresolved route.
    assert result.returncode == 0, result.stderr
    warnings = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    assert any(warning["code"] == "unresolved-route" for warning in warnings)


def test_spec_keeps_function_name_route_without_explicit_binding_route() -> None:
    # Given: neither decorator supplies an explicit route.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(methods=["POST"])
    @openapi(summary="implicit")
    def implicit_handler(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: the app is scanned and its spec is generated.
    spec = generate_openapi_spec(app=app)

    # Then: Azure's implicit function-name route remains documented.
    assert set(spec["paths"]["/api/implicit_handler"]) == {"post"}
