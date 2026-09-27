"""Smoke tests for the inference cookbook example."""

from __future__ import annotations

import importlib
import json
from typing import Any

import azure.functions as func
from openapi_spec_validator import validate

import azure_functions_openapi.decorator as decorator_module
from azure_functions_openapi.spec import generate_openapi_spec


def _load_example_module() -> Any:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    module = importlib.import_module("examples.inference_cookbook.function_app")
    return importlib.reload(module)


def test_inference_cookbook_runtime_response() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="GET",
        url="/api/greetings/Ada",
        body=b"",
        params={},
        route_params={"name": "Ada"},
        headers={},
    )

    response = fa.get_greeting(req)

    assert response.status_code == 200
    assert json.loads(response.get_body()) == {"message": "Hello, Ada!", "name": "Ada"}


def test_inference_cookbook_publishes_inferred_metadata() -> None:
    _load_example_module()
    spec = generate_openapi_spec(title="Inference Cookbook API")
    operation = spec["paths"]["/api/greetings/{name}"]["get"]

    validate(spec)

    assert operation["summary"] == "Greet a caller by name."
    assert "infer_docstring=True" in operation["description"]
    assert operation["parameters"] == [
        {
            "name": "name",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
    ]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"] == "#/components/schemas/GreetingResponse"
