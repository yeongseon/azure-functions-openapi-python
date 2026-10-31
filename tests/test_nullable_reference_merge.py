"""A nullable union converted for OpenAPI 3.0 accepts exactly what the original accepts."""

from __future__ import annotations

import copy
from typing import Annotated, Any, Literal

from openapi_schema_validator import OAS30Validator, OAS31Validator
from openapi_spec_validator import validate
from pydantic import BaseModel, Field, JsonValue, RootModel
import pytest

from azure_functions_openapi._schema_version_conversion import (
    _accepts_null,
    _convert_schema_to_3_0,
    _merge_wrapper_into_inlined,
)
from azure_functions_openapi.decorator import register_openapi_metadata
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec

PROBES: list[JsonValue] = [
    None,
    "",
    "a",
    "b",
    "az",
    "abc",
    "abcd",
    "abcdef",
    1,
    2,
    3,
    6,
    2.5,
    True,
    [],
    [1],
    {},
    {"a": 1},
    {"b": 1},
    {"a": 1, "b": 2},
]
BASE = {"Base": {"type": "object"}}
T_REF: dict[str, JsonValue] = {"$ref": "#/$defs/T"}


def nullable(target: dict[str, Any], wrapper: dict[str, Any] | None = None) -> tuple[Any, Any]:
    """A nullable union over a reference to *target*, with *wrapper* keys beside the union."""
    return {**(wrapper or {}), "anyOf": [T_REF, {"type": "null"}]}, {"T": target}


def _registry(node: dict[str, Any], definitions: dict[str, Any], hoisted: bool) -> OpenAPIRegistry:
    body = (
        {"$ref": "#/$defs/Holder", "$defs": {"Holder": node, **definitions}}
        if hoisted
        else {**node, "$defs": definitions}
    )
    registry = OpenAPIRegistry()
    registry.set("holder", {"route": "holder", "method": "post", "request_body": body})
    return registry


ROWS: list[tuple[str, tuple[Any, Any], list[JsonValue], list[JsonValue]]] = [
    (
        "all-of-on-both-sides",
        nullable({"allOf": [{"type": "object"}]}, {"allOf": [{"minProperties": 1}]}),
        [None, {"a": 1}],
        [{}, "x", 1, []],
    ),
    (
        "type-array-beside-an-all-of-target",
        nullable({"allOf": [{"type": "object"}]}, {"type": ["string", "integer"]}),
        [],
        [None, "x", 1, {}],
    ),
    (
        "pattern-on-both-sides",
        nullable({"type": "string", "pattern": "^a"}, {"pattern": "z$"}),
        [None, "az"],
        ["a", "abc", "b", 1],
    ),
    (
        "required-on-both-sides",
        nullable(
            {"type": "object", "required": ["b"], "properties": {"b": {"type": "integer"}}},
            {"required": ["a"]},
        ),
        [None, {"a": 1, "b": 2}],
        [{"a": 1}, {"b": 1}, {}, "x"],
    ),
    (
        "enum-on-both-sides",
        nullable({"type": "string", "enum": ["a", "b"]}, {"enum": ["a"]}),
        ["a"],
        [None, "b", "az", 1],
    ),
    (
        "type-on-both-sides",
        nullable({"type": "object"}, {"type": "object"}),
        [{}, {"a": 1}],
        [None, "x", 1],
    ),
    (
        "tighter-bound-wins",
        nullable({"type": "string", "maxLength": 5}, {"maxLength": 3}),
        [None, "abc"],
        ["abcd", "abcdef", 1],
    ),
    (
        "multiple-of-on-both-sides",
        nullable({"type": "number", "multipleOf": 2}, {"multipleOf": 3}),
        [None, 6],
        [2, 3, "x"],
    ),
    (
        "null-through-an-all-of-type-member",
        nullable({"allOf": [{"type": "object"}]}),
        [None, {}, {"a": 1}],
        ["x", 1],
    ),
    (
        "null-through-an-all-of-enum-member",
        nullable({"allOf": [{"enum": ["a", "b"]}]}),
        [None, "a", "b"],
        ["az", 1],
    ),
    (
        "null-through-a-nested-all-of",
        nullable({"allOf": [{"allOf": [{"type": "object"}]}]}),
        [None, {}],
        ["x", 1],
    ),
    (
        "null-through-an-all-of-union-member",
        nullable({"allOf": [{"anyOf": [{"type": "string"}, {"type": "integer"}]}]}),
        [None, "a", 1],
        [[], {}],
    ),
    (
        "null-through-a-contradiction",
        nullable({"enum": ["x"], "const": "y"}),
        [None],
        ["x", "y", 1, {}],
    ),
    (
        "null-through-an-empty-enum-contradiction",
        nullable({"enum": [], "const": 1}),
        [None],
        ["x", 1, {}],
    ),
    (
        "null-through-an-all-of-reference",
        (
            {"anyOf": [T_REF, {"type": "null"}]},
            {"T": {"allOf": [{"$ref": "#/$defs/Base"}]}, **BASE},
        ),
        [None, {}],
        ["x", 1],
    ),
    (
        "all-of-reference-beside-a-constraint",
        (
            {"description": "field", "anyOf": [T_REF, {"type": "null"}]},
            {"T": {"allOf": [{"$ref": "#/$defs/Base"}, {"minProperties": 1}]}, **BASE},
        ),
        [None, {"a": 1}],
        [{}, "x"],
    ),
    (
        "alias-of-a-reference",
        (
            {"description": "field", "anyOf": [T_REF, {"type": "null"}]},
            {"T": {"$ref": "#/$defs/Base", "description": "alias"}, **BASE},
        ),
        [None, {}],
        ["x", 1],
    ),
    (
        "alias-with-a-sibling-constraint",
        (
            {"anyOf": [T_REF, {"type": "null"}]},
            {"T": {"$ref": "#/$defs/Base", "minProperties": 1}, **BASE},
        ),
        [None, {"a": 1}],
        [{}, "x"],
    ),
    (
        "null-through-a-one-of-target",
        nullable({"oneOf": [{"type": "string"}, {"type": "integer"}]}),
        [None, "a", 1],
        [2.5, [], {}],
    ),
    (
        "null-through-a-nested-one-of",
        nullable({"allOf": [{"anyOf": [{"oneOf": [{"type": "integer"}, {"type": "string"}]}]}]}),
        [None, 1, "a"],
        [2.5, [], {}],
    ),
    (
        "null-through-a-not-member",
        nullable({"allOf": [{"not": {"type": "null"}}]}),
        [None, "x", {}],
        [],
    ),
    (
        "null-through-a-not-over-a-string",
        nullable({"allOf": [{"not": {"type": "string"}}]}),
        [None, 1, {}],
        ["x"],
    ),
    (
        "reference-sibling-type-inside-the-branch",
        (
            {"anyOf": [{"$ref": "#/$defs/T", "type": "object"}, {"type": "null"}]},
            {"T": {"type": "object"}},
        ),
        [None, {}, {"a": 1}],
        ["x", 1],
    ),
    (
        "outer-type-beside-a-union-of-references",
        (
            {
                "type": "object",
                "anyOf": [{"$ref": "#/$defs/T"}, {"$ref": "#/$defs/S"}, {"type": "null"}],
            },
            {"T": {"allOf": [{"type": "object"}]}, "S": {"type": "string"}},
        ),
        [{}],
        [None, "x", 1],
    ),
    (
        "union-of-references",
        (
            {"anyOf": [{"$ref": "#/$defs/T"}, {"$ref": "#/$defs/S"}, {"type": "null"}]},
            {"T": {"type": "object"}, "S": {"type": "string"}},
        ),
        [None, {}, "x"],
        [1, []],
    ),
    (
        "discriminated-union",
        (
            {
                "anyOf": [
                    {
                        "oneOf": [{"$ref": "#/$defs/Cat"}, {"$ref": "#/$defs/Dog"}],
                        "discriminator": {"propertyName": "kind"},
                    },
                    {"type": "null"},
                ]
            },
            {
                "Cat": {
                    "type": "object",
                    "properties": {"kind": {"const": "cat"}},
                    "required": ["kind"],
                },
                "Dog": {
                    "type": "object",
                    "properties": {"kind": {"const": "dog"}},
                    "required": ["kind"],
                },
            },
        ),
        [None, {"kind": "cat"}, {"kind": "dog"}],
        [{"kind": "fish"}, {}, "x"],
    ),
    (
        "one-of-union-with-a-null-member",
        (
            {"oneOf": [{"$ref": "#/$defs/T"}, {"$ref": "#/$defs/S"}, {"type": "null"}]},
            {"T": {"type": "object"}, "S": {"type": "string"}},
        ),
        [None, {}, "x"],
        [1, []],
    ),
    (
        "any-of-beside-a-one-of-union",
        (
            {
                "anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}],
                "oneOf": [{"$ref": "#/$defs/T"}, {"$ref": "#/$defs/S"}, {"type": "null"}],
            },
            {"T": {"type": "object"}, "S": {"type": "string"}},
        ),
        [None, "a"],
        [1, 2.5, {}, []],
    ),
    (
        "any-of-accepting-null-beside-a-one-of-union",
        (
            {
                "anyOf": [{"enum": [None, "a"]}, {"type": "integer"}],
                "oneOf": [{"$ref": "#/$defs/T"}, {"$ref": "#/$defs/S"}, {"type": "null"}],
            },
            {"T": {"allOf": [{"type": "object"}]}, "S": {"type": "string"}},
        ),
        [None, "a"],
        [1, "b", 2.5, {}, []],
    ),
]


@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
@pytest.mark.parametrize(("name", "union", "valid", "invalid"), ROWS, ids=[row[0] for row in ROWS])
def test_nullable_union_accepts_what_the_original_accepts(
    name: str,
    union: tuple[dict[str, Any], dict[str, Any]],
    valid: list[JsonValue],
    invalid: list[JsonValue],
    hoisted: bool,
) -> None:
    # Given: a nullable union with keys beside it, in the position a producer would emit it.
    node, definitions = union
    registry = _registry(node, definitions, hoisted)
    before = copy.deepcopy(registry.get("holder"))

    # When: strict generation passes, so nothing is reported as lost.
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)

    # Then: the document is valid, and both versions accept exactly the same instances.
    validate(spec)
    assert collect_spec_warnings(spec, registry) == ()
    schema = (
        {"$ref": "#/components/schemas/Holder"}
        if hoisted
        else spec["paths"]["/api/holder"]["post"]["requestBody"]["content"]["application/json"][
            "schema"
        ]
    )
    original = OAS31Validator({**node, "$defs": definitions})
    converted = OAS30Validator({**schema, "components": spec["components"]})
    assert all(original.is_valid(instance) for instance in valid)
    assert not any(original.is_valid(instance) for instance in invalid)
    assert [converted.is_valid(instance) for instance in PROBES] == [
        original.is_valid(instance) for instance in PROBES
    ]
    assert registry.get("holder") == before


def test_field_level_keys_win_over_the_referenced_schemas_annotations() -> None:
    # Given: both the referenced schema and the field describe themselves.
    definitions = {
        "T": {"type": "object", "description": "model", "title": "T", "x-ext": 1, "x-model": True}
    }
    node = {
        "description": "field",
        "title": "Field",
        "x-ext": 2,
        "anyOf": [T_REF, {"type": "null"}],
    }
    registry = _registry(node, definitions, hoisted=True)

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)

    # Then: the field's value wins a conflict, and what only the model declares is kept.
    assert spec["components"]["schemas"]["Holder"] == {
        "type": "object",
        "description": "field",
        "title": "Field",
        "x-ext": 2,
        "x-model": True,
        "nullable": True,
    }


@pytest.mark.parametrize("version", ["3.1.0", "3.2.0"])
def test_nullable_union_is_untouched_for_3_1_and_3_2(version: str) -> None:
    # Given
    node = {"allOf": [{"minProperties": 1}], "anyOf": [T_REF, {"type": "null"}]}
    registry = _registry(node, {"T": {"allOf": [{"type": "object"}]}}, hoisted=True)

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version=version, strict=True)

    # Then
    assert spec["components"]["schemas"]["Holder"] == {
        "allOf": [{"minProperties": 1}],
        "anyOf": [{"$ref": "#/components/schemas/T"}, {"type": "null"}],
    }
    assert collect_spec_warnings(spec, registry) == ()


class Address(BaseModel):
    """A postal address."""

    city: str


class AddressAlias(RootModel[Address]):
    """An alias of a model."""


class Account(BaseModel):
    home: Address | None = Field(default=None, description="Where the account holder lives")


class AliasedAccount(BaseModel):
    home: AddressAlias | None = Field(default=None, description="Where the account holder lives")


@pytest.mark.parametrize("version", ["3.0.0", "3.1.0"])
def test_field_description_replaces_the_models_docstring(version: str) -> None:
    # Given: ``Optional[Model]`` with a description on the field.
    registry = OpenAPIRegistry()
    register_openapi_metadata("/account", "POST", request_model=Account, registry=registry)

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version=version, strict=True)

    # Then: every version shows the field's description rather than ``Address``'s docstring.
    home = spec["components"]["schemas"]["Account"]["properties"]["home"]
    assert home["description"] == "Where the account holder lives"
    if version == "3.0.0":
        assert home["nullable"] is True
        assert home["type"] == "object"
    validate(spec)
    assert collect_spec_warnings(spec, registry) == ()


def test_nullable_reference_to_a_model_alias_accepts_null_and_enforces_the_model() -> None:
    # Given: Pydantic emits a ``RootModel`` alias as a component that is itself a ``$ref``.
    registry = OpenAPIRegistry()
    register_openapi_metadata("/account", "POST", request_model=AliasedAccount, registry=registry)

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)

    # Then: the 3.0 field accepts what the producer's own schema accepts.
    validate(spec)
    original = OAS31Validator(AliasedAccount.model_json_schema())
    converted = OAS30Validator(
        {"$ref": "#/components/schemas/AliasedAccount", "components": spec["components"]}
    )
    probes: list[JsonValue] = [
        {},
        {"home": None},
        {"home": {"city": "Seoul"}},
        {"home": {}},
        {"home": "Seoul"},
        {"home": 1},
    ]
    expected = [True, True, True, False, False, False]
    assert [original.is_valid(probe) for probe in probes] == expected
    assert [converted.is_valid(probe) for probe in probes] == expected
    home = spec["components"]["schemas"]["AliasedAccount"]["properties"]["home"]
    assert home["description"] == "Where the account holder lives"
    assert collect_spec_warnings(spec, registry) == ()


class Cat(BaseModel):
    kind: Literal["cat"]
    lives: int = 9


class Dog(BaseModel):
    kind: Literal["dog"]
    good: bool = True


Pet = Annotated[Cat | Dog, Field(discriminator="kind")]


class PetAlias(RootModel[Pet]):
    """A pet, as a model of its own."""


class Owner(BaseModel):
    pet: Pet | None = None


class AliasedOwner(BaseModel):
    pet: PetAlias | None = None


@pytest.mark.parametrize("model", [Owner, AliasedOwner])
def test_optional_discriminated_union_accepts_null(model: type[BaseModel]) -> None:
    # Given: an optional discriminated union, inline and as a ``RootModel`` alias.
    registry = OpenAPIRegistry()
    register_openapi_metadata("/owner", "POST", request_model=model, registry=registry)

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)

    # Then: null is valid, the discriminated branches are still enforced, nothing is lost.
    validate(spec)
    original = OAS31Validator(model.model_json_schema())
    converted = OAS30Validator(
        {"$ref": f"#/components/schemas/{model.__name__}", "components": spec["components"]}
    )
    probes: list[JsonValue] = [
        {},
        {"pet": None},
        {"pet": {"kind": "cat"}},
        {"pet": {"kind": "dog", "good": False}},
        {"pet": {"kind": "fish"}},
        {"pet": {"kind": "cat", "lives": "nine"}},
        {"pet": "cat"},
    ]
    expected = [True, True, True, True, False, False, False]
    assert [original.is_valid(probe) for probe in probes] == expected
    assert [converted.is_valid(probe) for probe in probes] == expected
    assert collect_spec_warnings(spec, registry) == ()


def test_unresolvable_reference_keeps_the_surrounding_all_of() -> None:
    # Given: a nullable union whose reference cannot be resolved, beside an ``allOf`` of its own.
    registry = _registry(
        {
            "allOf": [{"minProperties": 1}],
            "anyOf": [{"$ref": "#/components/schemas/Missing"}, {"type": "null"}],
        },
        {},
        hoisted=True,
    )

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0")

    # Then: the reference stays, null gets its own branch, and the constraint beside it stays.
    assert spec["components"]["schemas"]["Holder"] == {
        "allOf": [{"minProperties": 1}],
        "anyOf": [{"$ref": "#/components/schemas/Missing"}, {"nullable": True, "enum": [None]}],
    }


def test_no_null_branch_is_added_when_the_original_rejects_null() -> None:
    # Given: a ``type`` beside the union rules ``null`` out in the original.
    node = {"type": "object", "anyOf": [T_REF, {"type": "null"}]}
    registry = _registry(node, {"T": {"type": "object"}}, hoisted=True)

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)

    # Then: the union keeps its member and does not advertise a null it would reject.
    assert spec["components"]["schemas"]["Holder"] == {
        "type": "object",
        "anyOf": [{"$ref": "#/components/schemas/T"}],
    }


def test_union_of_unresolvable_references_gets_a_null_branch() -> None:
    # Given: references that cannot be resolved, so ``nullable`` cannot be placed on a branch.
    node = {
        "anyOf": [
            {"$ref": "#/components/schemas/A"},
            {"$ref": "#/components/schemas/B"},
            {"type": "null"},
        ]
    }

    # When
    converted = _convert_schema_to_3_0(node, schemas=None)

    # Then
    assert {"nullable": True, "enum": [None]} in converted["anyOf"]


def test_unresolvable_reference_beside_the_union_does_not_reject_null() -> None:
    # Given: a conjunct beside the union that refers to a missing component.
    node = {
        "allOf": [{"$ref": "#/components/schemas/Missing"}],
        "anyOf": [{"$ref": "#/components/schemas/A"}, {"type": "null"}],
    }

    # When
    converted = _convert_schema_to_3_0(node, schemas={})

    # Then: the original is assumed to accept null, so the union keeps its null branch.
    assert {"nullable": True, "enum": [None]} in converted["anyOf"]


COMPONENTS = "#/components/schemas/"
REFERENCED = {
    "Accepts": {"type": ["string", "null"]},
    "Rejects": {"type": "string"},
    "Cycle": {"allOf": [{"$ref": COMPONENTS + "Cycle"}]},
}


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        (True, True),
        (False, False),
        ({}, True),
        ({"type": "string"}, False),
        ({"type": "null"}, True),
        ({"type": ["string", "null"]}, True),
        ({"type": "string", "nullable": True}, True),
        ({"type": "string", "nullable": False}, False),
        ({"enum": ["a"]}, False),
        ({"enum": ["a", None]}, True),
        ({"const": "a"}, False),
        ({"const": None}, True),
        ({"allOf": [{"type": "null"}, {"type": "string"}]}, False),
        ({"allOf": [{"type": ["string", "null"]}, {"enum": [None, "a"]}]}, True),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, True),
        ({"anyOf": [{"type": "string"}, {"type": "integer"}]}, False),
        ({"oneOf": [{"type": "null"}, {"type": "string"}]}, True),
        ({"oneOf": [{"type": "null"}, {"enum": [None]}]}, False),
        ({"not": {"type": "null"}}, False),
        ({"not": {"type": "string"}}, True),
    ],
)
def test_null_acceptance_reads_every_keyword_that_can_reject_null(
    schema: Any, expected: bool
) -> None:
    # Given / When / Then
    assert _accepts_null(schema, None, ref_siblings_apply=True, assume_unknown=True) is expected


def test_null_acceptance_follows_references() -> None:
    # Given / When / Then: a resolved reference answers for its target.
    accepts, rejects, cycle = (
        {"$ref": COMPONENTS + name} for name in ("Accepts", "Rejects", "Cycle")
    )
    assert _accepts_null(accepts, REFERENCED, ref_siblings_apply=True, assume_unknown=False)
    assert not _accepts_null(rejects, REFERENCED, ref_siblings_apply=True, assume_unknown=False)
    # A cycle terminates and does not by itself reject null.
    assert _accepts_null(cycle, REFERENCED, ref_siblings_apply=True, assume_unknown=False)


@pytest.mark.parametrize(
    "reference",
    [COMPONENTS + "Missing", "https://example.com/schema.json"],
    ids=["missing", "remote"],
)
def test_unresolvable_reference_answers_with_the_callers_assumption(reference: str) -> None:
    # Given / When / Then
    node = {"$ref": reference}
    assert _accepts_null(node, REFERENCED, ref_siblings_apply=True, assume_unknown=True) is True
    assert _accepts_null(node, REFERENCED, ref_siblings_apply=True, assume_unknown=False) is False


def test_reference_siblings_apply_only_where_the_schema_dialect_reads_them() -> None:
    # Given: a reference that accepts null, with a ``type`` beside it.
    node = {"$ref": COMPONENTS + "Accepts", "type": "string"}

    # When / Then: 2020-12 applies the sibling; 3.0 ignores it.
    assert _accepts_null(node, REFERENCED, ref_siblings_apply=True, assume_unknown=False) is False
    assert _accepts_null(node, REFERENCED, ref_siblings_apply=False, assume_unknown=False) is True


def test_merging_a_wrapper_leaves_nullable_to_the_caller() -> None:
    # Given
    inlined = {"type": "object", "nullable": True}

    # When
    merged = _merge_wrapper_into_inlined(inlined, {"nullable": False, "description": "field"})

    # Then
    assert merged == {"type": "object", "nullable": True, "description": "field"}
