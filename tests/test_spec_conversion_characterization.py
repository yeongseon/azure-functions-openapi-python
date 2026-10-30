"""Cross-version conversion contracts before the #819 refactor."""

from __future__ import annotations

import copy

from openapi_schema_validator import OAS30Validator, OAS31Validator
from pydantic import JsonValue
import pytest

from azure_functions_openapi._schema_version_conversion import (
    _find_3_1_only_construct,
    _operation_schema_slots,
)
from azure_functions_openapi._warnings import WarningCode
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
        (
            {"type": ["string"]},
            {"type": "string"},
            {"type": ["string"]},
            ["yes"],
            [42, None],
        ),
        (
            {"type": ["string", "integer"]},
            {"anyOf": [{"type": "string"}, {"type": "integer"}]},
            {"type": ["string", "integer"]},
            ["yes", 42],
            [[1], 1.5, None],
        ),
        (
            {"type": ["string", "integer"], "minLength": 2, "minimum": 0},
            {
                "anyOf": [{"type": "string"}, {"type": "integer"}],
                "minLength": 2,
                "minimum": 0,
            },
            {"type": ["string", "integer"], "minLength": 2, "minimum": 0},
            ["ab", 0, 5],
            ["a", -1, 1.5],
        ),
        (
            {
                "type": ["string", "integer"],
                "anyOf": [
                    {"type": "string", "minLength": 2},
                    {"type": "integer", "minimum": 5},
                ],
            },
            {
                "anyOf": [
                    {"type": "string", "minLength": 2},
                    {"type": "integer", "minimum": 5},
                ],
                "allOf": [{"anyOf": [{"type": "string"}, {"type": "integer"}]}],
            },
            {
                "type": ["string", "integer"],
                "anyOf": [
                    {"type": "string", "minLength": 2},
                    {"type": "integer", "minimum": 5},
                ],
            },
            ["ab", 6],
            ["a", 4, 1.5, None],
        ),
        (
            {
                "type": "object",
                "properties": {"loc": {"type": "array", "items": {"type": ["string", "integer"]}}},
            },
            {
                "type": "object",
                "properties": {
                    "loc": {
                        "type": "array",
                        "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                    }
                },
            },
            {
                "type": "object",
                "properties": {"loc": {"type": "array", "items": {"type": ["string", "integer"]}}},
            },
            [{"loc": ["body", 0]}],
            [{"loc": [None]}, {"loc": [1.5]}],
        ),
        (
            {"not": {"type": ["string", "integer"]}},
            {"not": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
            {"not": {"type": ["string", "integer"]}},
            [[1], None, 1.5],
            ["x", 5],
        ),
    ],
    ids=[
        "legacy-nullable",
        "nullable-union",
        "nested-keywords",
        "single-type-array",
        "type-array",
        "type-array-with-sibling-keywords",
        "type-array-beside-any-of",
        "nested-type-array",
        "negated-type-array",
    ],
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


@pytest.mark.parametrize(
    ("schema", "construct"),
    [
        ({"type": ["string", "integer"]}, 'a "type" array'),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, 'an "anyOf" with a null type'),
        (
            {"type": "object", "properties": {"a": {"items": {"type": ["string"]}}}},
            'a "type" array',
        ),
        ({"allOf": ["junk", {"type": ["string"]}]}, 'a "type" array'),
        ({"$defs": {"X": {"type": ["string"]}}}, 'a "type" array'),
        ({"not": {"type": ["string", "integer"]}}, 'a "type" array'),
        ({"type": "string", "nullable": True}, None),
    ],
)
def test_audit_names_the_first_construct_openapi_3_0_cannot_express(
    schema: dict[str, JsonValue], construct: str | None
) -> None:
    # Given / When / Then: the finding names what is wrong, not just that something is.
    assert _find_3_1_only_construct(schema) == construct


@pytest.mark.parametrize(
    "odd",
    [
        {"type": []},
        {"type": ["string", "integer"], "discriminator": {"propertyName": "kind"}},
    ],
    ids=["empty-type-list", "type-array-beside-discriminator"],
)
@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
@pytest.mark.parametrize("strict", [False, True])
def test_unconvertible_construct_is_reported_through_the_downgrade_channel(
    odd: dict[str, JsonValue], hoisted: bool, strict: bool
) -> None:
    # Given: a ``type`` array no OpenAPI 3.0 conversion can normalize faithfully: an
    # empty list, or one beside a ``discriminator`` (a combinator would activate it).
    body = {"$ref": "#/$defs/Odd", "$defs": {"Odd": odd}} if hoisted else odd
    registry = OpenAPIRegistry()
    registry.set("odd", {"route": "odd", "method": "post", "request_body": body})
    subject = (
        "Schema 'Odd'" if hoisted else "POST /api/odd requestBody.content.application/json.schema"
    )

    # When / Then: strict mode refuses the document and names the construct and location.
    if strict:
        with pytest.raises(OpenAPISpecConfigError, match="3.1-only constructs") as caught:
            generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)
        assert subject in str(caught.value)
        assert '(a "type" array)' in str(caught.value)
        return

    # When: non-strict generation still produces a document.
    spec = generate_openapi_spec(
        registry=registry, openapi_version="3.0.0", hoist_flat_schemas=hoisted
    )

    # Then: the finding is a structured warning that --fail-on-warnings can gate on.
    (warning,) = collect_spec_warnings(spec, registry)
    assert warning.code is WarningCode.VERSION_DOWNGRADE_DROP
    assert warning.message.startswith(f"{subject} contains OpenAPI 3.1-only constructs")
    assert '(a "type" array)' in warning.message


def test_has_3_1_only_constructs_stays_importable_from_spec() -> None:
    # Given / When: the compatibility re-export that predates the construct-naming audit.
    from azure_functions_openapi.spec import _has_3_1_only_constructs

    # Then: it still answers the yes/no question it always did.
    assert _has_3_1_only_constructs({"type": ["string", "integer"]}) is True
    assert _has_3_1_only_constructs({"type": "string"}) is False


def test_operation_schema_slots_label_each_schema_and_skip_malformed_entries() -> None:
    # Given: an operation mixing well-formed schema positions with malformed raw entries.
    operation = {
        "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
        "responses": {
            "200": "junk",
            "201": {"content": {"application/json": "junk"}},
            "202": {"content": {"application/json": {"schema": {"type": "string"}}}},
        },
        "parameters": [
            "junk",
            {"name": "q", "in": "query", "schema": {"type": "string"}},
            {
                "name": "qs",
                "in": "querystring",
                "content": {"application/x-www-form-urlencoded": {"schema": {"type": "object"}}},
            },
        ],
    }

    # When
    locations = [location for location, _container, _key in _operation_schema_slots(operation)]

    # Then: every location names where the schema sits, and malformed entries are skipped.
    assert locations == [
        "requestBody.content.application/json.schema",
        "responses.202.content.application/json.schema",
        "parameters[1].schema",
        "parameters[2].content.application/x-www-form-urlencoded.schema",
    ]


@pytest.mark.parametrize(
    "operation",
    [
        {"requestBody": {"content": "junk"}, "responses": "junk"},
        {"requestBody": {"content": {"application/json": "junk"}}, "parameters": []},
        {"requestBody": "junk", "responses": {"200": {"content": "junk"}}},
        {"parameters": [{"name": "qs", "in": "querystring", "content": {"x": "junk"}}]},
    ],
)
def test_operation_schema_slots_yield_nothing_for_unusable_containers(
    operation: dict[str, JsonValue],
) -> None:
    # Given / When / Then
    assert list(_operation_schema_slots(operation)) == []
