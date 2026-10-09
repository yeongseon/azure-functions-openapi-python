"""Azure inline route constraints must normalize into a coherent OpenAPI path.

`items/{id:int}` has to become the path `/api/items/{id}` plus a required `id`
path parameter with an integer schema: OpenAPI matches a template variable to a
parameter by name, so leaving `{id:int}` in the path would describe a different
endpoint than the one the Azure runtime serves.
"""

from __future__ import annotations

from typing import Any

import azure.functions as func
from openapi_spec_validator import validate
import pytest

from azure_functions_openapi import openapi
from azure_functions_openapi.bridge import scan_endpoint_metadata
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec
from azure_functions_openapi.utils import parse_route_template, validate_route_path


@pytest.mark.parametrize(
    ("route", "expected_path", "expected_constraints"),
    [
        ("items/{id:int}", "items/{id}", {"id": "int"}),
        ("categories/{category:alpha}", "categories/{category}", {"category": "alpha"}),
        (
            "products/{category:alpha}/{id:int}",
            "products/{category}/{id}",
            {"category": "alpha", "id": "int"},
        ),
        ("plain/{id}", "plain/{id}", {}),
        ("no/params", "no/params", {}),
    ],
)
def test_parse_route_template(
    route: str, expected_path: str, expected_constraints: dict[str, str]
) -> None:
    assert parse_route_template(route) == (expected_path, expected_constraints)


@pytest.mark.parametrize("route", ["items/{id:int}", "products/{category:alpha}/{id:int}"])
def test_supported_constraints_are_accepted(route: str) -> None:
    assert validate_route_path(route) is True


@pytest.mark.parametrize("route", ["items/{id:}", "items/{:int}", "items/{id", "items/{}"])
def test_unsupported_or_malformed_routes_are_rejected(route: str) -> None:
    assert validate_route_path(route) is False


def _spec_for(entry: dict[str, Any], strict: bool = False) -> dict[str, Any]:
    registry = OpenAPIRegistry()
    registry.set("fn", entry)
    return generate_openapi_spec(title="T", registry=registry, strict=strict)


def test_int_constraint_becomes_a_required_integer_path_parameter() -> None:
    spec = _spec_for({"summary": "s", "method": "get", "route": "items/{id:int}"})

    assert "/api/items/{id}" in spec["paths"]
    (param,) = spec["paths"]["/api/items/{id}"]["get"]["parameters"]
    assert param == {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}


def test_alpha_constraint_maps_to_a_plain_string_schema() -> None:
    spec = _spec_for({"summary": "s", "method": "get", "route": "cats/{category:alpha}"})

    (param,) = spec["paths"]["/api/cats/{category}"]["get"]["parameters"]
    assert param["schema"] == {"type": "string"}
    assert "pattern" not in param["schema"]


def test_unconstrained_variable_becomes_a_required_string_parameter() -> None:
    # Given: an Azure route variable without an inline constraint.
    entry = {"summary": "s", "method": "get", "route": "users/{id}"}

    # When: the OpenAPI document is generated.
    spec = _spec_for(entry)

    # Then: the variable has a matching required string parameter and validates.
    (param,) = spec["paths"]["/api/users/{id}"]["get"]["parameters"]
    assert param == {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    validate(spec)


_UNSUPPORTED_ROUTES = [
    "items/{id?}",
    "items/{id:int?}",
    "files/{*rest}",
    "items/{id:guid}",
    "items/{enabled:bool}",
    "items/{created:datetime}",
    "items/{id:long}",
    "items/{value:float}",
    "items/{value:double}",
    "items/{value:decimal}",
    "items/{id:min(1)}",
    "items/{id:max(10)}",
    "items/{id:range(1,10)}",
    "items/{name:length(8)}",
    "items/{name:minlength(2)}",
    "items/{name:maxlength(12)}",
    "items/{slug:regex([a-z]+)}",
]


@pytest.mark.parametrize("route", _UNSUPPORTED_ROUTES)
def test_authored_routes_reject_unsupported_azure_semantics(route: str) -> None:
    # Given: an authored route using Azure syntax outside the supported subset.
    # When/Then: decoration rejects the route and identifies its unsupported token.
    with pytest.raises(ValueError, match="unsupported Azure route token") as excinfo:

        @openapi(summary="Unsupported route", method="get", route=route)
        def authored_route(_req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("OK")

    assert "authored_route" in str(excinfo.value)
    assert route in str(excinfo.value)


@pytest.mark.parametrize("route", _UNSUPPORTED_ROUTES)
def test_route_validator_rejects_unsupported_azure_semantics(route: str) -> None:
    assert validate_route_path(route) is False


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("route", _UNSUPPORTED_ROUTES)
def test_scanned_routes_do_not_weaken_unsupported_azure_semantics(route: str, strict: bool) -> None:
    # Given: a real SDK binding whose route is only resolved during app scanning.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route=route, methods=["GET"])
    @openapi(summary="Scanned route")
    def scanned_route(_req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    registry = OpenAPIRegistry()
    scan_endpoint_metadata(app, registry=registry)

    # When/Then: strict mode raises; non-strict mode skips with a structured warning.
    if strict:
        with pytest.raises(ValueError, match="unsupported Azure route token") as excinfo:
            generate_openapi_spec(title="T", registry=registry, strict=True)
        assert "scanned_route" in str(excinfo.value)
        assert route in str(excinfo.value)
        return

    spec = generate_openapi_spec(title="T", registry=registry)
    warnings = collect_spec_warnings(spec, registry=registry)
    assert spec["paths"] == {}
    assert [(warning.code.value, warning.function_name) for warning in warnings] == [
        ("operation-skipped", "scanned_route")
    ]
    assert route in warnings[0].message


@pytest.mark.parametrize(
    ("route", "parameter_name", "schema"),
    [
        ("items/{id:int}", "id", {"type": "integer"}),
        ("categories/{category:alpha}", "category", {"type": "string"}),
    ],
)
def test_scanned_routes_keep_supported_constraints(
    route: str, parameter_name: str, schema: dict[str, str]
) -> None:
    # Given: a real SDK binding using one of the two supported constraints.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route=route, methods=["GET"])
    @openapi(summary="Supported route")
    def scanned_supported_route(_req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    registry = OpenAPIRegistry()
    scan_endpoint_metadata(app, registry=registry)

    # When: the scanned operation is generated.
    spec = generate_openapi_spec(title="T", registry=registry)

    # Then: the constraint remains represented by its exact current schema.
    normalized_route, _constraints = parse_route_template(route)
    (parameter,) = spec["paths"][f"/api/{normalized_route}"]["get"]["parameters"]
    assert parameter == {
        "name": parameter_name,
        "in": "path",
        "required": True,
        "schema": schema,
    }


def test_dotted_static_route_generates_a_valid_document() -> None:
    spec = _spec_for({"summary": "s", "method": "get", "route": "v1.0/items"})

    assert "/api/v1.0/items" in spec["paths"]
    validate(spec)


def test_multiple_constraints_in_one_route() -> None:
    spec = _spec_for(
        {"summary": "s", "method": "get", "route": "products/{category:alpha}/{id:int}"}
    )

    params = spec["paths"]["/api/products/{category}/{id}"]["get"]["parameters"]
    by_name = {p["name"]: p["schema"] for p in params}
    assert by_name == {"category": {"type": "string"}, "id": {"type": "integer"}}


def test_explicit_metadata_wins_over_an_inferred_constraint() -> None:
    spec = _spec_for(
        {
            "summary": "s",
            "method": "get",
            "route": "items/{id:int}",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
        }
    )

    (param,) = spec["paths"]["/api/items/{id}"]["get"]["parameters"]
    assert param["schema"] == {"type": "string"}


def test_a_conflicting_explicit_schema_fails_strict_generation() -> None:
    entry = {
        "summary": "s",
        "method": "get",
        "route": "items/{id:int}",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
    }

    with pytest.raises(OpenAPISpecConfigError, match="route constrains it"):
        _spec_for(entry, strict=True)


def test_an_explicit_parameter_without_a_schema_adopts_the_constraint() -> None:
    spec = _spec_for(
        {
            "summary": "s",
            "method": "get",
            "route": "items/{id:int}",
            "parameters": [{"name": "id", "in": "path", "required": True}],
        }
    )

    (param,) = spec["paths"]["/api/items/{id}"]["get"]["parameters"]
    assert param["schema"] == {"type": "integer"}


def test_a_matching_explicit_schema_is_not_duplicated() -> None:
    spec = _spec_for(
        {
            "summary": "s",
            "method": "get",
            "route": "items/{id:int}",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
            ],
        }
    )

    params = spec["paths"]["/api/items/{id}"]["get"]["parameters"]
    assert len(params) == 1
