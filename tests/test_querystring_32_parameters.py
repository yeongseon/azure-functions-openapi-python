"""OpenAPI 3.2 `querystring` parameters must be emitted and validated as valid 3.2.

The generator emitted `{"in": "querystring", "content": ...}` with no `name`,
which 3.2 requires on every Parameter Object, and `_validate_spec()` accepted
only path/query/header/cookie — so it flagged the generator's own output,
failing strict generation and `--fail-on-warnings` for valid authoring input.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
import pytest

from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec

_FORM = "application/x-www-form-urlencoded"


class _Query(BaseModel):
    q: str


def _spec(entry: dict[str, Any], version: str = "3.2.0", strict: bool = False) -> dict[str, Any]:
    registry = OpenAPIRegistry()
    registry.set("fn", entry)
    return generate_openapi_spec(
        title="T", registry=registry, openapi_version=version, strict=strict
    )


def _param(spec: dict[str, Any]) -> dict[str, Any]:
    params: list[dict[str, Any]] = spec["paths"]["/api/s"]["get"]["parameters"]
    return next(p for p in params if p.get("in") == "querystring")


@pytest.mark.parametrize(
    "entry",
    [
        {"summary": "s", "method": "get", "route": "s", "querystring_model": _Query},
        {
            "summary": "s",
            "method": "get",
            "route": "s",
            "querystring_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
    ],
    ids=["model-backed", "raw-schema"],
)
def test_emits_one_valid_parameter_object(entry: dict[str, Any]) -> None:
    param = _param(_spec(entry))

    assert param["name"]
    assert param["in"] == "querystring"
    assert set(param) == {"name", "in", "content"}
    assert len(param["content"]) == 1
    assert "schema" in next(iter(param["content"].values()))


def test_valid_32_document_passes_strict_without_spurious_warnings() -> None:
    entry = {"summary": "s", "method": "get", "route": "s", "querystring_model": _Query}
    registry = OpenAPIRegistry()
    registry.set("fn", entry)

    spec = generate_openapi_spec(title="T", registry=registry, openapi_version="3.2.0", strict=True)

    messages = [w.message for w in collect_spec_warnings(spec, registry=registry)]
    assert not [m for m in messages if "Invalid parameter location" in m]


def test_querystring_is_still_rejected_before_32() -> None:
    entry = {"summary": "s", "method": "get", "route": "s", "querystring_model": _Query}
    for version in ("3.0.0", "3.1.0"):
        with pytest.raises(OpenAPISpecConfigError, match="require openapi_version"):
            _spec(entry, version=version)


def test_query_and_querystring_still_cannot_be_mixed() -> None:
    entry = {
        "summary": "s",
        "method": "get",
        "route": "s",
        "querystring_model": _Query,
        "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}],
    }
    with pytest.raises(OpenAPISpecConfigError, match="mixes 'query' and 'querystring'"):
        _spec(entry)


def test_at_most_one_querystring_parameter() -> None:
    raw = {"name": "qs", "in": "querystring", "content": {_FORM: {"schema": {"type": "object"}}}}
    entry = {
        "summary": "s",
        "method": "get",
        "route": "s",
        "querystring_model": _Query,
        "parameters": [raw],
    }
    with pytest.raises(OpenAPISpecConfigError, match="multiple"):
        _spec(entry)


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ({"in": "querystring", "content": {_FORM: {"schema": {}}}}, "non-empty 'name'"),
        ({"name": "qs", "in": "querystring", "schema": {"type": "object"}}, "requires\n?'?content"),
        ({"name": "qs", "in": "querystring", "content": {}}, "exactly one"),
        (
            {
                "name": "qs",
                "in": "querystring",
                "content": {_FORM: {"schema": {}}, "application/json": {"schema": {}}},
            },
            "exactly one",
        ),
    ],
    ids=["missing-name", "schema-instead-of-content", "zero-media-types", "two-media-types"],
)
def test_raw_querystring_authoring_is_enforced(raw: dict[str, Any], match: str) -> None:
    entry = {"summary": "s", "method": "get", "route": "s", "parameters": [raw]}
    with pytest.raises(OpenAPISpecConfigError):
        _spec(entry)


def test_a_well_formed_raw_querystring_parameter_is_accepted() -> None:
    raw = {"name": "qs", "in": "querystring", "content": {_FORM: {"schema": {"type": "object"}}}}
    entry = {"summary": "s", "method": "get", "route": "s", "parameters": [raw]}

    param = _param(_spec(entry, strict=True))

    assert param["name"] == "qs"
    assert list(param["content"]) == [_FORM]
