"""Smoke tests for the HTTP error responses example (offline, service-free)."""

from __future__ import annotations

import importlib
import json
from typing import Any

import azure.functions as func
from openapi_spec_validator import validate
import pytest

import azure_functions_openapi.decorator as decorator_module
from azure_functions_openapi.spec import generate_openapi_spec

_PATH = "/api/orders/{order_id}"


def _load_example_module() -> Any:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    module = importlib.import_module("examples.http_error_responses.function_app")
    return importlib.reload(module)


def _get(fa: Any, order_id: str) -> func.HttpResponse:
    req = func.HttpRequest(
        method="GET",
        url=f"/api/orders/{order_id}",
        body=b"",
        params={},
        route_params={"order_id": order_id},
        headers={},
    )
    response: func.HttpResponse = fa.get_order(req)
    return response


@pytest.mark.parametrize("version", ["3.0.0", "3.1.0"])
def test_spec_documents_success_and_error_responses(version: str) -> None:
    _load_example_module()
    spec = generate_openapi_spec(title="Errors", openapi_version=version)
    validate(spec)

    responses = spec["paths"][_PATH]["get"]["responses"]
    assert sorted(responses) == ["200", "404", "500"]
    assert list(responses["200"]["content"]) == ["application/json"]
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Order"
    }
    for status in ("404", "500"):
        assert list(responses[status]["content"]) == ["application/problem+json"]
        assert responses[status]["content"]["application/problem+json"]["schema"] == {
            "$ref": "#/components/schemas/ProblemDetails"
        }

    schemas = spec["components"]["schemas"]
    assert set(schemas["ProblemDetails"]["required"]) == {"title", "status", "detail"}
    assert set(schemas["ProblemDetails"]["properties"]) == {"type", "title", "status", "detail"}


@pytest.mark.parametrize(
    ("order_id", "status", "media_type"),
    [
        ("ord_1", 200, "application/json"),
        ("missing", 404, "application/problem+json"),
        ("boom", 500, "application/problem+json"),
    ],
)
def test_runtime_matches_documented_status_and_media_type(
    order_id: str, status: int, media_type: str
) -> None:
    fa = _load_example_module()
    spec = generate_openapi_spec(title="Errors")
    documented = spec["paths"][_PATH]["get"]["responses"][str(status)]

    response = _get(fa, order_id)

    assert response.status_code == status
    assert response.mimetype == media_type
    assert media_type in documented["content"]
    body = json.loads(response.get_body())
    if status == 200:
        assert set(body) == {"order_id", "status"}
    else:
        schema = spec["components"]["schemas"]["ProblemDetails"]
        assert set(schema["required"]) <= set(body)
        assert set(body) <= set(schema["properties"])
        assert body["status"] == status


def test_docs_link_the_runnable_example() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    page = (root / "docs" / "examples" / "http_error_responses.md").read_text(encoding="utf-8")
    assert "examples/http_error_responses/function_app.py" in page
    assert "tests/test_http_error_responses_example.py" in page
    assert "examples/http_error_responses.md" in (root / "docs" / "usage.md").read_text("utf-8")
    assert "examples/http_error_responses.md" in (root / "mkdocs.yml").read_text("utf-8")
    assert "examples/http_error_responses" in (root / "examples" / "README.md").read_text("utf-8")
