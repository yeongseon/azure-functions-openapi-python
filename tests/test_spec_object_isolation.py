"""Generated specs must not share mutable state with caller input or siblings.

`generate_openapi_spec()` used to assign caller-supplied `contact`, `license`,
`servers`, `external_docs`, `tags` and `security_schemes` straight into the
result, and reuse one registry entry's `tags`/`security` across every operation
expanded from it. Editing the returned document could therefore reach back into
the caller's own objects, and editing one method could change its siblings.
"""

from __future__ import annotations

from typing import Any

import azure.functions as func
import pytest

from azure_functions_openapi.decorator import clear_openapi_registry, openapi
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _caller_options() -> dict[str, Any]:
    return {
        "contact": {"name": "Team", "extra": {"emails": ["a@example.com"]}},
        "license": {"name": "MIT", "identifier": {"spdx": "MIT"}},
        "servers": [{"url": "https://api.example.com", "variables": {"v": {"default": "1"}}}],
        "external_docs": {"url": "https://docs.example.com", "meta": {"langs": ["en"]}},
        "tags": [{"name": "alpha", "externalDocs": {"url": "https://docs.example.com/alpha"}}],
        "security_schemes": {"apiKeyAuth": {"type": "apiKey", "name": "k", "in": "header"}},
    }


def _register_multi_method() -> None:
    app = func.FunctionApp()

    @openapi(summary="s", tags=["alpha"], security=[{"apiKeyAuth": []}])
    @app.route(route="multi", auth_level=func.AuthLevel.ANONYMOUS)
    def multi(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover - never invoked
        return func.HttpResponse("ok")


def test_mutating_the_spec_does_not_reach_caller_metadata() -> None:
    opts = _caller_options()
    spec = generate_openapi_spec(title="T", **opts)

    spec["info"]["contact"]["extra"]["emails"].append("mutated")
    spec["info"]["license"]["identifier"]["spdx"] = "mutated"
    spec["servers"][0]["variables"]["v"]["default"] = "mutated"
    spec["externalDocs"]["meta"]["langs"].append("mutated")
    spec["tags"][0]["externalDocs"]["url"] = "mutated"
    spec["components"]["securitySchemes"]["apiKeyAuth"]["in"] = "mutated"

    assert opts["contact"]["extra"]["emails"] == ["a@example.com"]
    assert opts["license"]["identifier"]["spdx"] == "MIT"
    assert opts["servers"][0]["variables"]["v"]["default"] == "1"
    assert opts["external_docs"]["meta"]["langs"] == ["en"]
    assert opts["tags"][0]["externalDocs"]["url"] == "https://docs.example.com/alpha"
    assert opts["security_schemes"]["apiKeyAuth"]["in"] == "header"


def test_mutating_caller_metadata_does_not_reach_an_existing_spec() -> None:
    opts = _caller_options()
    spec = generate_openapi_spec(title="T", **opts)

    opts["contact"]["extra"]["emails"].append("mutated")
    opts["license"]["identifier"]["spdx"] = "mutated"
    opts["servers"][0]["variables"]["v"]["default"] = "mutated"
    opts["external_docs"]["meta"]["langs"].append("mutated")
    opts["tags"][0]["externalDocs"]["url"] = "mutated"
    opts["security_schemes"]["apiKeyAuth"]["in"] = "mutated"

    assert spec["info"]["contact"]["extra"]["emails"] == ["a@example.com"]
    assert spec["info"]["license"]["identifier"]["spdx"] == "MIT"
    assert spec["servers"][0]["variables"]["v"]["default"] == "1"
    assert spec["externalDocs"]["meta"]["langs"] == ["en"]
    assert spec["tags"][0]["externalDocs"]["url"] == "https://docs.example.com/alpha"
    assert spec["components"]["securitySchemes"]["apiKeyAuth"]["in"] == "header"


def test_sibling_operations_do_not_share_security_or_tags() -> None:
    _register_multi_method()
    spec = generate_openapi_spec(title="T")
    path_item = spec["paths"]["/api/multi"]

    assert {"get", "post"} <= set(path_item)

    path_item["get"]["security"][0]["apiKeyAuth"].append("mutated")
    path_item["get"]["tags"].append("mutated")

    assert path_item["post"]["security"] == [{"apiKeyAuth": []}]
    assert path_item["post"]["tags"] == ["alpha"]

    path_item["post"]["security"][0]["apiKeyAuth"].append("other")
    path_item["post"]["tags"].append("other")

    assert path_item["get"]["security"] == [{"apiKeyAuth": ["mutated"]}]
    assert path_item["get"]["tags"] == ["alpha", "mutated"]


def test_registry_metadata_survives_operation_mutation() -> None:
    _register_multi_method()
    first = generate_openapi_spec(title="T")
    first["paths"]["/api/multi"]["get"]["tags"].append("mutated")
    first["paths"]["/api/multi"]["get"]["security"][0]["apiKeyAuth"].append("mutated")

    second = generate_openapi_spec(title="T")

    assert second["paths"]["/api/multi"]["get"]["tags"] == ["alpha"]
    assert second["paths"]["/api/multi"]["get"]["security"] == [{"apiKeyAuth": []}]


def test_interleaved_registries_preserve_their_own_diagnostics() -> None:
    # Given
    from azure_functions_openapi.registry import registry as singleton

    left = OpenAPIRegistry()
    left.set("left", {"route": "left", "method": "purge"})
    right = OpenAPIRegistry()
    right.set("right", {"route": "right", "parameters": 123})
    singleton.set("global", {"route": "global", "method": "get"})
    global_spec = generate_openapi_spec()
    left_spec = generate_openapi_spec(registry=left)
    left_warnings = collect_spec_warnings(left_spec, left)
    right_spec = generate_openapi_spec(registry=right)
    right_warnings = collect_spec_warnings(right_spec, right)
    # When
    generate_openapi_spec(registry=left, openapi_version="3.2.0")
    # Then: regenerating left neither resets right nor contaminates the singleton.
    assert collect_spec_warnings(right_spec, right) == right_warnings
    assert [w.code.value for w in right_warnings] == ["operation-skipped"]
    assert [w.code.value for w in left_warnings] == ["version-downgrade-drop"]
    assert collect_spec_warnings(global_spec) == ()
    assert generate_openapi_spec() == global_spec
    assert collect_spec_warnings(generate_openapi_spec(registry=left), left) == left_warnings
    assert collect_spec_warnings(right_spec, right) == right_warnings
