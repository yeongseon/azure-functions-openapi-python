from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import subprocess
import sys

import azure.functions as func
from pydantic import BaseModel
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
    register_openapi_routes,
)


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


def test_strict_generation_warns_when_default_route_cannot_be_verified() -> None:
    # Given: Azure's implicit route is correct, but the inner decorator cannot verify it.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(methods=["GET"])
    @openapi(summary="Implicit")
    def implicit(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: strict generation runs without the completed app.
    with pytest.warns(RuntimeWarning, match="could not be verified"):
        spec = generate_openapi_spec(strict=True)

    # Then: the compatible function-name route remains available under strict mode.
    assert set(spec["paths"]) == {"/api/implicit"}


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


def test_cli_unresolved_route_does_not_trip_fail_on_warnings(tmp_path: Path) -> None:
    # Given: a module-only import of an innermost @openapi with an implicit route.
    (tmp_path / "function_app.py").write_text(
        "import azure.functions as func\n"
        "from azure_functions_openapi import openapi\n"
        "app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)\n"
        "@app.route(methods=['GET'])\n"
        "@openapi(summary='Implicit')\n"
        "def implicit_items(req: func.HttpRequest): return func.HttpResponse('OK')\n",
        encoding="utf-8",
    )

    # When: the CLI runs with --strict --fail-on-warnings.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "azure_functions_openapi.cli",
            "generate",
            "--app",
            "function_app",
            "--strict",
            "--fail-on-warnings",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then: the advisory warning is reported but the spec is still emitted.
    assert result.returncode == 0, result.stderr
    assert "/api/implicit_items" in result.stdout
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


# ---------------------------------------------------------------------------
# Auto-expansion provenance survives an app scan, both decorator orders
# (issue #781): an unspecified-methods @app.route binding expands to every
# HTTP verb, and scanning the completed app (which concretizes each exploded
# entry's ``method``) must not disable the per-method operationId suffix or
# the automatic bodyless-method request-body rules that expansion requires.
# ---------------------------------------------------------------------------


class _Payload(BaseModel):
    name: str


def test_explicit_operation_id_stays_unique_per_method_after_app_scan_outermost() -> None:
    # Given: @openapi is outermost and can see the unspecified-methods binding
    # directly, so it already knows expansion is happening.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(operation_id="all_methods")
    @app.route(route="any")
    def any_method(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("{}")

    before = generate_openapi_spec(strict=True)

    # When: the completed app is scanned.
    after = generate_openapi_spec(app=app, strict=True)

    # Then: every method keeps a unique, per-method-suffixed operationId --
    # identical to the pre-scan result -- instead of colliding on the bare
    # "all_methods" id.
    before_ids = {method: op["operationId"] for method, op in before["paths"]["/api/any"].items()}
    after_ids = {method: op["operationId"] for method, op in after["paths"]["/api/any"].items()}
    assert after_ids == before_ids
    assert len(set(after_ids.values())) == len(after_ids)
    assert after_ids["get"] == "all_methods_get"


def test_explicit_operation_id_stays_unique_per_method_after_app_scan_innermost() -> None:
    # Given: @openapi is innermost, so it cannot see the binding and registers
    # with method=None; the bridge must explode it into per-method entries
    # that still carry the same "this was auto-expanded" context.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="any")
    @openapi(operation_id="all_methods")
    def any_method(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("{}")

    # When: the completed app is scanned, then scanned again (idempotency).
    first = generate_openapi_spec(app=app, strict=True)
    second = generate_openapi_spec(app=app, strict=True)

    # Then: unique per-method ids, stable across repeated scans.
    first_ids = {method: op["operationId"] for method, op in first["paths"]["/api/any"].items()}
    second_ids = {method: op["operationId"] for method, op in second["paths"]["/api/any"].items()}
    assert first_ids == second_ids
    assert len(set(first_ids.values())) == len(first_ids)
    assert first_ids["post"] == "all_methods_post"


def test_request_model_not_dropped_from_auto_expanded_bodyless_methods_outermost() -> None:
    # Given: an auto-expanded binding carries an explicit Pydantic request
    # model, with @openapi outermost.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(requests=_Payload)
    @app.route(route="any")
    def any_method(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("{}")

    before = generate_openapi_spec(strict=True)

    # When: the completed app is scanned under strict mode.
    after = generate_openapi_spec(app=app, strict=True)

    # Then: body-bearing methods keep the declared schema; bodyless methods
    # (GET/HEAD/DELETE) omit it -- matching the pre-scan result exactly,
    # instead of strict mode raising "explicit request model dropped".
    for spec in (before, after):
        operations = spec["paths"]["/api/any"]
        assert "requestBody" in operations["post"]
        assert "requestBody" in operations["put"]
        assert "requestBody" in operations["patch"]
        assert "requestBody" not in operations["get"]
        assert "requestBody" not in operations["head"]
        assert "requestBody" not in operations["delete"]
    assert (
        after["paths"]["/api/any"]["post"]["requestBody"]
        == before["paths"]["/api/any"]["post"]["requestBody"]
    )


def test_request_model_not_dropped_from_auto_expanded_bodyless_methods_innermost() -> None:
    # Given: the same scenario with @openapi innermost (method=None until the
    # bridge explodes it from the binding).
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="any")
    @openapi(requests=_Payload)
    def any_method(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("{}")

    # When: strict generation scans the completed app.
    spec = generate_openapi_spec(app=app, strict=True)

    # Then: generation succeeds (no OpenAPISpecConfigError) and the bodyless
    # rules apply exactly as they do for the outermost order.
    operations = spec["paths"]["/api/any"]
    assert "requestBody" in operations["post"]
    assert "requestBody" not in operations["get"]
    assert "requestBody" not in operations["delete"]


def test_register_openapi_routes_json_endpoint_reflects_expansion_fix() -> None:
    # Given: the documented register_openapi_routes() helper scans the app it
    # is given, exercising the same path a real deployment uses.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(operation_id="all_methods", requests=_Payload)
    @app.route(route="any")
    def any_method(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("{}")

    routes = register_openapi_routes(app, title="Expansion", version="1.0.0")
    assert routes.json is not None
    request = func.HttpRequest(
        method="GET", url="/api/openapi.json", headers={}, params={}, body=b""
    )

    # When: the JSON endpoint generates the spec (strict, per route registration).
    document = json.loads(routes.json(request).get_body())

    # Then: unique operation ids and correct bodyless omission, same as a
    # direct generate_openapi_spec(app=app, strict=True) call.
    operations = document["paths"]["/api/any"]
    ids = {method: op["operationId"] for method, op in operations.items()}
    assert len(set(ids.values())) == len(ids)
    assert "requestBody" in operations["post"]
    assert "requestBody" not in operations["get"]


def test_cli_app_variable_preserves_unique_operation_ids_for_expanded_methods(
    tmp_path: Path,
) -> None:
    # Given: an importable app whose unspecified-methods binding carries an
    # explicit operation_id, exercised through the module:app CLI path.
    (tmp_path / "function_app.py").write_text(
        "import azure.functions as func\n"
        "from azure_functions_openapi import openapi\n"
        "app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)\n"
        "@openapi(operation_id='cli_all_methods')\n"
        "@app.route(route='cli-any')\n"
        "def cli_any(req: func.HttpRequest): return func.HttpResponse('OK')\n",
        encoding="utf-8",
    )
    output = tmp_path / "openapi.json"

    # When: the CLI resolves and scans the completed FunctionApp under strict mode.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "azure_functions_openapi.cli",
            "generate",
            "--app",
            "function_app:app",
            "--strict",
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then: generation succeeds with distinct, suffixed operation ids per method.
    assert result.returncode == 0, result.stderr
    operations = json.loads(output.read_text(encoding="utf-8"))["paths"]["/api/cli-any"]
    ids = {method: op["operationId"] for method, op in operations.items()}
    assert len(set(ids.values())) == len(ids)
    assert ids["get"] == "cli_all_methods_get"


def test_explicit_method_binding_keeps_unsuffixed_operation_id_after_app_scan() -> None:
    # Given: a genuinely explicit single-method binding (no expansion at all).
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(operation_id="single")
    @app.route(route="single-method", methods=["POST"])
    def single_method(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: the completed app is scanned.
    spec = generate_openapi_spec(app=app, strict=True)

    # Then: the explicit id is kept verbatim -- it must not be suffixed, since
    # there was never more than one method to disambiguate.
    assert spec["paths"]["/api/single-method"]["post"]["operationId"] == "single"
