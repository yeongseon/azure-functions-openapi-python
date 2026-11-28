"""Executable contract for the decorator order example (offline, service-free)."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
import warnings

from azure_functions_openapi import generate_openapi_spec
from azure_functions_openapi.bridge import scan_endpoint_metadata
import azure_functions_openapi.decorator as decorator_module

_ROOT = Path(__file__).resolve().parent.parent


def _load_example_module() -> Any:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    module = importlib.import_module("examples.decorator_order.function_app")
    return importlib.reload(module)


def test_both_orders_generate_the_same_operation() -> None:
    fa = _load_example_module()

    outer = generate_openapi_spec(app=fa.outer_app)
    inner = generate_openapi_spec(app=fa.inner_app)

    operation = outer["paths"]["/api/things/{id}"]["get"]
    assert list(outer["paths"]) == list(inner["paths"]) == ["/api/things/{id}"]
    assert list(outer["paths"]["/api/things/{id}"]) == ["get"]
    assert operation["operationId"] == "getThing"
    assert operation["parameters"] == [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    ]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Thing"
    }
    assert operation["responses"]["404"] == {"description": "Thing not found"}
    assert inner == outer


def test_inner_order_without_an_app_falls_back_to_the_function_name() -> None:
    _load_example_module()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        spec = generate_openapi_spec()

    assert "/api/things/{id}" in spec["paths"]  # outer order read the binding at decoration
    assert "/api/get_thing_inner" in spec["paths"]  # inner order had no binding evidence
    assert any(
        "get_thing_inner" in str(w.message) and "could not be verified" in str(w.message)
        for w in caught
    )


def test_scanning_the_app_repairs_the_inner_order_in_the_global_registry() -> None:
    fa = _load_example_module()

    scan_endpoint_metadata(fa.inner_app)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        spec = generate_openapi_spec(app=fa.inner_app)

    assert list(spec["paths"]) == ["/api/things/{id}"]


def test_docs_link_the_example() -> None:
    page = (_ROOT / "docs" / "examples" / "decorator_order.md").read_text("utf-8")
    assert "examples/decorator_order/function_app.py" in page
    assert "tests/test_decorator_order_example.py" in page
    for doc in ("docs/architecture.md", "mkdocs.yml"):
        assert "decorator_order.md" in (_ROOT / doc).read_text("utf-8")
