"""Explicit schema failures and skipped operations must be observable.

Conversion failures on an explicitly supplied `request_model`/`response_model`
used to be swallowed — a generic schema or the default response was substituted
even under `strict=True` — and a malformed registry entry was dropped from the
document with nothing but a log line. Neither loss survives into the finished
spec, so `collect_spec_warnings()` could not reconstruct it afterwards.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import (
    get_openapi_registry,
    openapi,
    register_openapi_metadata,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    collect_spec_warnings,
    generate_openapi_report,
    generate_openapi_spec,
)


class _Unconvertible:
    """Neither a Pydantic v2 model nor a usable type hint."""


class _Filter(BaseModel):
    query: str


class _RequestModel(BaseModel):
    name: str


class _ResponseModel(BaseModel):
    identifier: int


def _codes(spec: dict[str, Any], registry: OpenAPIRegistry) -> set[str]:
    return {w.code.value for w in collect_spec_warnings(spec, registry=registry)}


def _registry_with(entry: dict[str, Any], key: str = "fn") -> OpenAPIRegistry:
    registry = OpenAPIRegistry()
    registry.set(key, entry)
    return registry


_RESPONSE_FAILURE = {
    "summary": "s",
    "method": "get",
    "path": "/thing",
    "response_model": _Unconvertible(),
}
_REQUEST_FAILURE = {
    "summary": "s",
    "method": "post",
    "path": "/thing",
    "request_model": _Unconvertible(),
}
# ``parameters`` must be iterable; an int raises TypeError mid-entry.
_MALFORMED = {"summary": "s", "method": "get", "path": "/boom", "parameters": 123}


@pytest.mark.parametrize("entry", [_RESPONSE_FAILURE, _REQUEST_FAILURE])
def test_strict_fails_on_explicit_model_conversion(entry: dict[str, Any]) -> None:
    registry = _registry_with(entry)

    with pytest.raises(OpenAPISpecConfigError) as excinfo:
        generate_openapi_spec(title="T", registry=registry, strict=True)

    assert "fn" in str(excinfo.value)
    assert excinfo.value.__cause__ is not None


@pytest.mark.parametrize(
    ("entry", "fragment"),
    [(_RESPONSE_FAILURE, "response model"), (_REQUEST_FAILURE, "request model")],
)
def test_non_strict_records_the_substitution(entry: dict[str, Any], fragment: str) -> None:
    registry = _registry_with(entry)
    spec = generate_openapi_spec(title="T", registry=registry)

    assert "schema-substitution" in _codes(spec, registry)
    warning = next(
        w
        for w in collect_spec_warnings(spec, registry=registry)
        if w.code.value == "schema-substitution"
    )
    assert warning.function_name == "fn"
    assert fragment in warning.message


def test_non_strict_records_a_skipped_operation() -> None:
    registry = _registry_with(_MALFORMED, key="boom")
    spec = generate_openapi_spec(title="T", registry=registry)

    assert spec.get("paths") in ({}, None)
    warning = next(
        w
        for w in collect_spec_warnings(spec, registry=registry)
        if w.code.value == "operation-skipped"
    )
    assert warning.function_name == "boom"
    assert "TypeError" in warning.message


def test_strict_still_raises_for_a_malformed_entry() -> None:
    registry = _registry_with(_MALFORMED, key="boom")
    with pytest.raises(TypeError):
        generate_openapi_spec(title="T", registry=registry, strict=True)


def test_report_surfaces_the_substitution() -> None:
    registry = _registry_with(_RESPONSE_FAILURE)
    report = generate_openapi_report(title="T", registry=registry)

    assert "schema-substitution" in {w.code.value for w in report.warnings}


def test_a_corrected_entry_drops_the_stale_warning() -> None:
    registry = _registry_with(_RESPONSE_FAILURE)
    first = generate_openapi_spec(title="T", registry=registry)
    assert "schema-substitution" in _codes(first, registry)

    registry.set("fn", {"summary": "s", "method": "get", "path": "/thing"})
    second = generate_openapi_spec(title="T", registry=registry)

    assert "schema-substitution" not in _codes(second, registry)


def test_warnings_do_not_leak_between_registries() -> None:
    degraded = _registry_with(_RESPONSE_FAILURE)
    healthy = _registry_with({"summary": "s", "method": "get", "path": "/ok"}, key="ok")

    degraded_spec = generate_openapi_spec(title="T", registry=degraded)
    healthy_spec = generate_openapi_spec(title="T", registry=healthy)

    assert "schema-substitution" in _codes(degraded_spec, degraded)
    assert "schema-substitution" not in _codes(healthy_spec, healthy)


def test_strict_rejects_request_model_on_bodyless_method() -> None:
    registry = OpenAPIRegistry()
    register_openapi_metadata("/search", "GET", request_model=_Filter, registry=registry)

    with pytest.raises(OpenAPISpecConfigError, match="GET /api/search"):
        generate_openapi_spec(registry=registry, strict=True)


def test_non_strict_warns_when_request_model_is_dropped() -> None:
    registry = OpenAPIRegistry()
    register_openapi_metadata("/search", "GET", request_model=_Filter, registry=registry)

    spec = generate_openapi_spec(registry=registry)

    assert "requestBody" not in spec["paths"]["/api/search"]["get"]
    warning = next(
        warning
        for warning in collect_spec_warnings(spec, registry=registry)
        if warning.code.value == "schema-substitution"
    )
    assert "request model" in warning.message
    assert "GET /api/search" in warning.message


def test_strict_decorator_request_failure_identifies_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @openapi(route="widgets/{id}", method="PATCH", requests=_RequestModel)
    def update_widget() -> None:
        pass

    registry = _registry_with(
        {
            **get_openapi_registry()[update_widget.__name__],
            "function_name": update_widget.__name__,
        },
        key=update_widget.__name__,
    )
    failure = TypeError("request conversion failed")

    def fail_conversion(model: Any, components: dict[str, Any]) -> dict[str, Any]:
        raise failure

    monkeypatch.setattr("azure_functions_openapi.spec.model_to_schema", fail_conversion)

    with pytest.raises(OpenAPISpecConfigError) as excinfo:
        generate_openapi_spec(
            registry=registry,
            route_prefix="/v1",
            strict=True,
        )

    message = str(excinfo.value)
    assert "PATCH /v1/widgets/{id}" in message
    assert "update_widget" in message
    assert "request body" in message
    assert excinfo.value.__cause__ is failure


def test_strict_programmatic_response_failure_identifies_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = OpenAPIRegistry()
    register_openapi_metadata(
        "/widgets",
        "POST",
        response_model=_ResponseModel,
        response={201: {"description": "Created"}},
        registry=registry,
    )
    failure = TypeError("response conversion failed")

    def fail_conversion(model: Any, components: dict[str, Any]) -> dict[str, Any]:
        raise failure

    monkeypatch.setattr("azure_functions_openapi.spec.model_to_schema", fail_conversion)

    with pytest.raises(OpenAPISpecConfigError) as excinfo:
        generate_openapi_spec(registry=registry, strict=True)

    message = str(excinfo.value)
    assert "POST /api/widgets" in message
    assert "post::/widgets" in message
    assert "response 201" in message
    assert excinfo.value.__cause__ is failure


def test_non_strict_schema_warnings_carry_context_in_deterministic_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = OpenAPIRegistry()
    register_openapi_metadata(
        "/z-response",
        "PUT",
        response_model=_ResponseModel,
        response={202: {"description": "Accepted"}},
        registry=registry,
    )
    register_openapi_metadata(
        "/a-request",
        "POST",
        request_model=_RequestModel,
        registry=registry,
    )

    def fail_conversion(model: Any, components: dict[str, Any]) -> dict[str, Any]:
        raise TypeError("conversion failed")

    monkeypatch.setattr("azure_functions_openapi.spec.model_to_schema", fail_conversion)

    spec = generate_openapi_spec(registry=registry, route_prefix="/v2")
    warnings = tuple(
        warning
        for warning in collect_spec_warnings(spec, registry=registry)
        if warning.code.value == "schema-substitution"
    )

    assert [(warning.method, warning.path, warning.location) for warning in warnings] == [
        ("POST", "/v2/a-request", "request body"),
        ("PUT", "/v2/z-response", "response 202"),
    ]
    assert [warning.function_name for warning in warnings] == [
        "post::/a-request",
        "put::/z-response",
    ]
