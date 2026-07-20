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
    scan_validation_metadata,
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


@dataclass
class MockBuilder:
    _function: MockFunction


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

    scan_validation_metadata(app)

    registry = get_openapi_registry()
    entry = registry["post::/api/users"]
    assert entry["response_model"] is ResponseModel
    assert "request_body" in entry


def test_scan_skips_non_validated_functions() -> None:
    app = _make_app(metadata=None)

    scan_validation_metadata(app)

    assert get_openapi_registry() == {}


def test_explicit_openapi_wins() -> None:
    register_openapi_metadata(path="/api/users", method="post", summary="explicit")
    app = _make_app(metadata={"body": CreateBody, "response_model": ResponseModel})

    scan_validation_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["summary"] == "explicit"


def test_body_model_registered_as_request_body() -> None:
    app = _make_app(metadata={"body": CreateBody})

    scan_validation_metadata(app)

    schema = get_openapi_registry()["post::/api/users"]["request_body"]
    assert schema["type"] == "object"
    assert "name" in schema["properties"]


def test_query_model_registered_as_parameters() -> None:
    app = _make_app(metadata={"query": QueryModel})

    scan_validation_metadata(app)

    params = get_openapi_registry()["post::/api/users"]["parameters"]
    assert any(p["in"] == "query" and p["name"] == "limit" for p in params)


def test_path_model_registered_as_parameters() -> None:
    app = _make_app(route="users/{user_id}", metadata={"path": PathModel})

    scan_validation_metadata(app)

    params = get_openapi_registry()["post::/api/users/{user_id}"]["parameters"]
    path_param = next(p for p in params if p["name"] == "user_id")
    assert path_param["in"] == "path"
    assert path_param["required"] is True


def test_response_model_registered() -> None:
    app = _make_app(metadata={"response_model": ResponseModel})

    scan_validation_metadata(app)

    assert get_openapi_registry()["post::/api/users"]["response_model"] is ResponseModel


def test_scan_without_validation_metadata() -> None:
    """Handlers without the convention attribute are silently skipped."""
    handler_fn = lambda req: req  # noqa: E731
    binding = MockBinding(route="users", methods=["POST"])
    fn = MockFunction(_name="create_user", _func=handler_fn, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_validation_metadata(app)

    assert get_openapi_registry() == {}


def test_scan_empty_app() -> None:
    scan_validation_metadata(MockApp(_function_builders=[]))
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
        scan_validation_metadata(app)


def test_scan_skips_non_http_bindings() -> None:
    handler = _make_validated_handler({"body": CreateBody})
    fn = MockFunction(
        _name="non_http",
        _func=handler,
        _bindings=[MockBinding(route="queue", methods=None, type="queueTrigger")],
    )
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_validation_metadata(app)

    assert get_openapi_registry() == {}


def test_scan_defaults_method_to_get_when_unspecified() -> None:
    handler = _make_validated_handler({"response_model": ResponseModel})
    binding = MockBinding(route="users", methods=None, type="httpTrigger")
    fn = MockFunction(_name="get_users", _func=handler, _bindings=[binding])
    app = MockApp(_function_builders=[MockBuilder(_function=fn)])

    scan_validation_metadata(app)

    assert "get::/api/users" in get_openapi_registry()


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
    scan_validation_metadata(app)

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
        scan_validation_metadata(app)


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

    scan_validation_metadata(app)

    assert "post::/api/users" in get_openapi_registry()


def test_scan_supports_empty_prefix_for_disabled_host_prefix() -> None:
    app = _make_app(metadata={"body": CreateBody})

    scan_validation_metadata(app, route_prefix="")

    assert "post::/users" in get_openapi_registry()


def test_scan_supports_custom_prefix() -> None:
    app = _make_app(metadata={"body": CreateBody})

    scan_validation_metadata(app, route_prefix="/v1")

    assert "post::/v1/users" in get_openapi_registry()


def test_scan_does_not_double_apply_prefix() -> None:
    app = _make_app(route="/api/users", metadata={"body": CreateBody})

    scan_validation_metadata(app, route_prefix="/api")

    assert "post::/api/users" in get_openapi_registry()
    assert "post::/api/api/users" not in get_openapi_registry()


def test_scan_normalizes_prefix_with_trailing_slash() -> None:
    app = _make_app(metadata={"body": CreateBody})

    scan_validation_metadata(app, route_prefix="v1/")

    assert "post::/v1/users" in get_openapi_registry()


def test_scan_does_not_treat_substring_match_as_already_prefixed() -> None:
    """A route like ``/apiary`` shares ``/api`` as a prefix string but is not
    actually under the ``/api`` route prefix. The composer must require the
    prefix be followed by ``/`` (or be an exact match) before treating the
    route as already prefixed; otherwise ``/apiary`` would be left bare and
    the deployed URL ``/api/apiary`` would not appear in the spec.
    """
    app = _make_app(route="/apiary", metadata={"body": CreateBody})

    scan_validation_metadata(app, route_prefix="/api")

    assert "post::/api/apiary" in get_openapi_registry()
    assert "post::/apiary" not in get_openapi_registry()


def test_scan_does_not_treat_apidocs_as_already_prefixed() -> None:
    app = _make_app(route="/apidocs", metadata={"body": CreateBody})

    scan_validation_metadata(app, route_prefix="/api")

    assert "post::/api/apidocs" in get_openapi_registry()
    assert "post::/apidocs" not in get_openapi_registry()


def test_scan_treats_exact_prefix_match_as_already_prefixed() -> None:
    app = _make_app(route="/api", metadata={"body": CreateBody})

    scan_validation_metadata(app, route_prefix="/api")

    assert "post::/api" in get_openapi_registry()
    assert "post::/api/api" not in get_openapi_registry()


def test_bridge_helpers_cover_default_normalization_paths() -> None:
    assert _normalize_method(None) == "get"
    assert _normalize_path("", "users", "/api") == "/api/users"


def test_extract_methods_handles_string_and_invalid_type() -> None:
    class _Binding:
        def __init__(self, methods: Any) -> None:
            self.methods = methods

    assert _extract_methods(_Binding("POST")) == ["post"]
    assert _extract_methods(_Binding(123)) == ["get"]


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
    scan_validation_metadata(app)

    params = get_openapi_registry()["post::/api/users"]["parameters"]
    header_param = next(p for p in params if p["name"] == "x_request_id")
    assert header_param["in"] == "header"


def test_scan_skips_builders_without_function_or_handler() -> None:
    builder_without_function: Any = type("Builder", (), {"_function": None})()
    function_without_handler = MockFunction(_name="no_handler", _func=None, _bindings=[])
    builder_without_handler = MockBuilder(_function=function_without_handler)
    app = MockApp(_function_builders=cast(Any, [builder_without_function, builder_without_handler]))

    scan_validation_metadata(app)
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