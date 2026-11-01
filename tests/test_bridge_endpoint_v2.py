from __future__ import annotations

import copy
from typing import Any

import azure.functions as func
import pytest

from azure_functions_openapi._endpoint_contract import read_v2_responses
from azure_functions_openapi._warnings import WarningCode
from azure_functions_openapi.bridge import (
    _discovered_operation_from_endpoint,
    scan_endpoint_metadata,
)
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec


def make_app(payload: dict[str, Any], route: str = "users") -> func.FunctionApp:
    app = func.FunctionApp()

    def handler(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse()

    setattr(handler, "_azure_functions_metadata", {"endpoint": payload})
    app.route(route=route, methods=["POST"])(handler)
    return app


def media(schema: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"application/json": {"schema": schema if schema is not None else {"type": "object"}}}


def test_v2_representation_when_synthetic_producer_is_scanned() -> None:
    # Given
    payload: dict[str, Any] = {
        "version": 2,
        "responses": {
            "201": {"content": media(), "headers": {"Location": {"schema": {"type": "string"}}}},
            "400": {"content": {"application/problem+json": {"schema": {"type": "object"}}}},
            "204": {"content": {}},
            "200": {"content": {"text/event-stream": {"schema": {"type": "string"}}}},
        },
    }
    original = copy.deepcopy(payload)
    reg = OpenAPIRegistry()
    # When
    scan_endpoint_metadata(make_app(payload), registry=reg)
    spec = generate_openapi_spec(registry=reg, strict=True)
    # Then
    responses = spec["paths"]["/api/users"]["post"]["responses"]
    assert responses["201"]["headers"]["Location"]["schema"] == {"type": "string"}
    assert responses["400"]["content"] == payload["responses"]["400"]["content"]
    assert responses["204"] == {"description": ""}
    assert responses["200"]["content"] == payload["responses"]["200"]["content"]
    assert payload == original


def test_read_v2_responses_hands_back_copies_of_the_producer_schemas() -> None:
    # Given
    payload: dict[str, Any] = {
        "version": 2,
        "responses": {
            "200": {
                "content": media({"type": "object", "properties": {"a": {"type": "string"}}}),
                "headers": {"X-Id": {"schema": {"type": "string", "enum": ["a"]}}},
            }
        },
    }
    original = copy.deepcopy(payload)

    # When
    responses, diagnostics = read_v2_responses(payload)
    detail = responses[200]
    detail["content"]["application/json"]["schema"]["properties"]["a"]["type"] = "integer"
    detail["headers"]["X-Id"]["schema"]["enum"].append("b")

    # Then
    assert diagnostics == []
    assert payload == original


@pytest.mark.parametrize(
    "detail",
    [
        {},
        {"schema": {}},
        {"content": None},
        {"content": []},
        {"content": {"application/json": {}}},
        {"content": {"application/json": {"schema": None}}},
        {"content": {"bad": {"schema": {}}}},
        {"content": {"application/json,garbage": {"schema": {}}}},
        {"content": {'text/"plain"': {"schema": {}}}},
        {"content": {"application/\u00fc": {"schema": {}}}},
        {"content": {"application/json\n": {"schema": {}}}},
        {"content": {"application/": {"schema": {}}}},
        {"content": {"/json": {"schema": {}}}},
        {
            "content": {
                "application/json": {"schema": {"type": "string"}},
                "Application/JSON": {"schema": {"type": "object"}},
            }
        },
        {"content": {1: {"schema": {}}}},
        {"content": media(), "description": None},
        {"content": media(), "headers": None},
        {"content": media(), "headers": {"X-Id": {}}},
        {"content": media(), "headers": {"X-Id": {"schema": {}, "description": 1}}},
        {"content": media(), "headers": {"X-Id": {"schema": {}}, "x-id": {"schema": {}}}},
        {"content": media(), "headers": {"Content-Type": {"schema": {}}}},
        {"content": media(), "headers": {"bad name": {"schema": {}}}},
        "bad",
    ],
)
def test_malformed_response_when_valid_sibling_exists(detail: Any) -> None:
    # Given
    payload = {
        "version": 2,
        "request_body": {"type": "object"},
        "responses": {"201": detail, "400": {"content": media()}},
    }
    reg = OpenAPIRegistry()
    # When
    scan_endpoint_metadata(make_app(payload), registry=reg)
    spec = generate_openapi_spec(registry=reg)
    # Then
    operation = spec["paths"]["/api/users"]["post"]
    assert set(operation["responses"]) == {"400"}
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {"type": "object"}
    warnings = collect_spec_warnings(spec, registry=reg)
    assert any(
        w.code == WarningCode.DISCOVERY_SKIPPED and "v2 responses.201" in w.message
        for w in warnings
    )


@pytest.mark.parametrize(
    "media_type", ["application/*", "*/*", "application/vnd.api+json", "text/event-stream"]
)
def test_media_type_is_accepted_when_both_halves_are_tokens(media_type: str) -> None:
    # Given
    payload = {"version": 2, "responses": {"200": {"content": {media_type: {"schema": {}}}}}}
    # When
    operation = _discovered_operation_from_endpoint("handler", payload, "/users", "post")
    # Then
    assert list(operation["response"][200]["content"]) == [media_type]
    assert operation["_endpoint_warnings"] == []


@pytest.mark.parametrize("status", [200, True, "199", "600", "0200", "default"])
def test_status_is_skipped_when_not_a_v2_status_string(status: Any) -> None:
    # Given
    payload = {"version": 2, "responses": {status: {"content": media()}}}
    # When
    operation = _discovered_operation_from_endpoint("handler", payload, "/users", "post")
    # Then
    assert operation["response"] == {}
    assert operation["_endpoint_warnings"]


@pytest.mark.parametrize("status", ["204", "205", "304"])
def test_response_is_skipped_when_status_forbids_body(status: str) -> None:
    # Given
    payload = {"version": 2, "responses": {status: {"content": media()}}}
    # When
    operation = _discovered_operation_from_endpoint("handler", payload, "/users", "post")
    # Then
    assert operation["response"] == {}
    assert operation["_endpoint_warnings"]


def test_allowlist_when_unknown_fields_are_present() -> None:
    # Given
    payload = {
        "version": 2,
        "future": True,
        "x-extra": True,
        "responses": {
            "201": {
                "content": {"application/json": {"schema": {"type": "null"}, "example": None}},
                "headers": {"Location": {"schema": {}, "description": "link", "future": True}},
                "future": True,
            }
        },
    }
    # When
    operation = _discovered_operation_from_endpoint("handler", payload, "/users", "post")
    # Then
    assert operation["response"][201] == {
        "description": "",
        "content": media({"type": "null"}),
        "headers": {"Location": {"schema": {}, "description": "link"}},
    }
    assert len(operation["_endpoint_warnings"]) == 4


def test_responses_are_skipped_when_mapping_is_malformed() -> None:
    # Given
    payload = {"version": 2, "responses": []}
    # When
    operation = _discovered_operation_from_endpoint("handler", payload, "/users", "post")
    # Then
    assert operation["response"] == {}
    assert operation["_endpoint_warnings"]
