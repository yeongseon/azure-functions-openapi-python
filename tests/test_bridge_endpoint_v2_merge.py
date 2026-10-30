from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel
import pytest
from test_bridge_endpoint_v2 import make_app, media

from azure_functions_openapi.bridge import (
    _merge_into_existing,
    _response_details_conflict,
    scan_endpoint_metadata,
)
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
        ({"content": {"application/json": {}}}, {"content": {}}, "body-less"),
        (
            {"content": {"Application/JSON": {"schema": {"type": "object"}}}},
            {"content": media({"type": "string"})},
            "media application/json",
        ),
        (
            {"content": {"application/json": {}}},
            {"content": {"text/plain": {"schema": {"type": "string"}}}},
            "media types",
        ),
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


def test_media_types_merge_case_insensitively_and_keep_the_explicit_spelling() -> None:
    # Given: the same media type spelled differently, with another media type on the explicit side.
    explicit = {
        "content": {
            "Application/JSON": {"schema": {"type": "object"}, "example": {"id": 1}},
            "text/plain": {"schema": {"type": "string"}},
        }
    }
    discovered = {
        "content": {
            "application/json": {"schema": {"type": "object"}},
            "text/csv": {"schema": {"type": "string"}},
        }
    }
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        path="/api/users", method="post", response={200: explicit}, registry=reg
    )

    # When
    scan_endpoint_metadata(make_app({"version": 2, "responses": {"200": discovered}}), registry=reg)
    spec = generate_openapi_spec(registry=reg, strict=True)

    # Then: one JSON representation under the explicit spelling, plus both other types.
    content = spec["paths"]["/api/users"]["post"]["responses"]["200"]["content"]
    assert set(content) == {"Application/JSON", "text/plain", "text/csv"}
    assert content["Application/JSON"] == {"schema": {"type": "object"}, "example": {"id": 1}}


@pytest.mark.parametrize("reverse", [False, True], ids=["declared-order", "reversed-order"])
def test_producer_case_variants_with_different_schemas_never_win_silently(reverse: bool) -> None:
    # Given: a producer declaring one media type twice, spelled differently, with two schemas.
    variants = [
        ("application/json", {"schema": {"type": "string"}}),
        ("Application/JSON", {"schema": {"type": "object"}}),
    ]
    content = dict(reversed(variants) if reverse else variants)
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        path="/api/users", method="post", response={200: {"content": media()}}, registry=reg
    )

    # When
    scan_endpoint_metadata(
        make_app({"version": 2, "responses": {"200": {"content": content}}}), registry=reg
    )
    spec = generate_openapi_spec(registry=reg, strict=True)

    # Then: the contradictory response is skipped with a diagnostic and the explicit one stays.
    response = spec["paths"]["/api/users"]["post"]["responses"]["200"]
    assert response["content"] == media()
    assert any("v2 responses.200" in reason for _, reason in reg.discovery_warnings)


@pytest.mark.parametrize("reverse", [False, True], ids=["declared-order", "reversed-order"])
def test_explicit_case_variants_with_different_schemas_conflict(reverse: bool) -> None:
    # Given: an explicit declaration that spells one media type two ways with two schemas.
    variants = [
        ("application/json", {"schema": {"type": "string"}}),
        ("Application/JSON", {"schema": {"type": "object"}}),
    ]
    explicit = {"content": dict(reversed(variants) if reverse else variants)}
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        path="/api/users", method="post", response={200: explicit}, registry=reg
    )

    # When / Then
    with pytest.raises(OpenAPISpecConfigError, match="declared with different schemas"):
        scan_endpoint_metadata(
            make_app({"version": 2, "responses": {"200": {"content": media()}}}), registry=reg
        )


@pytest.mark.parametrize(
    "detail",
    [
        {"content": media(), "headers": None},
        {"content": media(), "headers": {1: {"schema": {}}}},
        {"content": media(), "headers": {"X-Id": None}},
        {"content": media(), "headers": "x"},
    ],
    ids=["headers-none", "header-key-int", "header-entry-none", "headers-string"],
)
def test_malformed_explicit_headers_are_ignored_like_before(detail: dict[str, Any]) -> None:
    # Given
    existing = {"response": {200: detail}}
    # When
    _merge_into_existing(existing, {"response": {200: {"content": media()}}})
    # Then: reconciliation neither crashes nor invents headers.
    assert existing["response"][200]["content"] == media()


@pytest.mark.parametrize("headers", [None, "x", []], ids=["none", "string", "list"])
def test_discovered_headers_replace_malformed_explicit_headers(headers: Any) -> None:
    # Given: an explicit response whose headers entry is not a mapping.
    existing = {"response": {200: {"content": media(), "headers": headers}}}
    discovered = {
        "response": {
            200: {"content": media(), "headers": {"X-Id": {"schema": {"type": "integer"}}}}
        }
    }
    # When
    _merge_into_existing(existing, discovered)
    # Then
    assert existing["response"][200]["headers"] == {"X-Id": {"schema": {"type": "integer"}}}


def test_malformed_explicit_media_entry_is_a_configuration_error() -> None:
    # Given
    existing = {"response": {200: {"content": {"application/json": None}}}}
    # When / Then
    with pytest.raises(OpenAPISpecConfigError, match="malformed media entry"):
        _merge_into_existing(existing, {"response": {200: {"content": media()}}})


def test_schema_less_media_takes_the_discovered_schema() -> None:
    # Given: an explicit body-bearing media type that declares no schema yet.
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        path="/api/users",
        method="post",
        response={200: {"content": {"application/json": {"example": {"id": 1}}}}},
        registry=reg,
    )

    # When
    scan_endpoint_metadata(
        make_app({"version": 2, "responses": {"200": {"content": media()}}}), registry=reg
    )
    spec = generate_openapi_spec(registry=reg, strict=True)

    # Then
    content = spec["paths"]["/api/users"]["post"]["responses"]["200"]["content"]
    assert content["application/json"] == {"example": {"id": 1}, "schema": {"type": "object"}}


def test_response_model_json_survives_a_discovered_disjoint_status() -> None:
    # Given: a model plus a description-only 200, and discovered metadata for a different status.
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        path="/api/users",
        method="post",
        response_model=Result,
        response={200: {"description": "ok"}},
        registry=reg,
    )
    problem = {"application/problem+json": {"schema": {"type": "object"}}}

    # When
    scan_endpoint_metadata(
        make_app({"version": 2, "responses": {"400": {"content": problem}}}), registry=reg
    )
    spec = generate_openapi_spec(registry=reg, strict=True)

    # Then: the compiler still fills the model's JSON representation into the 200 response.
    responses = spec["paths"]["/api/users"]["post"]["responses"]
    assert responses["200"]["description"] == "ok"
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Result"
    }
    assert responses["400"]["content"] == problem


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


def test_response_model_status_gets_the_discovered_media_and_headers() -> None:
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
    assert response["content"]["application/json"]["schema"] == Result.model_json_schema()
    assert response["headers"]["Location"]["schema"] == {"type": "string"}


@pytest.mark.parametrize(("left", "right", "expected"), [(None, {}, True), ({}, {}, False)])
def test_comparison_when_raw_response_details_are_empty(
    left: Any, right: Any, expected: bool
) -> None:
    # Given / When / Then
    assert _response_details_conflict(left, right) is expected


def test_model_merge_when_raw_status_already_exists() -> None:
    # Given
    existing: dict[str, Any] = {"response_model": Result, "response": {201: {"content": media()}}}
    discovered = {
        "response": {
            201: {"content": media(), "headers": {"Location": {"schema": {"type": "string"}}}}
        }
    }
    # When
    _merge_into_existing(existing, discovered)
    # Then
    assert existing["response"][201]["headers"] == {"Location": {"schema": {"type": "string"}}}
