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
from azure_functions_openapi.spec import (
    generate_openapi_report,
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
)
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


def test_dict_map_schema_via_additional_properties_is_hoisted() -> None:
    schema = {
        "title": "WidgetMap",
        "type": "object",
        "additionalProperties": {"type": "integer"},
    }
    components = _make_components()

    result = hoist_inline_defs(schema, components, hoist_flat=True)

    assert result == {"$ref": "#/components/schemas/WidgetMap"}
    assert components["schemas"]["WidgetMap"]["additionalProperties"] == {"type": "integer"}


def test_open_object_with_bool_additional_properties_left_inline() -> None:
    schema = {"type": "object", "additionalProperties": True}
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


# ---------------------------------------------------------------------------
# Output-API propagation (issue #378): the option must reach every public
# spec-output wrapper, not only generate_openapi_spec.
# ---------------------------------------------------------------------------


def test_get_openapi_json_forwards_hoist_flag(_clean_registry: Any) -> None:
    scan_endpoint_metadata(_make_flat_app())

    default_json = get_openapi_json()
    hoisted_json = get_openapi_json(hoist_flat_schemas=True)

    assert "#/components/schemas/CreateUser" not in default_json
    assert '#/components/schemas/CreateUser' in hoisted_json


def test_get_openapi_yaml_forwards_hoist_flag(_clean_registry: Any) -> None:
    scan_endpoint_metadata(_make_flat_app())

    default_yaml = get_openapi_yaml()
    hoisted_yaml = get_openapi_yaml(hoist_flat_schemas=True)

    assert "CreateUser:" not in default_yaml
    assert "#/components/schemas/CreateUser" in hoisted_yaml


def test_generate_openapi_report_forwards_hoist_flag(_clean_registry: Any) -> None:
    scan_endpoint_metadata(_make_flat_app())

    default_report = generate_openapi_report()
    hoisted_report = generate_openapi_report(hoist_flat_schemas=True)

    assert _request_schema(default_report.spec) == _FLAT_BODY
    assert _request_schema(hoisted_report.spec) == {
        "$ref": "#/components/schemas/CreateUser"
    }
# ---------------------------------------------------------------------------
# JSON-Pointer-safe component names + strict hashing (issue #379)
# ---------------------------------------------------------------------------


def test_title_with_slash_is_sanitized_to_resolvable_ref() -> None:
    schema = {"title": "Order/Item", "type": "object", "properties": {"id": {"type": "integer"}}}
    components = _make_components()

    result = hoist_inline_defs(schema, components, hoist_flat=True)

    # ``/`` would otherwise be read as a JSON Pointer path separator.
    assert result == {"$ref": "#/components/schemas/Order_Item"}
    assert "Order_Item" in components["schemas"]
    assert "Order/Item" not in components["schemas"]


def test_title_with_tilde_is_sanitized_to_resolvable_ref() -> None:
    schema = {"title": "Order~Item", "type": "object", "properties": {"id": {"type": "integer"}}}
    components = _make_components()

    result = hoist_inline_defs(schema, components, hoist_flat=True)

    # ``~`` is the JSON Pointer escape character and must not survive verbatim.
    assert result == {"$ref": "#/components/schemas/Order_Item"}
    assert "Order_Item" in components["schemas"]


def test_sanitized_names_collide_and_alias_deterministically() -> None:
    # Two distinct titles sanitize to the same identifier with differing content.
    schema_a = {"title": "Order/Item", "type": "object", "properties": {"id": {"type": "integer"}}}
    schema_b = {"title": "Order~Item", "type": "object", "properties": {"id": {"type": "string"}}}
    components = _make_components()

    ref_a = hoist_inline_defs(schema_a, components, hoist_flat=True)
    ref_b = hoist_inline_defs(schema_b, components, hoist_flat=True)

    assert ref_a == {"$ref": "#/components/schemas/Order_Item"}
    assert ref_b != ref_a
    assert ref_b["$ref"].startswith("#/components/schemas/Order_Item")
    assert len(components["schemas"]) == 2


def test_anonymous_hash_rejects_non_json_schema() -> None:
    # Strict serialization (no ``default=str``) surfaces non-JSON metadata as a
    # loud failure instead of a non-deterministic, memory-address-tainted name.
    schema = {"type": "object", "properties": {"id": {"type": "integer"}}, "x": object()}
    components = _make_components()

    with pytest.raises(TypeError):
        hoist_inline_defs(schema, components, hoist_flat=True)


def test_defs_path_sanitizes_names_without_opt_in() -> None:
    # Regression (#379): the JSON-Pointer-safety bug is NOT opt-in-only. The
    # default ``$defs`` hoisting path (``hoist_flat=False``) flows through the
    # same ``_resolve_name_collision`` entry, so a ``$defs`` key containing ``/``
    # must also be sanitized and its ref rewritten to resolve.
    schema = {
        "$defs": {"Order/Item": {"type": "object", "properties": {"id": {"type": "integer"}}}},
        "type": "object",
        "properties": {"item": {"$ref": "#/$defs/Order/Item"}},
    }
    components = _make_components()

    result = hoist_inline_defs(schema, components)  # default: hoist_flat=False

    assert "Order_Item" in components["schemas"]
    assert "Order/Item" not in components["schemas"]
    assert result["properties"]["item"] == {"$ref": "#/components/schemas/Order_Item"}
