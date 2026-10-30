"""Instance contracts for nullable fallback composition and coupled numeric bounds."""

from __future__ import annotations

from typing import Any

from openapi_schema_validator import OAS30Validator, OAS31Validator
from openapi_spec_validator import validate
from pydantic import JsonValue
import pytest

from azure_functions_openapi._schema_version_conversion import (
    _accepts_null,
    _convert_schema_to_3_0,
)
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec

REF: dict[str, Any] = {"$ref": "#/$defs/T"}
PROBES: list[JsonValue] = [
    None,
    "x",
    "",
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
]
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
    if name.startswith("discriminator-"):
        root = spec["components"]["schemas"]["Holder"] if hoisted else schema
        polymorphism = (
            root
            if "discriminator" in root
            else root["allOf"][-1]["anyOf"][0]
            if "allOf" in root
            else root["anyOf"][0]
        )
        assert polymorphism["discriminator"]["propertyName"] == "kind"


def test_reference_target_uses_original_dialect_even_from_candidate() -> None:
    # Given: a target whose reference accepts null but whose own sibling rejects it.
    schemas = {"T": {"$ref": "#/components/schemas/U", "type": "string"}, "U": {"enum": [None]}}
    node = {"$ref": "#/components/schemas/T"}

    # When
    accepts = _accepts_null(node, schemas, ref_siblings_apply=False, assume_unknown=False)

    # Then: candidate references still resolve against the unconverted component map.
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
