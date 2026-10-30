from __future__ import annotations

import copy
from typing import Any

from openapi_spec_validator import validate
import pytest
from test_bridge_endpoint_v2 import make_app, media

from azure_functions_openapi._warnings import WarningCode
from azure_functions_openapi.bridge import _read_endpoint_hints, scan_endpoint_metadata
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    _validate_spec,
    collect_spec_warnings,
    generate_openapi_spec,
)


def nested_schema(kind: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/Child"}},
        "$defs": {
            "Child": {
                "type": "object",
                "properties": {"value": {"$ref": "#/$defs/Value"}},
                "$defs": {"Value": {"type": kind}},
            }
        },
    }


def assert_local_refs_resolve(node: Any, document: dict[str, Any]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith("#/"):
                target: Any = document
                for part in value[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
                assert isinstance(target, dict)
            else:
                assert_local_refs_resolve(value, document)
    elif isinstance(node, list):
        for value in node:
            assert_local_refs_resolve(value, document)


@pytest.mark.parametrize("version", ["3.0.0", "3.1.0", "3.2.0"])
@pytest.mark.parametrize("hoist_flat", [False, True])
def test_schemas_resolve_when_media_and_headers_have_colliding_nested_defs(
    version: str, hoist_flat: bool
) -> None:
    # Given
    payload: dict[str, Any] = {
        "version": 2,
        "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
        "responses": {
            "201": {
                "content": {
                    **media(nested_schema("integer")),
                    "application/problem+json": {"schema": nested_schema("string")},
                },
                "headers": {"X-Result": {"schema": nested_schema("boolean")}},
            },
            "204": {"content": {}},
        },
    }
    original = copy.deepcopy(payload)
    reg = OpenAPIRegistry()
    app = make_app(payload, "a")
    other = copy.deepcopy(payload)
    other["responses"]["201"]["headers"]["X-Result"]["schema"] = nested_schema("number")
    second_app = make_app(other, "b")
    scan_endpoint_metadata(app, registry=reg)
    scan_endpoint_metadata(second_app, registry=reg)
    scan_endpoint_metadata(app, registry=reg)
    # When
    spec = generate_openapi_spec(
        registry=reg, openapi_version=version, hoist_flat_schemas=hoist_flat, strict=True
    )
    # Then
    assert _validate_spec(spec) == []
    if version != "3.2.0":
        validate(spec)
    assert_local_refs_resolve(spec, spec)
    assert "$defs" not in repr(spec)
    components = spec["components"]["schemas"]
    for route, expected_header in (("a", "boolean"), ("b", "number")):
        operation = spec["paths"][f"/api/{route}"]["post"]
        assert operation["responses"]["204"] == {"description": ""}
        assert operation["parameters"][0]["schema"] == {"type": "integer"}
        response = operation["responses"]["201"]
        schemas = [(response["headers"]["X-Result"]["schema"], expected_header)]
        schemas.extend(
            (value["schema"], kind)
            for value, kind in zip(response["content"].values(), ("integer", "string"), strict=True)
        )
        for schema, kind in schemas:
            if "$ref" in schema:
                schema = components[schema["$ref"].split("/")[-1]]
            child = components[schema["properties"]["child"]["$ref"].split("/")[-1]]
            value = components[child["properties"]["value"]["$ref"].split("/")[-1]]
            assert value["type"] == kind
    assert payload == original


def test_registries_are_independent_when_versions_are_mixed() -> None:
    # Given
    first = OpenAPIRegistry()
    second = OpenAPIRegistry()
    legacy = make_app({"version": 1, "responses": {"204": {}}}, "legacy")
    modern = make_app({"version": 2, "responses": {"204": {"content": {}}}}, "modern")
    # When
    scan_endpoint_metadata(legacy, registry=first)
    scan_endpoint_metadata(modern, registry=second)
    a = generate_openapi_spec(registry=first)
    b = generate_openapi_spec(registry=second)
    # Then
    assert set(a["paths"]) == {"/api/legacy"}
    assert set(b["paths"]) == {"/api/modern"}
    assert a["paths"]["/api/legacy"]["post"]["responses"]["204"]["content"] == {
        "application/json": {"schema": None}
    }
    assert "content" not in b["paths"]["/api/modern"]["post"]["responses"]["204"]


@pytest.mark.parametrize("version", [999, None, True, "2"])
def test_version_skew_is_structured_when_no_supported_wrapper_exists(version: Any) -> None:
    # Given
    reg = OpenAPIRegistry()
    app = make_app({"version": version, "responses": {"201": {"content": media()}}})
    # When
    scan_endpoint_metadata(app, registry=reg)
    spec = generate_openapi_spec(registry=reg)
    # Then
    assert reg.entries["post::/api/users"]["response"] == {}
    assert any(
        w.code == WarningCode.VERSION_SKEW for w in collect_spec_warnings(spec, registry=reg)
    )


def test_supported_inner_wrapper_when_outer_version_is_unknown() -> None:
    # Given
    def inner() -> None:
        pass

    def outer() -> None:
        pass

    payload = {"version": 2, "responses": {"204": {"content": {}}}}
    setattr(inner, "_azure_functions_metadata", {"endpoint": payload})
    setattr(outer, "_azure_functions_metadata", {"endpoint": {"version": 999}})
    setattr(outer, "__wrapped__", inner)
    # When
    result = _read_endpoint_hints(outer)
    # Then
    assert result == payload
    assert result is not payload
