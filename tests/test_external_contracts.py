"""External OpenAPI validation and serialization contract tests.

``openapi-spec-validator>=0.9.0`` ships the official OpenAPI 3.2 schema and
validates 3.2-only ``querystring``, ``query``, ``additionalOperations``, and
``itemSchema`` constructs. The library's strict checks remain a complementary
authoring diagnostic; the external validator supplies the independent schema
contract exercised here.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any
import warnings

from openapi_spec_validator import validate
from pydantic import BaseModel
import pytest
import yaml

from azure_functions_openapi import (
    OpenAPIRegistry,
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
    register_openapi_metadata,
)


class _Event(BaseModel):
    sequence: int
    message: str


def _representative_registry() -> OpenAPIRegistry:
    registry = OpenAPIRegistry()
    register_openapi_metadata(
        "/contracts/{contract_id}",
        "get",
        summary="Values such as on, 2026-10-09, and 1.0 stay strings.",
        parameters=[
            {
                "name": "contract_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "example": "001"},
            }
        ],
        response={200: {"description": "yes"}},
        registry=registry,
    )
    return registry


def _openapi_32_registry() -> OpenAPIRegistry:
    registry = OpenAPIRegistry()
    register_openapi_metadata(
        "/search",
        "query",
        querystring={"type": "object", "properties": {"q": {"type": "string"}}},
        registry=registry,
    )
    register_openapi_metadata("/cache", "purge", registry=registry)
    register_openapi_metadata(
        "/events",
        "get",
        response={
            200: {
                "description": "Event stream",
                "content": {"text/event-stream": {"itemSchema": _Event}},
            }
        },
        registry=registry,
    )
    return registry


def test_openapi_32_only_constructs_pass_external_validation_without_warnings() -> None:
    # Given
    registry = _openapi_32_registry()

    # When
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        spec = generate_openapi_spec(
            title="External contract API",
            openapi_version="3.2.0",
            route_prefix="",
            strict=True,
            registry=registry,
        )

    # Then
    validate(spec)
    querystring = spec["paths"]["/search"]["query"]["parameters"][0]
    assert querystring["name"]
    assert querystring["in"] == "querystring"
    assert len(querystring["content"]) == 1
    assert set(spec["paths"]["/cache"]["additionalOperations"]) == {"PURGE"}
    assert spec["paths"]["/events"]["get"]["responses"]["200"]["content"]["text/event-stream"][
        "itemSchema"
    ] == {"$ref": "#/components/schemas/_Event"}


@pytest.mark.parametrize("openapi_version", ["3.0.0", "3.1.0", "3.2.0"])
@pytest.mark.parametrize(
    ("serializer", "loader"),
    [(get_openapi_json, json.loads), (get_openapi_yaml, yaml.safe_load)],
    ids=["json", "yaml"],
)
def test_serialized_document_round_trips_to_exact_generated_dict(
    openapi_version: str,
    serializer: Callable[..., str],
    loader: Callable[[str], dict[str, Any]],
) -> None:
    # Given
    registry = _representative_registry()
    expected = generate_openapi_spec(
        title="Round-trip API",
        version="2026-10-09",
        description="on",
        openapi_version=openapi_version,
        route_prefix="",
        strict=True,
        registry=registry,
    )

    # When
    document = loader(
        serializer(
            title="Round-trip API",
            version="2026-10-09",
            description="on",
            openapi_version=openapi_version,
            route_prefix="",
            strict=True,
            registry=registry,
        )
    )

    # Then
    assert document == expected
