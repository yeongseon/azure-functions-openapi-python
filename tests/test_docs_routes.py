from __future__ import annotations

import importlib
import json
from typing import Protocol

import azure.functions as func
import pytest
import yaml

from azure_functions_openapi import (
    clear_openapi_registry,
    generate_openapi_spec,
    openapi,
    register_openapi_routes,
)
from azure_functions_openapi.adapters.azure_functions import (
    extract_http_binding,
    get_function_name,
    get_user_handler,
    iter_functions,
)


class _BlueprintFactory(Protocol):
    def __call__(self) -> func.Blueprint: ...


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    clear_openapi_registry()


def _request(url: str, *, code: str | None = None) -> func.HttpRequest:
    params = {} if code is None else {"code": code}
    return func.HttpRequest(method="GET", url=url, body=b"", params=params, headers={})


def _documented_app() -> func.FunctionApp:
    app = func.FunctionApp()

    @openapi(summary="List widgets")
    @app.route(route="widgets", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def list_widgets(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("[]", mimetype="application/json")

    return app


def test_register_openapi_routes_registers_three_get_functions() -> None:
    app = _documented_app()

    routes = register_openapi_routes(app, title="Widget API", version="2.0.0")

    functions = iter_functions(app)
    docs_functions = functions[-3:]
    assert {get_function_name(function) for function in docs_functions} == {
        "openapi_docs",
        "openapi_openapi_json",
        "openapi_openapi_yaml",
    }
    assert {get_user_handler(function) for function in docs_functions} == {
        routes.json,
        routes.yaml,
        routes.docs,
    }
    for function in docs_functions:
        binding = extract_http_binding(function)
        assert binding is not None
        assert [method.value for method in binding.methods] == ["GET"]
        assert binding.auth_level is func.AuthLevel.ANONYMOUS


def test_registered_handlers_return_json_yaml_and_prefixed_swagger_url() -> None:
    app = _documented_app()
    routes = register_openapi_routes(
        app,
        title="Widget API",
        version="2.0.0",
        route_prefix="/v2",
    )
    assert routes.json is not None
    assert routes.yaml is not None
    assert routes.docs is not None

    json_response = routes.json(_request("/v2/openapi.json"))
    yaml_response = routes.yaml(_request("/v2/openapi.yaml"))
    docs_response = routes.docs(_request("/v2/docs"))

    json_document = json.loads(json_response.get_body())
    yaml_document = yaml.safe_load(yaml_response.get_body())
    assert json_response.status_code == 200
    assert json_response.mimetype == "application/json"
    assert json_document["info"]["title"] == "Widget API"
    assert json_document["info"]["version"] == "2.0.0"
    assert "/v2/widgets" in json_document["paths"]
    assert yaml_response.status_code == 200
    assert yaml_response.mimetype == "application/x-yaml"
    assert yaml_document == json_document
    assert docs_response.status_code == 200
    assert docs_response.mimetype == "text/html"
    assert 'url: "/v2/openapi.json"' in docs_response.get_body().decode()


def test_register_openapi_routes_supports_custom_routes_names_auth_and_options() -> None:
    app = _documented_app()

    routes = register_openapi_routes(
        app,
        title="Private API",
        version="3.0.0",
        json_route="schema/openapi.json",
        yaml_route="schema/openapi.yaml",
        docs_route="reference",
        route_prefix="gateway/",
        auth_level=func.AuthLevel.FUNCTION,
        name_prefix="private",
        spec_options={"description": "Private contract", "strict": True},
    )
    assert routes.json is not None
    assert routes.docs is not None

    functions = iter_functions(app)[-3:]
    assert {get_function_name(function) for function in functions} == {
        "private_reference",
        "private_schema_openapi_json",
        "private_schema_openapi_yaml",
    }
    bindings = [extract_http_binding(function) for function in functions]
    assert all(binding is not None for binding in bindings)
    assert {binding.route for binding in bindings if binding is not None} == {
        "schema/openapi.json",
        "schema/openapi.yaml",
        "reference",
    }
    assert all(
        binding.auth_level is func.AuthLevel.FUNCTION for binding in bindings if binding is not None
    )
    document = json.loads(routes.json(_request("/gateway/schema/openapi.json")).get_body())
    assert document["info"]["description"] == "Private contract"
    assert (
        'url: "/gateway/schema/openapi.json"'
        in routes.docs(_request("/gateway/reference")).get_body().decode()
    )


@pytest.mark.parametrize(
    ("auth_level", "code", "expected_url"),
    [
        (func.AuthLevel.FUNCTION, "host key/+", "/api/openapi.json?code=host+key%2F%2B"),
        (func.AuthLevel.FUNCTION, None, "/api/openapi.json"),
        (func.AuthLevel.ANONYMOUS, "ignored", "/api/openapi.json"),
    ],
)
def test_docs_handler_forwards_code_only_for_protected_routes(
    auth_level: func.AuthLevel,
    code: str | None,
    expected_url: str,
) -> None:
    # Given
    routes = register_openapi_routes(
        func.FunctionApp(),
        title="Widget API",
        version="1.0.0",
        auth_level=auth_level,
    )
    assert routes.docs is not None

    # When
    response = routes.docs(_request("/api/docs", code=code))

    # Then
    assert f'url: "{expected_url}"' in response.get_body().decode()


def test_register_openapi_routes_disabled_registers_nothing() -> None:
    app = _documented_app()
    before = tuple(iter_functions(app))

    routes = register_openapi_routes(app, title="Widget API", version="1.0.0", enabled=False)

    assert tuple(iter_functions(app)) == before
    assert routes.json is None
    assert routes.yaml is None
    assert routes.docs is None


@pytest.mark.parametrize("route", ["", " ", "/openapi.json"])
def test_register_openapi_routes_rejects_invalid_route_names(route: str) -> None:
    with pytest.raises(ValueError, match="route"):
        register_openapi_routes(
            func.FunctionApp(),
            title="Widget API",
            version="1.0.0",
            json_route=route,
        )


def test_register_openapi_routes_rejects_duplicate_routes() -> None:
    with pytest.raises(ValueError, match="distinct"):
        register_openapi_routes(
            func.FunctionApp(),
            title="Widget API",
            version="1.0.0",
            docs_route="openapi.json",
        )


def test_register_openapi_routes_rejects_sanitized_name_collisions_before_registration() -> None:
    # Given
    app = func.FunctionApp()

    # When / Then
    with pytest.raises(ValueError, match="function names must be distinct"):
        register_openapi_routes(
            app,
            title="Widget API",
            version="1.0.0",
            json_route="Docs",
            docs_route="docs",
        )

    assert iter_functions(app) == []


def test_register_openapi_routes_supports_blueprint_handlers() -> None:
    # Given
    module = importlib.import_module("azure.functions")
    blueprint_factory: _BlueprintFactory = getattr(module, "Blueprint")
    blueprint = blueprint_factory()
    routes = register_openapi_routes(blueprint, title="Blueprint API", version="1.0.0")
    app = func.FunctionApp()
    app.register_functions(blueprint)
    assert routes.json is not None
    assert routes.yaml is not None
    assert routes.docs is not None

    # When
    json_response = routes.json(_request("/api/openapi.json"))
    yaml_response = routes.yaml(_request("/api/openapi.yaml"))
    docs_response = routes.docs(_request("/api/docs"))

    # Then
    assert len(iter_functions(app)) == 3
    assert json.loads(json_response.get_body())["info"]["title"] == "Blueprint API"
    assert yaml.safe_load(yaml_response.get_body())["info"]["title"] == "Blueprint API"
    assert 'url: "/api/openapi.json"' in docs_response.get_body().decode()


def test_register_openapi_routes_rejects_invalid_auth_level() -> None:
    module = importlib.import_module("azure_functions_openapi")
    register = getattr(module, "register_openapi_routes")

    with pytest.raises(TypeError, match="auth_level"):
        register(
            func.FunctionApp(),
            title="Widget API",
            version="1.0.0",
            auth_level="anonymous",
        )


def test_documentation_handlers_do_not_appear_in_generated_spec() -> None:
    app = _documented_app()
    register_openapi_routes(app, title="Widget API", version="1.0.0")

    spec = generate_openapi_spec(app=app)

    assert set(spec["paths"]) == {"/api/widgets"}
