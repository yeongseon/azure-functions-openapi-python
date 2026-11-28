"""Smoke tests for the versioned response metadata example (offline, service-free)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import azure.functions as func
from openapi_spec_validator import validate
import pytest

from azure_functions_openapi.bridge import scan_endpoint_metadata
import azure_functions_openapi.decorator as decorator_module
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import generate_openapi_spec

_MEDIA_TYPE = "application/vnd.example.v2+json"
_ROOT = Path(__file__).resolve().parent.parent


def _load_example_module() -> Any:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    module = importlib.import_module("examples.versioned_response_metadata.function_app")
    return importlib.reload(module)


def _post(fa: Any, body: dict[str, Any]) -> func.HttpResponse:
    req = func.HttpRequest(
        method="POST",
        url="/api/invoices",
        body=json.dumps(body).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )
    response: func.HttpResponse = fa.create_invoice(req)
    return response


@pytest.mark.parametrize("version", ["3.0.0", "3.1.0"])
def test_generated_operation_documents_versioned_media_type_and_headers(version: str) -> None:
    _load_example_module()
    spec = generate_openapi_spec(title="Versioned", openapi_version=version)
    validate(spec)

    responses = spec["paths"]["/api/invoices"]["post"]["responses"]
    created = responses["201"]
    assert list(created["content"]) == [_MEDIA_TYPE]
    assert created["content"][_MEDIA_TYPE]["schema"]["required"] == ["invoice_id", "total_cents"]
    assert created["headers"] == {
        "Location": {"description": "URL of the created invoice.", "schema": {"type": "string"}},
        "ETag": {"description": "Entity tag of the invoice.", "schema": {"type": "string"}},
    }
    assert responses["400"]["content"] == {
        "application/problem+json": {"schema": {"type": "object"}}
    }


def test_runtime_emits_the_documented_headers_only_because_the_handler_sets_them() -> None:
    fa = _load_example_module()

    response = _post(fa, {"total_cents": 1200})

    assert response.status_code == 201
    assert response.mimetype == _MEDIA_TYPE
    assert response.headers["Location"] == "/api/invoices/inv_1"
    assert response.headers["ETag"] == '"v1"'
    assert json.loads(response.get_body()) == {"invoice_id": "inv_1", "total_cents": 1200}
    assert _post(fa, {}).status_code == 400


def test_documented_headers_do_not_depend_on_runtime_header_emission() -> None:
    fa = _load_example_module()
    app = func.FunctionApp()

    def silent_handler(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("{}", status_code=201)  # emits no headers at all

    setattr(silent_handler, "_azure_functions_metadata", {"endpoint": fa.ENDPOINT_METADATA})
    app.route(route="invoices", methods=["POST"])(silent_handler)

    registry = OpenAPIRegistry()
    scan_endpoint_metadata(app, registry=registry)
    silent = generate_openapi_spec(registry=registry)["paths"]["/api/invoices"]["post"]

    assert silent["responses"]["201"]["headers"].keys() == {"Location", "ETag"}
    assert "Location" not in func.HttpResponse("{}", status_code=201).headers


def test_docs_link_the_example() -> None:
    page = (_ROOT / "docs" / "examples" / "versioned_response_metadata.md").read_text("utf-8")
    assert "examples/versioned_response_metadata/function_app.py" in page
    assert "tests/test_versioned_response_metadata_example.py" in page
    assert "examples/versioned_response_metadata.md" in (
        _ROOT / "docs" / "extending" / "producer-guide.md"
    ).read_text("utf-8")
    assert "examples/versioned_response_metadata.md" in (_ROOT / "mkdocs.yml").read_text("utf-8")
