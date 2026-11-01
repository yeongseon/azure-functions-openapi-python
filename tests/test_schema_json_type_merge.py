"""Strict nullable conversion preserves constraints that differ by JSON value type."""

from __future__ import annotations

import json

from openapi_schema_validator import OAS30Validator, OAS31Validator
from openapi_spec_validator import validate
from pydantic import JsonValue
import pytest

from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec

Schema = dict[str, JsonValue]


def _convert(node: Schema, definitions: Schema, hoisted: bool) -> tuple[Schema, Schema]:
    registry = OpenAPIRegistry()
    body = (
        {"$ref": "#/$defs/Holder", "$defs": {"Holder": node, **definitions}}
        if hoisted
        else {**node, "$defs": definitions}
    )
    registry.set("holder", {"route": "holder", "method": "post", "request_body": body})
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)
    validate(spec)
    assert collect_spec_warnings(spec, registry) == ()
    root = (
        spec["components"]["schemas"]["Holder"]
        if hoisted
        else spec["paths"]["/api/holder"]["post"]["requestBody"]["content"]["application/json"][
            "schema"
        ]
    )
    return root, {**root, "components": spec.get("components", {})}


def _assert_instances(
    original: Schema, converted: Schema, cases: list[tuple[JsonValue, bool]]
) -> None:
    before = OAS31Validator(original)
    after = OAS30Validator(converted)
    for instance, expected in cases:
        assert before.is_valid(instance) is expected
        assert after.is_valid(instance) is expected


@pytest.fixture(
    params=[(True, 1), (1, True), (False, 0), (0, False)],
    ids=["true-one", "one-true", "false-zero", "zero-false"],
)
def pair(request: pytest.FixtureRequest) -> tuple[bool | int, bool | int]:
    values = request.param
    assert isinstance(values, tuple) and len(values) == 2
    first, second = values
    assert isinstance(first, (bool, int)) and isinstance(second, (bool, int))
    return first, second


@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
@pytest.mark.parametrize("key", ["anyOf", "oneOf"])
def test_wrapper_allof_preserves_json_distinct_constraints(
    pair: tuple[bool | int, bool | int], hoisted: bool, key: str
) -> None:
    # Given: both allOf lists look equal to Python but constrain different JSON values.
    first, second = pair
    target_constraint: Schema = {"properties": {"a": {"enum": [first]}}}
    wrapper_constraint: Schema = {"properties": {"a": {"enum": [second]}}}
    definitions: Schema = {"T": {"type": "object", "allOf": [target_constraint]}}
    node: Schema = {
        "allOf": [wrapper_constraint],
        key: [{"$ref": "#/$defs/T"}, {"type": "null"}],
    }

    # When: a strict conversion merges the wrapper with its referenced member.
    root, converted = _convert(node, definitions, hoisted)

    # Then: neither conjunct is discarded, and accepted/rejected instances stay the same.
    assert json.dumps(root["allOf"]) == json.dumps([target_constraint, wrapper_constraint])
    _assert_instances(
        {**node, "$defs": definitions},
        converted,
        [(None, True), ({}, True), ({"a": first}, False), ({"a": second}, False)],
    )


@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
@pytest.mark.parametrize("key", ["anyOf", "oneOf"])
def test_overlapping_items_preserve_nested_json_types(
    pair: tuple[bool | int, bool | int], hoisted: bool, key: str
) -> None:
    # Given: overlapping items contain nested enum objects differing only by JSON type.
    first, second = pair
    target_items: Schema = {"enum": [{"a": [first]}]}
    wrapper_items: Schema = {"enum": [{"a": [second]}]}
    definitions: Schema = {"T": {"type": "array", "items": target_items}}
    node: Schema = {
        "items": wrapper_items,
        key: [{"$ref": "#/$defs/T"}, {"type": "null"}],
    }

    # When
    root, converted = _convert(node, definitions, hoisted)

    # Then: the target's items survive and the wrapper's items form another conjunct.
    assert json.dumps(root["items"]) == json.dumps(target_items)
    assert json.dumps(root["allOf"]) == json.dumps([{"items": wrapper_items}])
    _assert_instances(
        {**node, "$defs": definitions},
        converted,
        [(None, True), ([], True), ([{"a": [first]}], False), ([{"a": [second]}], False)],
    )


@pytest.mark.parametrize(
    "placement",
    [(False, False), (False, True), (True, False), (True, True)],
    ids=[
        "inline-member-inline",
        "inline-member-component",
        "ref-member-inline",
        "ref-member-component",
    ],
)
@pytest.mark.parametrize("key", ["anyOf", "oneOf"])
def test_single_member_preserves_json_distinct_not_constraints(
    pair: tuple[bool | int, bool | int], placement: tuple[bool, bool], key: str
) -> None:
    # Given: the node and sole member reject different JSON objects through not.
    first, second = pair
    referenced, hoisted = placement
    member: Schema = {"type": "object", "not": {"enum": [{"a": first}]}}
    wrapper_not: Schema = {"enum": [{"a": second}]}
    definitions: Schema = {"T": member} if referenced else {}
    node: Schema = {
        "not": wrapper_not,
        key: [{"$ref": "#/$defs/T"} if referenced else member, {"type": "null"}],
    }

    # When
    root, converted = _convert(node, definitions, hoisted)

    # Then: not predicates stay separate instead of overwriting or dropping either one.
    if referenced:
        assert json.dumps(root["not"]) == json.dumps(member["not"])
        assert json.dumps(root["allOf"]) == json.dumps([{"not": wrapper_not}])
    else:
        assert json.dumps(root["not"]) == json.dumps(wrapper_not)
        assert json.dumps(root[key]) == json.dumps([member, {"nullable": True, "enum": [None]}])
    _assert_instances(
        {**node, "$defs": definitions},
        converted,
        [
            (None, True),
            ({}, True),
            ({"a": "x"}, True),
            ({"a": first}, False),
            ({"a": second}, False),
        ],
    )


@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
@pytest.mark.parametrize("referenced", [False, True], ids=["inline-member", "ref-member"])
def test_equal_constraints_merge_without_duplicate_conjuncts(
    hoisted: bool, referenced: bool
) -> None:
    # Given: genuinely equal allOf and items values on both sides of the merge.
    constraint: Schema = {"items": {"enum": [{"a": True}]}}
    member: Schema = {"type": "array", "items": constraint["items"], "allOf": [constraint]}
    definitions: Schema = {"T": member} if referenced else {}
    node: Schema = {
        **constraint,
        "allOf": [constraint],
        "anyOf": [{"$ref": "#/$defs/T"} if referenced else member, {"type": "null"}],
    }

    # When
    root, converted = _convert(node, definitions, hoisted)

    # Then: equality still permits a flat merge without extra allOf members.
    assert json.dumps(root, sort_keys=True) == json.dumps(
        {**member, "nullable": True}, sort_keys=True
    )
    _assert_instances(
        {**node, "$defs": definitions},
        converted,
        [(None, True), ([], True), ([{"a": True}], True), ([{"a": 1}], False)],
    )
