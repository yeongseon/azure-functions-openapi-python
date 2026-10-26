"""Cross-version conversion contracts before the #819 refactor."""

from __future__ import annotations

import copy

from openapi_schema_validator import OAS30Validator, OAS31Validator
from pydantic import JsonValue
import pytest

from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec

VERSIONS = ("3.0.0", "3.1.0", "3.2.0")
TUPLE_LOSS = (
    "tuple[integer, number] positional constraints cannot be preserved in OpenAPI 3.0 "
    "and were approximated as items.anyOf; a value valid at any position is now "
    "accepted at every position"
)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
@pytest.mark.parametrize(
    ("original", "expected_30", "expected_31", "valid", "invalid"),
    [
        (
            {"type": "string", "nullable": True, "example": "yes"},
            {"type": "string", "nullable": True, "example": "yes"},
            {"type": ["string", "null"], "examples": ["yes"]},
            [None, "yes"],
            [42],
        ),
        (
            {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]},
            {
                "nullable": True,
                "anyOf": [{"type": "string", "nullable": True}, {"type": "integer"}],
            },
            {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]},
            [None, "yes", 42],
            [[1]],
        ),
        (
            {
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "const": "fixed", "examples": ["fixed"]},
                    "score": {"type": "number", "exclusiveMinimum": 1},
                    "labels": {"type": "array", "items": {"type": ["string", "null"]}},
                },
            },
            {
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "enum": ["fixed"], "example": "fixed"},
                    "score": {"type": "number", "minimum": 1, "exclusiveMinimum": True},
                    "labels": {"type": "array", "items": {"type": "string", "nullable": True}},
                },
            },
            {
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "const": "fixed", "examples": ["fixed"]},
                    "score": {"type": "number", "exclusiveMinimum": 1},
                    "labels": {"type": "array", "items": {"type": ["string", "null"]}},
                },
            },
            [{"choice": "fixed", "score": 2, "labels": [None, "x"]}],
            [{"choice": "other"}, {"score": 1}, {"labels": [42]}],
        ),
    ],
    ids=["legacy-nullable", "nullable-union", "nested-keywords"],
)
def test_schema_conversion_at_every_operation_position(
    version: str,
    hoisted: bool,
    original: dict[str, JsonValue],
    expected_30: dict[str, JsonValue],
    expected_31: dict[str, JsonValue],
    valid: list[JsonValue],
    invalid: list[JsonValue],
) -> None:
    # Given: identical producer schemas in every supported operation position.
    payload = {"title": "Matrix", **original}
    schema = {"$ref": "#/$defs/Matrix", "$defs": {"Matrix": payload}} if hoisted else payload
    registry = OpenAPIRegistry()
    registry.set(
        "matrix",
        {
            "route": "matrix",
            "method": "post",
            "request_body": schema,
            "response": {200: {"content": {"application/json": {"schema": schema}}}},
            "parameters": [{"name": "value", "in": "query", "schema": schema}],
        },
    )
    before = copy.deepcopy(schema)

    # When
    spec = generate_openapi_spec(
        registry=registry, openapi_version=version, hoist_flat_schemas=hoisted, strict=True
    )

    # Then: exact schemas, not just the presence of a conversion keyword.
    expected = {"title": "Matrix", **(expected_30 if version == "3.0.0" else expected_31)}
    op = spec["paths"]["/api/matrix"]["post"]
    positions = [
        op["requestBody"]["content"]["application/json"]["schema"],
        op["responses"]["200"]["content"]["application/json"]["schema"],
        op["parameters"][0]["schema"],
    ]
    if hoisted:
        assert positions == [{"$ref": "#/components/schemas/Matrix"}] * 3
        assert spec["components"]["schemas"]["Matrix"] == expected
    else:
        assert positions == [expected] * 3
    validator = (OAS30Validator if version == "3.0.0" else OAS31Validator)(
        {**positions[0], "components": spec.get("components", {})}
    )
    assert all(validator.is_valid(instance) for instance in valid)
    assert all(not validator.is_valid(instance) for instance in invalid)
    assert collect_spec_warnings(spec, registry) == ()
    assert schema == before


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("homogeneous", [True, False])
@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
def test_prefix_items_conversion(version: str, homogeneous: bool, hoisted: bool) -> None:
    # Given
    items = [{"type": "integer"}, {"type": "integer" if homogeneous else "number"}]
    schema = {"type": "array", "prefixItems": items, "minItems": 2, "maxItems": 2}
    registry = OpenAPIRegistry()
    body = {"$ref": "#/$defs/Pair", "$defs": {"Pair": schema}} if hoisted else schema
    registry.set("pair", {"route": "pair", "method": "post", "request_body": body})

    # When
    spec = generate_openapi_spec(
        registry=registry,
        openapi_version=version,
        strict=homogeneous or version != "3.0.0",
    )

    # Then
    actual = spec["paths"]["/api/pair"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    if hoisted:
        assert actual == {"$ref": "#/components/schemas/Pair"}
        actual = spec["components"]["schemas"]["Pair"]
    expected = schema
    messages = []
    if version == "3.0.0":
        expected = {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": items[0] if homogeneous else {"anyOf": items},
        }
        messages = [] if homogeneous else [("Schema 'Pair': " if hoisted else "") + TUPLE_LOSS]
    assert actual == expected
    assert [w.message for w in collect_spec_warnings(spec, registry)] == messages
    validator = (OAS30Validator if version == "3.0.0" else OAS31Validator)(actual)
    assert validator.is_valid([1, 2])
    assert not validator.is_valid([1])
    assert validator.is_valid([2.5, 1]) == (version == "3.0.0" and not homogeneous)


def test_heterogeneous_tuple_strict_exception_is_repeatable() -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set(
        "pair",
        {
            "route": "pair",
            "method": "post",
            "request_body": {
                "type": "array",
                "prefixItems": [{"type": "integer"}, {"type": "number"}],
            },
        },
    )
    # When / Then
    for _ in range(2):
        with pytest.raises(OpenAPISpecConfigError) as caught:
            generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)
        assert str(caught.value) == (
            "Strict mode: generated spec has validation errors:\n  - " + TUPLE_LOSS
        )


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("strict", [False, True])
def test_mutual_nullable_reference_cycle(version: str, strict: bool) -> None:
    # Given: raw definitions keep component names independent of Pydantic versions.
    registry = OpenAPIRegistry()
    definitions = {
        name: {
            "type": "object",
            "properties": {
                "next": {
                    "anyOf": [{"$ref": f"#/$defs/{other}"}, {"type": "null"}],
                }
            },
        }
        for name, other in [("A", "B"), ("B", "A")]
    }
    registry.set(
        "cycle",
        {
            "route": "cycle",
            "method": "post",
            "request_body": {
                "$ref": "#/$defs/A",
                "$defs": definitions,
            },
        },
    )
    # When / Then
    if version == "3.0.0" and strict:
        with pytest.raises(OpenAPISpecConfigError, match="mutually-recursive reference"):
            generate_openapi_spec(registry=registry, openapi_version=version, strict=strict)
        return
    spec = generate_openapi_spec(registry=registry, openapi_version=version, strict=strict)
    schemas = spec["components"]["schemas"]
    if version == "3.0.0":
        assert schemas["A"]["properties"]["next"]["properties"]["next"]["properties"]["next"] == {
            "nullable": True,
            "allOf": [{"$ref": "#/components/schemas/B"}],
        }
        assert {w.code.value for w in collect_spec_warnings(spec, registry)} == {
            "version-downgrade-drop"
        }
    else:
        assert schemas == {
            name: {
                "type": "object",
                "properties": {
                    "next": {
                        "anyOf": [{"$ref": f"#/components/schemas/{other}"}, {"type": "null"}],
                    }
                },
            }
            for name, other in [("A", "B"), ("B", "A")]
        }
        assert collect_spec_warnings(spec, registry) == ()
    validator = (OAS30Validator if version == "3.0.0" else OAS31Validator)(
        {
            "$ref": "#/components/schemas/A",
            "components": spec["components"],
        }
    )
    assert validator.is_valid({"next": None})
    # Current 3.0 fallback loses nullability at a deeper recursive edge.
    assert validator.is_valid({"next": {"next": {"next": None}}}) == (version != "3.0.0")
