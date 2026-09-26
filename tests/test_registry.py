"""Focused tests for the public OpenAPIRegistry behavior."""

from __future__ import annotations

from azure_functions_openapi.registry import OpenAPIRegistry


def test_snapshot_is_a_detached_deep_copy() -> None:
    registry = OpenAPIRegistry()
    registry.set("operation", {"responses": {200: {"description": "ok"}}})

    snapshot = registry.snapshot()
    snapshot["operation"]["responses"][200]["description"] = "changed"

    assert registry.get("operation") == {"responses": {200: {"description": "ok"}}}


def test_diagnostics_are_deduplicated_and_sorted() -> None:
    registry = OpenAPIRegistry()
    registry.add_discovery_warning("zeta", "missing trigger")
    registry.add_discovery_warning("alpha", "invalid binding")
    registry.add_discovery_warning("zeta", "missing trigger")
    registry.add_empty_discovery("zeta-app")
    registry.add_empty_discovery("alpha-app")
    registry.add_duplicate_operation("get", "/zeta")
    registry.add_duplicate_operation("GET", "/zeta")
    registry.add_downgrade_drop("unsupported schema")

    assert registry.discovery_warnings == [
        ("alpha", "invalid binding"),
        ("zeta", "missing trigger"),
    ]
    assert registry.empty_discoveries == ["alpha-app", "zeta-app"]
    assert registry.duplicate_operations == ["GET /zeta"]
    assert registry.downgrade_drops == ["unsupported schema"]


def test_clear_diagnostics_preserves_entries() -> None:
    registry = OpenAPIRegistry()
    registry.set("operation", {"summary": "kept"})
    registry.add_duplicate_operation("get", "/operation")
    registry.add_empty_discovery("empty-app")

    registry.clear_diagnostics()

    assert registry.get("operation") == {"summary": "kept"}
    assert registry.duplicate_operations == []
    assert registry.empty_discoveries == []


def test_find_by_function_id_prefers_method_and_falls_back_to_unsplit_entry() -> None:
    registry = OpenAPIRegistry()
    registry.set("get::/items", {"_function_id": "handler", "method": "get"})
    registry.set("post::/items", {"_function_id": "handler", "method": "post"})

    assert registry.find_by_function_id("handler", "POST") == {
        "_function_id": "handler",
        "method": "post",
    }

    registry.set("handler", {"_function_id": "other", "method": None})
    assert registry.find_by_function_id("other", "patch") == {
        "_function_id": "other",
        "method": None,
    }
    assert registry.find_by_function_id("missing") is None


def test_count_by_function_name_counts_only_matching_entries() -> None:
    registry = OpenAPIRegistry()
    registry.set("one", {"function_name": "handler"})
    registry.set("two", {"function_name": "handler"})
    registry.set("three", {"function_name": "other"})

    assert registry.count_by_function_name("handler") == 2
    assert registry.count_by_function_name("missing") == 0
