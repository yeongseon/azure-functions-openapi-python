from __future__ import annotations

from typing import Any

from pydantic import BaseModel
import pytest

from azure_functions_openapi.bridge import (
    _HANDLER_METADATA_ATTR,
    _discovered_operation_from_endpoint,
    _models_conflict,
    _read_endpoint_hints,
    scan_validation_metadata,
)
from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    get_openapi_registry,
    register_openapi_metadata,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


# A representative flat endpoint payload (all JSON Schema, no model classes).
FLAT_ENDPOINT: dict[str, Any] = {
    "version": 1,
    "request_body": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    "request_body_required": True,
    "parameters": [
        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
    ],
    "responses": {
        "200": {"schema": {"type": "object", "properties": {"id": {"type": "integer"}}}},
    },
}


class MockBinding:
    def __init__(self, route: str, methods: list[str] | None, type: str = "httpTrigger") -> None:
        self.route = route
        self.methods = methods
        self.type = type


class MockFunction:
    def __init__(self, name: str, func: Any, bindings: list[Any]) -> None:
        self._name = name
        self._func = func
        self._bindings = bindings


class MockBuilder:
    def __init__(self, function: MockFunction) -> None:
        self._function = function


class MockApp:
    def __init__(self, builders: list[MockBuilder]) -> None:
        self._function_builders = builders


def _make_handler(namespaces: dict[str, Any]) -> Any:
    def handler(req: Any) -> Any:
        return req

    setattr(handler, _HANDLER_METADATA_ATTR, namespaces)
    return handler


def _make_app(
    namespaces: dict[str, Any],
    *,
    name: str = "create_user",
    route: str = "users",
    methods: list[str] | None = None,
) -> MockApp:
    handler = _make_handler(namespaces)
    binding = MockBinding(route=route, methods=methods or ["POST"])
    fn = MockFunction(name=name, func=handler, bindings=[binding])
    return MockApp([MockBuilder(fn)])


# ---------------------------------------------------------------------------
# _read_endpoint_hints
# ---------------------------------------------------------------------------


def test_read_endpoint_hints_accepts_version_1() -> None:
    handler = _make_handler({"endpoint": FLAT_ENDPOINT})
    result = _read_endpoint_hints(handler)
    assert result is not None
    assert result["request_body"]["properties"]["name"]["type"] == "string"


def test_read_endpoint_hints_missing_version_rejected() -> None:
    # ``version`` is a required key for the endpoint contract (unlike validation).
    handler = _make_handler({"endpoint": {"request_body": {"type": "object"}}})
    assert _read_endpoint_hints(handler) is None


def test_read_endpoint_hints_unsupported_version_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler = _make_handler({"endpoint": {"version": 999}})
    with caplog.at_level("WARNING", logger="azure_functions_openapi.bridge"):
        assert _read_endpoint_hints(handler) is None
    assert any("unsupported version" in m for m in caplog.messages)


def test_read_endpoint_hints_boolean_version_rejected() -> None:
    handler = _make_handler({"endpoint": {"version": True}})
    assert _read_endpoint_hints(handler) is None


def test_read_endpoint_hints_walks_wrapped_chain() -> None:
    inner: Any = lambda req: req  # noqa: E731
    setattr(inner, _HANDLER_METADATA_ATTR, {"endpoint": FLAT_ENDPOINT})
    outer: Any = lambda req: inner(req)  # noqa: E731
    outer.__wrapped__ = inner

    result = _read_endpoint_hints(outer)
    assert result is not None
    assert result["version"] == 1


def test_read_endpoint_hints_invalid_outer_valid_inner() -> None:
    inner: Any = lambda req: req  # noqa: E731
    setattr(inner, _HANDLER_METADATA_ATTR, {"endpoint": FLAT_ENDPOINT})
    outer: Any = lambda req: inner(req)  # noqa: E731
    setattr(outer, _HANDLER_METADATA_ATTR, {"endpoint": {"version": 999}})
    outer.__wrapped__ = inner

    result = _read_endpoint_hints(outer)
    assert result is not None
    assert result["version"] == 1


def test_read_endpoint_hints_self_referencing_stops() -> None:
    handler: Any = lambda req: req  # noqa: E731
    setattr(handler, _HANDLER_METADATA_ATTR, {"endpoint": {"version": 999}})
    handler.__wrapped__ = handler
    assert _read_endpoint_hints(handler) is None


def test_read_endpoint_hints_returns_deep_copy() -> None:
    handler = _make_handler({"endpoint": FLAT_ENDPOINT})
    result = _read_endpoint_hints(handler)
    assert result is not None
    result["request_body"]["properties"]["name"]["type"] = "mutated"

    stored = getattr(handler, _HANDLER_METADATA_ATTR)["endpoint"]
    assert stored["request_body"]["properties"]["name"]["type"] == "string"


def test_read_endpoint_hints_absent_namespace() -> None:
    handler = _make_handler({"validation": {"body": None}})
    assert _read_endpoint_hints(handler) is None


# ---------------------------------------------------------------------------
# _discovered_operation_from_endpoint
# ---------------------------------------------------------------------------


def test_discovered_operation_from_endpoint_shape() -> None:
    discovered = _discovered_operation_from_endpoint(
        "create_user", FLAT_ENDPOINT, "/api/users", "post"
    )
    assert discovered["request_body"]["type"] == "object"
    assert discovered["request_body_required"] is True
    assert discovered["parameters"][0]["name"] == "limit"
    assert discovered["response"][200]["content"]["application/json"]["schema"] == {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
    }
    assert discovered["response"][200]["description"] == ""


def test_discovered_operation_from_endpoint_defaults_and_filters() -> None:
    payload: dict[str, Any] = {
        "version": 1,
        "request_body": "not-a-dict",
        "parameters": ["bad", {"name": "ok", "in": "query"}],
        "responses": {
            "not-an-int": {"schema": {"type": "string"}},
            "201": "not-a-dict",
            "204": {"schema": {"type": "null"}},
        },
    }
    discovered = _discovered_operation_from_endpoint("fn", payload, "/api/x", "post")
    assert discovered["request_body"] is None
    assert discovered["request_body_required"] is True  # defaulted
    assert discovered["parameters"] == [{"name": "ok", "in": "query"}]
    assert set(discovered["response"].keys()) == {204}


def test_discovered_operation_from_endpoint_non_dict_responses() -> None:
    payload: dict[str, Any] = {"version": 1, "responses": "nope"}
    discovered = _discovered_operation_from_endpoint("fn", payload, "/api/x", "get")
    assert discovered["response"] == {}


# ---------------------------------------------------------------------------
# scan_validation_metadata — endpoint namespace happy path
# ---------------------------------------------------------------------------


def test_scan_registers_from_endpoint_namespace() -> None:
    app = _make_app({"endpoint": FLAT_ENDPOINT})
    scan_validation_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["request_body"]["properties"]["name"]["type"] == "string"
    assert entry["request_body_required"] is True
    assert entry["response"][200]["content"]["application/json"]["schema"]["properties"] == {
        "id": {"type": "integer"}
    }
    assert entry["parameters"][0]["name"] == "limit"


def test_scan_endpoint_request_body_not_required() -> None:
    payload = dict(FLAT_ENDPOINT)
    payload["request_body_required"] = False
    app = _make_app({"endpoint": payload})
    scan_validation_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["request_body_required"] is False


# ---------------------------------------------------------------------------
# Version-skew: endpoint preferred, validation fallback
# ---------------------------------------------------------------------------


class _Body(BaseModel):
    name: str


class _Resp(BaseModel):
    id: int


def test_scan_prefers_endpoint_over_validation_when_both_present() -> None:
    app = _make_app(
        {
            "endpoint": FLAT_ENDPOINT,
            "validation": {"body": _Body, "response_model": _Resp},
        }
    )
    scan_validation_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    # Endpoint path does NOT set response_model (it uses the raw ``response`` slot).
    assert entry["response_model"] is None
    assert entry["response"][200]["content"]["application/json"]["schema"]["properties"] == {
        "id": {"type": "integer"}
    }


def test_scan_falls_back_to_validation_when_only_validation_present() -> None:
    app = _make_app({"validation": {"body": _Body, "response_model": _Resp}})
    scan_validation_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["response_model"] is _Resp


def test_scan_falls_back_to_validation_when_endpoint_version_unsupported() -> None:
    app = _make_app(
        {
            "endpoint": {"version": 999, "request_body": {"type": "object"}},
            "validation": {"body": _Body, "response_model": _Resp},
        }
    )
    scan_validation_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["response_model"] is _Resp


# ---------------------------------------------------------------------------
# Merge into existing @openapi entry
# ---------------------------------------------------------------------------


def test_scan_endpoint_merges_into_existing_openapi_entry() -> None:
    register_openapi_metadata(path="/api/users", method="post", summary="explicit")
    app = _make_app({"endpoint": FLAT_ENDPOINT})
    scan_validation_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["summary"] == "explicit"  # explicit metadata preserved
    assert entry["request_body"]["properties"]["name"]["type"] == "string"
    assert entry["request_body_required"] is True
    assert 200 in entry["response"]


def test_scan_endpoint_conflicting_response_raises() -> None:
    register_openapi_metadata(
        path="/api/users",
        method="post",
        response={200: {"content": {"application/json": {"schema": {"type": "string"}}}}},
    )
    app = _make_app({"endpoint": FLAT_ENDPOINT})
    with pytest.raises(OpenAPISpecConfigError):
        scan_validation_metadata(app)


# ---------------------------------------------------------------------------
# _models_conflict — response dict
# ---------------------------------------------------------------------------


def test_models_conflict_response_dict_same_status_differs() -> None:
    assert (
        _models_conflict(
            {"response": {200: {"a": 1}}},
            {"response": {200: {"a": 2}}},
        )
        is True
    )


def test_models_conflict_response_dict_disjoint_status_ok() -> None:
    assert (
        _models_conflict(
            {"response": {200: {"a": 1}}},
            {"response": {404: {"a": 1}}},
        )
        is False
    )


# ---------------------------------------------------------------------------
# Nested-model known limitation (verbatim embed of $defs refs)
# ---------------------------------------------------------------------------


def test_scan_endpoint_embeds_nested_defs_verbatim() -> None:
    """Path A (MVP): nested-model ``$defs``/``#/$defs/`` refs are embedded
    verbatim rather than hoisted into ``components.schemas``. This documents the
    known limitation tracked by the follow-up hoisting issue.
    """
    nested_payload: dict[str, Any] = {
        "version": 1,
        "request_body": {
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/Child"}},
            "$defs": {"Child": {"type": "object", "properties": {"x": {"type": "integer"}}}},
        },
        "request_body_required": True,
    }
    app = _make_app({"endpoint": nested_payload})
    scan_validation_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    # The producer's $defs are preserved inline, unresolved (not hoisted).
    assert entry["request_body"]["$defs"]["Child"]["properties"]["x"]["type"] == "integer"
    assert entry["request_body"]["properties"]["child"]["$ref"] == "#/$defs/Child"
