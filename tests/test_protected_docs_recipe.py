"""Pin the protected Swagger UI troubleshooting recipe in docs/troubleshooting.md.

``_FakeHost`` is a test double for the Functions host's function-key check. It
compares a made-up dummy key; it does not prove real key enforcement on Azure.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

import azure.functions as func
import pytest

from azure_functions_openapi import register_openapi_routes
from azure_functions_openapi.docs_routes import DocsRoutes

_DUMMY_KEY = "FAKE-DOCS-KEY-0000"
_ROOT = Path(__file__).resolve().parent.parent


class _FakeHost:
    """Rejects a request unless it carries the dummy key (query ``code`` or header)."""

    def __init__(self, key: str) -> None:
        self._key = key

    def call(
        self,
        handler: Callable[[func.HttpRequest], func.HttpResponse],
        url: str,
        *,
        code: str | None = None,
        header_key: str | None = None,
    ) -> func.HttpResponse:
        params = {} if code is None else {"code": code}
        headers = {} if header_key is None else {"x-functions-key": header_key}
        request = func.HttpRequest(method="GET", url=url, params=params, headers=headers, body=b"")
        supplied = code if code is not None else header_key
        if supplied != self._key:
            return func.HttpResponse("Unauthorized", status_code=401)
        return handler(request)


def _routes(mode: Literal["header", "query", "none"]) -> tuple[_FakeHost, DocsRoutes]:
    app = func.FunctionApp()
    routes = register_openapi_routes(
        app,
        title="Private",
        version="1",
        auth_level=func.AuthLevel.FUNCTION,
        docs_key_forwarding=mode,
    )
    return _FakeHost(_DUMMY_KEY), routes


@pytest.fixture
def host_and_routes() -> tuple[_FakeHost, DocsRoutes]:
    return _routes("header")


def test_page_without_or_with_wrong_key_is_rejected(
    host_and_routes: tuple[_FakeHost, DocsRoutes],
) -> None:
    host, routes = host_and_routes
    docs = routes.docs
    assert docs is not None

    assert host.call(docs, "/api/docs").status_code == 401
    assert host.call(docs, "/api/docs", code="WRONG-KEY").status_code == 401


def test_page_with_key_is_served_without_embedding_the_key(
    host_and_routes: tuple[_FakeHost, DocsRoutes],
) -> None:
    host, routes = host_and_routes
    docs = routes.docs
    assert docs is not None

    response = host.call(docs, f"/api/docs?code={_DUMMY_KEY}", code=_DUMMY_KEY)

    assert response.status_code == 200
    body = response.get_body().decode()
    assert _DUMMY_KEY not in body
    assert _DUMMY_KEY not in repr(dict(response.headers))
    assert 'url: "/api/openapi.json"' in body
    assert "x-functions-key" in body
    assert "history.replaceState" in body


def test_spec_requires_the_key_in_a_header(host_and_routes: tuple[_FakeHost, DocsRoutes]) -> None:
    host, routes = host_and_routes
    spec = routes.json
    assert spec is not None

    assert host.call(spec, "/api/openapi.json").status_code == 401
    assert host.call(spec, "/api/openapi.json", header_key="WRONG-KEY").status_code == 401
    ok = host.call(spec, "/api/openapi.json", header_key=_DUMMY_KEY)
    assert ok.status_code == 200
    assert ok.mimetype == "application/json"


def test_legacy_query_mode_does_embed_the_key_for_contrast() -> None:
    host, routes = _routes("query")
    docs = routes.docs
    assert docs is not None

    body = host.call(docs, "/api/docs", code=_DUMMY_KEY).get_body().decode()

    assert f"code={_DUMMY_KEY}" in body


def test_none_mode_sends_no_key_to_the_spec_request() -> None:
    host, routes = _routes("none")
    docs = routes.docs
    assert docs is not None

    body = host.call(docs, "/api/docs", code=_DUMMY_KEY).get_body().decode()

    assert _DUMMY_KEY not in body
    assert "history.replaceState" not in body


def test_troubleshooting_documents_the_recipe() -> None:
    text = (_ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
    assert "Protected Swagger UI: the page loads but the spec does not" in text
    assert "tests/test_protected_docs_recipe.py" in text
    assert "UI display is not authorization" in text
    assert "security.md#protecting-documentation-routes" in text
