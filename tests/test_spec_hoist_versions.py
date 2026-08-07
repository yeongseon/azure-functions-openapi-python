"""Audit hoisted ``$defs`` for OpenAPI 3.0 / 3.1 correctness (issue #320).

``hoist_inline_defs`` lifts producer-authored inline ``$defs`` out of an
``endpoint`` schema into ``components.schemas`` and rewrites local
``#/$defs/{Model}`` refs to ``#/components/schemas/{Model}``. These tests pin
the interaction between hoisting and the 3.0-vs-3.1 emit path so a regression
cannot silently leak a raw ``$defs`` block (invalid in both versions) or a
3.1-only construct into a 3.0 document.

Design note (see #215): the 3.0 path does **not** down-convert Pydantic-v2
nullable patterns to ``nullable: true`` — it emits a *compatibility warning*
via ``_check_schemas_3_0_compatible`` (and raises in ``strict`` mode). The 3.1
path preserves the 2020-12 ``anyOf`` + ``{"type": "null"}`` nullable syntax.
"""

from __future__ import annotations

from typing import Any

import pytest

from azure_functions_openapi.bridge import _HANDLER_METADATA_ATTR, scan_endpoint_metadata
from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    get_openapi_registry,
)
from azure_functions_openapi.spec import generate_openapi_spec

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


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


def _make_app(request_body: dict[str, Any]) -> MockApp:
    def handler(req: Any) -> Any:
        return req

    setattr(
        handler,
        _HANDLER_METADATA_ATTR,
        {
            "endpoint": {
                "version": 1,
                "request_body": request_body,
                "request_body_required": True,
                "responses": {"200": {"schema": {"type": "object"}}},
            }
        },
    )
    binding = MockBinding(route="users", methods=["POST"])
    fn = MockFunction(name="create_user", func=handler, bindings=[binding])
    return MockApp([MockBuilder(fn)])


def _iter_dicts(node: Any) -> Any:
    """Yield every dict nested anywhere within *node* (inclusive)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


def _collect_refs(node: Any) -> list[str]:
    return [d["$ref"] for d in _iter_dicts(node) if isinstance(d.get("$ref"), str)]


def _has_defs_key(node: Any) -> bool:
    return any("$defs" in d for d in _iter_dicts(node))


# A request body whose inline ``$defs.Child`` carries a Pydantic-v2 nullable
# field (``anyOf`` containing ``{"type": "null"}``) — a 3.1-only construct.
NULLABLE_DEFS_BODY: dict[str, Any] = {
    "type": "object",
    "properties": {"child": {"$ref": "#/$defs/Child"}},
    "required": ["child"],
    "$defs": {
        "Child": {
            "type": "object",
            "properties": {
                "nickname": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
        }
    },
}

# A request body whose inline ``$defs.Child`` is 3.0-clean (no nullable/list types).
PLAIN_DEFS_BODY: dict[str, Any] = {
    "type": "object",
    "properties": {"child": {"$ref": "#/$defs/Child"}},
    "required": ["child"],
    "$defs": {
        "Child": {
            "type": "object",
            "properties": {"nickname": {"type": "string"}},
        }
    },
}


def _request_schema(spec: dict[str, Any]) -> dict[str, Any]:
    op = spec["paths"]["/api/users"]["post"]
    schema: dict[str, Any] = op["requestBody"]["content"]["application/json"]["schema"]
    return schema


# ---------------------------------------------------------------------------
# 3.0 — plain (clean) hoisted defs
# ---------------------------------------------------------------------------


def test_hoisted_defs_30_no_defs_leak_and_refs_resolve(
    caplog: pytest.LogCaptureFixture,
) -> None:
    scan_endpoint_metadata(_make_app(PLAIN_DEFS_BODY))
    assert get_openapi_registry()

    with caplog.at_level("WARNING", logger="azure_functions_openapi.spec"):
        spec = generate_openapi_spec(openapi_version="3.0.0")

    # No raw $defs key survives anywhere in the document.
    assert not _has_defs_key(spec)

    # Child was hoisted into components.schemas and the ref rewritten.
    assert "Child" in spec["components"]["schemas"]
    body_schema = _request_schema(spec)
    assert body_schema["properties"]["child"]["$ref"] == "#/components/schemas/Child"

    # Every ref points at components.schemas and resolves.
    for ref in _collect_refs(spec):
        assert ref.startswith("#/components/schemas/")
        assert ref.rsplit("/", 1)[-1] in spec["components"]["schemas"]

    # A 3.0-clean schema must not emit a compatibility warning.
    assert not any("3.0 compatibility" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# 3.0 — nullable hoisted defs → compatibility warning, still no leak
# ---------------------------------------------------------------------------


def test_hoisted_nullable_defs_30_warns_without_leak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    scan_endpoint_metadata(_make_app(NULLABLE_DEFS_BODY))

    with caplog.at_level("WARNING", logger="azure_functions_openapi.spec"):
        spec = generate_openapi_spec(openapi_version="3.0.0")

    # Hoisting must not leave a raw $defs block even for nullable defs.
    assert not _has_defs_key(spec)
    assert "Child" in spec["components"]["schemas"]

    # The nullable construct is surfaced as a 3.0 compatibility warning
    # (design #215: warn, do not silently down-convert).
    assert any("3.0 compatibility" in m and "Child" in m for m in caplog.messages), caplog.messages


def test_hoisted_nullable_defs_30_strict_raises() -> None:
    from azure_functions_openapi.exceptions import OpenAPISpecConfigError

    scan_endpoint_metadata(_make_app(NULLABLE_DEFS_BODY))

    with pytest.raises(OpenAPISpecConfigError, match="3.1-only constructs"):
        generate_openapi_spec(openapi_version="3.0.0", strict=True)


# ---------------------------------------------------------------------------
# 3.1 — nullable hoisted defs preserved, refs resolve, no leak
# ---------------------------------------------------------------------------


def test_hoisted_nullable_defs_31_preserved_and_refs_resolve() -> None:
    scan_endpoint_metadata(_make_app(NULLABLE_DEFS_BODY))
    spec = generate_openapi_spec(openapi_version="3.1.0")

    # No raw $defs anywhere.
    assert not _has_defs_key(spec)

    child = spec["components"]["schemas"]["Child"]
    nickname = child["properties"]["nickname"]
    # 3.1 preserves the 2020-12 nullable syntax (anyOf with a null type).
    assert "anyOf" in nickname
    assert {"type": "null"} in nickname["anyOf"]

    # Ref rewriting survived the 3.1 conversion.
    for ref in _collect_refs(spec):
        assert ref.startswith("#/components/schemas/")
        assert ref.rsplit("/", 1)[-1] in spec["components"]["schemas"]
