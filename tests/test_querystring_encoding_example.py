"""Executable contract for the OpenAPI 3.2 querystring encoding example."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import azure.functions as func
from jsonschema import Draft202012Validator
import pytest

import azure_functions_openapi.decorator as decorator_module
from azure_functions_openapi.decorator import register_openapi_metadata
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.spec import generate_openapi_spec

_ROOT = Path(__file__).resolve().parent.parent
_FORM = "application/x-www-form-urlencoded"
# What a 3.2 client sends for q="a + b", limit=5, tags=["x", "y"]: spaces become "+",
# a literal plus becomes %2B, and the array is exploded into repeated keys.
_CLIENT_URL = "https://example.test/api/search?q=a+%2B+b&limit=5&tags=x&tags=y"


def _load_example_module() -> Any:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    module = importlib.import_module("examples.querystring_encoding.function_app")
    return importlib.reload(module)


def _get(fa: Any, url: str) -> func.HttpResponse:
    response: func.HttpResponse = fa.search(
        func.HttpRequest(method="GET", url=url, body=b"", params={}, headers={})
    )
    return response


def test_32_document_has_exactly_one_querystring_parameter() -> None:
    _load_example_module()

    spec = generate_openapi_spec(title="QS", openapi_version="3.2.0", strict=True)

    assert spec["openapi"] == "3.2.0"
    parameters = spec["paths"]["/api/search"]["get"]["parameters"]
    assert parameters == [
        {
            "name": "querystring",
            "in": "querystring",
            "content": {_FORM: {"schema": {"$ref": "#/components/schemas/SearchQuery"}}},
        }
    ]
    assert not [p for p in parameters if p["in"] == "query"]
    schema = spec["components"]["schemas"]["SearchQuery"]
    assert set(schema["properties"]) == {"q", "limit", "tags"}
    assert schema["required"] == ["q"]


@pytest.mark.parametrize("version", ["3.0.0", "3.1.0"])
def test_older_versions_are_rejected_not_silently_downgraded(version: str) -> None:
    _load_example_module()

    with pytest.raises(OpenAPISpecConfigError, match="require openapi_version"):
        generate_openapi_spec(title="QS", openapi_version=version)


def test_documented_client_query_matches_the_generated_schema_and_handler() -> None:
    fa = _load_example_module()
    spec = generate_openapi_spec(title="QS", openapi_version="3.2.0")
    schema = {**spec["components"]["schemas"]["SearchQuery"]}

    decoded = {"q": "a + b", "limit": 5, "tags": ["x", "y"]}
    assert list(Draft202012Validator(schema).iter_errors(decoded)) == []

    response = _get(fa, _CLIENT_URL)

    assert response.status_code == 200
    assert json.loads(response.get_body()) == decoded


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://example.test/api/search?limit=5",  # q is required
        "https://example.test/api/search?q=a&limit=abc",  # limit must be an integer
    ],
)
def test_invalid_query_strings_are_rejected_by_the_handler(bad_url: str) -> None:
    fa = _load_example_module()

    assert _get(fa, bad_url).status_code == 400


def test_raw_encoding_object_is_passed_through_unchanged() -> None:
    _load_example_module()
    encoding = {"tags": {"style": "form", "explode": False}}
    raw = {
        "name": "qs",
        "in": "querystring",
        "content": {
            _FORM: {
                "schema": {"type": "object", "properties": {"tags": {"type": "array"}}},
                "encoding": encoding,
            }
        },
    }
    register_openapi_metadata("/api/raw", "GET", parameters=[raw])

    spec = generate_openapi_spec(title="QS", openapi_version="3.2.0")

    param = spec["paths"]["/api/raw"]["get"]["parameters"][0]
    assert param["content"][_FORM]["encoding"] == encoding


def test_docs_link_the_example() -> None:
    page = (_ROOT / "docs" / "examples" / "querystring_encoding.md").read_text("utf-8")
    assert "examples/querystring_encoding/function_app.py" in page
    assert "tests/test_querystring_encoding_example.py" in page
    assert "q=a+%2B+b&limit=5&tags=x&tags=y" in page
    for doc in ("docs/configuration.md", "mkdocs.yml"):
        assert "querystring_encoding.md" in (_ROOT / doc).read_text("utf-8")
