# tests/test_spec.py
"""Dedicated tests for ``azure_functions_openapi.spec`` (issue #587).

Covers the public spec-generation behavior of ``spec.py`` against an isolated
:class:`OpenAPIRegistry`: the exact info-document structure, version handling,
registered-endpoint emission, security-scheme merge/collision, the JSON/YAML
serializers, and the ``SpecReport``/warning pipeline. All tests assert concrete
observable results (exact values, exact structures, exact exception messages).
"""

import json

import pytest
import yaml

from azure_functions_openapi.decorator import register_openapi_metadata
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    SpecReport,
    collect_spec_warnings,
    generate_openapi_report,
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
)


def _items_registry() -> OpenAPIRegistry:
    """Isolated registry with a single fully-described GET endpoint."""
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        "/api/items",
        "GET",
        operation_id="listItems",
        summary="List items",
        description="Returns the item collection.",
        tags=["items"],
        response={200: {"description": "OK"}},
        registry=reg,
    )
    return reg


def test_generate_openapi_spec_rejects_unsupported_version() -> None:
    """An unknown ``openapi_version`` raises with the exact supported list."""
    with pytest.raises(OpenAPISpecConfigError) as excinfo:
        generate_openapi_spec(openapi_version="2.0", registry=OpenAPIRegistry())
    assert str(excinfo.value) == "Unsupported OpenAPI version: 2.0. Supported: 3.0.0, 3.1.0, 3.2.0"
   

def test_generate_openapi_spec_info_and_top_level_metadata() -> None:
    """Title/version/description plus #494 top-level metadata are emitted exactly."""
    spec = generate_openapi_spec(
        title="Items API",
        version="2.1.0",
        description="Item service.",
        servers=[{"url": "https://example.com"}],
        contact={"name": "Team", "email": "team@example.com"},
        license={"name": "MIT"},
        external_docs={"url": "https://docs.example.com"},
        tags=[{"name": "items"}],
        registry=OpenAPIRegistry(),
    )
    assert spec["openapi"] == "3.1.0"
    assert spec["info"] == {
        "title": "Items API",
        "version": "2.1.0",
        "description": "Item service.",
        "summary": "Items API",
        "contact": {"name": "Team", "email": "team@example.com"},
        "license": {"name": "MIT"},
    }
    assert spec["servers"] == [{"url": "https://example.com"}]
    assert spec["externalDocs"] == {"url": "https://docs.example.com"}
    assert spec["tags"] == [{"name": "items"}]


def test_generate_openapi_spec_uses_requested_openapi_version() -> None:
    """The 3.0.0 target stamps ``openapi: 3.0.0`` and omits the 3.1-only summary."""
    spec = generate_openapi_spec(openapi_version="3.0.0", registry=OpenAPIRegistry())
    assert spec["openapi"] == "3.0.0"
    assert "summary" not in spec["info"]
    assert spec["paths"] == {}


def test_registered_endpoint_emits_exact_operation() -> None:
    """A registered endpoint produces the exact operation object under its path."""
    spec = generate_openapi_spec(registry=_items_registry())
    assert list(spec["paths"]) == ["/api/items"]
    assert spec["paths"]["/api/items"]["get"] == {
        "summary": "List items",
        "description": "Returns the item collection.",
        "operationId": "listItems",
        "tags": ["items"],
        "responses": {"200": {"description": "OK"}},
    }


def test_registered_endpoint_auto_operation_id() -> None:
    """Without an explicit id, the operationId is derived from method + path."""
    reg = OpenAPIRegistry()
    register_openapi_metadata("/api/widgets", "POST", registry=reg)
    spec = generate_openapi_spec(registry=reg)
    assert spec["paths"]["/api/widgets"]["post"]["operationId"] == "post_api_widgets"


def test_security_scheme_collision_raises_with_exact_message() -> None:
    """Same scheme name with a different definition is a config error."""
    reg = OpenAPIRegistry()
    register_openapi_metadata(
        "/api/secure",
        "GET",
        security_scheme={"BearerAuth": {"type": "http", "scheme": "bearer"}},
        registry=reg,
    )
    with pytest.raises(OpenAPISpecConfigError) as excinfo:
        generate_openapi_spec(
            security_schemes={"BearerAuth": {"type": "http", "scheme": "basic"}},
            registry=reg,
        )
    assert str(excinfo.value) == (
        "Conflicting security scheme definition for 'BearerAuth': "
        "existing={'type': 'http', 'scheme': 'basic'}, "
        "new={'type': 'http', 'scheme': 'bearer'}"
    )


def test_security_schemes_merged_into_components() -> None:
    """Explicit ``security_schemes`` land under ``components.securitySchemes``."""
    spec = generate_openapi_spec(
        security_schemes={"BearerAuth": {"type": "http", "scheme": "bearer"}},
        registry=OpenAPIRegistry(),
    )
    assert spec["components"]["securitySchemes"] == {
        "BearerAuth": {"type": "http", "scheme": "bearer"}
    }


def test_get_openapi_json_matches_generate_openapi_spec() -> None:
    """The JSON serializer emits exactly the dict the generator returns."""
    reg = _items_registry()
    expected = generate_openapi_spec(title="T", registry=reg)
    assert json.loads(get_openapi_json(title="T", registry=reg)) == expected


def test_get_openapi_yaml_parses_to_expected_document() -> None:
    """The YAML serializer parses back to the same document structure."""
    doc = yaml.safe_load(get_openapi_yaml(title="T", registry=_items_registry()))
    assert doc["openapi"] == "3.1.0"
    assert doc["info"]["title"] == "T"
    assert doc["paths"]["/api/items"]["get"]["operationId"] == "listItems"


def test_generate_openapi_report_returns_spec_and_empty_warnings() -> None:
    """A clean registry yields a SpecReport whose warnings tuple is empty."""
    report = generate_openapi_report(title="T", registry=_items_registry())
    assert isinstance(report, SpecReport)
    assert report.spec["info"]["title"] == "T"
    assert report.spec["paths"]["/api/items"]["get"]["operationId"] == "listItems"
    assert report.warnings == ()


def test_collect_spec_warnings_empty_for_clean_spec() -> None:
    """A valid spec from a clean registry produces no structured warnings."""
    reg = _items_registry()
    spec = generate_openapi_spec(registry=reg)
    assert collect_spec_warnings(spec, registry=reg) == ()
