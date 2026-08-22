"""Tests for Azure Functions ``auth_level`` -> OpenAPI security inference (#482)."""

from __future__ import annotations

from typing import Any

import azure.functions as func
import pytest

from azure_functions_openapi.adapters import extract_auth_level, extract_http_binding
from azure_functions_openapi.bridge import scan_endpoint_metadata
from azure_functions_openapi.decorator import clear_openapi_registry, openapi
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    AZURE_FUNCTION_KEY_SCHEME_NAME,
    _infer_auth_security,
    generate_openapi_spec,
)

_FUNCTION_KEY_SCHEME = {
    "type": "apiKey",
    "in": "header",
    "name": "x-functions-key",
}


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _scan(app: func.FunctionApp) -> OpenAPIRegistry:
    reg = OpenAPIRegistry()
    scan_endpoint_metadata(app, registry=reg)
    return reg


# ---------------------------------------------------------------------------
# Unit: mapping helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", ["function", "admin"])
def test_infer_auth_security_maps_keyed_levels(level: str) -> None:
    inferred = _infer_auth_security(level)
    assert inferred is not None
    security, schemes = inferred
    assert security == [{AZURE_FUNCTION_KEY_SCHEME_NAME: []}]
    assert schemes == {AZURE_FUNCTION_KEY_SCHEME_NAME: _FUNCTION_KEY_SCHEME}


@pytest.mark.parametrize("level", ["anonymous", None, "", "unknown"])
def test_infer_auth_security_returns_none_for_public_or_unknown(level: Any) -> None:
    assert _infer_auth_security(level) is None


# ---------------------------------------------------------------------------
# Unit: adapter binding read
# ---------------------------------------------------------------------------


def test_extract_auth_level_reads_binding_enum() -> None:
    app = func.FunctionApp()

    @app.route(route="x", auth_level=func.AuthLevel.FUNCTION, methods=["GET"])
    def x(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover - body unused
        return func.HttpResponse("ok")

    built = app._function_builders[0].build(app.auth_level)
    binding = extract_http_binding(built)
    assert extract_auth_level(binding) == "function"


def test_extract_auth_level_none_when_absent() -> None:
    class _NoAuth:
        auth_level = None

    assert extract_auth_level(_NoAuth()) is None


# ---------------------------------------------------------------------------
# Integration: end-to-end spec generation
# ---------------------------------------------------------------------------


def test_function_level_infers_security_when_enabled() -> None:
    app = func.FunctionApp()

    @openapi(summary="orders")
    @app.route(route="orders", auth_level=func.AuthLevel.FUNCTION, methods=["GET"])
    def orders(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("ok")

    reg = _scan(app)
    spec = generate_openapi_spec(registry=reg, infer_auth_level=True)

    assert spec["paths"]["/api/orders"]["get"]["security"] == [{AZURE_FUNCTION_KEY_SCHEME_NAME: []}]
    assert spec["components"]["securitySchemes"] == {
        AZURE_FUNCTION_KEY_SCHEME_NAME: _FUNCTION_KEY_SCHEME
    }


def test_admin_level_infers_function_key_scheme() -> None:
    app = func.FunctionApp()

    @openapi(summary="admin")
    @app.route(route="admin", auth_level=func.AuthLevel.ADMIN, methods=["GET"])
    def admin(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("ok")

    reg = _scan(app)
    spec = generate_openapi_spec(registry=reg, infer_auth_level=True)

    assert spec["paths"]["/api/admin"]["get"]["security"] == [{AZURE_FUNCTION_KEY_SCHEME_NAME: []}]
    assert AZURE_FUNCTION_KEY_SCHEME_NAME in spec["components"]["securitySchemes"]


def test_anonymous_level_injects_no_security() -> None:
    app = func.FunctionApp()

    @openapi(summary="ping")
    @app.route(route="ping", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
    def ping(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("ok")

    reg = _scan(app)
    spec = generate_openapi_spec(registry=reg, infer_auth_level=True)

    assert "security" not in spec["paths"]["/api/ping"]["get"]
    assert "securitySchemes" not in spec.get("components", {})


def test_inference_off_by_default() -> None:
    app = func.FunctionApp()

    @openapi(summary="orders")
    @app.route(route="orders", auth_level=func.AuthLevel.FUNCTION, methods=["GET"])
    def orders(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("ok")

    reg = _scan(app)
    spec = generate_openapi_spec(registry=reg)

    assert "security" not in spec["paths"]["/api/orders"]["get"]
    assert "securitySchemes" not in spec.get("components", {})


def test_user_declared_security_wins_over_inference() -> None:
    app = func.FunctionApp()

    @openapi(
        summary="custom",
        security=[{"MyAuth": []}],
        security_scheme={"MyAuth": {"type": "http", "scheme": "bearer"}},
    )
    @app.route(route="custom", auth_level=func.AuthLevel.FUNCTION, methods=["GET"])
    def custom(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("ok")

    reg = _scan(app)
    spec = generate_openapi_spec(registry=reg, infer_auth_level=True)

    op = spec["paths"]["/api/custom"]["get"]
    assert op["security"] == [{"MyAuth": []}]
    schemes = spec["components"]["securitySchemes"]
    assert schemes["MyAuth"] == {"type": "http", "scheme": "bearer"}
    # No inferred scheme is injected for an operation that declared its own.
    assert AZURE_FUNCTION_KEY_SCHEME_NAME not in schemes


def test_mixed_levels_share_single_scheme() -> None:
    app = func.FunctionApp()

    @openapi(summary="orders")
    @app.route(route="orders", auth_level=func.AuthLevel.FUNCTION, methods=["GET"])
    def orders(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("ok")

    @openapi(summary="ping")
    @app.route(route="ping", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
    def ping(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("ok")

    reg = _scan(app)
    spec = generate_openapi_spec(registry=reg, infer_auth_level=True)

    assert spec["components"]["securitySchemes"] == {
        AZURE_FUNCTION_KEY_SCHEME_NAME: _FUNCTION_KEY_SCHEME
    }
    assert "security" in spec["paths"]["/api/orders"]["get"]
    assert "security" not in spec["paths"]["/api/ping"]["get"]


def test_get_openapi_json_forwards_infer_auth_level() -> None:
    import json

    from azure_functions_openapi.spec import get_openapi_json

    app = func.FunctionApp()

    @openapi(summary="orders")
    @app.route(route="orders", auth_level=func.AuthLevel.FUNCTION, methods=["GET"])
    def orders(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("ok")

    reg = _scan(app)
    payload = json.loads(get_openapi_json(registry=reg, infer_auth_level=True))
    assert AZURE_FUNCTION_KEY_SCHEME_NAME in payload["components"]["securitySchemes"]
