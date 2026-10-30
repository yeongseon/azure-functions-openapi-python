"""Array downgrade contracts measured against both OpenAPI schema validators."""

from __future__ import annotations

import copy
from typing import Final

from openapi_schema_validator import OAS30Validator, OAS31Validator
from openapi_spec_validator import validate
from pydantic import JsonValue
import pytest

from azure_functions_openapi._schema_version_conversion import (
    _convert_schema_to_3_0,
    _operation_schema_slots,
)
from azure_functions_openapi._warnings import WarningCode
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec

PROBES: Final[list[JsonValue]] = [
    [],
    ["a"],
    [1],
    [None],
    ["a", 1],
    [1, "a"],
    ["a", "b"],
    ["a", 1, None],
    [1, "a", 2],
    ["a", "b", "c"],
    None,
    "a",
    {},
]
CASES: Final[list[tuple[dict[str, JsonValue], bool]]] = [
    (dict[str, JsonValue](type="array", prefixItems=[{"type": "string"}], **tail, **cap), loss)
    for tail in ({}, {"items": True})
    for cap, loss in (
        ({}, True),
        ({"maxItems": 2}, True),
        ({"maxItems": 1}, False),
        ({"maxItems": 0}, False),
    )
] + [
    ({"type": "array"}, False),
    ({"type": "array", "items": True}, False),
    ({"type": "array", "items": False}, False),
    ({"type": "array", "prefixItems": [], "items": True}, False),
    ({"type": "array", "prefixItems": []}, False),
    ({"type": "array", "prefixItems": [{}], "items": True}, False),
    ({"type": "array", "prefixItems": [{"type": "string"}], "items": False}, False),
    ({"type": "array", "prefixItems": [{"type": "string"}], "items": {"type": "string"}}, False),
    ({"type": "array", "contains": {"type": "integer"}}, True),
    ({"type": ["array", "null"]}, False),
    ({"anyOf": [{"type": "array"}, {"type": "null"}]}, False),
]


def array_registry(schema: dict[str, JsonValue], hoisted: bool) -> OpenAPIRegistry:
    body = {"$ref": "#/$defs/Array", "$defs": {"Array": schema}} if hoisted else schema
    registry = OpenAPIRegistry()
    registry.set(
        "array",
        {
            "route": "array",
            "method": "post",
            "request_body": body,
            "response": {
                200: {
                    "description": "ok",
                    "content": {"application/json": {"schema": body}},
                    "headers": {
                        "X-Array": {"schema": body},
                        "X-Content": {"content": {"application/json": {"schema": body}}},
                    },
                }
            },
            "parameters": [{"name": "array", "in": "query", "schema": body}],
        },
    )
    return registry


@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
@pytest.mark.parametrize(("schema", "lossy"), CASES)
def test_array_items_preserve_acceptance_or_report_loss(
    schema: dict[str, JsonValue], lossy: bool, hoisted: bool
) -> None:
    # Given
    before = copy.deepcopy(schema)
    registry = array_registry(schema, hoisted)

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0")

    # Then
    validate(spec)
    original = OAS31Validator(schema)
    original_results = [original.is_valid(probe) for probe in PROBES]
    for _, container, key in _operation_schema_slots(spec["paths"]["/api/array"]["post"]):
        actual_schema = spec["components"]["schemas"]["Array"] if hoisted else container[key]
        if actual_schema.get("type") == "array":
            assert isinstance(actual_schema["items"], dict)
            if lossy and "prefixItems" in schema:
                assert actual_schema["items"] == {}
        converted = OAS30Validator({**container[key], "components": spec.get("components", {})})
        actual = [converted.is_valid(probe) for probe in PROBES]
        if lossy:
            assert actual != original_results
            assert all(new for old, new in zip(original_results, actual) if old)
        else:
            assert actual == original_results
    warnings = collect_spec_warnings(spec, registry)
    assert bool(warnings) is lossy
    assert all(w.code is WarningCode.VERSION_DOWNGRADE_DROP for w in warnings)
    if lossy:
        with pytest.raises(OpenAPISpecConfigError):
            generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)
    else:
        generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)
    assert schema == before


@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
@pytest.mark.parametrize(
    "slot",
    ["root", "properties", "items", "additionalProperties", "allOf", "anyOf", "oneOf", "not"],
)
@pytest.mark.parametrize("items", [{}, {"items": True}, {"items": {"type": "string"}}])
def test_item_normalization_reaches_nested_schema_positions(
    hoisted: bool, slot: str, items: dict[str, JsonValue]
) -> None:
    # Given
    child: dict[str, JsonValue] = {"type": "array", **items}
    wrappers: dict[str, dict[str, JsonValue]] = {
        "root": child,
        "properties": {"type": "object", "properties": {"a": child}},
        "items": {"type": "array", "items": child},
        "additionalProperties": {"type": "object", "additionalProperties": child},
        "allOf": {"allOf": [child]},
        "anyOf": {"anyOf": [child]},
        "oneOf": {"oneOf": [child]},
        "not": {"not": child},
    }
    schema = wrappers[slot]
    registry = array_registry(schema, hoisted)
    probes = [*PROBES, *[{"a": value} for value in PROBES], *[[value] for value in PROBES]]

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)

    # Then
    validate(spec)
    normalized = {**child, "items": items.get("items", {})}
    if normalized["items"] is True:
        normalized["items"] = {}
    root = (
        spec["components"]["schemas"]["Array"]
        if hoisted
        else next(_operation_schema_slots(spec["paths"]["/api/array"]["post"]))[1]["schema"]
    )
    nested = {
        "root": root,
        "properties": root.get("properties", {}).get("a"),
        "items": root.get("items"),
        "additionalProperties": root.get("additionalProperties"),
        "allOf": root.get("allOf", [None])[0],
        "anyOf": root.get("anyOf", [None])[0],
        "oneOf": root.get("oneOf", [None])[0],
        "not": root.get("not"),
    }
    assert nested[slot] == normalized
    original = OAS31Validator(schema)
    for _, container, key in _operation_schema_slots(spec["paths"]["/api/array"]["post"]):
        converted = OAS30Validator({**container[key], "components": spec.get("components", {})})
        assert [converted.is_valid(p) for p in probes] == [original.is_valid(p) for p in probes]
    assert collect_spec_warnings(spec, registry) == ()


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"type": "string"},
        {"type": "object"},
        {"nullable": True},
        {"type": "array", "items": {}},
        {"type": "array", "items": {"type": "string"}},
        {"type": "array", "nullable": True, "items": {"type": "integer"}},
        {"example": {"type": "array"}},
        {"x-data": {"type": "array"}},
    ],
)
def test_fill_leaves_other_schemas_and_existing_items_unchanged(
    schema: dict[str, JsonValue],
) -> None:
    # Given / When / Then
    assert _convert_schema_to_3_0(schema) == schema


@pytest.mark.parametrize("schema", [{"items": True}, {"items": False}])
def test_boolean_items_without_an_array_type_stay_type_specific(
    schema: dict[str, JsonValue],
) -> None:
    # Given / When
    converted = _convert_schema_to_3_0(schema)
    # Then
    assert isinstance(converted["items"], dict)
    assert [OAS30Validator(converted).is_valid(p) for p in PROBES] == [
        OAS31Validator(schema).is_valid(p) for p in PROBES
    ]


def test_open_tail_loss_names_the_unconstrained_tail_and_the_approximation() -> None:
    # Given: a prefix whose tail accepts anything.
    losses: list[str] = []

    # When
    converted = _convert_schema_to_3_0(
        {"type": "array", "prefixItems": [{"type": "string"}]}, lossy=losses
    )

    # Then
    assert converted == {"type": "array", "items": {}}
    assert losses == [
        "tuple[string, any] positional constraints cannot be preserved in OpenAPI 3.0 "
        "and were approximated as items: {}; a value valid at any position is now "
        "accepted at every position"
    ]
