"""Azure inline route constraints must normalize into a coherent OpenAPI path.

`items/{id:int}` has to become the path `/api/items/{id}` plus a required `id`
path parameter with an integer schema: OpenAPI matches a template variable to a
parameter by name, so leaving `{id:int}` in the path would describe a different
endpoint than the one the Azure runtime serves.
"""

from __future__ import annotations

from typing import Any

from openapi_spec_validator import validate
import pytest

from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import generate_openapi_spec
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


@pytest.mark.parametrize(
    ("route", "expected_path", "expected_constraints"),
    [
        ("items/{id:guid}", "items/{id}", {"id": "guid"}),
        ("items/{id?}", "items/{id}", {}),
        ("files/{*path}", "files/{path}", {}),
        ("items/{id:unknown}", "items/{id}", {"id": "unknown"}),
    ],
)
def test_full_azure_route_parameter_syntax_is_normalized(
    route: str, expected_path: str, expected_constraints: dict[str, str]
) -> None:
    assert validate_route_path(route) is True
    assert parse_route_template(route) == (expected_path, expected_constraints)


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
