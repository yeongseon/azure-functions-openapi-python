"""Golden equivalence test for issue #312.

Confirms that the OpenAPI spec generated from the shared ``endpoint`` metadata
namespace is *identical* to the spec generated from the legacy ``validation``
fallback path for the same handler — the confirming experiment that makes the
umbrella convergence (validation-python#270) safe to roll out.

Two-tier assertion strategy (per the pre-implementation design gate):

* **Tier 1 — full byte identity** for handlers whose response schema is not a
  Pydantic ``response_model`` class: body-only, query/path/header params, and
  combinations. For these, both code paths embed request-body and parameter
  schemas the same way, so ``json.dumps(spec, sort_keys=True)`` must match.

* **Tier 2 — documented divergence** for ``response_model`` handlers. Under the
  Path-A / MVP endpoint reader (openapi-python#311), producer response schemas
  are embedded *verbatim inline*, whereas the ``validation`` path hoists the
  Pydantic model into ``components.schemas`` and emits a ``$ref``. The two specs
  are therefore structurally different but *semantically equivalent*: resolving
  the validation ``$ref`` yields exactly the inline endpoint schema. Full byte
  identity for this case is deferred to the ``$defs`` hoisting follow-up
  (openapi-python#315).

To keep the hand-authored ``endpoint`` payload honest without importing the
producer package (this repo is the *consumer*), the endpoint namespace is
derived from the *same* Pydantic models using this repo's own helpers
(:func:`type_to_schema`, :func:`_model_to_parameters`) — exactly the schemas a
conforming producer is specified to emit.
"""

from __future__ import annotations

from enum import Enum
import json
from typing import Any

from pydantic import BaseModel
import pytest

from azure_functions_openapi.bridge import _model_to_parameters, scan_validation_metadata
from azure_functions_openapi.decorator import clear_openapi_registry
from azure_functions_openapi.spec import generate_openapi_spec
from azure_functions_openapi.utils import type_to_schema

# ---------------------------------------------------------------------------
# Mock Azure Functions app scaffolding (mirrors tests/test_bridge_endpoint.py)
# ---------------------------------------------------------------------------


class MockBinding:
    def __init__(self, route: str, methods: list[str], type: str = "httpTrigger") -> None:
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


def _make_app(
    namespaces: dict[str, Any],
    *,
    name: str = "create_user",
    route: str = "users",
    methods: list[str],
) -> MockApp:
    def handler(req: Any) -> Any:
        return req

    setattr(handler, "_azure_functions_metadata", namespaces)
    binding = MockBinding(route=route, methods=methods)
    fn = MockFunction(name=name, func=handler, bindings=[binding])
    return MockApp([MockBuilder(fn)])


# ---------------------------------------------------------------------------
# Honest derivation of the endpoint namespace from the same models
# ---------------------------------------------------------------------------


def _endpoint_from_validation(validation: dict[str, Any]) -> dict[str, Any]:
    """Derive the shared ``endpoint`` payload a conforming producer would emit.

    Request bodies become ``model_json_schema()`` (via :func:`type_to_schema`
    with ``components=None``); parameters use :func:`_model_to_parameters`;
    a ``response_model`` becomes an inline ``responses`` map. This is precisely
    the contract the producer packages are specified to follow, so reusing the
    consumer's own helpers keeps the two hand-authored inputs faithful.
    """
    endpoint: dict[str, Any] = {"version": 1}

    body = validation.get("body")
    if body is not None:
        endpoint["request_body"] = type_to_schema(body)
        endpoint["request_body_required"] = True

    parameters: list[dict[str, Any]] = []
    for location, key in (("query", "query"), ("path", "path"), ("header", "headers")):
        model = validation.get(key)
        if model is not None:
            parameters.extend(_model_to_parameters(model, location))
    endpoint["parameters"] = parameters

    response_model = validation.get("response_model")
    if response_model is not None:
        endpoint["responses"] = {"200": {"schema": type_to_schema(response_model)}}

    return endpoint


def _spec_for(namespaces: dict[str, Any], *, route: str, methods: list[str]) -> dict[str, Any]:
    """Generate a full OpenAPI spec for a single handler carrying *namespaces*."""
    clear_openapi_registry()
    try:
        app = _make_app(namespaces, route=route, methods=methods)
        scan_validation_metadata(app)
        return generate_openapi_spec()
    finally:
        clear_openapi_registry()


def _canonical(spec: dict[str, Any]) -> str:
    """Deterministic, order-insensitive serialization for byte comparison."""
    return json.dumps(spec, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Body(BaseModel):
    name: str
    age: int


class QueryParams(BaseModel):
    limit: int
    cursor: str | None = None


class PathParams(BaseModel):
    item_id: int


class HeaderParams(BaseModel):
    x_token: str


class Color(str, Enum):
    red = "red"
    blue = "blue"


class EnumBody(BaseModel):
    """Flat body whose enum field forces an inline ``$defs`` block.

    Both code paths embed ``request_body`` verbatim (the validation path also
    uses ``type_to_schema(body, components=None)``), so even a ``$defs``-bearing
    body stays byte-identical — hoisting only applies to ``response_model``.
    """

    color: Color


class Resp(BaseModel):
    id: int


class OptionalResp(BaseModel):
    """Response model with an ``Optional`` field.

    Exercises the OpenAPI 3.1 conversion (``_convert_schema_to_3_1``) on both
    paths: the endpoint inline schema goes through
    ``_convert_operation_schemas_to_3_1`` while the hoisted validation schema
    goes through ``_convert_schemas_to_3_1``. Semantic equivalence must still
    hold after conversion.
    """

    id: int
    note: str | None = None


# ---------------------------------------------------------------------------
# Tier 1 — full byte identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case_id", "validation", "route", "methods"),
    [
        ("body_only", {"body": Body}, "users", ["POST"]),
        ("query_params", {"query": QueryParams}, "search", ["GET"]),
        (
            "path_and_header",
            {"path": PathParams, "headers": HeaderParams},
            "items/{item_id}",
            ["GET"],
        ),
        ("body_and_query", {"body": Body, "query": QueryParams}, "users", ["POST"]),
        ("enum_body_inline_defs", {"body": EnumBody}, "users", ["POST"]),
    ],
)
def test_endpoint_spec_identical_to_validation(
    case_id: str,
    validation: dict[str, Any],
    route: str,
    methods: list[str],
) -> None:
    endpoint = _endpoint_from_validation(validation)

    spec_validation = _spec_for({"validation": validation}, route=route, methods=methods)
    spec_endpoint = _spec_for({"endpoint": endpoint}, route=route, methods=methods)

    assert _canonical(spec_endpoint) == _canonical(spec_validation), (
        f"endpoint-driven spec diverged from validation-driven spec for {case_id!r}"
    )


# ---------------------------------------------------------------------------
# Tier 2 — documented divergence with semantic equivalence (response_model)
# ---------------------------------------------------------------------------


def _response_schema(spec: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    op = spec["paths"][path][method]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert isinstance(schema, dict)
    return schema


@pytest.mark.parametrize("response_model", [Resp, OptionalResp])
def test_response_model_diverges_but_is_semantically_equivalent(
    response_model: type[BaseModel],
) -> None:
    """response_model: validation hoists to ``$ref``; endpoint inlines.

    Full byte identity is intentionally NOT expected under the Path-A endpoint
    reader (openapi-python#311). Instead we assert the documented divergence and
    prove semantic equivalence by resolving the validation ``$ref``. Byte
    identity is tracked by the ``$defs`` hoisting follow-up (#315).
    """
    validation: dict[str, Any] = {"response_model": response_model}
    route, method = "get_item", "get"

    spec_validation = _spec_for({"validation": validation}, route=route, methods=["GET"])
    spec_endpoint = _spec_for(
        {"endpoint": _endpoint_from_validation(validation)}, route=route, methods=["GET"]
    )
    path = "/api/get_item"

    # --- documented structural divergence ---
    # NOTE: When the $defs-hoisting follow-up (#315) lands, the endpoint path
    # will also hoist into components.schemas and this `!=` becomes `==`; this
    # assertion will then fail loudly, signalling the Tier-2 case can be
    # promoted to Tier-1 full identity.
    assert _canonical(spec_endpoint) != _canonical(spec_validation)

    validation_schema = _response_schema(spec_validation, path, method)
    endpoint_schema = _response_schema(spec_endpoint, path, method)

    # validation path -> $ref into components.schemas
    assert "$ref" in validation_schema
    ref_name = validation_schema["$ref"].rsplit("/", 1)[-1]
    assert spec_validation["components"]["schemas"][ref_name]  # hoisted

    # endpoint path -> inline schema, no hoisted component schemas
    assert "$ref" not in endpoint_schema
    assert not (spec_endpoint.get("components") or {}).get("schemas")

    # --- semantic equivalence: resolving the $ref yields the inline schema ---
    resolved = spec_validation["components"]["schemas"][ref_name]
    assert resolved == endpoint_schema


def test_response_model_with_body_shares_identical_request_body() -> None:
    """POST with body + response_model: request_body identical, response diverges.

    The request-body subtree is embedded verbatim by both paths and must match
    byte-for-byte; only the response subtree diverges under Path A.
    """
    validation: dict[str, Any] = {"body": Body, "response_model": Resp}
    route, method = "users", "post"

    spec_validation = _spec_for({"validation": validation}, route=route, methods=["POST"])
    spec_endpoint = _spec_for(
        {"endpoint": _endpoint_from_validation(validation)}, route=route, methods=["POST"]
    )
    path = "/api/users"

    request_body_validation = spec_validation["paths"][path][method]["requestBody"]
    request_body_endpoint = spec_endpoint["paths"][path][method]["requestBody"]
    assert request_body_endpoint == request_body_validation

    # Response still diverges (validation $ref vs endpoint inline).
    assert _response_schema(spec_endpoint, path, method) != _response_schema(
        spec_validation, path, method
    )
