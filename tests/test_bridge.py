from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel
import pytest

from azure_functions_openapi.bridge import (
    _HANDLER_METADATA_ATTR,
    _extract_methods,
    _field_type_to_schema,
    _merge_parameters,
    _model_to_parameters,
    _models_conflict,
    _normalize_method,
    _normalize_path,
    _read_validation_hints,
    scan_endpoint_metadata,
)
from azure_functions_openapi.decorator import (
    _openapi_registry,
    _registry_lock,
    clear_openapi_registry,
    get_openapi_registry,
    register_openapi_metadata,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.utils import model_to_schema, type_to_schema


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class CreateBody(BaseModel):
    name: str


class QueryModel(BaseModel):
    limit: int


class PathModel(BaseModel):
    user_id: int


class ResponseModel(BaseModel):
    id: int


class AltResponseModel(BaseModel):
    ok: bool


@dataclass
class MockBinding:
    route: str
    methods: list[str] | None
    type: str = "httpTrigger"


@dataclass
class MockFunction:
    _name: str
    _func: Any
    _bindings: list[Any]

    # Public accessors mirroring azure.functions Function; the adapter reads the
    # function exclusively through these (never the underscored fields).
    def get_function_name(self) -> str:
        return self._name

    def get_user_function(self) -> Any:
        return self._func

    def get_bindings(self) -> list[Any]:
        return self._bindings

    def is_http_function(self) -> bool:
        return any(
            str(getattr(b, "type", "")).lower() == "httptrigger" for b in self._bindings
        )


@dataclass
class MockBuilder:
    _function: MockFunction

    # Public, idempotent build() mirroring FunctionBuilder.build; the adapter
    # enumerates via _function_builders + this method (never get_functions()).
    def build(self, auth_level: Any = None) -> MockFunction:
        return self._function


@dataclass
class MockApp:
    _function_builders: list[MockBuilder]


def _make_validated_handler(metadata: dict[str, Any]) -> Any:
    def handler(req: Any) -> Any:
        return req

    setattr(handler, _HANDLER_METADATA_ATTR, {"validation": metadata})
    return handler


def _make_app(
    *,
    name: str = "create_user",
    route: str = "users",
    methods: list[str] | None = None,
    metadata: Any = None,
) -> MockApp:
    handler = _make_validated_handler(metadata) if metadata is not None else (lambda req: req)
    binding = MockBinding(route=route, methods=methods or ["POST"])
    fn = MockFunction(_name=name, _func=handler, _bindings=[binding])
    return MockApp(_function_builders=[MockBuilder(_function=fn)])


def test_scan_discovers_validation_metadata() -> None:
    app = _make_app(metadata={"body": CreateBody, "response_model": ResponseModel})

    scan_endpoint_metadata(app)

    registry = get_openapi_registry()
    entry = registry["post::/api/users"]
    assert entry["response_model"] is ResponseModel
    assert "request_body" in entry


def test_scan_skips_non_validated_functions() -> None:
    app = _make_app(metadata=None)

    scan_endpoint_metadata(app)

    assert get_openapi_registry() == {}


def test_explicit_openapi_wins() -> None:
    register_openapi_metadata(path="/api/users", method="post", summary="explicit")
    app = _make_app(metadata={"body": CreateBody, "response_model": ResponseModel})

    scan_endpoint_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["summary"] == "explicit"


def test_body_model_registered_as_request_body() -> None:
    app = _make_app(metadata={"body": CreateBody})

    scan_endpoint_metadata(app)

    schema = get_openapi_registry()["post::/api/users"]["request_body"]
    assert schema["type"] == "object"
    assert "name" in schema["properties"]


def test_query_model_registered_as_parameters() -> None:
    app = _make_app(metadata={"query": QueryModel})

    scan_endpoint_metadata(app)

    params = get_openapi_registry()["post::/api/users"]["parameters"]
    assert any(p["in"] == "query" and p["name"] == "limit" for p in params)


def test_path_model_registered_as_parameters() -> None:
    app = _make_app(route="users/{user_id}", metadata={"path": PathModel})

    scan_endpoint_metadata(app)

    params = get_openapi_registry()["post::/api/users/{user_id}"]["parameters"]
    path_param = next(p for p in params if p["name"] == "user_id")
    assert path_param["in"] == "path"
    assert path_param["required"] is True


def test_response_model_registered() -> None:
    app = _make_app(metadata={"response_model": ResponseModel})

    scan_endpoint_metadata(app)

    assert get_openapi_registry()["post::/api/users"]["response_model"] is ResponseModel


def test_scan_without_validation_metadata() -> None:
    """Handlers without the convention attribute are silently skipped."""
    handler_fn = lambda req: req  # noqa: E731
    binding = MockBinding(route="users", methods=["POST"])
    fn = MockFunction(_name="create_user", _func=handler_fn, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    assert get_openapi_registry() == {}


def test_scan_empty_app() -> None:
    scan_endpoint_metadata(MockApp(_function_builders=[]))
    assert get_openapi_registry() == {}


def test_model_to_parameters_conversion() -> None:
    params = _model_to_parameters(QueryModel, "query")
    limit = next(p for p in params if p["name"] == "limit")
    assert limit["in"] == "query"
    assert limit["schema"]["type"] == "integer"


def test_conflict_detection() -> None:
    register_openapi_metadata(path="/api/users", method="post", response_model=AltResponseModel)
    app = _make_app(metadata={"response_model": ResponseModel})

    with pytest.raises(OpenAPISpecConfigError):
        scan_endpoint_metadata(app)


def test_scan_skips_non_http_bindings() -> None:
    handler = _make_validated_handler({"body": CreateBody})
    fn = MockFunction(
        _name="non_http",
        _func=handler,
        _bindings=[MockBinding(route="queue", methods=None, type="queueTrigger")],
    )
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    assert get_openapi_registry() == {}


def test_scan_expands_unspecified_methods_to_all_http_methods() -> None:
    # Azure runtime responds to *all* HTTP methods when methods= is omitted, so
    # the scan must register every HttpMethod rather than defaulting to GET.
    handler = _make_validated_handler({"response_model": ResponseModel})
    binding = MockBinding(route="users", methods=None, type="httpTrigger")
    fn = MockFunction(_name="get_users", _func=handler, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    registry_keys = set(get_openapi_registry())
    for method in ("get", "post", "put", "delete", "patch", "head", "options"):
        assert f"{method}::/api/users" in registry_keys


def test_scan_omits_request_body_from_expanded_bodyless_methods() -> None:
    # Policy (#335): when methods= is unspecified we expand to all HTTP methods,
    # but GET/HEAD/DELETE must not carry a requestBody (OpenAPI leaves it
    # undefined there). Body-bearing methods keep it.
    handler = _make_validated_handler({"body": CreateBody})
    binding = MockBinding(route="users", methods=None, type="httpTrigger")
    fn = MockFunction(_name="users", _func=handler, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    registry = get_openapi_registry()
    for method in ("get", "head", "delete"):
        assert registry[f"{method}::/api/users"]["request_body"] is None
    for method in ("post", "put", "patch"):
        assert registry[f"{method}::/api/users"]["request_body"] is not None

    registry_keys = set(get_openapi_registry())
    for method in ("get", "post", "put", "delete", "patch", "head", "options"):
        assert f"{method}::/api/users" in registry_keys


def test_scan_reconciles_plain_openapi_recommended_order_expansion() -> None:
    # #354: whichever decorator order is used, @openapi decorates the function
    # before the HTTP-trigger binding is observable, so the entry is registered
    # with method=None and emits GET only. This is easiest to hit in the
    # README-recommended order (@openapi above @app.route). The scan sees the
    # wrapped builder with an httptrigger binding that omits methods=, and must
    # reconcile the entry to expand to every HTTP method — even though the
    # handler carries no endpoint/validation metadata.
    from azure_functions_openapi.decorator import openapi
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(summary="list things", route="things")
    def things(req: Any) -> Any:
        return req

    binding = MockBinding(route="things", methods=None, type="httpTrigger")
    fn = MockFunction(_name="things", _func=things, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)
    spec = generate_openapi_spec("T", "1.0.0")

    assert set(spec["paths"]["/api/things"].keys()) == {
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "head",
        "options",
    }


def test_scan_does_not_expand_plain_openapi_with_explicit_method() -> None:
    # #354 guard: reconciliation must never override an explicit method. When the
    # @openapi entry declares a method, an unspecified-methods binding does not
    # trigger all-method expansion.
    from azure_functions_openapi.decorator import openapi
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(summary="make thing", route="things", method="post")
    def make_thing(req: Any) -> Any:
        return req

    binding = MockBinding(route="things", methods=None, type="httpTrigger")
    fn = MockFunction(_name="make_thing", _func=make_thing, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)
    spec = generate_openapi_spec("T", "1.0.0")

    assert set(spec["paths"]["/api/things"].keys()) == {"post"}


def test_scan_reconciles_method_for_openapi_below_route_post() -> None:
    # #358: when @openapi sits BELOW @app.route, it decorates the raw function
    # and registers with method=None (no binding visible). The scan sees the
    # POST binding and must explode the method=None entry into a per-method
    # entry — otherwise every method collapses into a lone GET.
    from azure_functions_openapi.decorator import openapi
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(summary="create thing", route="things")
    def make_thing(req: Any) -> Any:
        return req

    setattr(make_thing, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})
    binding = MockBinding(route="things", methods=["POST"], type="httpTrigger")
    fn = MockFunction(_name="make_thing", _func=make_thing, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    registry = get_openapi_registry()
    # The original method=None short-name entry must be gone; only the
    # per-method entry remains.
    assert "make_thing" not in registry
    assert "post::/api/things" in registry
    entry = registry["post::/api/things"]
    assert entry["method"] == "post"
    assert entry["summary"] == "create thing"
    assert entry["request_body"] is not None

    spec = generate_openapi_spec("T", "1.0.0")
    assert set(spec["paths"]["/api/things"].keys()) == {"post"}


def test_scan_reconciles_method_for_openapi_below_route_unspecified_expands() -> None:
    # #358: an unspecified-methods binding below @openapi expands to every HTTP
    # method, with GET/HEAD/DELETE stripped of the request body.
    from azure_functions_openapi.decorator import openapi
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(summary="any thing", route="things")
    def any_thing(req: Any) -> Any:
        return req

    setattr(any_thing, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})
    binding = MockBinding(route="things", methods=None, type="httpTrigger")
    fn = MockFunction(_name="any_thing", _func=any_thing, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    registry = get_openapi_registry()
    assert "any_thing" not in registry
    for method in ("get", "head", "delete"):
        assert registry[f"{method}::/api/things"]["request_body"] is None
    for method in ("post", "put", "patch"):
        assert registry[f"{method}::/api/things"]["request_body"] is not None

    spec = generate_openapi_spec("T", "1.0.0")
    assert set(spec["paths"]["/api/things"].keys()) == {
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "head",
        "options",
    }


def test_scan_reconciles_method_for_openapi_below_route_multi_method() -> None:
    # #358: an explicit multi-method binding below @openapi produces one entry
    # per method (not a single collapsed GET).
    from azure_functions_openapi.decorator import openapi
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(summary="rw thing", route="things")
    def rw_thing(req: Any) -> Any:
        return req

    setattr(rw_thing, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})
    binding = MockBinding(route="things", methods=["GET", "POST"], type="httpTrigger")
    fn = MockFunction(_name="rw_thing", _func=rw_thing, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    spec = generate_openapi_spec("T", "1.0.0")
    assert set(spec["paths"]["/api/things"].keys()) == {"get", "post"}


def test_scan_below_route_is_idempotent_across_repeated_scans() -> None:
    # #358: re-running the scan must not duplicate or drop per-method entries.
    from azure_functions_openapi.decorator import openapi
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(summary="idem thing", route="things")
    def idem_thing(req: Any) -> Any:
        return req

    setattr(idem_thing, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})
    binding = MockBinding(route="things", methods=["POST"], type="httpTrigger")
    fn = MockFunction(_name="idem_thing", _func=idem_thing, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)
    scan_endpoint_metadata(app)

    spec = generate_openapi_spec("T", "1.0.0")
    assert set(spec["paths"]["/api/things"].keys()) == {"post"}


def test_scan_below_route_does_not_override_explicit_openapi_method() -> None:
    # #358 guard: an explicit method= on @openapi must never be exploded or
    # overridden by the binding — the entry keeps its declared method.
    from azure_functions_openapi.decorator import openapi
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(summary="explicit thing", route="things", method="put")
    def explicit_thing(req: Any) -> Any:
        return req

    setattr(explicit_thing, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})
    binding = MockBinding(route="things", methods=["POST"], type="httpTrigger")
    fn = MockFunction(_name="explicit_thing", _func=explicit_thing, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    spec = generate_openapi_spec("T", "1.0.0")
    assert set(spec["paths"]["/api/things"].keys()) == {"put"}


def test_scan_below_route_preserves_binding_route_when_name_differs() -> None:
    # #360: the explode branch must carry the binding route onto each clone.
    # @openapi below @app.route registers route=None; without preservation the
    # spec falls back to the function name and emits the wrong path. Uses a
    # route that can never equal the function name (real-world case).
    from azure_functions_openapi.decorator import openapi
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(summary="create user")
    def handler_one(req: Any) -> Any:
        return req

    setattr(handler_one, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})
    binding = MockBinding(route="users/create", methods=["POST"], type="httpTrigger")
    fn = MockFunction(_name="handler_one", _func=handler_one, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    registry = get_openapi_registry()
    assert registry["post::/api/users/create"]["route"] == "users/create"

    spec = generate_openapi_spec("T", "1.0.0")
    # Correct binding-derived path, NOT /api/handler_one, and not double-prefixed.
    assert set(spec["paths"].keys()) == {"/api/users/create"}
    assert set(spec["paths"]["/api/users/create"].keys()) == {"post"}


def test_scan_below_route_preserves_explicit_openapi_route_override() -> None:
    # #360: an explicit @openapi(route=...) must win over the binding route.
    from azure_functions_openapi.decorator import openapi
    from azure_functions_openapi.spec import generate_openapi_spec

    @openapi(summary="create user", route="custom/path")
    def handler_three(req: Any) -> Any:
        return req

    setattr(handler_three, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})
    binding = MockBinding(route="users/create", methods=["POST"], type="httpTrigger")
    fn = MockFunction(_name="handler_three", _func=handler_three, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_endpoint_metadata(app)

    spec = generate_openapi_spec("T", "1.0.0")
    assert set(spec["paths"].keys()) == {"/api/custom/path"}


def test_scan_merges_explicit_function_name_entry() -> None:
    with _registry_lock:
        _openapi_registry["create_user"] = {
            "summary": "explicit",
            "description": "",
            "tags": ["default"],
            "operation_id": "create_user",
            "route": "/api/users",
            "method": "post",
            "parameters": [],
            "security": [],
            "security_scheme": {},
            "request_model": None,
            "request_body": None,
            "request_body_required": True,
            "response_model": None,
            "response": {},
            "function_name": "create_user",
            "_function_id": "tests.create_user",
        }

    app = _make_app(name="create_user", metadata={"body": CreateBody})
    scan_endpoint_metadata(app)

    entry = get_openapi_registry()["create_user"]
    assert entry["summary"] == "explicit"
    assert entry["request_body"]["type"] == "object"


def test_parameter_conflict_detection() -> None:
    register_openapi_metadata(
        path="/api/users",
        method="post",
        parameters=[
            {"name": "limit", "in": "query", "required": True, "schema": {"type": "string"}}
        ],
    )
    app = _make_app(metadata={"query": QueryModel})

    with pytest.raises(OpenAPISpecConfigError, match="Conflicting validation"):
        scan_endpoint_metadata(app)


def test_type_to_schema_registers_defs_for_generic_types() -> None:
    components: dict[str, Any] = {"schemas": {}}

    schema = type_to_schema(list[ResponseModel], components)

    assert schema["type"] == "array"
    assert schema["items"]["$ref"] == "#/components/schemas/ResponseModel"
    assert "ResponseModel" in components["schemas"]


def test_model_to_schema_accepts_generic_type_hints() -> None:
    components: dict[str, Any] = {"schemas": {}}

    schema = model_to_schema(list[ResponseModel], components)

    assert schema["type"] == "array"
    assert schema["items"]["$ref"] == "#/components/schemas/ResponseModel"


def test_type_to_schema_without_components() -> None:
    schema = type_to_schema(ResponseModel | None)
    assert "anyOf" in schema or "oneOf" in schema or "type" in schema


# ---------------------------------------------------------------------------
# Tests for _read_validation_hints enhancements (Issue #172)
# ---------------------------------------------------------------------------


class TestWrappedChainTraversal:
    """Verify __wrapped__ chain walking finds metadata on inner handlers."""

    def test_metadata_on_inner_wrapped_handler(self) -> None:
        """Metadata set on an inner handler is found through __wrapped__."""
        inner: Any = lambda req: req  # noqa: E731
        setattr(inner, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})

        outer: Any = lambda req: inner(req)  # noqa: E731
        outer.__wrapped__ = inner

        result = _read_validation_hints(outer)
        assert result is not None
        assert result["body"] is CreateBody

    def test_metadata_on_outer_wins(self) -> None:
        """When both outer and inner have metadata, outer wins (first match)."""
        inner: Any = lambda req: req  # noqa: E731
        setattr(inner, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})

        outer: Any = lambda req: inner(req)  # noqa: E731
        setattr(outer, _HANDLER_METADATA_ATTR, {"validation": {"response_model": ResponseModel}})
        outer.__wrapped__ = inner

        result = _read_validation_hints(outer)
        assert result is not None
        assert "response_model" in result
        assert "body" not in result

    def test_no_metadata_in_chain(self) -> None:
        """Returns None when no handler in the chain has metadata."""
        inner: Any = lambda req: req  # noqa: E731
        outer: Any = lambda req: inner(req)  # noqa: E731
        outer.__wrapped__ = inner

        assert _read_validation_hints(outer) is None

    def test_deeply_nested_wrapped_chain(self) -> None:
        """Metadata is found several levels deep."""
        bottom: Any = lambda req: req  # noqa: E731
        setattr(bottom, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})

        current: Any = bottom
        for _ in range(5):
            wrapper: Any = lambda req, fn=current: fn(req)  # noqa: E731
            wrapper.__wrapped__ = current
            current = wrapper

        result = _read_validation_hints(current)
        assert result is not None
        assert result["body"] is CreateBody

    def test_self_referencing_wrapped_stops(self) -> None:
        """A handler whose __wrapped__ points to itself doesn't loop."""
        handler: Any = lambda req: req  # noqa: E731
        handler.__wrapped__ = handler

        # Should not hang; just returns None
        assert _read_validation_hints(handler) is None


class TestVersionValidation:
    """Verify version gating in _read_validation_hints."""

    def test_missing_version_accepted(self) -> None:
        """No 'version' key is treated as v1 — accepted."""
        handler = lambda req: req  # noqa: E731
        setattr(handler, _HANDLER_METADATA_ATTR, {"validation": {"body": CreateBody}})

        result = _read_validation_hints(handler)
        assert result is not None
        assert result["body"] is CreateBody

    def test_version_1_accepted(self) -> None:
        """Explicit nested version=1 is accepted."""
        handler = lambda req: req  # noqa: E731
        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {
                "validation": {"version": 1, "body": CreateBody},
            },
        )

        result = _read_validation_hints(handler)
        assert result is not None
        assert result["body"] is CreateBody

    def test_unsupported_version_skipped(self) -> None:
        """Unsupported integer version emits warning and returns None."""
        handler = lambda req: req  # noqa: E731
        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {
                "validation": {"version": 999, "body": CreateBody},
            },
        )

        result = _read_validation_hints(handler)
        assert result is None

    def test_malformed_version_string_skipped(self) -> None:
        """Non-int version (e.g. string) emits warning and returns None."""
        handler = lambda req: req  # noqa: E731
        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {
                "validation": {"version": "1", "body": CreateBody},
            },
        )

        result = _read_validation_hints(handler)
        assert result is None

    def test_malformed_version_float_skipped(self) -> None:
        """Float version is rejected (only int accepted)."""
        handler = lambda req: req  # noqa: E731
        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {
                "validation": {"version": 1.0, "body": CreateBody},
            },
        )

        result = _read_validation_hints(handler)
        assert result is None

    def test_unsupported_version_warning_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Warning is logged with handler repr and unsupported version."""
        handler = lambda req: req  # noqa: E731
        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {
                "validation": {"version": 42, "body": CreateBody},
            },
        )

        with caplog.at_level("WARNING", logger="azure_functions_openapi.bridge"):
            _read_validation_hints(handler)

        assert any("unsupported version" in m for m in caplog.messages)
        assert any("42" in m for m in caplog.messages)

    def test_outer_invalid_version_inner_valid_discovered(self) -> None:
        """Invalid version on outer should not block valid inner metadata."""
        inner: Any = lambda req: req  # noqa: E731
        setattr(
            inner,
            _HANDLER_METADATA_ATTR,
            {
                "validation": {"version": 1, "body": CreateBody},
            },
        )

        outer: Any = lambda req: inner(req)  # noqa: E731
        setattr(
            outer,
            _HANDLER_METADATA_ATTR,
            {
                "validation": {"version": 999, "body": ResponseModel},
            },
        )
        outer.__wrapped__ = inner

        result = _read_validation_hints(outer)
        assert result is not None
        # Inner metadata (v1) is discovered, not the outer (v999)
        assert result["body"] is CreateBody

    def test_boolean_version_rejected(self) -> None:
        """version=True is a bool, not int — should be rejected."""
        handler = lambda req: req  # noqa: E731
        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {
                "validation": {"version": True, "body": CreateBody},
            },
        )

        result = _read_validation_hints(handler)
        assert result is None


class TestDeepCopyMutationSafety:
    """Returned hints are deep copies — mutating them doesn't affect the handler."""

    def test_mutation_does_not_affect_handler(self) -> None:
        handler = lambda req: req  # noqa: E731
        original_meta = {"body": CreateBody, "extra": {"nested": "value"}}
        setattr(handler, _HANDLER_METADATA_ATTR, {"validation": original_meta})

        result = _read_validation_hints(handler)
        assert result is not None

        # Mutate the returned copy
        result["injected"] = "attack"
        result["extra"]["nested"] = "mutated"

        # Original is untouched
        stored = getattr(handler, _HANDLER_METADATA_ATTR)["validation"]
        assert "injected" not in stored
        assert stored["extra"]["nested"] == "value"

    def test_successive_reads_are_independent(self) -> None:
        handler = lambda req: req  # noqa: E731
        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {
                "validation": {"body": CreateBody, "extra": {"key": "original"}},
            },
        )

        first = _read_validation_hints(handler)
        assert first is not None
        first["extra"]["key"] = "changed"

        second = _read_validation_hints(handler)
        assert second is not None
        assert second["extra"]["key"] == "original"


def test_scan_uses_default_api_prefix() -> None:
    app = _make_app(metadata={"body": CreateBody})

    scan_endpoint_metadata(app)

    assert "post::/api/users" in get_openapi_registry()


def test_scan_supports_empty_prefix_for_disabled_host_prefix() -> None:
    app = _make_app(metadata={"body": CreateBody})

    scan_endpoint_metadata(app, route_prefix="")

    assert "post::/users" in get_openapi_registry()


def test_scan_supports_custom_prefix() -> None:
    app = _make_app(metadata={"body": CreateBody})

    scan_endpoint_metadata(app, route_prefix="/v1")

    assert "post::/v1/users" in get_openapi_registry()


def test_scan_does_not_double_apply_prefix() -> None:
    app = _make_app(route="/api/users", metadata={"body": CreateBody})

    scan_endpoint_metadata(app, route_prefix="/api")

    assert "post::/api/users" in get_openapi_registry()
    assert "post::/api/api/users" not in get_openapi_registry()


def test_scan_normalizes_prefix_with_trailing_slash() -> None:
    app = _make_app(metadata={"body": CreateBody})

    scan_endpoint_metadata(app, route_prefix="v1/")

    assert "post::/v1/users" in get_openapi_registry()


def test_scan_does_not_treat_substring_match_as_already_prefixed() -> None:
    """A route like ``/apiary`` shares ``/api`` as a prefix string but is not
    actually under the ``/api`` route prefix. The composer must require the
    prefix be followed by ``/`` (or be an exact match) before treating the
    route as already prefixed; otherwise ``/apiary`` would be left bare and
    the deployed URL ``/api/apiary`` would not appear in the spec.
    """
    app = _make_app(route="/apiary", metadata={"body": CreateBody})

    scan_endpoint_metadata(app, route_prefix="/api")

    assert "post::/api/apiary" in get_openapi_registry()
    assert "post::/apiary" not in get_openapi_registry()


def test_scan_does_not_treat_apidocs_as_already_prefixed() -> None:
    app = _make_app(route="/apidocs", metadata={"body": CreateBody})

    scan_endpoint_metadata(app, route_prefix="/api")

    assert "post::/api/apidocs" in get_openapi_registry()
    assert "post::/apidocs" not in get_openapi_registry()


def test_scan_treats_exact_prefix_match_as_already_prefixed() -> None:
    app = _make_app(route="/api", metadata={"body": CreateBody})

    scan_endpoint_metadata(app, route_prefix="/api")

    assert "post::/api" in get_openapi_registry()
    assert "post::/api/api" not in get_openapi_registry()


def test_bridge_helpers_cover_default_normalization_paths() -> None:
    assert _normalize_method(None) == "get"
    assert _normalize_path("", "users", "/api") == "/api/users"


def test_extract_methods_handles_string_and_invalid_type() -> None:
    class _Binding:
        def __init__(self, methods: Any) -> None:
            self.methods = methods

    assert _extract_methods(_Binding("POST")) == (["post"], False)
    assert _extract_methods(_Binding(123)) == (["get"], False)
    # Unspecified methods= expands to every HTTP method (expanded=True).
    assert _extract_methods(_Binding(None)) == (
        ["get", "post", "put", "delete", "patch", "head", "options"],
        True,
    )
    # An explicit empty list is a different signal: not expanded.
    assert _extract_methods(_Binding([])) == (["get"], False)


def test_merge_parameters_appends_non_conflicting_items() -> None:
    merged = _merge_parameters(
        [{"name": "id", "in": "path", "schema": {"type": "string"}}],
        [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
    )
    assert len(merged) == 2
    assert any(p["name"] == "limit" and p["in"] == "query" for p in merged)


def test_models_conflict_detects_request_body_mismatch() -> None:
    assert (
        _models_conflict(
            {"request_body": {"type": "object", "properties": {"a": {"type": "string"}}}},
            {"request_body": {"type": "object", "properties": {"a": {"type": "integer"}}}},
        )
        is True
    )


def test_field_type_to_schema_primitives_and_collected_defs() -> None:
    class _NestedModel(BaseModel):
        name: str

    assert _field_type_to_schema(str) == {"type": "string"}
    assert _field_type_to_schema(float) == {"type": "number"}
    assert _field_type_to_schema(bool) == {"type": "boolean"}
    assert _field_type_to_schema(list[int]) == {"type": "array"}

    schema = _field_type_to_schema(list[_NestedModel])
    assert "$defs" not in schema
    assert schema["type"] == "array"


def test_model_to_parameters_rejects_non_pydantic_model() -> None:
    with pytest.raises(TypeError, match="model_fields"):
        _model_to_parameters(object, "query")


def test_scan_includes_headers_model_as_header_parameters() -> None:
    class HeaderModel(BaseModel):
        x_request_id: str

    app = _make_app(metadata={"headers": HeaderModel})
    scan_endpoint_metadata(app)

    params = get_openapi_registry()["post::/api/users"]["parameters"]
    header_param = next(p for p in params if p["name"] == "x_request_id")
    assert header_param["in"] == "header"


def test_scan_skips_builders_without_function_or_handler() -> None:
    # Under the public-accessor contract the only "skip" signal is a built
    # function whose user handler is None (get_user_function() -> None).
    function_without_handler = MockFunction(_name="no_handler", _func=None, _bindings=[])
    builder_without_handler = MockBuilder(_function=function_without_handler)
    another_without_handler = MockBuilder(
        _function=MockFunction(_name="also_no_handler", _func=None, _bindings=[])
    )
    app = MockApp(
        _function_builders=cast(Any, [builder_without_handler, another_without_handler])
    )

    scan_endpoint_metadata(app)
    assert get_openapi_registry() == {}


class TestNestedVersionGate:
    """Regression: the version gate reads the nested namespace payload, not the top level."""

    def test_top_level_version_is_ignored(self) -> None:
        """A stray top-level 'version' must not gate; the nested v1 payload is accepted."""
        handler = lambda req: req  # noqa: E731
        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {
                "version": 999,  # top-level: producers never set this — must be ignored
                "validation": {"version": 1, "body": CreateBody},
            },
        )

        result = _read_validation_hints(handler)
        assert result is not None
        assert result["body"] is CreateBody

    def test_nested_unsupported_version_rejected_despite_valid_top_level(self) -> None:
        """Only the nested version gates; a valid top-level 'version' cannot rescue it."""
        handler = lambda req: req  # noqa: E731
        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {
                "version": 1,  # top-level: ignored
                "validation": {"version": 999, "body": CreateBody},
            },
        )

        assert _read_validation_hints(handler) is None
