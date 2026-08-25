"""Tests for top-level / info metadata passthrough on ``generate_openapi_spec`` (#494).

Covers the ``servers``, ``contact``, ``license``, ``external_docs`` and top-level
``tags`` passthrough parameters. Each field must be emitted only when supplied and
must land in the correct location (``info`` vs document root).
"""

from __future__ import annotations

from typing import Any

import azure.functions as func
import pytest

from azure_functions_openapi.bridge import scan_endpoint_metadata
from azure_functions_openapi.decorator import clear_openapi_registry, openapi
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import generate_openapi_spec


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _reg() -> OpenAPIRegistry:
    app = func.FunctionApp()

    @openapi(summary="orders")
    @app.route(route="orders", methods=["GET"])
    def orders(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover - body unused
        return func.HttpResponse("ok")

    reg = OpenAPIRegistry()
    scan_endpoint_metadata(app, registry=reg)
    return reg


def test_defaults_omit_all_passthrough_fields() -> None:
    spec = generate_openapi_spec(registry=_reg())

    assert "servers" not in spec
    assert "externalDocs" not in spec
    assert "tags" not in spec
    assert "contact" not in spec["info"]
    assert "license" not in spec["info"]


def test_servers_emitted_at_document_root() -> None:
    servers = [{"url": "https://api.example.com", "description": "prod"}]
    spec = generate_openapi_spec(registry=_reg(), servers=servers)

    assert spec["servers"] == servers


def test_contact_and_license_nest_under_info() -> None:
    contact = {"name": "DX", "email": "dx@example.com"}
    license_obj = {"name": "MIT", "url": "https://opensource.org/licenses/MIT"}
    spec = generate_openapi_spec(registry=_reg(), contact=contact, license=license_obj)

    assert spec["info"]["contact"] == contact
    assert spec["info"]["license"] == license_obj


def test_external_docs_emitted_at_document_root() -> None:
    external_docs = {"url": "https://docs.example.com", "description": "guide"}
    spec = generate_openapi_spec(registry=_reg(), external_docs=external_docs)

    assert spec["externalDocs"] == external_docs


def test_top_level_tags_emitted_at_document_root() -> None:
    tags = [{"name": "orders", "description": "Order operations"}]
    spec = generate_openapi_spec(registry=_reg(), tags=tags)

    assert spec["tags"] == tags


def test_all_fields_together() -> None:
    servers = [{"url": "https://api.example.com"}]
    contact = {"name": "DX"}
    license_obj = {"name": "MIT"}
    external_docs = {"url": "https://docs.example.com"}
    tags = [{"name": "orders"}]

    spec = generate_openapi_spec(
        registry=_reg(),
        servers=servers,
        contact=contact,
        license=license_obj,
        external_docs=external_docs,
        tags=tags,
    )

    assert spec["servers"] == servers
    assert spec["info"]["contact"] == contact
    assert spec["info"]["license"] == license_obj
    assert spec["externalDocs"] == external_docs
    assert spec["tags"] == tags
