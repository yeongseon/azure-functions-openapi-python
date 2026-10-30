from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel
import pytest
from test_bridge_endpoint_v2 import make_app, media

from azure_functions_openapi.bridge import _merge_into_existing, scan_endpoint_metadata
from azure_functions_openapi.decorator import register_openapi_metadata
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import generate_openapi_spec


def test_union_when_shared_media_and_headers_match() -> None:
    # Given
    explicit: dict[str, Any] = {
        "description": "explicit",
        "content": media(),
        "headers": {"location": {"schema": {"type": "string"}, "description": "explicit"}},
    }
    explicit["content"]["application/json"]["example"] = {"id": 1}
    discovered = {
        "description": "producer",
        "content": {**media(), "application/problem+json": {"schema": {"type": "object"}}},
        "headers": {
            "Location": {"schema": {"type": "string"}, "description": "producer"},
            "X-Id": {"schema": {"type": "integer"}},
        },
    }
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        path="/api/users", method="post", response={201: explicit}, registry=reg
    )
    payload = {"version": 2, "responses": {"201": discovered, "404": {"content": {}}}}
    original = copy.deepcopy(payload)
    app = make_app(payload)
    # When
    scan_endpoint_metadata(app, registry=reg)
    scan_endpoint_metadata(app, registry=reg)
    spec = generate_openapi_spec(registry=reg, strict=True)
    # Then
    responses = spec["paths"]["/api/users"]["post"]["responses"]
    assert set(responses) == {"201", "404"}
    assert responses["201"]["description"] == "explicit"
    assert set(responses["201"]["content"]) == {"application/json", "application/problem+json"}
    assert responses["201"]["content"]["application/json"]["example"] == {"id": 1}
    assert responses["201"]["headers"] == {
        "location": {"schema": {"type": "string"}, "description": "explicit"},
        "X-Id": {"schema": {"type": "integer"}},
    }
    assert payload == original


@pytest.mark.parametrize(
    ("explicit", "discovered", "context"),
    [
        ({"content": media()}, {"content": media({"type": "string"})}, "media application/json"),
        (
            {"content": media()},
            {"content": {"text/plain": {"schema": {"type": "string"}}}},
            "media types",
        ),
        ({"description": "empty"}, {"content": media()}, "body-less"),
        ({"content": media()}, {"content": {}}, "body-less"),
        (
            {"content": media(), "headers": {"location": {"schema": {"type": "integer"}}}},
            {"content": media(), "headers": {"Location": {"schema": {"type": "string"}}}},
            "header Location",
        ),
    ],
)
def test_conflict_when_runtime_response_contract_differs(
    explicit: dict[str, Any], discovered: dict[str, Any], context: str
) -> None:
    # Given
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        path="/api/users", method="post", response={201: explicit}, registry=reg
    )
    app = make_app({"version": 2, "responses": {"201": discovered}})
    # When / Then
    with pytest.raises(OpenAPISpecConfigError) as exc:
        scan_endpoint_metadata(app, registry=reg)
    assert all(part in str(exc.value) for part in ("POST /api/users", "status 201", context))


def test_bodyless_merge_when_only_prose_differs() -> None:
    # Given
    existing = {"response": {"204": {"description": "explicit"}}}
    # When
    _merge_into_existing(existing, {"response": {204: {"description": "producer"}}})
    # Then
    assert existing["response"] == {"204": {"description": "explicit"}}


def test_inference_is_superseded_when_v2_is_discovered() -> None:
    # Given
    existing: dict[str, Any] = {
        "_response_inferred": True,
        "response_model": str,
        "response": {200: {"content": media({"type": "string"})}},
    }
    # When
    _merge_into_existing(existing, {"response": {204: {"description": ""}}})
    # Then
    assert existing["response"] == {204: {"description": ""}}
    assert existing["response_model"] is None
    assert "_response_inferred" not in existing


class Result(BaseModel):
    id: int


def test_response_model_keeps_json_when_discovered_media_fills_gap() -> None:
    # Given
    reg = OpenAPIRegistry()
    register_openapi_metadata(path="/api/users", method="post", response_model=Result, registry=reg)
    content = media(Result.model_json_schema())
    content["text/plain"] = {"schema": {"type": "string"}}
    app = make_app(
        {
            "version": 2,
            "responses": {
                "201": {"content": content, "headers": {"Location": {"schema": {"type": "string"}}}}
            },
        }
    )
    # When
    scan_endpoint_metadata(app, registry=reg)
    spec = generate_openapi_spec(registry=reg, strict=True)
    # Then
    response = spec["paths"]["/api/users"]["post"]["responses"]["201"]
    assert set(response["content"]) == {"application/json", "text/plain"}
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Result"
    }
    assert response["headers"]["Location"]["schema"] == {"type": "string"}
