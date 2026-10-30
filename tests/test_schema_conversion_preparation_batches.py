"""Preparation work scales with schema batches, not reference expansions."""

from __future__ import annotations

import copy
import inspect
from typing import Any

from pydantic import JsonValue
import pytest

from azure_functions_openapi import _schema_version_conversion as conversion
from azure_functions_openapi._schema_3_0_preparation import _prepare_schema_for_3_0
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import generate_openapi_spec


@pytest.mark.parametrize("component_count", [8, 24])
@pytest.mark.parametrize("operation_count", [5, 15])
def test_preparation_is_linear_when_generating_components_and_operations(
    monkeypatch: pytest.MonkeyPatch, component_count: int, operation_count: int
) -> None:
    # Given: both batches expand nullable references against the complete component map.
    definitions: dict[str, JsonValue] = {"Leaf": {"type": "string"}}
    for index in range(component_count - 1):
        definitions[f"Model{index}"] = {
            "type": "object",
            "properties": {"value": {"anyOf": [{"$ref": "#/$defs/Leaf"}, {"type": "null"}]}},
        }
    registry = OpenAPIRegistry()
    for index in range(operation_count):
        registry.set(
            f"operation{index}",
            {
                "route": f"operation{index}",
                "method": "post",
                "request_body": {
                    "$defs": definitions if index == 0 else {},
                    "anyOf": [{"$ref": "#/$defs/Model0"}, {"type": "null"}],
                },
                "response": {
                    200: {"content": {"application/json": {"schema": {"$ref": "#/$defs/Model0"}}}}
                },
            },
        )
    calls = 0

    def counting_prepare(
        schema: dict[str, JsonValue], lossy: list[str] | None, location: str = ""
    ) -> dict[str, JsonValue]:
        nonlocal calls
        calls += 1
        return _prepare_schema_for_3_0(schema, lossy, location)

    monkeypatch.setattr(conversion, "_prepare_schema_for_3_0", counting_prepare)

    # When
    spec = generate_openapi_spec(registry=registry, openapi_version="3.0.0")

    # Then
    assert len(spec["components"]["schemas"]) == component_count
    assert len(spec["paths"]) == operation_count
    assert calls <= 3 * (component_count + operation_count)


def test_component_batches_keep_preparation_and_conversion_message_order() -> None:
    # Given: preparation losses precede conversion losses within each component.
    schemas: dict[str, JsonValue] = {
        "Tuple": {
            "type": "array",
            "items": [{"type": "string"}, {"type": "integer"}],
            "contains": {"type": "string"},
        },
        "Object": {"type": "object", "propertyNames": {"maxLength": 3}},
        "Boolean": False,
    }
    expected_schemas: dict[str, JsonValue] = {}
    expected_messages: list[str] = []
    for name, schema in schemas.items():
        losses: list[str] = []
        expected_schemas[name] = (
            conversion._convert_schema_to_3_0(schema, schemas, lossy=losses)
            if isinstance(schema, dict)
            else schema
        )
        expected_messages.extend(f"Schema '{name}': {message}" for message in losses)
    before = copy.deepcopy(schemas)

    # When
    converted, messages = conversion._convert_schemas_to_3_0(schemas)

    # Then
    assert converted == expected_schemas
    assert messages == expected_messages
    assert schemas == before


NULLABLE_X = {"anyOf": [{"$ref": "#/components/schemas/X"}, {"type": "null"}]}
X_LOSS = (
    "Schema 'X': dropped 'propertyNames' at /propertyNames: "
    "OpenAPI 3.0 does not define it; key names are no longer restricted"
)


def test_compatibility_wrapper_reports_what_an_expanded_reference_drops() -> None:
    # Given: a raw component map, as an external caller of the wrapper would pass it.
    schemas: dict[str, JsonValue] = {"X": {"type": "object", "propertyNames": {"maxLength": 2}}}
    node = {"properties": {"first": NULLABLE_X, "second": NULLABLE_X}}
    before = copy.deepcopy(schemas)
    losses: list[str] = []

    # When
    converted = conversion._convert_schema_to_3_0(node, schemas, lossy=losses)

    # Then: the dropped keyword is neither kept nor silent, and a repeated expansion adds nothing.
    assert converted["properties"]["first"] == {"type": "object", "nullable": True}
    assert converted["properties"]["second"] == {"type": "object", "nullable": True}
    assert losses == [X_LOSS]
    assert schemas == before


def test_batch_conversions_report_a_component_once_however_often_it_is_expanded() -> None:
    # Given: an inline slot and another component both expand the same nullable reference.
    schemas: dict[str, Any] = {
        "X": {"type": "object", "propertyNames": {"maxLength": 2}},
        "Y": {"type": "object", "properties": {"x": NULLABLE_X}},
    }
    paths = {
        "/a": {"post": {"requestBody": {"content": {"application/json": {"schema": NULLABLE_X}}}}}
    }

    # When
    operation_losses = conversion._convert_operation_schemas_to_3_0(paths, schemas)
    _, component_losses = conversion._convert_schemas_to_3_0(schemas)

    # Then: components are reported by their own pass, not by the places that expand them.
    assert operation_losses == []
    assert component_losses == [X_LOSS]


def test_compatibility_wrapper_keeps_its_signature() -> None:
    # Given / When
    parameters = inspect.signature(conversion._convert_schema_to_3_0).parameters

    # Then
    assert list(parameters) == ["schema", "schemas", "resolving", "lossy"]
    assert parameters["schema"].default is inspect.Parameter.empty
    assert parameters["schemas"].default is None
    assert parameters["resolving"].default == frozenset()
    assert parameters["lossy"].default is None
