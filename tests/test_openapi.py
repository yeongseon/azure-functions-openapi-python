# tests/test_openapi.py
import importlib
import json
from typing import Any
from unittest.mock import patch

from pydantic import BaseModel
import pytest
import yaml

from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    openapi,
    register_openapi_metadata,
)
from azure_functions_openapi.spec import (
    DEFAULT_OPENAPI_INFO_DESCRIPTION,
    _ensure_default_response,
    _validate_spec,
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
)

OPENAPI_MODULE = importlib.import_module("azure_functions_openapi.spec")


def _register_http_trigger() -> None:
    @openapi(
        route="/api/http_trigger",
        summary="HTTP Trigger with name parameter",
        description=(
            "Returns a greeting using the **name** from query or body.\n\n"
            "### Usage\n\n"
            "`?name=Azure`\n\n"
            "```json\n"
            '{"name": "Azure"}\n'
            "```"
        ),
        tags=["Example"],
        operation_id="greetUser",
        response={200: {"description": "OK"}},
    )
    def http_trigger() -> None:
        pass


def test_generate_openapi_spec_structure() -> None:
    @openapi(
        route="/sample_func",
        summary="Sample summary",
        description="Sample description",
        response={200: {"description": "Success"}},
        parameters=[
            {
                "name": "q",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Optional query string",
            }
        ],
    )
    def sample_func() -> None:
        pass

    spec = generate_openapi_spec(title="My API", version="1.2.3", route_prefix="")

    assert spec["openapi"] == "3.0.0"
    assert spec["info"]["title"] == "My API"
    assert spec["info"]["version"] == "1.2.3"
    assert "/sample_func" in spec["paths"]

    op = spec["paths"]["/sample_func"]["get"]
    p = op["parameters"][0]
    assert p == {
        "name": "q",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
        "description": "Optional query string",
    }


def test_get_openapi_json_output() -> None:
    data = json.loads(get_openapi_json())

    assert {"openapi", "info", "paths"} <= data.keys()
    assert isinstance(data["paths"], dict)


def test_generate_openapi_spec_uses_default_info_description() -> None:
    spec = generate_openapi_spec(route_prefix="")

    assert spec["info"]["description"] == DEFAULT_OPENAPI_INFO_DESCRIPTION


def test_get_openapi_json_and_yaml_accept_custom_info_description() -> None:
    description = "Custom API description for generated docs."

    json_data = json.loads(get_openapi_json(description=description))
    yaml_data = get_openapi_yaml(description=description)

    assert json_data["info"]["description"] == description
    assert f"description: {description}" in yaml_data


def test_generate_openapi_spec_with_request_body() -> None:
    @openapi(
        route="/func_with_body",
        method="post",
        summary="With Body",
        description="Endpoint with request body",
        response={200: {"description": "OK"}},
        request_body={
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["username", "password"],
        },
    )
    def func_with_body() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    rb = spec["paths"]["/func_with_body"]["post"]["requestBody"]
    schema = rb["content"]["application/json"]["schema"]
    assert {"username", "password"} <= schema["properties"].keys()


def test_response_schema_and_examples() -> None:
    @openapi(
        route="/greet",
        summary="Greet user",
        description="Returns a greeting message.",
        response={
            200: {
                "description": "OK",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"message": {"type": "string"}},
                        },
                        "examples": {
                            "sample": {
                                "summary": "A sample response",
                                "value": {"message": "Hello, Azure!"},
                            }
                        },
                    }
                },
            }
        },
    )
    def greet() -> None:
        pass

    op = generate_openapi_spec(route_prefix="")["paths"]["/greet"]["get"]
    assert (
        op["responses"]["200"]["content"]["application/json"]["examples"]["sample"]["value"][
            "message"
        ]
        == "Hello, Azure!"
    )


def test_generate_openapi_spec_with_route_and_method() -> None:
    @openapi(
        route="/custom-path",
        summary="Test with custom route/method",
        description="Checks that route and method are reflected",
        response={200: {"description": "OK"}},
        method="post",
    )
    def custom_func() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    assert "post" in spec["paths"]["/custom-path"]


def test_generate_openapi_spec_normalizes_route_without_leading_slash() -> None:
    @openapi(
        route="hello",
        method="post",
        summary="Route normalization",
        response={200: {"description": "OK"}},
    )
    def hello() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    assert "/hello" in spec["paths"]
    assert "hello" not in spec["paths"]
    assert "post" in spec["paths"]["/hello"]


def test_generate_openapi_spec_normalizes_default_function_path() -> None:
    @openapi(
        summary="Default route normalization",
        response={200: {"description": "OK"}},
    )
    def default_path_func() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    assert "/default_path_func" in spec["paths"]


def test_generate_spec_with_pydantic_models() -> None:
    class RequestModel(BaseModel):
        username: str
        password: str

    class ResponseModel(BaseModel):
        message: str

    @openapi(
        summary="Login user",
        description="Authenticates a user and returns a welcome message.",
        request_model=RequestModel,
        response_model=ResponseModel,
        method="post",
    )
    def login() -> None:
        pass

    op = generate_openapi_spec(route_prefix="")["paths"]["/login"]["post"]
    schema_req = op["requestBody"]["content"]["application/json"]["schema"]
    schema_resp = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_req == {"$ref": "#/components/schemas/RequestModel"}
    assert schema_resp == {"$ref": "#/components/schemas/ResponseModel"}

    spec = generate_openapi_spec(route_prefix="")
    components = spec.get("components", {})
    schemas = components.get("schemas", {})
    assert "RequestModel" in schemas
    assert "ResponseModel" in schemas
    assert "$defs" not in schemas["RequestModel"]
    assert "$defs" not in schemas["ResponseModel"]


def test_response_200_is_preserved_when_response_model_exists() -> None:
    class MergeResponseModel(BaseModel):
        message: str

    @openapi(
        route="/merge-response",
        summary="Merge response",
        response={
            200: {
                "description": "Custom 200",
                "headers": {"X-Trace-Id": {"schema": {"type": "string"}}},
                "content": {
                    "application/json": {
                        "examples": {
                            "sample": {"value": {"message": "ok"}},
                        }
                    }
                },
            }
        },
        response_model=MergeResponseModel,
    )
    def merge_response_func() -> None:
        pass

    response_200 = generate_openapi_spec(route_prefix="")["paths"]["/merge-response"]["get"][
        "responses"
    ]["200"]
    assert response_200["description"] == "Custom 200"
    assert "X-Trace-Id" in response_200["headers"]
    assert "sample" in response_200["content"]["application/json"]["examples"]
    assert response_200["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MergeResponseModel"
    }


def test_response_model_uses_explicit_first_success_status_code() -> None:
    class CreatedModel(BaseModel):
        id: str

    @openapi(
        route="/created-with-model",
        method="post",
        summary="Created with model",
        response={201: {"description": "Created"}, 400: {"description": "Bad Request"}},
        response_model=CreatedModel,
    )
    def created_with_model_func() -> None:
        pass

    responses = generate_openapi_spec(route_prefix="")["paths"]["/created-with-model"]["post"][
        "responses"
    ]
    assert "200" not in responses
    assert responses["201"]["description"] == "Created"
    assert responses["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CreatedModel"
    }


def test_response_model_defaults_to_200_when_no_success_response_declared() -> None:
    class DefaultSuccessModel(BaseModel):
        ok: bool

    @openapi(
        route="/response-model-default-200",
        summary="Response model default 200",
        response={400: {"description": "Bad Request"}},
        response_model=DefaultSuccessModel,
    )
    def response_model_default_200_func() -> None:
        pass

    responses = generate_openapi_spec(route_prefix="")["paths"]["/response-model-default-200"][
        "get"
    ]["responses"]
    assert "200" in responses
    assert responses["200"]["description"] == "Successful Response"
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DefaultSuccessModel"
    }


def test_response_model_uses_explicit_200_when_declared() -> None:
    class Explicit200Model(BaseModel):
        message: str

    @openapi(
        route="/response-model-explicit-200",
        summary="Response model explicit 200",
        response={200: {"description": "OK"}, 201: {"description": "Created"}},
        response_model=Explicit200Model,
    )
    def response_model_explicit_200_func() -> None:
        pass

    responses = generate_openapi_spec(route_prefix="")["paths"]["/response-model-explicit-200"][
        "get"
    ]["responses"]
    assert responses["200"]["description"] == "OK"
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Explicit200Model"
    }


def test_openapi_spec_contains_operation_id_and_tags() -> None:
    _register_http_trigger()
    spec = json.loads(get_openapi_json())
    item = spec["paths"]["/api/http_trigger"]["get"]

    assert item["operationId"] == "greetUser"
    assert item["tags"] == ["Example"]
    assert "HTTP Trigger with name parameter" in item["summary"]
    assert "### Usage" in item["description"]
    # GET operations have no requestBody
    assert "responses" in item and "200" in item["responses"]


def test_markdown_description_rendering() -> None:
    _register_http_trigger()
    item = json.loads(get_openapi_json())["paths"]["/api/http_trigger"]["get"]
    desc = item["description"]
    assert "### Usage" in desc and "`?name=Azure`" in desc and "```json" in desc


def test_generate_openapi_spec_with_cookie_parameter() -> None:
    @openapi(
        route="/cookie_test",
        summary="Cookie param example",
        description="Test endpoint with cookie parameter",
        parameters=[
            {
                "name": "session_id",
                "in": "cookie",
                "required": True,
                "schema": {"type": "string"},
                "description": "User session ID",
            }
        ],
    )
    def cookie_test() -> None:
        pass

    params = generate_openapi_spec(route_prefix="")["paths"]["/cookie_test"]["get"]["parameters"]
    cookie_param = next(p for p in params if p["in"] == "cookie")
    assert cookie_param["name"] == "session_id"


def test_generate_openapi_spec_with_security() -> None:
    @openapi(
        route="/secure",
        summary="Secure endpoint",
        security=[{"BearerAuth": []}],
        response={200: {"description": "OK"}},
    )
    def secure_endpoint() -> None:
        pass

    op = generate_openapi_spec(route_prefix="")["paths"]["/secure"]["get"]
    assert op["security"] == [{"BearerAuth": []}]


def test_generate_openapi_spec_adds_default_200_response_when_missing() -> None:
    @openapi(
        route="/default-response",
        method="post",
        summary="Default response",
        request_body={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
    )
    def default_response_func() -> None:
        pass

    responses = generate_openapi_spec(route_prefix="")["paths"]["/default-response"]["post"][
        "responses"
    ]
    assert responses["200"] == {
        "description": "Successful Response",
        "content": {"application/json": {"schema": {"type": "object"}}},
    }


def test_generate_openapi_spec_keeps_explicit_non_200_responses_without_adding_200() -> None:
    @openapi(
        route="/created-response",
        method="post",
        summary="Created response",
        response={201: {"description": "Created"}},
    )
    def created_response_func() -> None:
        pass

    responses = generate_openapi_spec(route_prefix="")["paths"]["/created-response"]["post"][
        "responses"
    ]
    assert "200" not in responses
    assert responses["201"] == {"description": "Created"}


def test_generate_openapi_spec_with_security_schemes_param() -> None:
    """Test that security_schemes param adds components.securitySchemes."""

    @openapi(
        route="/secure-param",
        summary="Secured with param",
        security=[{"BearerAuth": []}],
        response={200: {"description": "OK"}},
    )
    def secure_param_endpoint() -> None:
        pass

    spec = generate_openapi_spec(
        security_schemes={"BearerAuth": {"type": "http", "scheme": "bearer"}},
        route_prefix="",
    )
    assert "components" in spec
    assert "securitySchemes" in spec["components"]
    assert spec["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
    }
    op = spec["paths"]["/secure-param"]["get"]
    assert op["security"] == [{"BearerAuth": []}]


def test_generate_openapi_spec_with_decorator_security_scheme() -> None:
    """Test that security_scheme in @openapi decorator adds components.securitySchemes."""

    @openapi(
        route="/secure-decorator",
        summary="Secured with decorator scheme",
        security=[{"ApiKeyAuth": []}],
        security_scheme={"ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
        response={200: {"description": "OK"}},
    )
    def secure_decorator_endpoint() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    assert "components" in spec
    assert "securitySchemes" in spec["components"]
    assert spec["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }


def test_generate_openapi_spec_merges_security_schemes() -> None:
    """Test that security schemes from both param and decorators are merged."""

    @openapi(
        route="/secure-merged",
        summary="Merged schemes",
        security=[{"OAuth2": ["read"]}],
        security_scheme={
            "OAuth2": {
                "type": "oauth2",
                "flows": {
                    "implicit": {
                        "authorizationUrl": "https://example.com/auth",
                        "scopes": {"read": "Read"},
                    },
                },
            }
        },
        response={200: {"description": "OK"}},
    )
    def secure_merged_endpoint() -> None:
        pass

    spec = generate_openapi_spec(
        security_schemes={"BearerAuth": {"type": "http", "scheme": "bearer"}},
        route_prefix="",
    )
    schemes = spec["components"]["securitySchemes"]
    assert "BearerAuth" in schemes
    assert "OAuth2" in schemes


def test_security_schemes_in_json_output() -> None:
    """Test that security schemes appear in JSON output."""

    @openapi(
        route="/secure-json",
        summary="Secured JSON",
        security=[{"BearerAuth": []}],
        security_scheme={"BearerAuth": {"type": "http", "scheme": "bearer"}},
        response={200: {"description": "OK"}},
    )
    def secure_json_endpoint() -> None:
        pass

    json_str = get_openapi_json(
        security_schemes={"BearerAuth": {"type": "http", "scheme": "bearer"}},
    )
    spec = json.loads(json_str)
    assert "securitySchemes" in spec.get("components", {})


def test_response_model_with_content_not_dict() -> None:
    """When existing 200 response has content that is not a dict, it gets replaced."""

    class ContentModel(BaseModel):
        msg: str

    @openapi(
        route="/content-not-dict",
        summary="Content not dict",
        response={
            200: {
                "description": "OK",
                "content": "not_a_dict",
            }
        },
        response_model=ContentModel,
    )
    def content_not_dict_func() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    resp_200 = spec["paths"]["/content-not-dict"]["get"]["responses"]["200"]
    assert resp_200["description"] == "OK"
    # content should have been replaced with a proper dict containing the schema
    content = resp_200.get("content", {})
    assert isinstance(content, dict)
    assert "application/json" in content


def test_response_model_with_json_content_not_dict() -> None:
    """When existing 200 response has application/json that is not a dict, it gets replaced."""

    class JsonContentModel(BaseModel):
        msg: str

    @openapi(
        route="/json-content-not-dict",
        summary="JSON content not dict",
        response={
            200: {
                "description": "OK",
                "content": {
                    "application/json": "not_a_dict",
                },
            }
        },
        response_model=JsonContentModel,
    )
    def json_content_not_dict_func() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    resp_200 = spec["paths"]["/json-content-not-dict"]["get"]["responses"]["200"]
    json_content = resp_200["content"]["application/json"]
    assert isinstance(json_content, dict)
    assert "schema" in json_content


def test_response_model_schema_generation_failure_no_200() -> None:
    """When model_to_schema fails and there is no existing 200, fallback is used."""

    class FailModel(BaseModel):
        x: int

    @openapi(
        route="/schema-fail-no-200",
        summary="Schema fail no 200",
        response_model=FailModel,
    )
    def schema_fail_no_200_func() -> None:
        pass

    with patch.object(
        OPENAPI_MODULE,
        "model_to_schema",
        side_effect=Exception("schema generation failed"),
    ):
        spec = generate_openapi_spec(route_prefix="")

    resp_200 = spec["paths"]["/schema-fail-no-200"]["get"]["responses"]["200"]
    assert resp_200["description"] == "Successful Response"
    assert resp_200["content"]["application/json"]["schema"] == {"type": "object"}


def test_response_model_schema_generation_failure_with_200() -> None:
    """When model_to_schema fails and there IS an existing 200, fallback still works."""

    class FailModel2(BaseModel):
        x: int

    @openapi(
        route="/schema-fail-with-200",
        summary="Schema fail with 200",
        response={200: {"description": "Custom 200"}},
        response_model=FailModel2,
    )
    def schema_fail_with_200_func() -> None:
        pass

    with patch.object(
        OPENAPI_MODULE,
        "model_to_schema",
        side_effect=Exception("schema generation failed"),
    ):
        spec = generate_openapi_spec(route_prefix="")

    # Since 200 already exists, the fallback shouldn't overwrite it (L138 check)
    resp_200 = spec["paths"]["/schema-fail-with-200"]["get"]["responses"]["200"]
    assert resp_200["description"] == "Custom 200"


def test_malformed_registry_entry_skipped() -> None:
    """A registry entry that causes KeyError/TypeError/ValueError should be skipped."""

    # First register a valid function
    @openapi(
        route="/valid-endpoint",
        summary="Valid",
        response={200: {"description": "OK"}},
    )
    def valid_func() -> None:
        pass

    # Now patch the registry to include a malformed entry alongside valid ones
    from azure_functions_openapi.decorator import get_openapi_registry

    real_registry = get_openapi_registry()

    # Create a malformed entry that will cause TypeError when processed
    malformed_registry = dict(real_registry)
    # response has a non-dict detail value which causes TypeError at dict(detail) on L110
    malformed_registry["broken_func"] = {
        "route": "/broken",
        "method": "get",
        "response": {200: 42},  # detail=42 → dict(42) raises TypeError
    }

    with patch.object(
        OPENAPI_MODULE,
        "get_openapi_registry",
        return_value=malformed_registry,
    ):
        spec = generate_openapi_spec(route_prefix="")

    # Valid endpoint should still be present
    assert "/valid-endpoint" in spec["paths"]
    # Broken endpoint should be skipped (not crash the whole spec generation)


def test_security_scheme_collision_raises_value_error() -> None:
    """Conflicting security scheme definitions across decorators raise ValueError."""

    # Register a function with a well-known scheme name
    @openapi(
        route="/collision-a",
        summary="First",
        security=[{"SharedAuth": []}],
        security_scheme={"SharedAuth": {"type": "http", "scheme": "bearer"}},
        response={200: {"description": "OK"}},
    )
    def collision_func_a() -> None:
        pass

    from azure_functions_openapi.decorator import get_openapi_registry

    real_registry = get_openapi_registry()
    conflicting = dict(real_registry)
    # Inject a second entry that redefines SharedAuth with a *different* definition
    conflicting["collision_func_b"] = {
        "route": "/collision-b",
        "method": "get",
        "summary": "Second",
        "description": "",
        "tags": ["default"],
        "operation_id": None,
        "parameters": [],
        "security": [{"SharedAuth": []}],
        "security_scheme": {"SharedAuth": {"type": "apiKey", "in": "header", "name": "X-Key"}},
        "request_model": None,
        "request_body": None,
        "response_model": None,
        "response": {200: {"description": "OK"}},
        "function_name": "collision_func_b",
        "_function_id": "tests.test_openapi.collision_func_b",
    }

    with patch.object(
        OPENAPI_MODULE,
        "get_openapi_registry",
        return_value=conflicting,
    ):
        with pytest.raises(ValueError, match="Conflicting security scheme definition"):
            generate_openapi_spec(route_prefix="")


def test_generate_openapi_spec_with_delete_request_body() -> None:
    """DELETE endpoints can have a requestBody when one is specified."""

    @openapi(
        route="/items/{id}",
        method="delete",
        summary="Delete item with body",
        request_body={"type": "object", "properties": {"reason": {"type": "string"}}},
        response={204: {"description": "No Content"}},
    )
    def delete_with_body_func() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    op = spec["paths"]["/items/{id}"]["delete"]
    assert "requestBody" in op
    assert op["requestBody"]["required"] is True
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    assert schema["properties"]["reason"]["type"] == "string"


def test_generate_openapi_spec_request_body_required_false() -> None:
    """request_body_required=False is reflected in the generated spec."""

    @openapi(
        route="/optional-body-spec",
        method="post",
        summary="Optional body spec",
        request_body={"type": "object"},
        request_body_required=False,
        response={200: {"description": "OK"}},
    )
    def optional_body_spec_func() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    rb = spec["paths"]["/optional-body-spec"]["post"]["requestBody"]
    assert rb["required"] is False


def _make_conflicting_registry() -> dict[str, Any]:
    """Return a registry with two entries that define the same security scheme differently."""
    empty_scopes: list[str] = []
    return {
        "fn_a": {
            "route": "/a",
            "method": "get",
            "summary": "",
            "description": "",
            "tags": ["default"],
            "operation_id": None,
            "parameters": [],
            "security": [{"Auth": empty_scopes}],
            "security_scheme": {"Auth": {"type": "http", "scheme": "bearer"}},
            "request_model": None,
            "request_body": None,
            "request_body_required": True,
            "response_model": None,
            "response": {200: {"description": "OK"}},
            "function_name": "fn_a",
            "_function_id": "fn_a",
        },
        "fn_b": {
            "route": "/b",
            "method": "get",
            "summary": "",
            "description": "",
            "tags": ["default"],
            "operation_id": None,
            "parameters": [],
            "security": [{"Auth": empty_scopes}],
            "security_scheme": {"Auth": {"type": "apiKey", "in": "header", "name": "X-Key"}},
            "request_model": None,
            "request_body": None,
            "request_body_required": True,
            "response_model": None,
            "response": {200: {"description": "OK"}},
            "function_name": "fn_b",
            "_function_id": "fn_b",
        },
    }


def test_get_openapi_json_propagates_value_error() -> None:
    """get_openapi_json must not swallow ValueError from collision detection."""
    with patch.object(
        OPENAPI_MODULE, "get_openapi_registry", return_value=_make_conflicting_registry()
    ):
        with pytest.raises(ValueError, match="Conflicting security scheme definition"):
            get_openapi_json()


def test_get_openapi_yaml_propagates_value_error() -> None:
    """get_openapi_yaml must not swallow ValueError from collision detection."""
    with patch.object(
        OPENAPI_MODULE, "get_openapi_registry", return_value=_make_conflicting_registry()
    ):
        with pytest.raises(ValueError, match="Conflicting security scheme definition"):
            get_openapi_yaml()


# ---------------------------------------------------------------------------
# Unit tests for _ensure_default_response helper
# ---------------------------------------------------------------------------


def test_ensure_default_response_empty_uses_generic_schema() -> None:
    """Empty responses dict gets a 200 with generic object schema."""
    responses: dict[str, Any] = {}
    _ensure_default_response(responses)
    assert "200" in responses
    assert responses["200"]["description"] == "Successful Response"
    assert responses["200"]["content"]["application/json"]["schema"] == {"type": "object"}


def test_ensure_default_response_empty_uses_provided_schema() -> None:
    """Empty responses dict gets a 200 using the supplied schema."""
    responses: dict[str, Any] = {}
    schema = {"type": "string", "description": "A plain string"}
    _ensure_default_response(responses, schema=schema)
    assert responses["200"]["content"]["application/json"]["schema"] == schema


def test_ensure_default_response_noop_when_nonempty() -> None:
    """Non-empty responses dict is left untouched."""
    existing = {"200": {"description": "Already here"}}
    _ensure_default_response(existing)
    assert existing == {"200": {"description": "Already here"}}


def test_ensure_default_response_noop_with_non_200_entry() -> None:
    """A dict with only non-200 entries is also left untouched."""
    existing = {"404": {"description": "Not found"}}
    _ensure_default_response(existing)
    assert "200" not in existing
    assert "404" in existing


def test_get_openapi_json_accepts_empty_route_prefix() -> None:
    clear_openapi_registry()
    register_openapi_metadata(path="/users", method="get")

    spec = json.loads(get_openapi_json(route_prefix=""))

    assert "/users" in spec["paths"]
    assert "/api/users" not in spec["paths"]


def test_get_openapi_yaml_accepts_custom_route_prefix() -> None:
    clear_openapi_registry()
    register_openapi_metadata(path="/users", method="get")

    spec = yaml.safe_load(get_openapi_yaml(route_prefix="/v1"))

    assert "/v1/users" in spec["paths"]
    assert "/api/users" not in spec["paths"]


def test_get_openapi_json_default_route_prefix_matches_runtime_url() -> None:
    clear_openapi_registry()
    register_openapi_metadata(path="/users", method="get")

    spec = json.loads(get_openapi_json())

    assert "/api/users" in spec["paths"]


class TestValidateSpec:
    """Tests for _validate_spec post-generation validation."""

    def test_missing_path_parameter_definition(self) -> None:
        spec = {
            "paths": {
                "/items/{id}": {
                    "get": {
                        "operationId": "get_item",
                        "parameters": [],
                    }
                }
            }
        }
        warnings = _validate_spec(spec)
        assert any("{id}" in w and "no matching path parameter" in w for w in warnings)

    def test_path_param_not_required(self) -> None:
        spec = {
            "paths": {
                "/items/{id}": {
                    "get": {
                        "operationId": "get_item",
                        "parameters": [
                            {"name": "id", "in": "path", "required": False},
                        ],
                    }
                }
            }
        }
        warnings = _validate_spec(spec)
        assert any("must be required" in w for w in warnings)

    def test_duplicate_operation_id(self) -> None:
        spec = {
            "paths": {
                "/a": {"get": {"operationId": "dup_op"}},
                "/b": {"get": {"operationId": "dup_op"}},
            }
        }
        warnings = _validate_spec(spec)
        assert any("Duplicate operationId" in w and "dup_op" in w for w in warnings)

    def test_duplicate_parameter_name_in(self) -> None:
        spec = {
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "list_items",
                        "parameters": [
                            {"name": "q", "in": "query"},
                            {"name": "q", "in": "query"},
                        ],
                    }
                }
            }
        }
        warnings = _validate_spec(spec)
        assert any("Duplicate parameter" in w and "q" in w for w in warnings)

    def test_valid_spec_no_warnings(self) -> None:
        spec = {
            "paths": {
                "/items/{id}": {
                    "get": {
                        "operationId": "get_item",
                        "parameters": [
                            {"name": "id", "in": "path", "required": True},
                        ],
                    }
                },
                "/items": {
                    "get": {
                        "operationId": "list_items",
                        "parameters": [
                            {"name": "q", "in": "query"},
                        ],
                    }
                },
            }
        }
        warnings = _validate_spec(spec)
        assert warnings == []

    def test_multiple_template_vars(self) -> None:
        spec = {
            "paths": {
                "/users/{user_id}/items/{item_id}": {
                    "get": {
                        "operationId": "get_user_item",
                        "parameters": [
                            {"name": "user_id", "in": "path", "required": True},
                            # item_id missing
                        ],
                    }
                }
            }
        }
        warnings = _validate_spec(spec)
        assert any("{item_id}" in w and "no matching path parameter" in w for w in warnings)
        # user_id is provided — no "no matching" warning for it
        assert not any(
            "no matching path parameter" in w and "{user_id}" in w and "{item_id}" not in w
            for w in warnings
        )
