"""Return-type inference (P1-A).

Covers the Phase 1 feature that infers the 200 response schema from a handler's
return annotation, at both decorator-time (``@openapi``) and scan-time (bare
``@app.route`` with no ``@openapi``). Inference is strictly the lowest-precedence
response source: explicit ``responses=`` and validation/enrichment metadata both
supersede it, and it must never raise on unresolved annotations.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel
import pytest

from azure_functions_openapi.bridge import (
    _HANDLER_METADATA_ATTR,
    _merge_into_existing,
    _models_conflict,
    scan_endpoint_metadata,
)
from azure_functions_openapi.decorator import (
    _infer_response_from_return,
    clear_openapi_registry,
    get_openapi_registry,
    openapi,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class User(BaseModel):
    id: int
    name: str


class Other(BaseModel):
    ok: bool


# ---------------------------------------------------------------------------
# _infer_response_from_return (unit)
# ---------------------------------------------------------------------------


def test_infer_basemodel_return() -> None:
    def handler(req: Any) -> User:  # pragma: no cover - body never executed
        raise NotImplementedError

    model, response = _infer_response_from_return(handler)
    assert model is User
    assert response is None


def test_infer_container_generic_return() -> None:
    def handler(req: Any) -> list[User]:  # pragma: no cover - body never executed
        raise NotImplementedError

    model, response = _infer_response_from_return(handler)
    assert model is None
    assert response is not None
    assert response[200]["content"]["application/json"]["schema"] == list[User]


def test_infer_optional_return_is_union_shorthand() -> None:
    def handler(req: Any) -> Optional[User]:  # pragma: no cover
        raise NotImplementedError

    model, response = _infer_response_from_return(handler)
    assert model is None
    assert response is not None


@pytest.mark.parametrize(
    "annotation",
    [None, "str", "int", "dict", "Any"],
    ids=["none", "str", "int", "bare-dict", "any"],
)
def test_infer_non_documentable_returns_nothing(annotation: str | None) -> None:
    ns: dict[str, Any] = {"Any": Any}
    if annotation is None:
        exec("def handler(req):\n    raise NotImplementedError", ns)  # noqa: S102
        handler = ns["handler"]
    else:
        src = f"def handler(req):\n    ...\nhandler.__annotations__ = {{'return': {annotation}}}"
        exec(src, ns)  # noqa: S102 - constructs a handler with a scalar return
        handler = ns["handler"]

    model, response = _infer_response_from_return(handler)
    assert model is None
    assert response is None


def test_infer_forward_ref_never_raises() -> None:
    # Simulate ``from __future__ import annotations`` leaving an unresolved
    # stringized forward reference: get_type_hints() raises NameError, which the
    # helper must swallow and yield nothing rather than break spec generation.
    def handler(req: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    handler.__annotations__ = {"return": "ThisTypeDoesNotExistAnywhere"}

    model, response = _infer_response_from_return(handler)
    assert model is None
    assert response is None


# ---------------------------------------------------------------------------
# Decorator-time inference
# ---------------------------------------------------------------------------


def test_decorator_infers_response_model_from_return() -> None:
    @openapi(summary="Get a user")
    def get_user(req: Any) -> User:  # pragma: no cover
        raise NotImplementedError

    entry = get_openapi_registry()["get_user"]
    assert entry["response_model"] is User
    assert entry["_response_inferred"] is True


def test_decorator_infers_array_response_from_return() -> None:
    @openapi(summary="List users")
    def list_users(req: Any) -> list[User]:  # pragma: no cover
        raise NotImplementedError

    entry = get_openapi_registry()["list_users"]
    assert entry["response_model"] is None
    schema = entry["response"][200]["content"]["application/json"]["schema"]
    assert schema == list[User]
    assert entry["_response_inferred"] is True


def test_explicit_responses_win_over_inference() -> None:
    # Oracle precedence: explicit > validation > inference. An explicit
    # responses= must never be overridden by the return annotation.
    @openapi(summary="Create", responses=Other)
    def create(req: Any) -> User:  # pragma: no cover
        raise NotImplementedError

    entry = get_openapi_registry()["create"]
    assert entry["response_model"] is Other
    assert entry["_response_inferred"] is False


def test_no_annotation_infers_nothing() -> None:
    @openapi(summary="Bare")
    def bare(req: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    entry = get_openapi_registry()["bare"]
    assert entry["response_model"] is None
    assert entry["response"] == {}
    assert entry["_response_inferred"] is False


# ---------------------------------------------------------------------------
# Scan-time inference (zero-decorator @app.route)
# ---------------------------------------------------------------------------


class _MockBinding:
    def __init__(self, route: str, methods: list[str]) -> None:
        self.route = route
        self.methods = methods
        self.type = "httpTrigger"


class _MockFunction:
    def __init__(self, name: str, func: Any, bindings: list[Any]) -> None:
        self._name = name
        self._func = func
        self._bindings = bindings

    def get_function_name(self) -> str:
        return self._name

    def get_user_function(self) -> Any:
        return self._func

    def get_bindings(self) -> list[Any]:
        return self._bindings

    def is_http_function(self) -> bool:
        return True


class _MockBuilder:
    def __init__(self, function: _MockFunction) -> None:
        self._function = function

    def build(self, auth_level: Any = None) -> _MockFunction:
        return self._function


class _MockApp:
    def __init__(self, builders: list[_MockBuilder]) -> None:
        self._function_builders = builders


def _app_for(handler: Any, *, name: str, route: str, methods: list[str]) -> _MockApp:
    fn = _MockFunction(name=name, func=handler, bindings=[_MockBinding(route, methods)])
    return _MockApp([_MockBuilder(fn)])


def test_scan_infers_array_response_for_bare_route() -> None:
    def list_users(req: Any) -> list[User]:  # pragma: no cover
        raise NotImplementedError

    scan_endpoint_metadata(_app_for(list_users, name="list_users", route="users", methods=["GET"]))

    entry = get_openapi_registry()["get::/api/users"]
    assert entry["_response_inferred"] is True
    schema = entry["response"][200]["content"]["application/json"]["schema"]
    assert schema == list[User]


def test_scan_infers_response_model_for_bare_route() -> None:
    def get_user(req: Any) -> User:  # pragma: no cover
        raise NotImplementedError

    scan_endpoint_metadata(_app_for(get_user, name="get_user", route="users", methods=["GET"]))

    entry = get_openapi_registry()["get::/api/users"]
    assert entry["response_model"] is User
    assert entry["_response_inferred"] is True


def test_scan_bare_route_without_annotation_registers_nothing() -> None:
    def ping(req: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    scan_endpoint_metadata(_app_for(ping, name="ping", route="ping", methods=["GET"]))

    assert "get::/api/ping" not in get_openapi_registry()


def test_scan_endpoint_enrichment_supersedes_inference() -> None:
    # A handler carrying validation/enrichment metadata AND a return annotation:
    # the enrichment (higher precedence) is used; inference is gated off.
    def create_user(req: Any) -> User:  # pragma: no cover
        raise NotImplementedError

    setattr(
        create_user,
        _HANDLER_METADATA_ATTR,
        {
            "endpoint": {
                "version": 1,
                "responses": {
                    "200": {"schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}
                },
            }
        },
    )

    scan_endpoint_metadata(
        _app_for(create_user, name="create_user", route="users", methods=["POST"])
    )

    entry = get_openapi_registry()["post::/api/users"]
    # Enrichment response wins; the entry is not marked inferred.
    assert entry.get("_response_inferred") is not True
    assert entry["response"][200]["content"]["application/json"]["schema"] == {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
    }


# ---------------------------------------------------------------------------
# Merge precedence: validation supersedes an inferred response
# ---------------------------------------------------------------------------


def test_merge_validation_supersedes_inferred_response_model() -> None:
    existing: dict[str, Any] = {
        "response_model": User,
        "response": {},
        "_response_inferred": True,
        "parameters": [],
    }
    discovered: dict[str, Any] = {"response_model": Other, "parameters": []}

    # No conflict: inference always yields to discovered metadata.
    assert _models_conflict(existing, discovered) is False
    _merge_into_existing(existing, discovered)

    assert existing["response_model"] is Other
    assert "_response_inferred" not in existing


def test_merge_validation_supersedes_inferred_response_dict() -> None:
    existing: dict[str, Any] = {
        "response_model": None,
        "response": {200: {"description": "OK", "content": {"application/json": {"schema": User}}}},
        "_response_inferred": True,
        "parameters": [],
    }
    discovered: dict[str, Any] = {
        "response": {
            200: {
                "description": "Validated",
                "content": {"application/json": {"schema": {"type": "object"}}},
            }
        },
        "parameters": [],
    }

    assert _models_conflict(existing, discovered) is False
    _merge_into_existing(existing, discovered)

    assert existing["response"][200]["description"] == "Validated"
    assert "_response_inferred" not in existing
