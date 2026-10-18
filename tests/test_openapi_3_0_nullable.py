"""Down-convert nested container nullability to valid OpenAPI 3.0 form (issue #562).

OpenAPI 3.0 has no ``{"type": "null"}`` sentinel and cannot mark a ``$ref``
nullable inline. Pydantic v2 emits ``Optional[T]`` as
``{"anyOf": [<T>, {"type": "null"}]}`` and multi-type unions as
``{"type": [..., "null"]}`` — both 3.1/2020-12 constructs. These tests pin the
3.0 emit path so it rewrites those idioms to the 3.0 ``nullable: true`` form,
while the 3.1 path stays faithful (locked by #558 / test_openapi_3_1.py).

A nullable ``$ref`` inlines the referenced schema's own content (rather than
an ``allOf``-wrapped ``$ref``) and a nullable multi-type union attaches
``nullable`` directly to one branch, because ``nullable: true`` only takes
effect on the exact schema object that also carries the ``type`` it exempts —
a bare ``$ref``, or a combinator wrapper with more than one branch, cannot
otherwise ever satisfy a real OpenAPI 3.0 validator for a ``null`` instance
(issue #782; see ``TestNullableInstanceValidation`` below, which checks
against the actual reference validator rather than only document structure).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import clear_openapi_registry, register_openapi_metadata
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    OPENAPI_VERSION_3_0,
    OPENAPI_VERSION_3_1,
    _collapse_nullable_combinator,
    _convert_schema_to_3_0,
    _convert_schemas_to_3_0,
    generate_openapi_spec,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _iter_dicts(node: Any) -> Any:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


def _has_null_type(node: Any) -> bool:
    return any(d.get("type") == "null" for d in _iter_dicts(node))


def _has_type_array(node: Any) -> bool:
    return any(isinstance(d.get("type"), list) for d in _iter_dicts(node))


# ---------------------------------------------------------------------------
# _convert_schema_to_3_0 — scalar / union / enum
# ---------------------------------------------------------------------------


class TestConvertSchemaTo30Scalars:
    def test_nullable_inline_scalar(self) -> None:
        schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}

        result = _convert_schema_to_3_0(schema)

        assert result == {"type": "string", "nullable": True}
        assert "anyOf" not in result

    def test_type_array_single_non_null(self) -> None:
        result = _convert_schema_to_3_0({"type": ["string", "null"]})

        assert result == {"type": "string", "nullable": True}

    def test_type_array_multi_non_null(self) -> None:
        result = _convert_schema_to_3_0({"type": ["string", "integer", "null"]})

        assert result["nullable"] is True
        assert "type" not in result
        assert result["anyOf"] == [{"type": "string"}, {"type": "integer"}]
        assert not _has_null_type(result)
        assert not _has_type_array(result)

    def test_type_array_only_null(self) -> None:
        result = _convert_schema_to_3_0({"type": ["null"]})

        assert result["nullable"] is True
        assert "type" not in result

    def test_enum_with_null(self) -> None:
        result = _convert_schema_to_3_0({"enum": [None, "a", "b"]})

        assert result["enum"] == ["a", "b"]
        assert result["nullable"] is True

    def test_non_nullable_passthrough(self) -> None:
        schema = {"type": "string", "description": "plain"}

        assert _convert_schema_to_3_0(schema) == schema

    def test_non_dict_passthrough(self) -> None:
        assert _convert_schema_to_3_0("nope") == "nope"  # type: ignore[arg-type,comparison-overlap]


# ---------------------------------------------------------------------------
# _collapse_nullable_combinator — $ref / annotation / conflict
# ---------------------------------------------------------------------------


class TestCollapseNullableCombinator:
    def test_nullable_ref_wraps_in_allof(self) -> None:
        schema = {"anyOf": [{"$ref": "#/components/schemas/User"}, {"type": "null"}]}

        result = _collapse_nullable_combinator(schema)

        assert result == {
            "nullable": True,
            "allOf": [{"$ref": "#/components/schemas/User"}],
        }
        assert "anyOf" not in result

    def test_nullable_ref_lifts_annotation_siblings(self) -> None:
        schema = {
            "anyOf": [
                {"$ref": "#/components/schemas/User", "description": "the user"},
                {"type": "null"},
            ]
        }

        result = _collapse_nullable_combinator(schema)

        assert result["allOf"] == [{"$ref": "#/components/schemas/User"}]
        assert result["description"] == "the user"
        assert result["nullable"] is True

    def test_existing_annotation_wins_over_member(self) -> None:
        schema = {
            "description": "outer",
            "anyOf": [{"type": "string", "description": "inner"}, {"type": "null"}],
        }

        result = _collapse_nullable_combinator(schema)

        # Existing node annotation is preserved (setdefault semantics).
        assert result["description"] == "outer"
        assert result["type"] == "string"
        assert result["nullable"] is True

    def test_structural_conflict_keeps_combinator(self) -> None:
        # Wrapper already has a (different) ``type`` — an ambiguous structural
        # overlap must not be silently merged away.
        schema = {"type": "object", "anyOf": [{"type": "string"}, {"type": "null"}]}

        result = _collapse_nullable_combinator(schema)

        assert result["nullable"] is True
        assert result["anyOf"] == [{"type": "string"}]
        assert result["type"] == "object"

    def test_multiple_non_null_members_patch_first_branch_nullable(self) -> None:
        # Regression (#782): a sibling "nullable" on the anyOf/oneOf wrapper
        # itself has no effect once there is more than one non-null branch --
        # the reference OAS 3.0 validator descends into each branch
        # independently and rejects null against every one of them. The first
        # branch is patched to carry "nullable" directly (alongside its own
        # "type"), so at least one branch actually accepts null.
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]}

        result = _collapse_nullable_combinator(schema)

        assert result["nullable"] is True
        assert result["anyOf"] == [{"type": "string", "nullable": True}, {"type": "integer"}]

    def test_no_null_member_unchanged(self) -> None:
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}

        assert _collapse_nullable_combinator(schema) == schema


# ---------------------------------------------------------------------------
# _convert_schema_to_3_0 — nested containers
# ---------------------------------------------------------------------------


class TestConvertSchemaTo30Nested:
    def test_list_of_optional_ref(self) -> None:
        schema = {
            "type": "array",
            "items": {"anyOf": [{"$ref": "#/components/schemas/User"}, {"type": "null"}]},
        }

        result = _convert_schema_to_3_0(schema)

        assert result["type"] == "array"
        assert result["items"] == {
            "nullable": True,
            "allOf": [{"$ref": "#/components/schemas/User"}],
        }
        assert not _has_null_type(result)

    def test_optional_list(self) -> None:
        schema = {
            "anyOf": [
                {"type": "array", "items": {"type": "string"}},
                {"type": "null"},
            ]
        }

        result = _convert_schema_to_3_0(schema)

        assert result["type"] == "array"
        assert result["items"] == {"type": "string"}
        assert result["nullable"] is True

    def test_dict_of_optional(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        }

        result = _convert_schema_to_3_0(schema)

        assert result["additionalProperties"] == {"type": "string", "nullable": True}
        assert not _has_null_type(result)

    def test_optional_dict(self) -> None:
        schema = {
            "anyOf": [
                {"type": "object", "additionalProperties": {"type": "integer"}},
                {"type": "null"},
            ]
        }

        result = _convert_schema_to_3_0(schema)

        assert result["type"] == "object"
        assert result["additionalProperties"] == {"type": "integer"}
        assert result["nullable"] is True

    def test_nested_defs_converted(self) -> None:
        schema = {
            "type": "object",
            "$defs": {
                "Child": {
                    "type": "object",
                    "properties": {"n": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
                }
            },
        }

        result = _convert_schema_to_3_0(schema)

        assert result["$defs"]["Child"]["properties"]["n"] == {
            "type": "string",
            "nullable": True,
        }

    def test_convert_schemas_maps_all(self) -> None:
        schemas = {
            "A": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "B": {"type": "integer"},
        }

        result, lossy = _convert_schemas_to_3_0(schemas)

        assert result["A"] == {"type": "string", "nullable": True}
        assert result["B"] == {"type": "integer"}
        assert lossy == []


# ---------------------------------------------------------------------------
# End-to-end — list[Optional[User]] response under 3.0 vs 3.1
# ---------------------------------------------------------------------------


class User(BaseModel):
    id: str
    name: str


class Choice(BaseModel):
    value: Literal["fixed"]


def _list_optional_user_spec(version: str) -> dict[str, Any]:
    reg = OpenAPIRegistry()
    reg.set(
        "list_users",
        {
            "route": "users",
            "method": "get",
            "summary": "List users",
            "response": {
                200: {
                    "description": "ok",
                    "content": {"application/json": {"schema": list[User | None]}},
                }
            },
        },
    )
    return generate_openapi_spec(openapi_version=version, registry=reg)


def _response_schema(spec: dict[str, Any]) -> dict[str, Any]:
    op = spec["paths"]["/api/users"]["get"]
    schema: dict[str, Any] = op["responses"]["200"]["content"]["application/json"]["schema"]
    return schema


class TestListOptionalUserEndToEnd:
    def test_30_converts_literal_const_to_enum(self) -> None:
        validate_spec = pytest.importorskip("openapi_spec_validator").validate_spec
        registry = OpenAPIRegistry()
        register_openapi_metadata(
            "/choice",
            "POST",
            request_model=Choice,
            registry=registry,
        )

        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_0,
            registry=registry,
            strict=True,
        )

        value_schema = spec["components"]["schemas"]["Choice"]["properties"]["value"]
        assert value_schema["enum"] == ["fixed"]
        assert "const" not in value_schema
        validate_spec(spec)

    def test_30_is_null_free_and_valid(self) -> None:
        spec = _list_optional_user_spec(OPENAPI_VERSION_3_0)

        schema = _response_schema(spec)
        assert schema["type"] == "array"
        items = schema["items"]
        # Regression (#782): a bare allOf-wrapped $ref does not actually
        # accept null under OpenAPI 3.0 (nullable only takes effect on the
        # same schema object as the type it exempts) -- the referenced
        # User schema's own content is inlined here instead, so "nullable"
        # and "type" coexist on the one schema object that needs them.
        assert items.get("nullable") is True
        assert "allOf" not in items
        assert "$ref" not in items
        assert items["type"] == "object"
        assert set(items["properties"]) == {"id", "name"}
        assert items["required"] == ["id", "name"]
        # The registered component itself is untouched by the inlined copy.
        assert "nullable" not in spec["components"]["schemas"]["User"]

        # No 3.1-only constructs leak into a 3.0 document.
        assert not _has_null_type(spec)
        assert not _has_type_array(spec)

    def test_30_nullable_ref_instance_validates(self) -> None:
        # Given: the same list[Optional[User]] response as above.
        openapi_schema_validator = pytest.importorskip("openapi_schema_validator")
        spec = _list_optional_user_spec(OPENAPI_VERSION_3_0)
        schema = _response_schema(spec)

        # When: a real OpenAPI 3.0 validator checks a null member alongside a
        # valid User instance -- not just the document's structural validity.
        root_schema = {**schema, "components": spec.get("components", {})}
        validator = openapi_schema_validator.OAS30Validator(root_schema)
        errors = list(validator.iter_errors([None, {"id": "1", "name": "Ada"}]))

        # Then: both the null and the valid instance are accepted.
        assert errors == []

    def test_31_preserves_faithful_anyof(self) -> None:
        spec = _list_optional_user_spec(OPENAPI_VERSION_3_1)

        items = _response_schema(spec)["items"]
        assert "anyOf" in items
        assert {"type": "null"} in items["anyOf"]


# ---------------------------------------------------------------------------
# Instance-semantic regressions (#782): a structurally valid OpenAPI 3.0
# document is not sufficient -- these check the generated schemas against the
# actual reference OpenAPI 3.0 validator with real, valid Pydantic payloads
# (not just shape assertions), mirroring the issue's own reproductions.
# ---------------------------------------------------------------------------


class _NullableChild(BaseModel):
    name: str


class _NullableUnionPayload(BaseModel):
    child: _NullableChild | None = None
    choice: str | int | None = None


class _TupleModel(BaseModel):
    value: tuple[int, float]


class _TreeNode(BaseModel):
    label: str
    next: _TreeNode | None = None


_TreeNode.model_rebuild()


def _oas30_validator_for(spec: dict[str, Any], path: str, method: str) -> Any:
    openapi_schema_validator = pytest.importorskip("openapi_schema_validator")
    operation = spec["paths"][path][method]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    root_schema = {**response_schema, "components": spec.get("components", {})}
    return openapi_schema_validator.OAS30Validator(root_schema)


class TestNullableInstanceValidation:
    def test_nullable_ref_and_nullable_union_accept_all_null_payload(self) -> None:
        # Given: the issue's own reproduction -- a nullable $ref field and a
        # nullable multi-type union field, both left at their default None.
        registry = OpenAPIRegistry()
        register_openapi_metadata(
            "/nullable", "GET", response_model=_NullableUnionPayload, registry=registry
        )

        # When: generating under OpenAPI 3.0, strict (no lossy construct here).
        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_0, registry=registry, strict=True
        )
        validator = _oas30_validator_for(spec, "/api/nullable", "get")
        instance = _NullableUnionPayload().model_dump(mode="json")

        # Then: the all-null payload validates with zero errors.
        assert instance == {"child": None, "choice": None}
        assert list(validator.iter_errors(instance)) == []

    def test_nullable_ref_and_nullable_union_accept_populated_payload(self) -> None:
        # Given: the same schema, but with both fields populated instead.
        registry = OpenAPIRegistry()
        register_openapi_metadata(
            "/nullable", "GET", response_model=_NullableUnionPayload, registry=registry
        )
        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_0, registry=registry, strict=True
        )
        validator = _oas30_validator_for(spec, "/api/nullable", "get")

        # When / Then: both the $ref branch and each union member still work.
        for instance in (
            _NullableUnionPayload(child=_NullableChild(name="Ada"), choice="hello").model_dump(
                mode="json"
            ),
            _NullableUnionPayload(child=_NullableChild(name="Ada"), choice=42).model_dump(
                mode="json"
            ),
        ):
            assert list(validator.iter_errors(instance)) == []

    def test_nullable_union_still_rejects_genuinely_invalid_payload(self) -> None:
        # Given: the broadened nullable conversion must not become a blanket
        # "anything goes" escape hatch.
        registry = OpenAPIRegistry()
        register_openapi_metadata(
            "/nullable", "GET", response_model=_NullableUnionPayload, registry=registry
        )
        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_0, registry=registry, strict=True
        )
        validator = _oas30_validator_for(spec, "/api/nullable", "get")

        # When: "choice" is a type that is neither string, integer, nor null.
        errors = list(validator.iter_errors({"child": None, "choice": [1, 2, 3]}))

        # Then: it is still rejected.
        assert errors != []

    def test_self_referential_nullable_model_does_not_recurse_forever(self) -> None:
        # Given: a model whose only nullable field refers back to itself.
        registry = OpenAPIRegistry()
        register_openapi_metadata("/tree", "GET", response_model=_TreeNode, registry=registry)

        # When: generation completes (would hang/overflow without the
        # resolving-set cycle guard. The guard inlines one level of the
        # self-reference -- as deep as it can go without looping -- and the
        # next level back to the same component falls back to the pre-#782
        # allOf form, which stays structurally valid but, like every
        # nullable $ref before this fix, does not itself satisfy a null
        # at that depth).
        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_0, registry=registry, strict=True
        )

        # Then: a leaf instance (null at the one level the guard inlines)
        # validates with zero errors.
        validator = _oas30_validator_for(spec, "/api/tree", "get")
        leaf_instance = _TreeNode(label="leaf").model_dump(mode="json")
        assert list(validator.iter_errors(leaf_instance)) == []

        # And the inlined level's own nested "next" is the documented
        # fallback form, not an infinite inlining of the same component.
        nested_next = spec["components"]["schemas"]["_TreeNode"]["properties"]["next"][
            "properties"
        ]["next"]
        assert nested_next["allOf"] == [{"$ref": "#/components/schemas/_TreeNode"}]


class TestOverlappingTupleInstanceValidation:
    def test_overlapping_int_float_tuple_non_strict_accepts_valid_instance(self) -> None:
        # Given: tuple[int, float] -- the issue's own reproduction. "integer"
        # is a JSON Schema subset of "number", so oneOf would wrongly reject
        # a valid (1, 2.5) by matching both branches; anyOf must not.
        registry = OpenAPIRegistry()
        register_openapi_metadata("/tuples", "GET", response_model=_TupleModel, registry=registry)

        # When: generating under non-strict mode (the lossy tuple approximation
        # is allowed through, with a structured warning).
        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_0, registry=registry, strict=False
        )
        schema = spec["components"]["schemas"]["_TupleModel"]["properties"]["value"]
        assert schema["items"] == {"anyOf": [{"type": "integer"}, {"type": "number"}]}

        # Then: the real (1, 2.5) instance validates against the real schema.
        validator = _oas30_validator_for(spec, "/api/tuples", "get")
        instance = _TupleModel(value=(1, 2.5)).model_dump(mode="json")
        assert instance["value"] == [1, 2.5]
        assert list(validator.iter_errors(instance)) == []

    def test_overlapping_tuple_still_rejects_wrong_length(self) -> None:
        # Given: the approximation drops positional typing, but must still
        # enforce the tuple's own minItems/maxItems constraints.
        registry = OpenAPIRegistry()
        register_openapi_metadata("/tuples", "GET", response_model=_TupleModel, registry=registry)
        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_0, registry=registry, strict=False
        )
        validator = _oas30_validator_for(spec, "/api/tuples", "get")

        # When: the array has only one element instead of exactly two.
        errors = list(validator.iter_errors({"value": [1]}))

        # Then: it is still rejected.
        assert errors != []

    def test_overlapping_tuple_strict_mode_raises_instead_of_approximating(self) -> None:
        # Given / When / Then: strict mode must fail rather than silently
        # emit the position-losing approximation (#782's policy requirement).
        registry = OpenAPIRegistry()
        register_openapi_metadata("/tuples", "GET", response_model=_TupleModel, registry=registry)

        from azure_functions_openapi.exceptions import OpenAPISpecConfigError

        with pytest.raises(OpenAPISpecConfigError, match="positional constraints"):
            generate_openapi_spec(
                openapi_version=OPENAPI_VERSION_3_0, registry=registry, strict=True
            )

    def test_homogeneous_tuple_is_faithful_not_lossy(self) -> None:
        # Given: every position shares the identical type -- nothing
        # position-specific to lose, so this must remain faithful (items:
        # <schema>, no anyOf, no warning) even under strict mode.
        class _HomogeneousTupleModel(BaseModel):
            value: tuple[int, int]

        registry = OpenAPIRegistry()
        register_openapi_metadata(
            "/pair", "GET", response_model=_HomogeneousTupleModel, registry=registry
        )

        # When
        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_0, registry=registry, strict=True
        )

        # Then
        schema = spec["components"]["schemas"]["_HomogeneousTupleModel"]["properties"]["value"]
        assert schema["items"] == {"type": "integer"}
        assert "anyOf" not in schema["items"]
