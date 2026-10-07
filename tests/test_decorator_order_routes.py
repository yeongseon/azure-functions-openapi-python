from __future__ import annotations

from collections.abc import Iterator

import azure.functions as func
import pytest

from azure_functions_openapi import (
    clear_openapi_registry,
    generate_openapi_spec,
    openapi,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def test_spec_uses_binding_route_when_openapi_is_outermost() -> None:
    # Given: @openapi can inspect the builder returned by @app.route.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(summary="outer")
    @app.route(route="things/{id}", methods=["PATCH"])
    def outer_handler(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: binding metadata is reconciled and the spec is generated.
    spec = generate_openapi_spec(app=app)

    # Then: the binding route, method, and route parameter are documented.
    operation = spec["paths"]["/api/things/{id}"]["patch"]
    assert operation["parameters"] == [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    ]


def test_spec_uses_binding_route_when_openapi_is_innermost() -> None:
    # Given: @openapi runs before @app.route and cannot inspect its binding yet.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.function_name(name="custom_name")
    @app.route(route="items/{item_id:int}", methods=["GET", "DELETE"])
    @openapi(summary="inner")
    def inner_handler(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: binding metadata is reconciled with a custom host route prefix.
    spec = generate_openapi_spec(app=app, route_prefix="/v1")

    # Then: neither the Python nor registered function name becomes the path.
    path_item = spec["paths"]["/v1/items/{item_id}"]
    assert set(path_item) == {"get", "delete"}
    assert path_item["get"]["parameters"] == [
        {
            "name": "item_id",
            "in": "path",
            "required": True,
            "schema": {"type": "integer"},
        }
    ]
    assert "/v1/inner_handler" not in spec["paths"]
    assert "/v1/custom_name" not in spec["paths"]


def test_spec_keeps_function_name_route_without_explicit_binding_route() -> None:
    # Given: neither decorator supplies an explicit route.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(methods=["POST"])
    @openapi(summary="implicit")
    def implicit_handler(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    # When: the app is scanned and its spec is generated.
    spec = generate_openapi_spec(app=app)

    # Then: Azure's implicit function-name route remains documented.
    assert set(spec["paths"]["/api/implicit_handler"]) == {"post"}
