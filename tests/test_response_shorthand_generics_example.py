"""Smoke tests for the response shorthand generics example (offline, service-free)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import azure.functions as func
from openapi_spec_validator import validate
import pytest

import azure_functions_openapi.decorator as decorator_module
from azure_functions_openapi.spec import generate_openapi_spec

_ROOT = Path(__file__).resolve().parent.parent


def _load_example_module() -> Any:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    module = importlib.import_module("examples.response_shorthand_generics.function_app")
    return importlib.reload(module)


@pytest.mark.parametrize("version", ["3.0.0", "3.1.0"])
def test_list_shorthand_resolves_to_an_array_of_the_model(version: str) -> None:
    _load_example_module()
    spec = generate_openapi_spec(title="Shorthand", openapi_version=version)
    validate(spec)

    schema = spec["paths"]["/api/items"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert schema == {"type": "array", "items": {"$ref": "#/components/schemas/Item"}}
    assert set(spec["components"]["schemas"]["Item"]["properties"]) == {"id", "name"}


def test_runtime_body_matches_the_documented_array_shape() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(method="GET", url="/api/items", body=b"", params={}, headers={})

    response = fa.list_items(req)

    assert json.loads(response.get_body()) == [
        {"id": 1, "name": "widget"},
        {"id": 2, "name": "gadget"},
    ]


def test_callable_shorthand_is_rejected_at_decoration_time() -> None:
    fa = _load_example_module()

    message = fa.declare_rejected_shorthand()

    assert "unsupported generic origin 'Callable'" in message
    assert "explicit OpenAPI Response Object mapping" in message


def test_rejected_declaration_leaves_only_the_explicit_mapping_registered() -> None:
    fa = _load_example_module()
    fa.declare_rejected_shorthand()

    spec = generate_openapi_spec(title="Shorthand")

    callbacks = spec["paths"]["/api/callbacks"]["get"]
    assert callbacks["summary"] == "Describe a callback registration"
    assert callbacks["responses"]["200"]["content"]["application/json"]["schema"]["required"] == [
        "url"
    ]


def test_docs_link_the_example() -> None:
    page = (_ROOT / "docs" / "examples" / "response_shorthand_generics.md").read_text("utf-8")
    assert "examples/response_shorthand_generics/function_app.py" in page
    assert "unsupported generic origin 'Callable'" in page
    assert "tests/test_response_shorthand_generics_example.py" in page
    assert "examples/response_shorthand_generics.md" in (_ROOT / "docs" / "usage.md").read_text(
        "utf-8"
    )
    assert "examples/response_shorthand_generics.md" in (_ROOT / "mkdocs.yml").read_text("utf-8")
