from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel
import pytest
from test_bridge_endpoint_v2 import make_app, media

from azure_functions_openapi.bridge import (
    _merge_into_existing,
    _merge_response_detail,
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


@pytest.mark.parametrize("detail", [None, [], "x", 1], ids=["none", "list", "string", "int"])
def test_non_mapping_explicit_response_entry_is_left_as_declared(detail: Any) -> None:
    # Given
    existing: dict[str, Any] = {"response": {200: detail}}
    # When
    _merge_into_existing(existing, {"response": {200: {"content": media()}}})
    # Then
    assert existing["response"] == {200: detail}


@pytest.mark.parametrize("detail", [None, [], "x", 1], ids=["none", "list", "string", "int"])
def test_non_mapping_discovered_response_entry_does_not_replace_the_explicit_one(
    detail: Any,
) -> None:
    # Given
    existing: dict[str, Any] = {"response": {200: {"content": media()}}}
    # When
    _merge_into_existing(existing, {"response": {200: detail}})
    # Then
    assert existing["response"] == {200: {"content": media()}}


def test_scan_keeps_a_non_mapping_explicit_response_entry() -> None:
    # Given
    reg = OpenAPIRegistry()
    explicit: Any = {200: None}
    register_openapi_metadata(path="/api/users", method="post", response=explicit, registry=reg)
    payload = {"version": 1, "responses": {"200": {"schema": {"type": "object"}}}}
    # When
    scan_endpoint_metadata(make_app(payload), registry=reg)
    # Then
    (entry,) = reg.snapshot().values()
    assert entry["response"] == {200: None}


def test_explicit_response_map_shared_by_two_registries_is_not_written_through() -> None:
    # Given: one explicit declaration object registered in two independent registries.
    shared: dict[Any, Any] = {200: {"content": media()}}
    original = copy.deepcopy(shared)
    first, second = OpenAPIRegistry(), OpenAPIRegistry()
    discoveries = ((first, "first", "object"), (second, "second", "string"))
    for registry, _, _ in discoveries:
        register_openapi_metadata(
            path="/api/users", method="post", response=shared, registry=registry
        )

    # When: each registry discovers a different description and a different extra media schema.
    for registry, description, schema_type in discoveries:
        payload = {
            "version": 2,
            "responses": {
                "200": {
                    "description": description,
                    "content": {
                        **media(),
                        "application/problem+json": {"schema": {"type": schema_type}},
                    },
                }
            },
        }
        scan_endpoint_metadata(make_app(payload), registry=registry)

    # Then: the caller's map is untouched and each registry keeps only its own discovery.
    assert shared == original
    for registry, description, schema_type in discoveries:
        spec = generate_openapi_spec(registry=registry, strict=True)
        response = spec["paths"]["/api/users"]["post"]["responses"]["200"]
        assert response["description"] == description
        assert response["content"]["application/problem+json"]["schema"] == {"type": schema_type}


@pytest.mark.parametrize("reverse", [False, True], ids=["declared-order", "reversed-order"])
def test_media_entries_sharing_one_dictionary_are_filled_independently(reverse: bool) -> None:
    # Given: an explicit declaration that reuses one empty media template for two media types.
    shared: dict[str, Any] = {}
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        path="/api/users",
        method="post",
        response={200: {"content": {"application/json": shared, "text/plain": shared}}},
        registry=reg,
    )
    content = {**media(), "text/plain": {"schema": {"type": "string"}}}
    if reverse:
        content = dict(reversed(content.items()))
    app = make_app({"version": 2, "responses": {"200": {"content": content}}})

    # When / Then: every scan gives each media type the schema its producer declared.
    for _ in range(3):
        scan_endpoint_metadata(app, registry=reg)
        spec = generate_openapi_spec(registry=reg, strict=True)
        response = spec["paths"]["/api/users"]["post"]["responses"]["200"]
        assert {name: entry["schema"] for name, entry in response["content"].items()} == {
            "application/json": {"type": "object"},
            "text/plain": {"type": "string"},
        }
    assert shared == {}


def test_header_entries_sharing_one_dictionary_are_filled_independently() -> None:
    # Given
    shared: dict[str, Any] = {}
    existing = {"headers": {"X-A": shared, "X-B": shared}}
    discovered = {
        "headers": {"X-A": {"schema": {"type": "string"}}, "X-B": {"schema": {"type": "integer"}}}
    }

    # When
    merged = _merge_response_detail(existing, discovered)

    # Then
    assert merged["headers"] == discovered["headers"]
    assert shared == {}


@pytest.mark.parametrize("reverse", [False, True], ids=["declared-order", "reversed-order"])
def test_explicit_header_case_variants_with_different_schemas_conflict(reverse: bool) -> None:
    # Given: one explicit header declared under two spellings with different schemas.
    pairs = [("X-Id", {"schema": {"type": "integer"}}), ("x-id", {"schema": {"type": "string"}})]
    if reverse:
        pairs.reverse()
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        path="/api/users",
        method="post",
        response={200: {"content": media(), "headers": dict(pairs)}},
        registry=reg,
    )
    app = make_app(
        {
            "version": 2,
            "responses": {
                "200": {"content": media(), "headers": {"x-id": {"schema": {"type": "string"}}}}
            },
        }
    )

    # When / Then: neither order silently selects one variant, on any scan.
    for _ in range(3):
        with pytest.raises(OpenAPISpecConfigError, match="header x-id declared with different"):
            scan_endpoint_metadata(app, registry=reg)


def test_explicit_header_case_variants_with_one_schema_are_accepted() -> None:
    # Given
    schema = {"schema": {"type": "string"}}
    existing = {
        "response": {200: {"content": media(), "headers": {"X-Id": schema, "x-id": schema}}}
    }
    discovered = {"response": {200: {"content": media(), "headers": {"x-id": schema}}}}

    # When
    _merge_into_existing(existing, discovered)

    # Then
    assert set(existing["response"][200]["headers"]) == {"X-Id", "x-id"}


def test_merged_detail_does_not_share_nested_data_with_the_explicit_one() -> None:
    # Given
    existing = {"content": media(), "x-extra": {"a": 1}}

    # When
    merged = _merge_response_detail(existing, {"content": media()})
    merged["x-extra"]["a"] = 2
    merged["content"]["application/json"]["schema"]["type"] = "array"

    # Then
    assert existing == {"content": media(), "x-extra": {"a": 1}}


@pytest.mark.parametrize("field", ["content", "headers"])
@pytest.mark.parametrize("has_other_entry", [False, True], ids=["no-map", "other-entry"])
def test_new_entries_are_copied_from_the_discovered_detail(
    field: str, has_other_entry: bool
) -> None:
    # Given: discovery adds an entry to a response that has no such map, or has another entry.
    entry = {"schema": {"type": "object", "properties": {"a": {"type": "string"}}}}
    existing: dict[str, Any] = (
        {field: {"X-Old": {"schema": {"type": "string"}}}} if has_other_entry else {}
    )
    discovered = {field: {"X-New": copy.deepcopy(entry)}}

    # When
    merged = _merge_response_detail(existing, discovered)
    merged[field]["X-New"]["schema"]["properties"]["a"]["type"] = "integer"

    # Then
    assert discovered == {field: {"X-New": entry}}


def test_gap_filled_values_are_copied_from_the_discovered_entry() -> None:
    # Given: an explicit media entry without a schema, and a discovered schema for it.
    discovered = {"content": media({"type": "object", "properties": {"a": {"type": "string"}}})}
    original = copy.deepcopy(discovered)

    # When
    merged = _merge_response_detail({"content": {"application/json": {}}}, discovered)
    merged["content"]["application/json"]["schema"]["properties"]["a"]["type"] = "integer"

    # Then
    assert discovered == original


def test_discovered_detail_for_a_new_status_is_copied() -> None:
    # Given
    existing: dict[str, Any] = {"response": {}}
    discovered = {"response": {201: {"content": media()}}}

    # When
    _merge_into_existing(existing, discovered)
    existing["response"][201]["content"]["application/json"]["schema"]["type"] = "array"

    # Then
    assert discovered["response"][201]["content"] == media()


def test_merge_ignores_discovered_headers_and_content_that_are_not_mappings() -> None:
    # Given
    existing: dict[str, Any] = {
        "content": media(),
        "headers": {"X-Id": {"schema": {"type": "integer"}}},
    }
    # When
    merged = _merge_response_detail(existing, {"content": "x", "headers": None})
    # Then
    assert merged == existing


@pytest.mark.parametrize(
    ("current_key", "incoming_key"), [(1, "1"), ("1", 1)], ids=["explicit-int", "discovered-int"]
)
def test_merge_matches_header_names_by_their_text(current_key: Any, incoming_key: Any) -> None:
    # Given
    existing = {"headers": {current_key: {"schema": {"type": "string"}}}}
    discovered = {"headers": {incoming_key: {"schema": {"type": "string"}, "description": "d"}}}
    # When
    merged = _merge_response_detail(existing, discovered)
    # Then
    assert merged["headers"] == {current_key: {"schema": {"type": "string"}, "description": "d"}}


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
