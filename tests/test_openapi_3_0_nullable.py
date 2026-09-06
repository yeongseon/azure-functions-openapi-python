"""Down-convert nested container nullability to valid OpenAPI 3.0 form (issue #562).

OpenAPI 3.0 has no ``{"type": "null"}`` sentinel and cannot mark a ``$ref``
nullable inline. Pydantic v2 emits ``Optional[T]`` as
``{"anyOf": [<T>, {"type": "null"}]}`` and multi-type unions as
``{"type": [..., "null"]}`` — both 3.1/2020-12 constructs. These tests pin the
3.0 emit path so it rewrites those idioms to the 3.0 ``nullable: true`` form
(``allOf`` wrapper for a nullable ``$ref``), while the 3.1 path stays faithful
(locked by #558 / test_openapi_3_1.py).
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import clear_openapi_registry
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

    def test_multiple_non_null_members_keep_combinator(self) -> None:
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]}

        result = _collapse_nullable_combinator(schema)

        assert result["nullable"] is True
        assert result["anyOf"] == [{"type": "string"}, {"type": "integer"}]

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

        result = _convert_schemas_to_3_0(schemas)

        assert result["A"] == {"type": "string", "nullable": True}
        assert result["B"] == {"type": "integer"}


# ---------------------------------------------------------------------------
# End-to-end — list[Optional[User]] response under 3.0 vs 3.1
# ---------------------------------------------------------------------------


class User(BaseModel):
    id: str
    name: str


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
                    "content": {"application/json": {"schema": List[Optional[User]]}},
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
    def test_30_is_null_free_and_valid(self) -> None:
        spec = _list_optional_user_spec(OPENAPI_VERSION_3_0)

        schema = _response_schema(spec)
        assert schema["type"] == "array"
        items = schema["items"]
        assert items.get("nullable") is True
        assert items["allOf"] == [{"$ref": "#/components/schemas/User"}]

        # No 3.1-only constructs leak into a 3.0 document.
        assert not _has_null_type(spec)
        assert not _has_type_array(spec)

    def test_31_preserves_faithful_anyof(self) -> None:
        spec = _list_optional_user_spec(OPENAPI_VERSION_3_1)

        items = _response_schema(spec)["items"]
        assert "anyOf" in items
        assert {"type": "null"} in items["anyOf"]
