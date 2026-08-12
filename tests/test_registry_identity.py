"""Tests for registry identity/locking hardening (issues #279, #284)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import wraps
import threading
from typing import Any

from pydantic import BaseModel
import pytest

from azure_functions_openapi.bridge import scan_endpoint_metadata
from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    get_openapi_registry,
    openapi,
    register_openapi_metadata,
)
from azure_functions_openapi.registry import (
    OpenAPIRegistry,
    canonical_function_id,
    ensure_canonical_identity,
)
from azure_functions_openapi.spec import generate_openapi_spec


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


# ── Mock Azure Functions SDK objects (mirrors tests/test_bridge.py) ──────────
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

    def get_function_name(self) -> str:
        return self._name

    def get_user_function(self) -> Any:
        return self._func

    def get_bindings(self) -> list[Any]:
        return self._bindings

    def is_http_function(self) -> bool:
        return any(str(getattr(b, "type", "")).lower() == "httptrigger" for b in self._bindings)


@dataclass
class MockBuilder:
    _function: MockFunction

    def build(self, auth_level: Any = None) -> MockFunction:
        return self._function


@dataclass
class MockApp:
    _function_builders: list[MockBuilder]


def _make_app(name: str, route: str, handler: Any, method: str = "post") -> MockApp:
    binding = MockBinding(route=route, methods=[method.upper()])
    fn = MockFunction(_name=name, _func=handler, _bindings=[binding])
    return MockApp(_function_builders=[MockBuilder(_function=fn)])


def _set_validation(handler: Any, metadata: dict[str, Any]) -> None:
    setattr(handler, "_azure_functions_metadata", {"validation": metadata})


class Body(BaseModel):
    name: str


# Two @openapi handlers that share the short name ``create_user`` but live in
# different scopes → different qualname → the classic cross-module collision.
def _make_handler_a() -> Any:
    @openapi(summary="A", route="users", method="post")
    def create_user(req: Any) -> Any:
        return req

    return create_user


def _make_handler_b() -> Any:
    @openapi(summary="B", route="accounts", method="post")
    def create_user(req: Any) -> Any:
        return req

    return create_user


# ── #284: registry mutators are self-locking ────────────────────────────────
def test_registry_set_and_setdefault_without_external_lock() -> None:
    reg = OpenAPIRegistry()
    reg.set("k", {"function_name": "k"})
    assert reg.get("k") == {"function_name": "k"}
    # setdefault returns existing without overwriting
    assert reg.setdefault("k", {"function_name": "other"})["function_name"] == "k"
    assert reg.setdefault("new", {"function_name": "new"})["function_name"] == "new"


def test_registry_concurrent_registration_is_safe() -> None:
    reg = OpenAPIRegistry()

    def worker(i: int) -> None:
        for j in range(50):
            reg.set(f"{i}-{j}", {"function_name": f"{i}-{j}"})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(reg.snapshot()) == 8 * 50


# ── #279: canonical identity helper ─────────────────────────────────────────
def test_canonical_function_id_uses_module_and_qualname() -> None:
    def handler(req: Any) -> Any:
        return req

    cid = canonical_function_id(handler)
    assert cid.endswith(".test_canonical_function_id_uses_module_and_qualname.<locals>.handler")
    assert handler.__module__ in cid


def test_canonical_function_id_unwraps_functools_wraps() -> None:
    def inner(req: Any) -> Any:
        return req

    @wraps(inner)
    def outer(req: Any) -> Any:
        return inner(req)

    assert canonical_function_id(outer) == canonical_function_id(inner)


# ── #392: dynamically-created (factory/closure) handler identity ────────────
def _module_level_handler(req: Any) -> Any:  # top-level: no ``<locals>``
    return req


def _openapi_factory(tag: str) -> Any:
    """Return a fresh @openapi-decorated closure handler per call.

    Every invocation builds a new ``handler`` object whose ``__qualname__`` is
    identical (``_openapi_factory.<locals>.handler``), reproducing the #392
    collision that used to collapse distinct handlers onto one registry entry.
    """

    @openapi(summary=tag, route=f"items/{tag}", method="get")
    def handler(req: Any) -> Any:
        return req

    return handler


def test_factory_handlers_get_distinct_canonical_ids() -> None:
    a = _openapi_factory("a")
    b = _openapi_factory("b")
    # Same qualname, but decoration stamped a per-object token, so identities
    # diverge instead of colliding.
    assert a.__qualname__ == b.__qualname__
    assert canonical_function_id(a) != canonical_function_id(b)


def test_two_factory_handlers_register_as_two_entries() -> None:
    a = _openapi_factory("a")
    b = _openapi_factory("b")
    reg = get_openapi_registry()
    ids = {entry.get("_function_id") for entry in reg.values()}
    # Both handlers survive as distinct entries — no silent data loss.
    assert canonical_function_id(a) in ids
    assert canonical_function_id(b) in ids
    assert canonical_function_id(a) != canonical_function_id(b)


def test_module_level_identity_is_unchanged() -> None:
    cid = canonical_function_id(_module_level_handler)
    # Module-level functions carry no disambiguation token.
    assert "#" not in cid
    assert cid == f"{_module_level_handler.__module__}.{_module_level_handler.__qualname__}"
    # ensure_canonical_identity is a no-op for them (idempotent, unchanged id).
    assert ensure_canonical_identity(_module_level_handler) == cid
    assert canonical_function_id(_module_level_handler) == cid


# ── #279: bridge merges into the correct entry despite short-name collision ──
@pytest.mark.parametrize("register_a_first", [True, False])
def test_bridge_merges_into_correct_handler_on_name_collision(register_a_first: bool) -> None:
    if register_a_first:
        handler_a = _make_handler_a()
        handler_b = _make_handler_b()
    else:
        handler_b = _make_handler_b()
        handler_a = _make_handler_a()

    # Attach validation metadata only to handler A and scan it.
    _set_validation(handler_a, {"body": Body})
    app = _make_app(name="create_user", route="users", handler=handler_a)
    scan_endpoint_metadata(app)

    reg = get_openapi_registry()
    a_id = canonical_function_id(handler_a)
    b_id = canonical_function_id(handler_b)
    entry_a = next(e for e in reg.values() if e.get("_function_id") == a_id)
    entry_b = next(e for e in reg.values() if e.get("_function_id") == b_id)

    # Metadata merged into A (its route), never into B.
    assert entry_a.get("request_body") is not None
    assert entry_a["summary"] == "A"
    assert entry_b.get("request_body") is None
    assert entry_b["summary"] == "B"


def test_bridge_double_scan_does_not_duplicate(caplog: pytest.LogCaptureFixture) -> None:
    handler_a = _make_handler_a()
    _set_validation(handler_a, {"body": Body})
    app = _make_app(name="create_user", route="users", handler=handler_a)

    scan_endpoint_metadata(app)
    count_after_first = len(get_openapi_registry())
    scan_endpoint_metadata(app)
    count_after_second = len(get_openapi_registry())

    assert count_after_first == count_after_second


def test_bridge_refuses_ambiguous_short_name_fallback(caplog: pytest.LogCaptureFixture) -> None:
    # Two @openapi entries share the short name; scan a third, unregistered
    # handler whose canonical id matches neither and whose route matches no
    # endpoint. The short-name fallback must refuse to merge and warn.
    _make_handler_a()
    _make_handler_b()

    def create_user(req: Any) -> Any:  # not @openapi-registered
        return req

    _set_validation(create_user, {"body": Body})
    app = _make_app(name="create_user", route="unrelated", handler=create_user)

    with caplog.at_level("WARNING"):
        scan_endpoint_metadata(app)

    assert any("ambiguous" in rec.message.lower() for rec in caplog.records)
    # A standalone endpoint was registered instead of a wrong merge.
    assert "post::/api/unrelated" in get_openapi_registry()


# ── Injected registry: generate_openapi_spec(registry=...) (#324) ───────────
def test_generate_openapi_spec_uses_injected_registry_not_global() -> None:
    """An injected registry is used verbatim and the global one is not consulted."""
    # Populate a detached registry with one entry...
    register_openapi_metadata(path="/api/injected", method="get", summary="Injected")
    injected = OpenAPIRegistry()
    for key, entry in get_openapi_registry().items():
        injected.set(key, entry)

    # ...then empty the global registry so any leakage would be observable.
    clear_openapi_registry()
    assert get_openapi_registry() == {}

    spec = generate_openapi_spec(registry=injected)

    # The injected entry drives the spec even though the global registry is empty.
    assert "/api/injected" in spec["paths"]
    assert "get" in spec["paths"]["/api/injected"]


def test_generate_openapi_spec_falls_back_to_global_when_registry_absent() -> None:
    """Without an injected registry, the global registry remains the source."""
    register_openapi_metadata(path="/api/global", method="get", summary="Global")

    spec = generate_openapi_spec()

    assert "/api/global" in spec["paths"]
