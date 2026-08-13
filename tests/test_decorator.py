# tests/test_decorator.py

import azure.functions as func
from azure.functions.decorators.function_app import FunctionBuilder
from pydantic import BaseModel
import pytest

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


def test_openapi_auto_detects_route_and_method_from_function_builder() -> None:
    """When @openapi omits route/method, they should be extracted from @app.route."""
    _clear_registry()
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(summary="Create user")
    @app.route(route="users", methods=["POST"])
    def create_user(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("Created", status_code=201)

    registry = get_openapi_registry()
    assert registry["create_user"]["route"] == "users"
    assert registry["create_user"]["method"] == "post"

    spec = generate_openapi_spec(route_prefix="")
    assert "/users" in spec["paths"]
    assert "post" in spec["paths"]["/users"]


def test_openapi_explicit_route_overrides_binding() -> None:
    """Explicit route/method in @openapi should take precedence over binding."""
    _clear_registry()
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(summary="Custom", route="/custom-path", method="put")
    @app.route(route="users", methods=["POST"])
    def override_func(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=200)

    registry = get_openapi_registry()
    assert registry["override_func"]["route"] == "/custom-path"
    assert registry["override_func"]["method"] == "put"


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


def test_openapi_raises_error_for_invalid_method() -> None:
    """Test that @openapi rejects invalid HTTP methods like typos."""
    import pytest

    with pytest.raises(ValueError, match="Invalid HTTP method"):

        @openapi(summary="Bad method", method="posts")
        def bad_method_func() -> None:
            pass


def test_openapi_normalizes_method_to_lowercase() -> None:
    """Test that @openapi normalizes method to lowercase."""

    @openapi(summary="Uppercase method", method="POST")
    def uppercase_method_func() -> None:
        pass

    registry = get_openapi_registry()
    assert registry["uppercase_method_func"]["method"] == "post"


def test_openapi_raises_sdk_incompatible_error_when_function_builder_internals_change() -> None:
    """Regression #212 / design-review #272: defensive guard around
    FunctionBuilder._function._func now raises the dedicated SDKIncompatibleError."""
    from azure.functions.decorators.function_app import FunctionBuilder
    import pytest

    from azure_functions_openapi.exceptions import (
        OpenAPISpecConfigError,
        SDKIncompatibleError,
    )

    # Build a FunctionBuilder-shaped object whose ``_function`` lacks ``_func``,
    # simulating an SDK internal restructure.
    fake_builder = FunctionBuilder.__new__(FunctionBuilder)
    fake_builder._function = object()  # type: ignore[assignment]

    # SDKIncompatibleError subclasses OpenAPISpecConfigError (and ValueError), so
    # existing broad handlers keep working while the failure stays distinguishable.
    assert issubclass(SDKIncompatibleError, OpenAPISpecConfigError)
    with pytest.raises(SDKIncompatibleError, match="azure-functions SDK appears incompatible"):
        openapi(summary="x")(fake_builder)


def test_openapi_raises_on_multiple_binding_methods_without_explicit_method() -> None:
    """When @app.route has multiple methods, @openapi must require an explicit method=."""
    _clear_registry()
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    import pytest

    from azure_functions_openapi.exceptions import OpenAPISpecConfigError

    with pytest.raises(OpenAPISpecConfigError, match="multiple methods"):

        @openapi(summary="Ambiguous")
        @app.route(route="items", methods=["GET", "POST"])
        def items(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("OK")


def test_openapi_explicit_method_wins_over_multiple_binding_methods() -> None:
    """Explicit method= in @openapi bypasses the ambiguity check."""
    _clear_registry()
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @openapi(summary="List items", method="get")
    @app.route(route="items", methods=["GET", "POST"])
    def list_items(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK")

    registry = get_openapi_registry()
    assert registry["list_items"]["method"] == "get"


def test_openapi_below_route_with_non_trigger_binding_imports_cleanly() -> None:
    """Regression (#347 follow-up / v0.21.1): ``@openapi`` applied BELOW
    ``@app.route`` on top of a non-trigger binding (e.g. Durable Functions
    ``durable_client_input``) must not raise at import time.

    Decorators apply bottom-up, so when ``@openapi`` runs the FunctionBuilder
    has the input binding but NOT the HTTP trigger yet. On 0.21.0 the eager
    ``FunctionBuilder.build()`` raised ``ValueError: ... does not have a
    trigger`` and killed the user's ``function_app.py`` import. The decorator
    must instead tolerate the not-yet-built builder (mirroring
    ``iter_functions``), recover the handler, and still register metadata.
    """
    _clear_registry()
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="pipeline/start", methods=["POST"])
    @openapi(summary="Start", tags=["ai"])
    @app.generic_input_binding(arg_name="client", type="durableClient")
    def start_pipeline(req: func.HttpRequest, client: object) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=202)

    assert isinstance(start_pipeline, FunctionBuilder)

    registry = get_openapi_registry()
    assert "start_pipeline" in registry
    assert registry["start_pipeline"]["summary"] == "Start"
    assert registry["start_pipeline"]["tags"] == ["ai"]
    # Route/method could not be auto-detected at decoration time (no trigger
    # yet); they stay unresolved until discovery/spec generation reconciles them.
    assert registry["start_pipeline"]["route"] is None
    assert registry["start_pipeline"]["method"] is None


def test_openapi_below_route_resolves_final_route_via_discovery() -> None:
    """After decoration completes, ``scan_endpoint_metadata`` reconciles the
    unresolved route/method from the now-built HTTP trigger binding, so the
    generated spec renders the real path -- no endpoint is lost (v0.21.1)."""
    _clear_registry()
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="pipeline/start", methods=["POST"])
    @openapi(summary="Start", tags=["ai"])
    @app.generic_input_binding(arg_name="client", type="durableClient")
    def start_pipeline(req: func.HttpRequest, client: object) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=202)

    from azure_functions_openapi.bridge import scan_endpoint_metadata

    scan_endpoint_metadata(app, route_prefix="")
    spec = generate_openapi_spec(route_prefix="")
    assert "/pipeline/start" in spec["paths"]
    assert "post" in spec["paths"]["/pipeline/start"]


def test_resolve_metadata_target_recovers_handler_from_unbuilt_builder() -> None:
    """``_resolve_metadata_target`` returns the underlying handler off a builder
    that cannot build yet (no trigger), without a successful build (v0.21.1)."""
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.generic_input_binding(arg_name="client", type="durableClient")
    def orphan(req: func.HttpRequest, client: object) -> func.HttpResponse:
        return func.HttpResponse("OK")

    builder = app._function_builders[0]
    original, handler = decorator_module._resolve_metadata_target(builder)
    assert original is builder
    assert callable(handler)
    assert handler.__name__ == "orphan"


def test_extract_binding_hints_returns_none_for_unbuildable_builder() -> None:
    """``_extract_binding_hints`` yields all-unresolved hints for a builder that
    cannot build yet, instead of propagating the no-trigger ``ValueError``."""
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.generic_input_binding(arg_name="client", type="durableClient")
    def orphan(req: func.HttpRequest, client: object) -> func.HttpResponse:
        return func.HttpResponse("OK")

    builder = app._function_builders[0]
    assert decorator_module._extract_binding_hints(builder) == (None, None, False, False)


def test_resolve_metadata_target_reraises_when_handler_unrecoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a builder cannot build (no trigger) AND no handler can be recovered,
    the original ``ValueError`` must propagate -- the fallback never silently
    swallows a genuinely broken builder (v0.21.1)."""
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.generic_input_binding(arg_name="client", type="durableClient")
    def orphan(req: func.HttpRequest, client: object) -> func.HttpResponse:
        return func.HttpResponse("OK")

    from azure_functions_openapi import adapters

    monkeypatch.setattr(adapters, "get_unbuilt_user_handler", lambda _builder: None)
    builder = app._function_builders[0]
    with pytest.raises(ValueError):
        decorator_module._resolve_metadata_target(builder)



# ── #410: unified responses= with per-status model-derived schemas ──────────


def test_openapi_responses_dict_accepts_per_status_model() -> None:
    """A bare Pydantic model as a status value is normalized to a Response Object."""
    _clear_registry()

    @openapi(
        summary="Typed 2xx body + extra statuses",
        route="/api/items",
        method="post",
        responses={
            202: _UnifiedResponseModel,
            400: {"description": "Bad request"},
        },
    )
    def per_status_model_func() -> None:
        pass

    entry = get_openapi_registry()["per_status_model_func"]
    # No discrete response_model channel is used for per-status dict form.
    assert entry["response_model"] is None
    resp = entry["response"]
    # 202 expanded to a Response Object carrying the model in schema position.
    assert resp[202]["description"] == "Successful Response"
    assert resp[202]["content"]["application/json"]["schema"] is _UnifiedResponseModel
    # Non-model dict entries pass through unchanged.
    assert resp[400] == {"description": "Bad request"}


def test_openapi_responses_dict_non_2xx_model_default_description() -> None:
    """A bare model on a non-2xx status defaults to a generic 'Response' description."""
    _clear_registry()

    @openapi(summary="Error body", responses={409: _UnifiedResponseModel})
    def non_2xx_model_func() -> None:
        pass

    resp = get_openapi_registry()["non_2xx_model_func"]["response"]
    assert resp[409]["description"] == "Response"
    assert resp[409]["content"]["application/json"]["schema"] is _UnifiedResponseModel


def test_openapi_responses_dict_per_status_model_generates_schema() -> None:
    """End-to-end: per-status model resolves to a $ref and registers a component."""
    _clear_registry()

    @openapi(
        summary="Typed 2xx body + extra statuses",
        route="/api/items",
        method="post",
        responses={
            202: _UnifiedResponseModel,
            400: {"description": "Bad request"},
        },
    )
    def per_status_spec_func() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    op = spec["paths"]["/api/items"]["post"]
    responses = op["responses"]
    # 202 carries a $ref to the model schema; 400 keeps its plain description.
    schema = responses["202"]["content"]["application/json"]["schema"]
    assert "$ref" in schema
    assert schema["$ref"].endswith("/_UnifiedResponseModel")
    assert responses["400"]["description"] == "Bad request"
    assert "_UnifiedResponseModel" in spec["components"]["schemas"]


def test_openapi_responses_dict_model_in_content_schema() -> None:
    """A Pydantic model in the content.schema position is resolved at spec-gen."""
    _clear_registry()

    @openapi(
        summary="Model in explicit content schema",
        route="/api/items",
        method="post",
        responses={
            201: {
                "description": "Created",
                "content": {"application/json": {"schema": _UnifiedResponseModel}},
            },
        },
    )
    def content_schema_model_func() -> None:
        pass

    spec = generate_openapi_spec(route_prefix="")
    op = spec["paths"]["/api/items"]["post"]
    schema = op["responses"]["201"]["content"]["application/json"]["schema"]
    assert "$ref" in schema
    assert "_UnifiedResponseModel" in spec["components"]["schemas"]


def test_openapi_responses_dict_rejects_invalid_value() -> None:
    """A non-dict, non-model status value fails fast at decoration time."""
    _clear_registry()

    with pytest.raises(ValueError) as exc_info:

        @openapi(
            summary="Invalid responses entry",
            responses={200: "bad"},  # type: ignore[dict-item]
        )
        def invalid_responses_func() -> None:
            pass

    assert "Invalid 'responses' entry for status 200" in str(exc_info.value)