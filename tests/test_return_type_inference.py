"""Return-type inference (P1-A).

Covers the Phase 1 feature that infers the 200 response schema from a handler's
return annotation, at both decorator-time (``@openapi``) and scan-time (bare
``@app.route`` with no ``@openapi``). Inference is strictly the lowest-precedence
response source: explicit ``responses=`` and validation/enrichment metadata both
supersede it, and it must never raise on unresolved annotations.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from _scan_helpers import _app_for
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
from azure_functions_openapi.spec import generate_openapi_spec


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


def test_infer_optional_return_flattens_to_model() -> None:
    # ``Optional[User]`` is treated as "may or may not produce a value", so the
    # inferred 200 body is the model itself — not a nullable ``anyOf`` (#558).
    def handler(req: Any) -> Optional[User]:  # pragma: no cover
        raise NotImplementedError

    model, response = _infer_response_from_return(handler)
    assert model is User
    assert response is None


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


# ---------------------------------------------------------------------------
# Optional[T]-return 200 semantics (#558) — root flatten, nested preserved
# ---------------------------------------------------------------------------


def test_infer_union_return_drops_only_the_none_branch() -> None:
    # A multi-member union keeps its non-``None`` members but drops ``None`` at
    # the response root (#558).
    def handler(req: Any) -> Union[User, Other, None]:  # pragma: no cover
        raise NotImplementedError

    model, response = _infer_response_from_return(handler)
    assert model is None
    assert response is not None
    schema = response[200]["content"]["application/json"]["schema"]
    assert schema == Union[User, Other]


def test_infer_list_of_optional_preserves_nested_shape() -> None:
    # Only the *root* union is unwrapped; nested nullability describes the real
    # JSON shape of array elements and is preserved (#558).
    def handler(req: Any) -> list[Optional[User]]:  # pragma: no cover
        raise NotImplementedError

    model, response = _infer_response_from_return(handler)
    assert model is None
    assert response is not None
    assert response[200]["content"]["application/json"]["schema"] == list[Optional[User]]


def _spec_response_schema(route: str, openapi_version: str) -> Any:
    spec = generate_openapi_spec(openapi_version=openapi_version)
    responses = spec["paths"][route]["get"]["responses"]
    return responses["200"]["content"]["application/json"]["schema"]


@pytest.mark.parametrize("openapi_version", ["3.0.0", "3.1.0"])
def test_optional_return_emits_plain_model_ref_in_spec(openapi_version: str) -> None:
    # ``Optional[User]`` renders as the bare model ``$ref`` — identical across
    # OpenAPI 3.0 and 3.1, with no top-level ``{"type": "null"}`` (#558).
    @openapi(summary="opt", route="/opt", method="get")
    def handler(req: Any) -> Optional[User]:  # pragma: no cover
        raise NotImplementedError

    schema = _spec_response_schema("/api/opt", openapi_version)
    assert schema == {"$ref": "#/components/schemas/User"}


def test_list_of_optional_return_keeps_nullable_items_in_3_1() -> None:
    # In OpenAPI 3.1, nullable array items are the faithful, valid shape (#558).
    @openapi(summary="listopt", route="/listopt", method="get")
    def handler(req: Any) -> list[Optional[User]]:  # pragma: no cover
        raise NotImplementedError

    schema = _spec_response_schema("/api/listopt", "3.1.0")
    assert schema["type"] == "array"
    assert schema["items"]["anyOf"] == [
        {"$ref": "#/components/schemas/User"},
        {"type": "null"},
    ]
