"""Characterization tests for the legacy ``request_model`` / ``response_model``
decorator parameters (issue #491).

The discrete ``request_model`` / ``response_model`` parameters are deprecated in
favour of the unified ``requests`` / ``responses`` surface, but they remain
supported. These tests pin the *schema-generation* behaviour of the legacy
paths — specifically that nested Pydantic models reachable through the legacy
parameters are hoisted into ``components.schemas`` and referenced via ``$ref``
(rather than being emitted inline as raw ``$defs``) — so upcoming cleanups
(itemSchema downgrade-channel unification, top-level passthrough) cannot
silently regress them.

Sequenced before #492 (``feat/itemSchema downgrade``) and #493
(``get_origin`` shorthand restriction); see the cross-repo backlog review.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
import warnings

from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    openapi,
)
from azure_functions_openapi.spec import generate_openapi_spec


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


# ---------------------------------------------------------------------------
# Models with a nested BaseModel so that Pydantic emits a ``$defs`` block that
# must be hoisted into ``components.schemas``.
# ---------------------------------------------------------------------------


class Address(BaseModel):
    street: str
    city: str


class CreateUserRequest(BaseModel):
    name: str
    address: Address


class UserResponse(BaseModel):
    id: int
    address: Address


def _find_operation(spec: dict[str, Any], method: str) -> dict[str, Any]:
    """Return the single operation object for *method* across all paths."""
    for path_item in spec["paths"].values():
        if method in path_item:
            return cast("dict[str, Any]", path_item[method])
    raise AssertionError(f"no {method!r} operation found in generated spec")


def _register_legacy_handlers() -> None:
    """Register handlers using the deprecated discrete params (warnings muted)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @openapi(
            route="users",
            method="post",
            request_model=CreateUserRequest,
            response_model=UserResponse,
        )
        def create_user(req: Any) -> Any:  # pragma: no cover - never invoked
            return req


def test_legacy_request_model_hoists_nested_defs_into_components() -> None:
    _register_legacy_handlers()

    spec = generate_openapi_spec()

    op = _find_operation(spec, "post")
    request_schema = op["requestBody"]["content"]["application/json"]["schema"]

    # The requestBody references the top-level model by $ref, not inline.
    assert request_schema == {"$ref": "#/components/schemas/CreateUserRequest"}

    schemas = spec["components"]["schemas"]
    # Both the top-level model and its nested model are hoisted as components.
    assert "CreateUserRequest" in schemas
    assert "Address" in schemas

    # The hoisted top-level model refers to the nested model via components,
    # never via a leftover ``#/$defs/`` pointer, and carries no inline $defs.
    create_user_schema = schemas["CreateUserRequest"]
    assert "$defs" not in create_user_schema
    assert create_user_schema["properties"]["address"] == {"$ref": "#/components/schemas/Address"}


def test_legacy_response_model_hoists_nested_defs_into_components() -> None:
    _register_legacy_handlers()

    spec = generate_openapi_spec()

    op = _find_operation(spec, "post")
    # Locate the 2xx response schema regardless of the concrete status key.
    responses = op["responses"]
    success_key = next(key for key in responses if key.isdigit() and 200 <= int(key) < 300)
    response_schema = responses[success_key]["content"]["application/json"]["schema"]

    assert response_schema == {"$ref": "#/components/schemas/UserResponse"}

    schemas = spec["components"]["schemas"]
    assert "UserResponse" in schemas
    assert "Address" in schemas

    user_response_schema = schemas["UserResponse"]
    assert "$defs" not in user_response_schema
    assert user_response_schema["properties"]["address"] == {"$ref": "#/components/schemas/Address"}


def test_legacy_request_and_response_share_one_hoisted_nested_component() -> None:
    """The shared nested ``Address`` model dedupes to a single component entry
    reachable from both the request and response models via the legacy paths."""
    _register_legacy_handlers()

    spec = generate_openapi_spec()
    schemas = spec["components"]["schemas"]

    # Exactly one Address component is registered even though both the request
    # and the response model embed it.
    address_keys = [name for name in schemas if name == "Address"]
    assert address_keys == ["Address"]

    assert (
        schemas["CreateUserRequest"]["properties"]["address"]
        == schemas["UserResponse"]["properties"]["address"]
        == {"$ref": "#/components/schemas/Address"}
    )


def test_legacy_model_params_still_emit_deprecation_warning() -> None:
    """The characterization above mutes deprecation warnings; this pins that the
    legacy params continue to emit a ``DeprecationWarning`` (guarding the
    deprecation contract while the hoisting behaviour is exercised)."""
    with pytest.warns(DeprecationWarning, match="unified"):

        @openapi(
            route="users",
            method="post",
            request_model=CreateUserRequest,
            response_model=UserResponse,
        )
        def create_user(req: Any) -> Any:  # pragma: no cover - never invoked
            return req
