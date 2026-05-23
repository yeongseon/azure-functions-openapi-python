# tests/test_decorator.py

import azure.functions as func
from azure.functions.decorators.function_app import FunctionBuilder
from pydantic import BaseModel

import azure_functions_openapi.decorator as decorator_module
from azure_functions_openapi.decorator import get_openapi_registry, openapi
from azure_functions_openapi.spec import generate_openapi_spec


def _clear_registry() -> None:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()


def test_openapi_registers_metadata() -> None:
    @openapi(
        summary="Test Summary",
        description="Detailed test description",
        response={200: {"description": "OK"}},
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
    def dummy_function() -> None:
        pass

    registry = get_openapi_registry()
    assert "dummy_function" in registry
    assert registry["dummy_function"]["summary"] == "Test Summary"
    assert registry["dummy_function"]["description"] == "Detailed test description"
    assert 200 in registry["dummy_function"]["response"]

    # Check parameters metadata
    parameters = registry["dummy_function"].get("parameters")
    assert isinstance(parameters, list)
    assert parameters[0]["name"] == "q"
    assert parameters[0]["in"] == "query"
    assert parameters[0]["required"] is False
    assert parameters[0]["schema"]["type"] == "string"
    assert parameters[0]["description"] == "Optional query string"


def test_openapi_registers_metadata_with_request_body() -> None:
    @openapi(
        summary="Test with body",
        description="Test endpoint with request body",
        response={201: {"description": "Created"}},
        parameters=[],
        request_body={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        },
    )
    def dummy_with_body() -> None:
        pass

    registry = get_openapi_registry()
    assert "dummy_with_body" in registry
    assert "request_body" in registry["dummy_with_body"]
    schema = registry["dummy_with_body"]["request_body"]
    assert schema["type"] == "object"
    assert "name" in schema["properties"]
    assert schema["properties"]["name"]["type"] == "string"


def test_openapi_registers_security_metadata() -> None:
    @openapi(
        summary="Secured endpoint",
        security=[{"BearerAuth": []}],
    )
    def secured_dummy() -> None:
        pass

    registry = get_openapi_registry()
    assert registry["secured_dummy"]["security"] == [{"BearerAuth": []}]


def test_openapi_accepts_function_builder_when_decorator_is_outermost() -> None:
    _clear_registry()
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(summary="Hello", description="Returns plain text.")
    @app.route(route="hello")
    def hello(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("Hello", status_code=200)

    assert isinstance(hello, FunctionBuilder)

    registry = get_openapi_registry()
    assert registry["hello"]["summary"] == "Hello"
    assert registry["hello"]["description"] == "Returns plain text."

    spec = generate_openapi_spec(route_prefix="")
    assert "/hello" in spec["paths"]


def test_openapi_keeps_function_builder_chain_intact() -> None:
    _clear_registry()
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.function_name(name="hello_alias")
    @openapi(summary="Hello")
    @app.route(route="hello")
    def hello(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("Hello", status_code=200)

    assert isinstance(hello, FunctionBuilder)
    built = app._function_builders[0].build(app.auth_level)

    assert built.get_function_name() == "hello_alias"


def test_openapi_raises_error_for_dict_request_model() -> None:
    """Test that passing a dict to request_model raises ValueError with helpful message."""
    import pytest

    with pytest.raises(ValueError) as exc_info:

        @openapi(
            summary="Test with invalid request_model",
            request_model={"name": "string"},  # type: ignore[arg-type]
        )
        def invalid_request_model_func() -> None:
            pass

    assert "request_model must be a Pydantic BaseModel class, not a dict" in str(exc_info.value)
    assert "request_body" in str(exc_info.value)


def test_openapi_raises_error_for_dict_response_model() -> None:
    """Test that passing a dict to response_model raises ValueError with helpful message."""
    import pytest

    with pytest.raises(ValueError) as exc_info:

        @openapi(
            summary="Test with invalid response_model",
            response_model={"message": "string"},  # type: ignore[arg-type]
        )
        def invalid_response_model_func() -> None:
            pass

    assert "response_model must be a Pydantic BaseModel class, not a dict" in str(exc_info.value)
    assert "response" in str(exc_info.value)


def test_openapi_raises_error_for_non_basemodel_request_model() -> None:
    """Test that passing a non-BaseModel class to request_model raises ValueError."""
    import pytest

    class NotAModel:
        pass

    with pytest.raises(ValueError) as exc_info:

        @openapi(
            summary="Test with non-BaseModel",
            request_model=NotAModel,  # type: ignore[arg-type]
        )
        def non_basemodel_request_func() -> None:
            pass

    assert "request_model must be a Pydantic BaseModel subclass" in str(exc_info.value)


def test_openapi_raises_error_for_non_basemodel_response_model() -> None:
    """Test that passing a non-BaseModel class to response_model raises ValueError."""
    import pytest

    class NotAModel:
        pass

    with pytest.raises(ValueError) as exc_info:

        @openapi(
            summary="Test with non-BaseModel",
            response_model=NotAModel,  # type: ignore[arg-type]
        )
        def non_basemodel_response_func() -> None:
            pass

    assert "response_model must be a Pydantic BaseModel subclass" in str(exc_info.value)


def test_openapi_registers_security_scheme_metadata() -> None:
    @openapi(
        summary="Secured with scheme",
        security=[{"BearerAuth": []}],
        security_scheme={"BearerAuth": {"type": "http", "scheme": "bearer"}},
    )
    def secured_scheme_dummy() -> None:
        pass

    registry = get_openapi_registry()
    assert registry["secured_scheme_dummy"]["security_scheme"] == {
        "BearerAuth": {"type": "http", "scheme": "bearer"}
    }


class _UnifiedRequestModel(BaseModel):
    name: str


class _UnifiedResponseModel(BaseModel):
    ok: bool


def test_openapi_requests_accepts_model() -> None:
    @openapi(summary="Unified request model", requests=_UnifiedRequestModel)
    def unified_request_model_func() -> None:
        pass

    registry = get_openapi_registry()
    assert registry["unified_request_model_func"]["request_model"] is _UnifiedRequestModel
    assert registry["unified_request_model_func"]["request_body"] is None


def test_openapi_requests_accepts_dict() -> None:
    request_schema = {"type": "object"}

    @openapi(summary="Unified request body", requests=request_schema)
    def unified_request_body_func() -> None:
        pass

    registry = get_openapi_registry()
    assert registry["unified_request_body_func"]["request_model"] is None
    assert registry["unified_request_body_func"]["request_body"] == request_schema


def test_openapi_responses_accepts_model() -> None:
    @openapi(summary="Unified response model", responses=_UnifiedResponseModel)
    def unified_response_model_func() -> None:
        pass

    registry = get_openapi_registry()
    assert registry["unified_response_model_func"]["response_model"] is _UnifiedResponseModel
    assert registry["unified_response_model_func"]["response"] == {}


def test_openapi_responses_accepts_dict() -> None:
    manual_responses = {201: {"description": "Created"}}

    @openapi(summary="Unified response dict", responses=manual_responses)
    def unified_response_dict_func() -> None:
        pass

    registry = get_openapi_registry()
    assert registry["unified_response_dict_func"]["response_model"] is None
    assert registry["unified_response_dict_func"]["response"] == manual_responses


def test_openapi_raises_error_when_requests_and_request_model_provided() -> None:
    import pytest

    with pytest.raises(ValueError) as exc_info:

        @openapi(
            summary="Conflicting request params",
            requests=_UnifiedRequestModel,
            request_model=_UnifiedRequestModel,
        )
        def conflicting_requests_func() -> None:
            pass

    assert "Cannot provide both 'requests' and 'request_model'/'request_body'." in str(
        exc_info.value
    )


def test_openapi_raises_error_when_responses_and_response_model_provided() -> None:
    import pytest

    with pytest.raises(ValueError) as exc_info:

        @openapi(
            summary="Conflicting response params",
            responses=_UnifiedResponseModel,
            response_model=_UnifiedResponseModel,
        )
        def conflicting_responses_func() -> None:
            pass

    assert "Cannot provide both 'responses' and 'response_model'/'response'." in str(exc_info.value)


def test_openapi_registers_request_body_required_default() -> None:
    """request_body_required defaults to True and is stored in registry."""

    @openapi(
        summary="Required body by default",
        method="post",
        request_body={"type": "object"},
        response={200: {"description": "OK"}},
    )
    def default_required_func() -> None:
        pass

    registry = get_openapi_registry()
    assert registry["default_required_func"]["request_body_required"] is True


def test_openapi_registers_request_body_required_false() -> None:
    """request_body_required=False is stored in registry and used in spec."""
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(
        summary="Optional body",
        route="/optional-body",
        method="post",
        request_body={"type": "object"},
        request_body_required=False,
        response={200: {"description": "OK"}},
    )
    def optional_body_func() -> None:
        pass

    registry = get_openapi_registry()
    assert registry["optional_body_func"]["request_body_required"] is False

    spec = generate_openapi_spec(route_prefix="")
    rb = spec["paths"]["/optional-body"]["post"]["requestBody"]
    assert rb["required"] is False



def test_openapi_raises_runtime_error_when_function_builder_internals_change() -> None:
    """Regression #212: defensive guard around FunctionBuilder._function._func."""
    from azure.functions.decorators.function_app import FunctionBuilder
    import pytest

    # Build a FunctionBuilder-shaped object whose ``_function`` lacks ``_func``,
    # simulating an SDK internal restructure.
    fake_builder = FunctionBuilder.__new__(FunctionBuilder)
    fake_builder._function = object()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="azure-functions SDK appears incompatible"):
        openapi(summary="x")(fake_builder)