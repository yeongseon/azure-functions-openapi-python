"""Instance contracts for nullable fallback composition and coupled numeric bounds."""

from __future__ import annotations

import json
from typing import Any

from openapi_schema_validator import OAS30Validator, OAS31Validator
from openapi_spec_validator import validate
from pydantic import JsonValue
import pytest

from azure_functions_openapi._schema_version_conversion import (
    _accepts_null,
    _component_name,
    _convert_schema_to_3_0,
    _convert_schema_to_3_1,
    _convert_schemas_to_3_0,
    _keep_null_verdict,
    _merge_wrapper_into_inlined,
    _output_null_verdict,
)
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec

REF: dict[str, Any] = {"$ref": "#/$defs/T"}
PROBES: list[JsonValue] = [
    None,
    "x",
    "a",
    "b",
    "",
    5,
    -1,
    0,
    1,
    2,
    2.5,
    3,
    3.5,
    4,
    True,
    [],
    {},
    {"kind": "Cat"},
    {"kind": "Dog"},
    {"kind": "fish"},
    {"a": 1},
    {"a": 1, "b": 2},
    {"b": "x"},
    {"b": 1},
]
TARGETS_WITH_DISCRIMINATOR: list[tuple[str, dict[str, Any]]] = [
    ("min", {"type": "number", "minimum": 0}),
    ("exclusive", {"type": "number", "exclusiveMinimum": 2}),
    ("max", {"type": "number", "maximum": 10}),
    ("required", {"type": "object", "required": ["a"]}),
    ("enum", {"type": "string", "enum": ["a", "b"]}),
]
FIELD_CONSTRAINTS: list[tuple[str, dict[str, Any]]] = [
    ("min1", {"minimum": 1}),
    ("exclusive1", {"exclusiveMinimum": 1}),
    ("max5", {"maximum": 5}),
    ("required-b", {"required": ["b"]}),
    ("enum-a", {"enum": ["a", 3]}),
    ("all-of", {"allOf": [{"minimum": 3}]}),
]
OBJECT_SCOPE_ROWS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    (
        "both-declare-and-conflict",
        {"properties": {"a": {}}, "additionalProperties": {"type": "string"}},
        {"properties": {"a": {}}, "additionalProperties": False},
    ),
    ("wrapper-closed", {"additionalProperties": False}, {"properties": {"a": {}}}),
    ("target-closed", {"properties": {"a": {}}}, {"additionalProperties": False}),
    (
        "different-properties",
        {"properties": {"b": {"type": "integer"}}, "additionalProperties": {"type": "string"}},
        {"properties": {"a": {}}, "additionalProperties": False},
    ),
    (
        "identical",
        {"properties": {"a": {}}, "additionalProperties": False},
        {"properties": {"a": {}}, "additionalProperties": False},
    ),
    ("no-overlap", {"properties": {"a": {}}, "additionalProperties": False}, {"required": ["a"]}),
]
DISCRIMINATOR = {"propertyName": "kind"}
NULL_MEMBERS: list[tuple[str, dict[str, Any]]] = [
    ("plain", {"type": "null"}),
    ("rejecting", {"type": "null", "not": {}}),
    ("enum-without-null", {"type": "null", "enum": ["x"]}),
    ("const", {"type": "null", "const": 1}),
    ("all-of-string", {"type": "null", "allOf": [{"type": "string"}]}),
    ("discriminated", {"type": "null", "allOf": [{}], "discriminator": DISCRIMINATOR}),
    ("reference", {"type": "null", "$ref": "#/$defs/S"}),
]
RETAINED_MEMBERS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("reference-sibling", {**REF, "description": "member"}, {"T": {"allOf": [{"type": "string"}]}}),
    ("inline", {"type": "string"}, {}),
    ("accepting-reference", REF, {"T": {"type": ["string", "null"]}}),
]
NULL_MEMBER_DEFINITIONS: dict[str, Any] = {"S": {"type": "string"}}
TARGETS_ACCEPTING_NULL_WITH_DISCRIMINATOR: list[tuple[str, dict[str, Any]]] = [
    ("all-of", {"allOf": [{"enum": [None]}], "discriminator": DISCRIMINATOR}),
    (
        "one-of",
        {"oneOf": [{"$ref": "#/$defs/Cat"}, {"type": "null"}], "discriminator": DISCRIMINATOR},
    ),
    (
        "any-of",
        {"anyOf": [{"type": "string"}, {"type": "null"}], "discriminator": DISCRIMINATOR},
    ),
]
CAT: dict[str, Any] = {
    "type": "object",
    "properties": {"kind": {"const": "Cat"}},
    "required": ["kind"],
}
CASES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    (
        "member-conflicting-allof",
        {"anyOf": [{**REF, "allOf": [{"type": "string"}]}, {"type": "null"}]},
        {"T": {"type": "object"}},
    ),
    (
        "member-compatible-allof",
        {"anyOf": [{**REF, "allOf": [{"minProperties": 1}]}, {"type": "null"}]},
        {"T": {"type": "object"}},
    ),
    (
        "alias-discriminator",
        {"discriminator": {"propertyName": "kind"}, "anyOf": [REF, {"type": "null"}]},
        {"T": {"$ref": "#/$defs/U"}, "U": {"type": "object"}},
    ),
    *[
        (
            f"bounds-{position}-{lower}-{target_exclusive}-{wrapper_exclusive}",
            {
                **(wrapper if position == "node" else {}),
                "anyOf": [{**REF, **(wrapper if position == "member" else {})}, {"type": "null"}],
            },
            {"T": {"type": "number", **target}},
        )
        for position in ("node", "member")
        for lower in (True, False)
        for target_exclusive in (True, False)
        for wrapper_exclusive in (True, False)
        for target, wrapper in [
            (
                {
                    ("exclusiveMinimum" if target_exclusive else "minimum")
                    if lower
                    else ("exclusiveMaximum" if target_exclusive else "maximum"): 2 if lower else 3
                },
                {
                    ("exclusiveMinimum" if wrapper_exclusive else "minimum")
                    if lower
                    else ("exclusiveMaximum" if wrapper_exclusive else "maximum"): 3 if lower else 2
                },
            )
        ]
    ],
    *[
        (
            f"single-discriminator-{name}",
            {"discriminator": {"propertyName": "kind"}, "anyOf": [member, {"type": "null"}]},
            {"T": target},
        )
        for name, member, target in [
            ("bare", REF, {"type": "object"}),
            ("inline", {"type": "object"}, {}),
            ("not", REF, {"not": {"type": "string"}}),
        ]
    ],
    *[
        (f"oneof-collision-{name}", {"oneOf": [{"not": {"type": "string"}}, sentinel]}, {})
        for name, sentinel in [
            ("type", {"type": "null"}),
            ("const", {"const": None}),
            ("enum", {"enum": [None]}),
        ]
    ],
    (
        "oneof-keys-reject-null",
        {"type": "object", "oneOf": [{"not": {"type": "string"}}, {"type": "null"}]},
        {},
    ),
    (
        "both-unions",
        {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "oneOf": [{"not": {"type": "string"}}, {"type": "null"}],
        },
        {},
    ),
    (
        "multi-ref-siblings",
        {"anyOf": [{**REF, "allOf": [{"type": "string"}]}, {"type": "integer"}, {"type": "null"}]},
        {"T": {"type": "object"}},
    ),
    ("null-collision-ref", {"oneOf": [REF, {"type": "null"}]}, {"T": {"enum": [None, "x"]}}),
    (
        "multi-ref-sibling-bound",
        {"anyOf": [{**REF, "minimum": 3}, {"type": "string"}, {"type": "null"}]},
        {"T": {"type": "number", "exclusiveMinimum": 2}},
    ),
    (
        "zero-discriminator",
        {"discriminator": {"propertyName": "kind"}, "allOf": [{}], "anyOf": [{"type": "null"}]},
        {},
    ),
    *[
        (
            f"target-discriminator-{target_name}-{wrap_name}-{key}",
            {**wrap, key: [REF, {"type": "null"}]},
            {"T": {**target, "discriminator": {"propertyName": "kind"}}},
        )
        for key in ("anyOf", "oneOf")
        for target_name, target in TARGETS_WITH_DISCRIMINATOR
        for wrap_name, wrap in FIELD_CONSTRAINTS
    ],
    *[
        (
            f"discriminator-collision-ruled-out-{key}",
            {
                "type": "object",
                "discriminator": {"propertyName": "kind"},
                key: [{"$ref": "#/$defs/T"}, {"$ref": "#/$defs/U"}, {"type": "null"}],
            },
            {"T": {"enum": [None, "a"]}, "U": {"type": "object"}},
        )
        for key in ("oneOf", "anyOf")
    ],
    *[
        (
            f"single-discriminator-null-ruled-out-{key}",
            {
                "type": "object",
                "discriminator": {"propertyName": "kind"},
                key: [REF, {"type": "null"}],
            },
            {"T": {"type": "object"}},
        )
        for key in ("anyOf", "oneOf")
    ],
    *[
        (
            f"member-discriminator-{key}-{shape}",
            {key: [*members, {"type": "null"}]},
            {"T": {"type": "object"}, "S": {"type": "string"}},
        )
        for key in ("anyOf", "oneOf")
        for shape, members in [
            (
                "sole",
                [{**REF, "discriminator": {"propertyName": "kind"}}],
            ),
            (
                "mixed",
                [
                    {**REF, "discriminator": {"propertyName": "kind"}},
                    {"$ref": "#/$defs/S"},
                ],
            ),
            (
                "two",
                [
                    {**REF, "discriminator": {"propertyName": "kind"}},
                    {"$ref": "#/$defs/T", "discriminator": {"propertyName": "kind"}},
                ],
            ),
        ]
    ],
    *[
        (
            f"null-member-{key}-{retained_name}-{null_name}-{count}",
            {key: [retained, *([null_member] * count)]},
            {**NULL_MEMBER_DEFINITIONS, **definitions},
        )
        for key in ("anyOf", "oneOf")
        for retained_name, retained, definitions in RETAINED_MEMBERS
        for null_name, null_member in NULL_MEMBERS
        for count in (1, 2, 3)
    ],
    *[
        (
            f"null-member-{key}-mixed-{first_name}-{second_name}",
            {key: [{**REF, "description": "member"}, first, second]},
            {"T": {"allOf": [{"type": "string"}]}},
        )
        for key in ("anyOf", "oneOf")
        for first_name, first in NULL_MEMBERS[:3]
        for second_name, second in NULL_MEMBERS[:3]
    ],
    *[
        (
            f"null-only-{key}-{name}",
            {key: members},
            {},
        )
        for key in ("anyOf", "oneOf")
        for name, members in [
            ("single", [{"type": "null"}]),
            ("two", [{"type": "null"}, {"type": "null"}]),
            ("three", [{"type": "null"}, {"type": "null"}, {"type": "null"}]),
            ("rejecting", [{"type": "null", "not": {}}]),
            ("mixed", [{"type": "null"}, {"type": "null", "enum": ["x"]}]),
            ("rejecting-pair", [{"type": "null", "not": {}}, {"type": "null", "not": {}}]),
        ]
    ],
    *[
        (
            f"null-only-rest-rejects-null-{key}",
            {"type": "object", key: [{"type": "null"}, {"type": "null"}]},
            {},
        )
        for key in ("anyOf", "oneOf")
    ],
    *[
        (
            f"accepting-target-discriminator-{key}-{target_name}-{member_name}",
            {key: [member, {"type": "null"}]},
            {"T": target, **({"Cat": CAT} if target_name == "one-of" else {})},
        )
        for key in ("anyOf", "oneOf")
        for target_name, target in TARGETS_ACCEPTING_NULL_WITH_DISCRIMINATOR
        for member_name, member in [("bare", REF), ("sibling", {**REF, "description": "member"})]
    ],
    *[
        (
            f"inline-discriminator-accepting-{key}",
            {
                key: [
                    {"allOf": [{"enum": [None]}], "discriminator": DISCRIMINATOR},
                    {"type": "null"},
                ]
            },
            {},
        )
        for key in ("anyOf", "oneOf")
    ],
    *[
        (
            f"scoped-nulls-{key}-{count}",
            {
                "discriminator": DISCRIMINATOR,
                key: [
                    {"$ref": "#/$defs/Cat"},
                    {"$ref": "#/$defs/Dog"},
                    *([{"type": "null"}] * count),
                ],
            },
            {
                "Cat": CAT,
                "Dog": {**CAT, "properties": {"kind": {"const": "Dog"}}},
            },
        )
        for key in ("anyOf", "oneOf")
        for count in (1, 2, 3)
    ],
    *[
        (
            f"nested-nullable-sole-member-{key}-{inner_key}",
            {key: [{inner_key: [{}, {"type": "null"}]}, {"type": "null"}]},
            {},
        )
        for key in ("anyOf", "oneOf")
        for inner_key in ("anyOf", "oneOf")
    ],
    *[
        (
            f"nested-nullable-beside-type-{name}",
            {
                "type": "object",
                "anyOf": [{"discriminator": DISCRIMINATOR, "oneOf": inner}, {"type": "null"}],
            },
            {"ALLNULL": {"allOf": [{"enum": [None]}]}},
        )
        for name, inner in [
            (
                "plain",
                [{"oneOf": [{"type": "null"}]}, {"anyOf": [{"type": "string"}], "type": "null"}],
            ),
            (
                "reference",
                [{"oneOf": [{"$ref": "#/$defs/ALLNULL"}, {"type": "null"}]}, {"type": "null"}],
            ),
        ]
    ],
    *[
        (
            f"nested-null-member-with-discriminator-{key}-{inner_key}-{combinator}",
            {
                key: [
                    {
                        inner_key: [
                            {combinator: [{}], "discriminator": DISCRIMINATOR, "type": "null"}
                        ]
                    },
                    {"type": "null"},
                ]
            },
            {},
        )
        for key in ("anyOf", "oneOf")
        for inner_key in ("anyOf", "oneOf")
        for combinator in ("allOf", "anyOf", "oneOf")
    ],
    *[
        (
            f"unresolved-pointer-{key}-{name}",
            {**beside, key: members},
            {"Meta": {"type": "object", "properties": {"name": {"type": "string"}}}},
        )
        for key in ("anyOf", "oneOf")
        for name, beside, members in [
            (
                "under-not",
                {"not": {"$ref": "#/$defs/Meta/properties/name"}},
                [{"type": "integer"}, {"type": "null"}],
            ),
            ("as-member", {}, [{"$ref": "#/$defs/Meta/properties/name"}, {"type": "null"}]),
            (
                "member-with-sibling",
                {},
                [
                    {"$ref": "#/$defs/Meta/properties/name", "description": "member"},
                    {"type": "null"},
                ],
            ),
        ]
    ],
    *[
        (
            f"object-scope-{key}-{name}",
            {**wrapper, key: [REF, {"type": "null"}]},
            {"T": {"type": "object", **target}},
        )
        for key in ("anyOf", "oneOf")
        for name, wrapper, target in OBJECT_SCOPE_ROWS
    ],
    *[
        (f"merged-up-const-{key}-{name}", {key: [member, {"type": "null"}]}, {})
        for key in ("anyOf", "oneOf")
        for name, member in [
            ("null", {"const": None}),
            ("string", {"const": "a", "type": "string"}),
            ("bare", {"const": "a"}),
        ]
    ],
    *[
        (
            f"merged-up-not-{key}",
            {"not": {"type": "string"}, key: [{"not": {}}, {"type": "null"}]},
            {},
        )
        for key in ("anyOf", "oneOf")
    ],
    (
        "discriminator-collision-restored-member",
        {
            "discriminator": DISCRIMINATOR,
            "oneOf": [
                {"allOf": [{"$ref": "#/$defs/U", "type": "string"}]},
                {"$ref": "#/$defs/Cat"},
                {"type": "null"},
            ],
        },
        {"U": {}, "Cat": CAT},
    ),
    *[
        (
            f"discriminator-collision-{key}-{accepting}-{mapping}",
            {
                "discriminator": {
                    "propertyName": "kind",
                    **({"mapping": {"A": "#/$defs/A"}} if mapping else {}),
                },
                key: [
                    *({"$ref": f"#/$defs/{name}"} for name in members),
                    {"type": "null"},
                ],
            },
            {
                "A": {"enum": [None, "a"]},
                "B": {"type": ["object", "null"]},
                "S": {"type": "string"},
                "O": {"type": "object"},
            },
        )
        for key in ("oneOf", "anyOf")
        for accepting, members in [
            ("one", ("A", "S")),
            ("two", ("A", "B")),
            ("all", ("A", "B", "S")),
        ]
        for mapping in (False, True)
    ],
    *[
        (
            f"discriminator-{key}-{mapping}-{rejects_null}-{existing}",
            {
                **({"type": "object"} if rejects_null else {}),
                **(
                    {"anyOf": [{"minProperties": 1}], "allOf": [{"maxProperties": 2}]}
                    if existing
                    else {}
                ),
                "discriminator": {
                    "propertyName": "kind",
                    **(
                        {"mapping": {"Cat": "#/$defs/Cat", "Dog": "#/$defs/Dog"}} if mapping else {}
                    ),
                },
                key: [{"$ref": "#/$defs/Cat"}, {"$ref": "#/$defs/Dog"}, {"type": "null"}],
            },
            {
                name: {
                    "type": "object",
                    "properties": {"kind": {"const": name}},
                    "required": ["kind"],
                }
                for name in ("Cat", "Dog")
            },
        )
        for key in ("oneOf", "anyOf")
        for mapping in (False, True)
        for rejects_null in (False, True)
        for existing in ((False, True) if key == "oneOf" else (False,))
    ],
]


@pytest.mark.parametrize("hoisted", [False, True], ids=["inline", "component"])
@pytest.mark.parametrize(("name", "node", "definitions"), CASES, ids=[row[0] for row in CASES])
def test_nullable_fallback_preserves_instance_acceptance(
    name: str, node: dict[str, Any], definitions: dict[str, Any], hoisted: bool
) -> None:
    # Given: producer schemas with ref siblings or constraints beside a nullable union.
    registry = OpenAPIRegistry()
    body = (
        {"$ref": "#/$defs/Holder", "$defs": {"Holder": node, **definitions}}
        if hoisted
        else {**node, "$defs": definitions}
    )
    registry.set("holder", {"route": "holder", "method": "post", "request_body": body})

    # When: strict generation must not silently change the set of valid instances.
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0", strict=True)

    # Then: both instance validators agree and the resulting document is valid.
    validate(spec)
    schema: dict[str, Any] = (
        {"$ref": "#/components/schemas/Holder"}
        if hoisted
        else spec["paths"]["/api/holder"]["post"]["requestBody"]["content"]["application/json"][
            "schema"
        ]
    )
    original = OAS31Validator({**node, "$defs": definitions})
    converted = OAS30Validator({**schema, "components": spec.get("components", {})})
    assert [converted.is_valid(p) for p in PROBES] == [original.is_valid(p) for p in PROBES]
    assert collect_spec_warnings(spec, registry) == ()
    if name.startswith("multi-ref-"):
        root = spec["components"]["schemas"]["Holder"] if hoisted else schema
        assert root["anyOf"][0]["allOf"][0] == {"$ref": "#/components/schemas/T"}
    if name.startswith(("member-discriminator-", "discriminator-collision-")):
        assert "discriminator" not in str(spec["paths"]) + str(spec.get("components", {}))
    if name.startswith("target-discriminator-"):
        components = spec.get("components", {}).get("schemas", {})
        holder = components["Holder"] if hoisted else schema
        assert "allOf" not in holder or "discriminator" not in holder
    if name.startswith("discriminator-") and not name.startswith("discriminator-collision-"):
        root = spec["components"]["schemas"]["Holder"] if hoisted else schema
        polymorphism = root if "discriminator" in root else root[name.split("-")[1]][0]
        assert polymorphism["discriminator"]["propertyName"] == "kind"
    if name.startswith("scoped-nulls-"):
        root = spec["components"]["schemas"]["Holder"] if hoisted else schema
        key = name.split("-")[2]
        assert root[key][0]["discriminator"]["propertyName"] == "kind"
        assert len(root[key]) == 1 + int(name.rsplit("-", 1)[1])


def test_reference_target_uses_original_dialect_even_from_candidate() -> None:
    # Given: a target whose reference accepts null but whose own sibling rejects it.
    schemas = {"T": {"$ref": "#/components/schemas/U", "type": "string"}, "U": {"enum": [None]}}
    node = {"$ref": "#/components/schemas/T"}

    # When
    accepts = _accepts_null(node, schemas, ref_siblings_apply=False, assume_unknown=False)

    # Then: candidate references still resolve against the unconverted component map, where the
    # keys beside a reference apply.
    assert accepts is False


def test_anyof_is_collapsed_before_oneof_without_changing_acceptance() -> None:
    # Given: both unions can supply the type placed beside nullable.
    node = {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "oneOf": [{"type": "object"}, {"type": "null"}],
    }

    # When
    converted = _convert_schema_to_3_0(node)

    # Then: preserve canonical ordering as well as the intersection's instance meaning.
    assert converted["type"] == "string"
    assert [OAS30Validator(converted).is_valid(p) for p in PROBES] == [
        OAS31Validator(node).is_valid(p) for p in PROBES
    ]
    validate(
        {
            "openapi": "3.0.0",
            "info": {"title": "order", "version": "1"},
            "paths": {},
            "components": {"schemas": {"Ordered": converted}},
        }
    )


@pytest.mark.parametrize("shape", ["sole", "multi"])
def test_reference_with_siblings_is_not_expanded_for_the_nullable_idiom(shape: str) -> None:
    # Given: a sibling-bearing reference to a component that carries a dropped keyword.
    member = {"$ref": "#/components/schemas/T", "minimum": 3}
    members = [member] if shape == "sole" else [member, {"type": "string"}]
    node = {"anyOf": [*members, {"type": "null"}]}
    schemas = {"T": {"type": "number", "contains": {"type": "integer"}}}
    losses: list[str] = []

    # When
    converted = _convert_schema_to_3_0(node, schemas, lossy=losses)

    # Then: the reference stays a reference, and the component's own loss is not reported again.
    assert converted["anyOf"][0]["allOf"][0] == {"$ref": "#/components/schemas/T"}
    assert losses == []


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"oneOf": [{"enum": [None, "a"]}, {"type": "string"}], "nullable": True}, True),
        (
            {
                "oneOf": [{"enum": [None, "a"]}, {"type": "string"}],
                "discriminator": {"propertyName": "kind"},
                "nullable": True,
            },
            False,
        ),
        ({"allOf": [{"minimum": 1}], "discriminator": {"propertyName": "kind"}}, False),
        ({"type": "number", "discriminator": {"propertyName": "kind"}, "nullable": True}, True),
    ],
    ids=["union", "union-with-discriminator", "all-of-with-discriminator", "discriminator-alone"],
)
def test_candidate_with_an_active_discriminator_rejects_null(schema: Any, expected: bool) -> None:
    # Given / When / Then: 3.0 validators reject null where a discriminator is active.
    assert _accepts_null(schema, None, ref_siblings_apply=False, assume_unknown=False) is expected
    assert _accepts_null(
        {k: v for k, v in schema.items() if k != "discriminator"},
        None,
        ref_siblings_apply=False,
        assume_unknown=False,
    ) is (expected or "discriminator" in schema)


def test_a_discriminator_in_a_reference_target_is_enforced_in_the_3_0_reading() -> None:
    # Given: a component that accepts null in 2020-12 but carries a discriminator beside an allOf,
    # and a second component that reaches it through its own allOf.
    schemas = {
        "T": {"allOf": [{"enum": [None]}], "discriminator": DISCRIMINATOR},
        "Chain": {"allOf": [{"$ref": "#/components/schemas/T"}]},
    }
    for name in ("T", "Chain"):
        node = {"$ref": f"#/components/schemas/{name}"}

        # When / Then: the original reading ignores the discriminator, and the 3.0 reading
        # enforces it inside the target and through nested members.
        assert _accepts_null(node, schemas, ref_siblings_apply=True, assume_unknown=False)
        assert not _accepts_null(node, schemas, ref_siblings_apply=False, assume_unknown=False)


@pytest.mark.parametrize("key", ["anyOf", "oneOf"])
def test_a_nullable_union_below_the_schema_is_read_as_the_original_in_both_readings(
    key: str,
) -> None:
    # Given: a target that is itself a nullable union with a discriminator beside it, which
    # conversion rewrites so that it still accepts null, and the same union without the null member.
    cat = {"$ref": "#/components/schemas/Cat"}
    schemas = {
        "WithNull": {key: [cat, {"type": "null"}], "discriminator": DISCRIMINATOR},
        "Without": {key: [cat, {"type": "string"}], "discriminator": DISCRIMINATOR},
        "Cat": {"type": "object"},
    }

    # When / Then: the nullable union answers as the original does in the 3.0 reading, while the
    # one without a null member is read as the document will be and rejects null.
    with_null = {"$ref": "#/components/schemas/WithNull"}
    without = {"$ref": "#/components/schemas/Without"}
    assert _accepts_null(with_null, schemas, ref_siblings_apply=False, assume_unknown=False)
    assert not _accepts_null(without, schemas, ref_siblings_apply=False, assume_unknown=False)
    assert _accepts_null(with_null, schemas, ref_siblings_apply=True, assume_unknown=False)
    assert not _accepts_null(without, schemas, ref_siblings_apply=True, assume_unknown=False)


def test_a_branch_that_answers_null_differently_in_3_0_gets_its_answer_back() -> None:
    # Given: components whose 3.0 reading of null differs from their 2020-12 reading, in both
    # directions: a discriminator that rejects null, and a nested reference whose sibling type
    # (which rejects null) 3.0 ignores.
    schemas = {
        "Accepting": {"allOf": [{"enum": [None]}], "discriminator": DISCRIMINATOR},
        "Open": {},
        "Plain": {"type": "string"},
    }
    accepting = {"$ref": "#/components/schemas/Accepting"}
    sibling = {"allOf": [{"$ref": "#/components/schemas/Open", "type": "string"}]}
    null_only = {"nullable": True, "enum": [None]}

    # When / Then: a branch that accepted null and now rejects it is joined with the null schema,
    # one that rejected it and now accepts it is kept from it, and an unchanged one is returned
    # as it is.
    assert _keep_null_verdict(accepting, accepting, schemas) == {"anyOf": [accepting, null_only]}
    assert _keep_null_verdict(sibling, sibling, schemas) == {"allOf": [sibling, {"not": null_only}]}
    plain = {"$ref": "#/components/schemas/Plain"}
    assert _keep_null_verdict(plain, plain, schemas) is plain


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("#/components/schemas/X", "X"),
        ("#/components/schemas/X/properties/name", None),
        ("#/components/schemas/", None),
        ("#/$defs/X", None),
        ("https://example.com/schemas/x.json", None),
        ("urn:uuid:1234567890abcdef1234567890", None),
    ],
)
def test_only_an_exact_component_reference_names_a_component(
    ref: str, expected: str | None
) -> None:
    # Given / When / Then: a pointer into a component or an external reference names none.
    assert _component_name(ref) == expected


def test_a_pointer_into_a_component_does_not_resolve_to_a_component_of_its_last_segment() -> None:
    # Given: a pointer into Meta, and an unrelated component that happens to be called ``name``.
    schemas = {
        "name": {"type": "integer"},
        "Meta": {"type": "object", "properties": {"name": {"type": "string"}}},
    }
    pointer = "#/components/schemas/Meta/properties/name"

    # When
    converted = _convert_schema_to_3_0({"anyOf": [{"$ref": pointer}, {"type": "null"}]}, schemas)
    unresolved: set[str] = set()
    accepts = _accepts_null(
        {"$ref": pointer},
        schemas,
        ref_siblings_apply=True,
        assume_unknown=False,
        unresolved=unresolved,
    )

    # Then: the unrelated component is neither inlined nor read for the pointer.
    assert converted == {"anyOf": [{"$ref": pointer}, {"nullable": True, "enum": [None]}]}
    assert accepts is False
    assert unresolved == {pointer}


def test_every_reference_that_cannot_be_resolved_is_reported_to_the_caller() -> None:
    # Given: a node that reaches a missing component, a pointer, an external reference, a
    # resolvable one and a cycle.
    schemas = {
        "Known": {"type": "string"},
        "Loop": {"anyOf": [{"$ref": "#/components/schemas/Loop"}]},
    }
    refs = [
        "#/components/schemas/Missing",
        "#/components/schemas/Known/type",
        "https://example.com/x.json",
    ]
    node = {
        "allOf": [
            *({"$ref": ref} for ref in refs),
            {"$ref": "#/components/schemas/Known"},
            {"$ref": "#/components/schemas/Loop"},
        ]
    }
    unresolved: set[str] = set()

    # When
    _accepts_null(
        node, schemas, ref_siblings_apply=True, assume_unknown=True, unresolved=unresolved
    )

    # Then: only the ones that could not be resolved are listed.
    assert unresolved == set(refs)


def test_a_reference_that_cannot_be_resolved_below_a_nullable_union_is_reported_too() -> None:
    # Given: an unresolvable reference inside a nullable union that sits below the schema.
    gone = "#/components/schemas/Gone"
    node = {"allOf": [{"anyOf": [{"$ref": gone}, {"type": "null"}]}]}
    unresolved: set[str] = set()

    # When: the converted document is read, where such a union is read as the original.
    _accepts_null(node, {}, ref_siblings_apply=False, assume_unknown=True, unresolved=unresolved)

    # Then
    assert unresolved == {gone}


@pytest.mark.parametrize("key", ["anyOf", "oneOf"])
def test_a_rejection_that_rests_on_an_unresolved_reference_keeps_the_null_branch(key: str) -> None:
    # Given: a ``not`` over a reference that cannot be resolved, beside a nullable union.
    node = {
        "not": {"$ref": "#/components/schemas/Gone"},
        key: [{"type": "integer"}, {"type": "null"}],
    }

    # When
    converted = _convert_schema_to_3_0(node, {})

    # Then: assuming the reference accepts null would make ``not`` reject it, which is no proof.
    assert converted == {
        "not": {"$ref": "#/components/schemas/Gone"},
        key: [{"type": "integer"}, {"nullable": True, "enum": [None]}],
    }


def test_a_rejection_that_does_not_depend_on_an_unresolved_reference_still_drops_the_branch() -> (
    None
):
    # Given: a type that rejects null, beside a ``not`` over a reference that cannot be resolved.
    node = {
        "type": "object",
        "not": {"$ref": "#/components/schemas/Gone"},
        "anyOf": [{"$ref": "#/components/schemas/T", "description": "member"}, {"type": "null"}],
    }

    # When
    converted = _convert_schema_to_3_0(node, {"T": {"type": "object"}})

    # Then: the type alone proves the rejection, so the null branch is left out.
    assert converted["anyOf"] == [
        {"description": "member", "allOf": [{"$ref": "#/components/schemas/T"}]}
    ]


def test_object_keys_of_a_field_stay_with_the_properties_they_were_written_beside() -> None:
    # Given: an inlined closed schema and a field that declares the same properties and an open one.
    inlined = {"type": "object", "properties": {"a": {}}, "additionalProperties": False}
    wrapper = {
        "properties": {"a": {}},
        "additionalProperties": {"type": "string"},
        "nullable": True,
    }

    # When
    merged = _merge_wrapper_into_inlined(inlined, wrapper)

    # Then: the field's additionalProperties keeps its properties in one conjunct, so ``a`` is
    # not an additional property there.
    assert merged == {
        **inlined,
        "allOf": [{"properties": {"a": {}}, "additionalProperties": {"type": "string"}}],
    }


def test_object_keys_that_both_sides_declare_alike_are_not_repeated() -> None:
    # Given / When
    inlined = {"type": "object", "properties": {"a": {}}, "additionalProperties": False}
    merged = _merge_wrapper_into_inlined(
        inlined, {"properties": {"a": {}}, "additionalProperties": False}
    )

    # Then
    assert merged == inlined


@pytest.mark.parametrize(
    ("inlined", "wrapper", "expected_conjunct"),
    [
        (
            {"properties": {"a": {}}},
            {"additionalProperties": False},
            {"additionalProperties": False},
        ),
        ({"additionalProperties": False}, {"properties": {"a": {}}}, {"properties": {"a": {}}}),
    ],
    ids=["wrapper-closed", "target-closed"],
)
def test_one_sided_object_keys_do_not_change_what_the_other_side_declared(
    inlined: dict[str, Any], wrapper: dict[str, Any], expected_conjunct: dict[str, Any]
) -> None:
    # Given / When
    merged = _merge_wrapper_into_inlined({"type": "object", **inlined}, wrapper)

    # Then: the wrapper's keys form their own conjunct instead of joining the other side's.
    assert merged == {"type": "object", **inlined, "allOf": [expected_conjunct]}


def test_the_output_verdict_is_the_one_both_readings_give() -> None:
    # Given: components, one of which a reference's sibling type changes the answer for: the
    # specification ignores that sibling and validators built on JSON Schema apply it.
    schemas = {
        "Open": {},
        "Plain": {"type": "string"},
        "Accepting": {"allOf": [{"enum": [None]}], "discriminator": DISCRIMINATOR},
    }
    sibling = {"allOf": [{"$ref": "#/components/schemas/Open", "type": "string"}]}
    plain = {"$ref": "#/components/schemas/Plain"}
    accepting = {"$ref": "#/components/schemas/Accepting"}

    # When / Then: readings that agree give their answer, a disagreement gives None (which no
    # original answer equals), and unknown references are answered as asked.
    assert _output_null_verdict(sibling, schemas, assume_unknown=True) is None
    assert _output_null_verdict(plain, schemas, assume_unknown=True) is False
    assert _output_null_verdict(accepting, schemas, assume_unknown=True) is False
    assert _output_null_verdict({"nullable": True}, schemas, assume_unknown=True) is True
    missing = {"$ref": "#/components/schemas/Missing"}
    assert _output_null_verdict(missing, schemas, assume_unknown=True) is True
    assert _output_null_verdict(missing, schemas, assume_unknown=False) is False


def test_a_nullable_union_below_the_schema_is_read_as_the_original_in_every_reading() -> None:
    # Given: a member that is a nullable union with a discriminator beside it, which conversion
    # rewrites so that it still accepts null although a discriminator would reject it.
    nested = {
        "anyOf": [{"discriminator": DISCRIMINATOR, "oneOf": [{"type": "string"}, {"type": "null"}]}]
    }

    # When / Then: both readings of the output answer as the original does, so they agree.
    assert _output_null_verdict(nested, {}, assume_unknown=True) is True


def test_a_nullable_union_member_is_left_to_its_own_conversion() -> None:
    # Given: a reference with a sibling (so the fallback is written), beside a member that is
    # itself a nullable union with a discriminator.
    node = {
        "anyOf": [
            {"discriminator": DISCRIMINATOR, "oneOf": [{"type": "string"}, {"type": "null"}]},
            {"$ref": "#/components/schemas/T", "description": "member"},
            {"type": "null"},
        ]
    }

    # When
    converted = _convert_schema_to_3_0(node, {"T": {"type": "string"}})

    # Then: the nested union is rewritten on its own and is not wrapped to restore an answer.
    null_only = {"nullable": True, "enum": [None]}
    assert converted == {
        "anyOf": [
            {"oneOf": [{"type": "string"}, null_only]},
            {"description": "member", "allOf": [{"$ref": "#/components/schemas/T"}]},
            null_only,
        ]
    }


def test_a_null_member_whose_nested_reference_sibling_changes_its_answer_is_restored() -> None:
    # Given: a null member that also requires a string through a sibling of a reference, which
    # the specification ignores (so the member would then accept null) and validators apply.
    sibling = {"$ref": "#/components/schemas/Open", "type": "string"}
    node = {
        "anyOf": [
            {"$ref": "#/components/schemas/T", "description": "member"},
            {"type": "null", "allOf": [sibling]},
        ]
    }

    # When
    converted = _convert_schema_to_3_0(node, {"T": {"type": "string"}, "Open": {}})

    # Then: the null branch is kept from accepting null, as the original did.
    null_only = {"nullable": True, "enum": [None]}
    assert converted["anyOf"][1] == {
        "allOf": [{"allOf": [sibling], **null_only}, {"not": null_only}]
    }


def test_the_discriminator_dial_can_be_set_apart_from_the_sibling_dial() -> None:
    # Given: a component that accepts null but carries a discriminator beside an allOf.
    schemas = {"T": {"allOf": [{"enum": [None]}], "discriminator": DISCRIMINATOR}}
    node = {"$ref": "#/components/schemas/T"}

    # When / Then: the discriminator is enforced or not as asked, whichever reading the
    # siblings follow, and it defaults to the reading of the siblings.
    for siblings in (True, False):
        assert _accepts_null(
            node,
            schemas,
            ref_siblings_apply=siblings,
            discriminator_active=False,
            assume_unknown=False,
        )
        assert not _accepts_null(
            node,
            schemas,
            ref_siblings_apply=siblings,
            discriminator_active=True,
            assume_unknown=False,
        )
    assert _accepts_null(node, schemas, ref_siblings_apply=True, assume_unknown=False)
    assert not _accepts_null(node, schemas, ref_siblings_apply=False, assume_unknown=False)


def test_a_null_only_schema_loses_its_discriminator() -> None:
    # Given: a null member that carries a combinator and a discriminator.
    node = {"type": "null", "allOf": [{}], "discriminator": DISCRIMINATOR}

    # When
    converted = _convert_schema_to_3_0(node)

    # Then: it discriminates nothing, and 3.0 would enforce it beside the allOf and reject null.
    assert converted == {"allOf": [{}], "nullable": True, "enum": [None]}


@pytest.mark.parametrize("key", ["anyOf", "oneOf"])
def test_a_member_that_is_a_nullable_union_stays_a_member(key: str) -> None:
    # Given: a nullable union whose only other member is a nullable union itself.
    node = {key: [{"oneOf": [{}, {"type": "null"}]}, {"type": "null"}]}

    # When
    converted = _convert_schema_to_3_0(node)

    # Then: the inner union is not merged into this node (that would make it this node's own),
    # so the inner oneOf still sees two matches for null and the outer null branch is kept.
    null_only = {"nullable": True, "enum": [None]}
    assert converted == {key: [{"oneOf": [{}, null_only]}, null_only]}


def test_a_const_that_arrives_with_a_merged_member_becomes_an_enum() -> None:
    # Given: a null member beside a member that is a const.
    converted = _convert_schema_to_3_0({"anyOf": [{"const": None}, {"type": "null"}]})

    # When / Then: the const is an enum like the node's own would be, so the document is valid.
    assert converted == {"nullable": True, "enum": [None]}


def test_a_not_that_differs_from_the_nodes_own_keeps_the_union() -> None:
    # Given: a node with its own not, and a sole member with another one that rejects everything.
    node = {"not": {"type": "string"}, "oneOf": [{"not": {}}, {"type": "null"}]}

    # When
    converted = _convert_schema_to_3_0(node)

    # Then: the member's not is not dropped in favor of the node's.
    assert converted == {
        "not": {"type": "string"},
        "oneOf": [{"not": {}}, {"nullable": True, "enum": [None]}],
    }


@pytest.mark.parametrize("key", ["anyOf", "oneOf"])
def test_an_ordinary_nullable_union_gets_no_restoring_wrapper(key: str) -> None:
    # Given: the common shape, a reference with a description beside a null member.
    node = {key: [{**REF, "description": "member"}, {"type": "null"}]}
    components = {"T": {"type": "object"}}

    # When
    converted = _convert_schema_to_3_0(
        json.loads(json.dumps(node).replace("#/$defs/", "#/components/schemas/")), components
    )

    # Then: nothing but the reference's own allOf and the null branch.
    assert converted == {
        key: [
            {"description": "member", "allOf": [{"$ref": "#/components/schemas/T"}]},
            {"nullable": True, "enum": [None]},
        ]
    }


def test_each_null_member_stays_a_branch_with_its_constraints() -> None:
    # Given: a oneOf of a reference and three null members, one of which constrains itself.
    node = {
        "oneOf": [
            {"$ref": "#/components/schemas/T", "description": "member"},
            {"type": "null"},
            {"type": "null", "description": "again"},
            {"type": "null", "not": {}},
        ]
    }

    # When
    converted = _convert_schema_to_3_0(node, {"T": {"type": "string"}})

    # Then: three null branches, so a oneOf still counts two matches for null, and the last
    # one keeps rejecting every instance.
    assert converted["oneOf"][1:] == [
        {"nullable": True, "enum": [None]},
        {"description": "again", "nullable": True, "enum": [None]},
        {"not": {}, "nullable": True, "enum": [None]},
    ]


def test_a_reference_beside_a_null_type_moves_into_all_of() -> None:
    # Given: a null member that also refers to a schema: both apply, so nothing is accepted, and
    # 3.0 ignores the keys beside a reference.
    node = {
        "anyOf": [
            {"$ref": "#/components/schemas/T", "description": "member"},
            {"type": "null", "$ref": "#/components/schemas/S"},
        ]
    }

    # When
    converted = _convert_schema_to_3_0(node, {"T": {"type": "integer"}, "S": {"type": "string"}})

    # Then: the reference is the first conjunct of the null branch, not a bare key beside it.
    assert converted["anyOf"][1] == {
        "allOf": [{"$ref": "#/components/schemas/S"}],
        "nullable": True,
        "enum": [None],
    }


def test_a_union_of_null_members_only_keeps_its_branches_when_they_do_not_add_up() -> None:
    # Given: unions of null members, one of which is a plain pair under anyOf.
    pair = [{"type": "null"}, {"type": "null"}]

    # When
    one_of = _convert_schema_to_3_0({"oneOf": pair})
    any_of = _convert_schema_to_3_0({"anyOf": pair})
    rejecting = _convert_schema_to_3_0({"anyOf": [{"type": "null", "not": {}}]})

    # Then: the oneOf needs its two branches (null matches both, so it is rejected), while the
    # anyOf of plain null members and the null-only schema accept the same instances.
    null_only = {"nullable": True, "enum": [None]}
    assert one_of == {"oneOf": [null_only, null_only]}
    assert any_of == null_only
    assert rejecting == {"anyOf": [{"not": {}, **null_only}]}


@pytest.mark.parametrize("key", ["anyOf", "oneOf"])
@pytest.mark.parametrize(
    "members",
    [
        [{"type": "string", "nullable": True}],
        [{"type": "string", "nullable": True}, {"type": "integer"}],
        [{"$ref": "#/$defs/NullableString"}],
        [{"$ref": "#/$defs/NullableString"}, {"type": "integer"}],
        [{"type": "string", "nullable": True}, {"enum": [None, "a"]}],
    ],
    ids=["inline", "inline-and-integer", "reference", "reference-and-integer", "two-nullable"],
)
def test_nullable_in_the_input_is_read_like_the_3_1_conversion(
    key: str, members: list[dict[str, Any]]
) -> None:
    # Given: an input whose members say ``nullable: true`` beside an explicit null member.
    definitions = {"NullableString": {"type": "string", "nullable": True}}
    node = {key: [*members, {"type": "null"}]}
    probes: list[JsonValue] = [None, "a", "x", 1, 2.5, {}, []]
    components_node = json.loads(json.dumps(node).replace("#/$defs/", "#/components/schemas/"))

    # When
    converted_3_0 = _convert_schema_to_3_0(components_node, definitions)
    converted_3_1 = _convert_schema_to_3_1(node)

    # Then: the library's own 3.1 conversion and its 3.0 conversion accept the same instances.
    components_3_0 = _convert_schemas_to_3_0(definitions)[0]
    components_3_1 = {name: _convert_schema_to_3_1(value) for name, value in definitions.items()}
    in_3_0 = OAS30Validator({**converted_3_0, "components": {"schemas": components_3_0}})
    in_3_1 = OAS31Validator({**converted_3_1, "$defs": components_3_1})
    assert [in_3_0.is_valid(p) for p in probes] == [in_3_1.is_valid(p) for p in probes]


def test_conjuncts_beside_an_inlined_discriminator_go_in_an_outer_all_of() -> None:
    # Given: an inlined schema with an inert discriminator and a field that tightens a bound.
    discriminator = {"propertyName": "kind"}
    inlined = {"type": "number", "minimum": 0, "discriminator": discriminator, "nullable": True}

    # When
    merged = _merge_wrapper_into_inlined(inlined, {"minimum": 1, "description": "field"})

    # Then: the discriminator stays beside plain keys, and the annotation describes the field.
    assert merged == {
        "description": "field",
        "allOf": [
            {"type": "number", "minimum": 0, "discriminator": discriminator, "nullable": True},
            {"minimum": 1},
        ],
    }


def test_wrapper_all_of_equal_to_the_inlined_one_is_not_repeated() -> None:
    # Given / When
    merged = _merge_wrapper_into_inlined(
        {"type": "object", "allOf": [{"minProperties": 1}]}, {"allOf": [{"minProperties": 1}]}
    )

    # Then
    assert merged == {"type": "object", "allOf": [{"minProperties": 1}]}
