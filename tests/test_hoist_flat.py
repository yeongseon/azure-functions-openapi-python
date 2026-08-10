"""Opt-in flat-schema hoisting (issue #375).

``hoist_inline_defs(..., hoist_flat=True)`` promotes structured *flat* schemas
(objects/arrays with no inline ``$defs`` and no local ``#/$defs`` refs) into
``components.schemas`` and replaces them with a ``$ref``. This deduplicates a
flat schema reused across endpoints exactly like model-class schemas already
are. The default (``hoist_flat=False``) preserves the verbatim inline behaviour
from #311, and trivial scalar schemas are always left inline.
"""

from __future__ import annotations

from typing import Any

import pytest

from azure_functions_openapi.bridge import _HANDLER_METADATA_ATTR, scan_endpoint_metadata
from azure_functions_openapi.decorator import clear_openapi_registry, get_openapi_registry
from azure_functions_openapi.spec import generate_openapi_spec
from azure_functions_openapi.utils import hoist_inline_defs


def _make_components() -> dict[str, Any]:
    return {"schemas": {}}


def test_flat_schema_left_inline_by_default() -> None:
    schema = {"title": "Widget", "type": "object", "properties": {"id": {"type": "integer"}}}
    components = _make_components()

    result = hoist_inline_defs(schema, components)

    assert result == schema
    assert components["schemas"] == {}


def test_flat_schema_promoted_when_opted_in() -> None:
    schema = {"title": "Widget", "type": "object", "properties": {"id": {"type": "integer"}}}
    components = _make_components()

    result = hoist_inline_defs(schema, components, hoist_flat=True)

    assert result == {"$ref": "#/components/schemas/Widget"}
    assert components["schemas"]["Widget"]["properties"] == {"id": {"type": "integer"}}


def test_identical_flat_schemas_dedupe_to_one_component() -> None:
    schema_a = {"title": "Widget", "type": "object", "properties": {"id": {"type": "integer"}}}
    schema_b = {"title": "Widget", "type": "object", "properties": {"id": {"type": "integer"}}}
    components = _make_components()

    ref_a = hoist_inline_defs(schema_a, components, hoist_flat=True)
    ref_b = hoist_inline_defs(schema_b, components, hoist_flat=True)

    assert ref_a == ref_b == {"$ref": "#/components/schemas/Widget"}
    assert list(components["schemas"]) == ["Widget"]


def test_same_name_different_content_gets_alias() -> None:
    schema_a = {"title": "Widget", "type": "object", "properties": {"id": {"type": "integer"}}}
    schema_b = {"title": "Widget", "type": "object", "properties": {"id": {"type": "string"}}}
    components = _make_components()

    ref_a = hoist_inline_defs(schema_a, components, hoist_flat=True)
    ref_b = hoist_inline_defs(schema_b, components, hoist_flat=True)

    assert ref_a == {"$ref": "#/components/schemas/Widget"}
    assert ref_b != ref_a
    assert ref_b["$ref"].startswith("#/components/schemas/Widget")
    assert len(components["schemas"]) == 2


def test_anonymous_flat_schema_gets_deterministic_hash_name() -> None:
    schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
    components = _make_components()

    result = hoist_inline_defs(schema, components, hoist_flat=True)

    ref = result["$ref"]
    assert ref.startswith("#/components/schemas/InlineSchema_")
    name = ref.rsplit("/", 1)[-1]
    assert name in components["schemas"]

    # A second identical anonymous schema dedupes to the same hash-based name.
    result2 = hoist_inline_defs(dict(schema), components, hoist_flat=True)
    assert result2 == result
    assert list(components["schemas"]) == [name]


def test_array_flat_schema_is_hoisted() -> None:
    schema = {"title": "WidgetList", "type": "array", "items": {"type": "string"}}
    components = _make_components()

    result = hoist_inline_defs(schema, components, hoist_flat=True)

    assert result == {"$ref": "#/components/schemas/WidgetList"}
    assert components["schemas"]["WidgetList"]["items"] == {"type": "string"}


def test_trivial_scalar_schema_left_inline_even_when_opted_in() -> None:
    schema = {"type": "string"}
    components = _make_components()

    result = hoist_inline_defs(schema, components, hoist_flat=True)

    assert result == schema
    assert components["schemas"] == {}


def test_schema_with_defs_uses_main_path_regardless_of_flag() -> None:
    schema = {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/Child"}},
        "$defs": {"Child": {"type": "object", "properties": {"n": {"type": "integer"}}}},
    }
    components = _make_components()

    result = hoist_inline_defs(schema, components, hoist_flat=True)

    # $defs are lifted to components; root stays inline with rewritten refs.
    assert "$defs" not in result
    assert components["schemas"]["Child"]["properties"] == {"n": {"type": "integer"}}
    assert result["properties"]["child"] == {"$ref": "#/components/schemas/Child"}


def test_input_schema_is_not_mutated() -> None:
    schema = {"title": "Widget", "type": "object", "properties": {"id": {"type": "integer"}}}
    original = {"title": "Widget", "type": "object", "properties": {"id": {"type": "integer"}}}
    components = _make_components()

    hoist_inline_defs(schema, components, hoist_flat=True)

    assert schema == original


# ---------------------------------------------------------------------------
# Spec-level integration: hoist_flat_schemas plumbs through generate_openapi_spec
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class _MockBinding:
    def __init__(self, route: str, methods: list[str] | None, type: str = "httpTrigger") -> None:
        self.route = route
        self.methods = methods
        self.type = type


class _MockFunction:
    def __init__(self, name: str, func: Any, bindings: list[Any]) -> None:
        self._name = name
        self._func = func
        self._bindings = bindings

    def get_function_name(self) -> str:
        return self._name

    def get_user_function(self) -> Any:
        return self._func

    def get_bindings(self) -> list[Any]:
        return self._bindings

    def is_http_function(self) -> bool:
        return any(str(getattr(b, "type", "")).lower() == "httptrigger" for b in self._bindings)


class _MockBuilder:
    def __init__(self, function: _MockFunction) -> None:
        self._function = function

    def build(self, auth_level: Any = None) -> _MockFunction:
        return self._function


class _MockApp:
    def __init__(self, builders: list[_MockBuilder]) -> None:
        self._function_builders = builders


_FLAT_BODY: dict[str, Any] = {
    "title": "CreateUser",
    "type": "object",
    "properties": {"name": {"type": "string"}},
}


def _make_flat_app() -> _MockApp:
    def handler(req: Any) -> Any:
        return req

    setattr(
        handler,
        _HANDLER_METADATA_ATTR,
        {
            "endpoint": {
                "version": 1,
                "request_body": _FLAT_BODY,
                "request_body_required": True,
                "responses": {"200": {"schema": {"type": "object"}}},
            }
        },
    )
    binding = _MockBinding(route="users", methods=["POST"])
    fn = _MockFunction(name="create_user", func=handler, bindings=[binding])
    return _MockApp([_MockBuilder(fn)])


def _request_schema(spec: dict[str, Any]) -> dict[str, Any]:
    op = spec["paths"]["/api/users"]["post"]
    schema: dict[str, Any] = op["requestBody"]["content"]["application/json"]["schema"]
    return schema


def test_spec_keeps_flat_body_inline_by_default(_clean_registry: Any) -> None:
    scan_endpoint_metadata(_make_flat_app())
    assert get_openapi_registry()

    spec = generate_openapi_spec()

    assert _request_schema(spec) == _FLAT_BODY
    assert "CreateUser" not in spec.get("components", {}).get("schemas", {})


def test_spec_hoists_flat_body_when_opted_in(_clean_registry: Any) -> None:
    scan_endpoint_metadata(_make_flat_app())
    assert get_openapi_registry()

    spec = generate_openapi_spec(hoist_flat_schemas=True)

    assert _request_schema(spec) == {"$ref": "#/components/schemas/CreateUser"}
    assert spec["components"]["schemas"]["CreateUser"]["properties"] == {"name": {"type": "string"}}
