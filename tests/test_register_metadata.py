from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import azure.functions as func
from pydantic import BaseModel
import pytest

from azure_functions_openapi import (
    clear_openapi_registry,
    generate_openapi_spec,
    render_swagger_ui,
)
from azure_functions_openapi.decorator import (
    get_openapi_registry,
    openapi,
    register_openapi_metadata,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class DemoResponseModel(BaseModel):
    message: str


def test_register_basic_metadata() -> None:
    register_openapi_metadata(path="/api/chat/invoke", method="POST", summary="Chat invoke")

    registry = get_openapi_registry()
    assert "post::/api/chat/invoke" in registry
    assert registry["post::/api/chat/invoke"]["summary"] == "Chat invoke"
    assert registry["post::/api/chat/invoke"]["route"] == "/api/chat/invoke"
    assert registry["post::/api/chat/invoke"]["method"] == "post"


def test_register_with_all_fields() -> None:
    request_body = {
        "type": "object",
        "properties": {"prompt": {"type": "string"}},
        "required": ["prompt"],
    }
    responses = {
        201: {
            "description": "Created",
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    }
    parameters = [
        {"name": "tenant", "in": "query", "required": False, "schema": {"type": "string"}},
    ]
    security: list[dict[str, list[str]]] = [{"BearerAuth": []}]
    security_scheme = {"BearerAuth": {"type": "http", "scheme": "bearer"}}

    register_openapi_metadata(
        path="/api/all-fields",
        method="POST",
        operation_id="custom_operation_id",
        summary="All fields",
        description="All optional fields populated",
        tags=["custom"],
        request_body=request_body,
        request_body_required=False,
        response_model=DemoResponseModel,
        response=responses,
        parameters=parameters,
        security=security,
        security_scheme=security_scheme,
    )

    registry = get_openapi_registry()
    entry = registry["post::/api/all-fields"]
    assert entry["operation_id"] == "custom_operation_id"
    assert entry["summary"] == "All fields"
    assert entry["description"] == "All optional fields populated"
    assert entry["tags"] == ["custom"]
    assert entry["request_body"] == request_body
    assert entry["request_body_required"] is False
    assert entry["response_model"] is DemoResponseModel
    assert entry["response"] == responses
    assert entry["parameters"] == parameters
    assert entry["security"] == security
    assert entry["security_scheme"] == security_scheme


def test_register_generates_operation_id() -> None:
    register_openapi_metadata(path="/api/chat/invoke", method="POST")

    registry = get_openapi_registry()
    assert registry["post::/api/chat/invoke"]["operation_id"] == "post_api_chat_invoke"


def test_register_custom_operation_id() -> None:
    register_openapi_metadata(path="/api/chat/invoke", method="POST", operation_id="myCustomOp")

    registry = get_openapi_registry()
    assert registry["post::/api/chat/invoke"]["operation_id"] == "myCustomOp"


def test_register_coexists_with_decorator() -> None:
    register_openapi_metadata(
        path="/api/programmatic",
        method="POST",
        summary="Programmatic endpoint",
    )

    @openapi(route="/api/decorated", method="get", summary="Decorated endpoint")
    def decorated_handler() -> None:
        pass

    spec = generate_openapi_spec()
    assert "/api/programmatic" in spec["paths"]
    assert "post" in spec["paths"]["/api/programmatic"]
    assert "/api/decorated" in spec["paths"]
    assert "get" in spec["paths"]["/api/decorated"]


def test_register_multiple_endpoints() -> None:
    register_openapi_metadata(path="/api/items", method="GET")
    register_openapi_metadata(path="/api/items", method="POST")
    register_openapi_metadata(path="/api/items/{id}", method="DELETE")

    spec = generate_openapi_spec()
    assert "/api/items" in spec["paths"]
    assert "get" in spec["paths"]["/api/items"]
    assert "post" in spec["paths"]["/api/items"]
    assert "/api/items/{id}" in spec["paths"]
    assert "delete" in spec["paths"]["/api/items/{id}"]


def test_register_same_path_different_methods() -> None:
    register_openapi_metadata(path="/api/chat", method="GET")
    register_openapi_metadata(path="/api/chat", method="POST")

    registry = get_openapi_registry()
    assert "get::/api/chat" in registry
    assert "post::/api/chat" in registry


def test_register_empty_path_raises() -> None:
    with pytest.raises(ValueError, match="path must be a non-empty string"):
        register_openapi_metadata(path="", method="GET")


def test_register_empty_method_raises() -> None:
    with pytest.raises(ValueError, match="method must be a non-empty string"):
        register_openapi_metadata(path="/api/empty-method", method="")


def test_register_invalid_method_raises() -> None:
    with pytest.raises(ValueError, match="Invalid HTTP method"):
        register_openapi_metadata(path="/api/bad", method="BAD METHOD")


def test_register_with_response_model() -> None:
    register_openapi_metadata(
        path="/api/with-model",
        method="GET",
        response_model=DemoResponseModel,
    )

    spec = generate_openapi_spec()
    op = spec["paths"]["/api/with-model"]["get"]
    assert op["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DemoResponseModel"
    }


def test_register_with_request_body_dict() -> None:
    request_body = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    register_openapi_metadata(
        path="/api/with-request-body",
        method="POST",
        request_body=request_body,
        request_body_required=False,
    )

    spec = generate_openapi_spec()
    op = spec["paths"]["/api/with-request-body"]["post"]
    assert op["requestBody"]["required"] is False
    assert op["requestBody"]["content"]["application/json"]["schema"] == request_body


def test_register_with_security() -> None:
    register_openapi_metadata(
        path="/api/secure",
        method="GET",
        security=[{"BearerAuth": []}],
        security_scheme={"BearerAuth": {"type": "http", "scheme": "bearer"}},
    )

    spec = generate_openapi_spec()
    op = spec["paths"]["/api/secure"]["get"]
    assert op["security"] == [{"BearerAuth": []}]
    assert spec["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
    }


def test_register_with_parameters() -> None:
    parameters: list[dict[str, Any]] = [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "include", "in": "query", "required": False, "schema": {"type": "string"}},
    ]
    register_openapi_metadata(
        path="/api/items/{id}",
        method="GET",
        parameters=parameters,
    )

    spec = generate_openapi_spec()
    op = spec["paths"]["/api/items/{id}"]["get"]
    assert op["parameters"] == parameters


def test_register_appears_in_generated_spec() -> None:
    register_openapi_metadata(
        path="/api/round-trip",
        method="PATCH",
        summary="Round trip",
        description="Programmatic registry round trip",
    )

    spec = generate_openapi_spec()
    assert "/api/round-trip" in spec["paths"]
    op = spec["paths"]["/api/round-trip"]["patch"]
    assert op["summary"] == "Round trip"
    assert op["description"] == "Programmatic registry round trip"
    assert op["operationId"] == "patch_api_round_trip"


def test_register_appears_in_swagger_ui() -> None:
    register_openapi_metadata(path="/api/swagger-path", method="GET")

    response = render_swagger_ui(openapi_url="/api/swagger-path")
    body = response.get_body().decode("utf-8")
    assert "/api/swagger-path" in body


def test_register_thread_safety() -> None:
    def _register(i: int) -> None:
        register_openapi_metadata(path=f"/api/concurrent/{i}", method="GET")

    count = 64
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(_register, range(count)))

    registry = get_openapi_registry()
    assert len(registry) == count
    spec = generate_openapi_spec()
    for i in range(count):
        assert f"/api/concurrent/{i}" in spec["paths"]


def test_register_no_key_collision_for_similar_paths() -> None:
    """Regression test: paths like /api/users/{id} and /api/users/id must not collide."""
    register_openapi_metadata(path="/api/users/{id}", method="GET")
    register_openapi_metadata(path="/api/users/id", method="GET")

    registry = get_openapi_registry()
    assert "get::/api/users/{id}" in registry
    assert "get::/api/users/id" in registry
    assert len(registry) == 2


def test_register_invalid_route_raises() -> None:
    """Route validation rejects dangerous patterns like path traversal."""
    with pytest.raises(ValueError, match="Invalid route path"):
        register_openapi_metadata(path="/api/../secret", method="GET")


def test_register_invalid_operation_id_raises() -> None:
    """Regression test: explicit operation_id that sanitizes to empty must be rejected."""
    with pytest.raises(ValueError, match="Invalid operation ID"):
        register_openapi_metadata(path="/api/test", method="GET", operation_id="!!!")


def test_register_sanitizable_operation_id_accepted() -> None:
    """An operation_id that sanitizes to a non-empty string should be accepted."""
    register_openapi_metadata(path="/api/sanitize", method="POST", operation_id="my-op_id.v2")
    registry = get_openapi_registry()
    entry = registry["post::/api/sanitize"]
    # sanitize_operation_id strips non-alphanumeric except underscore
    assert entry["operation_id"]  # non-empty after sanitization


class DemoRequestModel(BaseModel):
    prompt: str
    max_tokens: int = 100


def test_register_with_request_model() -> None:
    """request_model should produce $ref schema in generated spec (no $defs)."""
    register_openapi_metadata(
        path="/api/with-request-model",
        method="POST",
        request_model=DemoRequestModel,
    )

    spec = generate_openapi_spec()
    op = spec["paths"]["/api/with-request-model"]["post"]
    assert op["requestBody"]["required"] is True
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    assert "$ref" in schema
    assert schema["$ref"] == "#/components/schemas/DemoRequestModel"
    assert "DemoRequestModel" in spec["components"]["schemas"]


def test_register_request_model_and_request_body_raises() -> None:
    """Cannot provide both request_model and request_body."""
    with pytest.raises(ValueError, match="Cannot provide both"):
        register_openapi_metadata(
            path="/api/both",
            method="POST",
            request_model=DemoRequestModel,
            request_body={"type": "object"},
        )


def test_spec_bare_openapi_without_binding_stays_single_get() -> None:
    # #347: a bare @openapi with no @app.route binding and no method= has no
    # evidence that the runtime answers every method, so it must emit a single
    # GET operation rather than fanning out to all seven HTTP verbs.
    @openapi(route="/api/hello", summary="Hello")
    def hello() -> None:  # pragma: no cover - registration only
        ...

    spec = generate_openapi_spec()
    assert set(spec["paths"]["/api/hello"]) == {"get"}


def test_spec_expands_unspecified_method_with_route_binding() -> None:
    # #335/#347: @openapi over an @app.route that omits methods= DOES carry
    # binding evidence that the runtime answers every method, so it expands to
    # one operation per HTTP method.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(route="/api/hello", summary="Hello")
    @app.route(route="hello")
    def hello(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("OK", status_code=200)

    spec = generate_openapi_spec()
    assert set(spec["paths"]["/api/hello"]) == {
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "head",
        "options",
    }


def test_spec_expanded_methods_omit_body_on_get_head_delete() -> None:
    # #335 policy 1: a body-carrying route whose binding omits methods= expands
    # to all methods but must not attach requestBody to GET/HEAD/DELETE.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(route="/api/thing", requests=DemoRequestModel)
    @app.route(route="thing")
    def thing(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("OK", status_code=200)

    spec = generate_openapi_spec()
    path_item = spec["paths"]["/api/thing"]
    for method in ("get", "head", "delete"):
        assert "requestBody" not in path_item[method]
    for method in ("post", "put", "patch"):
        assert "requestBody" in path_item[method]


def test_spec_explicit_method_stays_single_operation() -> None:
    # An explicit method= is unaffected by the expansion policy.
    register_openapi_metadata(path="/api/explicit", method="POST")

    spec = generate_openapi_spec()
    assert set(spec["paths"]["/api/explicit"]) == {"post"}


def test_spec_expanded_methods_keep_unique_operation_ids() -> None:
    # #335 regression: an explicit operation_id on an unspecified-method route
    # (binding present, methods= omitted) must not be reused verbatim across
    # every expanded operation (duplicate operationIds are invalid and error
    # under strict=True). Each emitted operation is suffixed with its method.
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(route="/api/dup", operation_id="myOp")
    @app.route(route="dup")
    def dup(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("OK", status_code=200)

    spec = generate_openapi_spec()
    path_item = spec["paths"]["/api/dup"]
    op_ids = [op["operationId"] for op in path_item.values()]
    assert len(op_ids) == len(set(op_ids))
    assert set(op_ids) == {f"myOp_{m}" for m in path_item}
