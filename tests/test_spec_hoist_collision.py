"""Deterministic ``$defs`` hoisting: collision aliasing, byte-identical output,
and combinator/recursive edge cases (issue #315).

``hoist_inline_defs`` lifts producer-authored inline ``$defs`` into
``components.schemas``. Same-name definitions with identical content are merged;
same-name definitions with *different* content receive a deterministic ``_2``
alias plus a ``WARNING`` (so a silent last-write-wins overwrite can never ship).
These tests pin that contract and prove the output is stable across runs.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from azure_functions_openapi.bridge import _HANDLER_METADATA_ATTR, scan_endpoint_metadata
from azure_functions_openapi.decorator import clear_openapi_registry, get_openapi_registry
from azure_functions_openapi.spec import get_openapi_json
from azure_functions_openapi.utils import hoist_inline_defs

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _iter_dicts(node: Any) -> Any:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


def _has_defs_key(node: Any) -> bool:
    return any("$defs" in d for d in _iter_dicts(node))


def _collect_refs(node: Any) -> list[str]:
    return [d["$ref"] for d in _iter_dicts(node) if isinstance(d.get("$ref"), str)]


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

    def get_function_name(self) -> str:
        return self._name

    def get_user_function(self) -> Any:
        return self._func

    def get_bindings(self) -> list[Any]:
        return self._bindings

    def is_http_function(self) -> bool:
        return any(str(getattr(b, "type", "")).lower() == "httptrigger" for b in self._bindings)


class MockBuilder:
    def __init__(self, function: MockFunction) -> None:
        self._function = function

    def build(self, auth_level: Any = None) -> MockFunction:
        return self._function


class MockApp:
    def __init__(self, builders: list[MockBuilder]) -> None:
        self._function_builders = builders


def _make_app(request_body: dict[str, Any], *, route: str = "users") -> MockApp:
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
    binding = MockBinding(route=route, methods=["POST"])
    fn = MockFunction(name="create_user", func=handler, bindings=[binding])
    return MockApp([MockBuilder(fn)])


# ---------------------------------------------------------------------------
# Collision aliasing — same name, different content → deterministic _2 + WARNING
# ---------------------------------------------------------------------------


def test_collision_different_content_gets_deterministic_alias_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    components: dict[str, Any] = {"schemas": {"Child": {"type": "object", "properties": {}}}}
    schema = {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/Child"}},
        "$defs": {
            "Child": {"type": "object", "properties": {"nickname": {"type": "string"}}},
        },
    }

    with caplog.at_level("WARNING", logger="azure_functions_openapi.utils"):
        root = hoist_inline_defs(schema, components)

    # Original "Child" is preserved; the colliding definition is aliased to Child_2.
    assert components["schemas"]["Child"] == {"type": "object", "properties": {}}
    assert "Child_2" in components["schemas"]
    assert components["schemas"]["Child_2"]["properties"]["nickname"] == {"type": "string"}
    # The referring $ref was rewritten to the alias.
    assert root["properties"]["child"]["$ref"] == "#/components/schemas/Child_2"
    # A WARNING was emitted naming both the original and the alias.
    assert any("collision" in m and "Child" in m and "Child_2" in m for m in caplog.messages)


def test_collision_identical_content_merges_without_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    child = {"type": "object", "properties": {"nickname": {"type": "string"}}}
    components: dict[str, Any] = {"schemas": {"Child": dict(child)}}
    schema = {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/Child"}},
        "$defs": {"Child": dict(child)},
    }

    with caplog.at_level("WARNING", logger="azure_functions_openapi.utils"):
        root = hoist_inline_defs(schema, components)

    # Identical content → merged onto the existing name, no alias, no warning.
    assert "Child_2" not in components["schemas"]
    assert root["properties"]["child"]["$ref"] == "#/components/schemas/Child"
    assert not any("collision" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Determinism — same input yields byte-identical output across runs
# ---------------------------------------------------------------------------


_NESTED_BODY: dict[str, Any] = {
    "type": "object",
    "properties": {
        "a": {"$ref": "#/$defs/A"},
        "b": {"$ref": "#/$defs/B"},
    },
    "required": ["a", "b"],
    "$defs": {
        "A": {"type": "object", "properties": {"x": {"$ref": "#/$defs/B"}}},
        "B": {"type": "object", "properties": {"y": {"type": "integer"}}},
    },
}


def test_hoisting_is_byte_identical_across_runs() -> None:
    def _one() -> str:
        clear_openapi_registry()
        scan_endpoint_metadata(_make_app(_NESTED_BODY))
        assert get_openapi_registry()
        return get_openapi_json(openapi_version="3.1.0")

    first = _one()
    second = _one()
    assert first == second  # byte-for-byte stable
    # And the payload actually hoisted (no residual $defs, refs resolve).
    doc = json.loads(first)
    assert not _has_defs_key(doc)
    for ref in _collect_refs(doc):
        assert ref.startswith("#/components/schemas/")


# ---------------------------------------------------------------------------
# Edge cases — recursive defs and anyOf / oneOf / allOf sharing refs
# ---------------------------------------------------------------------------


def test_recursive_defs_hoist_without_infinite_loop() -> None:
    components: dict[str, Any] = {"schemas": {}}
    schema = {
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {
                    "value": {"type": "integer"},
                    "next": {"$ref": "#/$defs/Node"},
                },
            }
        },
    }
    root = hoist_inline_defs(schema, components)
    assert "Node" in components["schemas"]
    # Self-reference rewritten into components.schemas and still points at Node.
    assert (
        components["schemas"]["Node"]["properties"]["next"]["$ref"] == "#/components/schemas/Node"
    )
    assert root["properties"]["node"]["$ref"] == "#/components/schemas/Node"
    assert not _has_defs_key(components["schemas"])


@pytest.mark.parametrize("combinator", ["anyOf", "oneOf", "allOf"])
def test_combinators_sharing_defs_are_hoisted(combinator: str) -> None:
    components: dict[str, Any] = {"schemas": {}}
    schema = {
        "type": "object",
        "properties": {
            "either": {
                combinator: [
                    {"$ref": "#/$defs/Cat"},
                    {"$ref": "#/$defs/Dog"},
                ]
            }
        },
        "$defs": {
            "Cat": {"type": "object", "properties": {"meow": {"type": "boolean"}}},
            "Dog": {"type": "object", "properties": {"bark": {"type": "boolean"}}},
        },
    }
    root = hoist_inline_defs(schema, components)
    assert {"Cat", "Dog"} <= set(components["schemas"])
    branch = root["properties"]["either"][combinator]
    assert branch[0]["$ref"] == "#/components/schemas/Cat"
    assert branch[1]["$ref"] == "#/components/schemas/Dog"
    assert not _has_defs_key(root)
