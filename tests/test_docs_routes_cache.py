"""Conditional GET and per-registration caching for the documentation routes (#943)."""

from __future__ import annotations

from collections.abc import Iterator
import json
import threading
from typing import Any

import azure.functions as func
import pytest

import azure_functions_openapi as package
from azure_functions_openapi import (
    clear_openapi_registry,
    register_openapi_routes,
)
from azure_functions_openapi.docs_routes import DocsRoutes


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


@pytest.fixture
def render_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    for name in ("get_openapi_json", "get_openapi_yaml"):
        original = getattr(package, name)

        def counted(*args: Any, _name: str = name, _orig: Any = original, **kwargs: Any) -> str:
            calls.append(_name)
            return _orig(*args, **kwargs)  # type: ignore[no-any-return]

        monkeypatch.setattr(package, name, counted)
    return calls


def _routes(**kwargs: Any) -> DocsRoutes:
    return register_openapi_routes(func.FunctionApp(), title="API", version="1.0.0", **kwargs)


def _get(handler: Any, etag: str | None = None, url: str = "/openapi.json") -> func.HttpResponse:
    headers = {"If-None-Match": etag} if etag is not None else {}
    response: func.HttpResponse = handler(
        func.HttpRequest(method="GET", url=url, headers=headers, body=b"")
    )
    return response


def test_json_and_yaml_send_a_strong_etag_and_revalidation_policy() -> None:
    routes = _routes()
    assert routes.json is not None and routes.yaml is not None

    for handler in (routes.json, routes.yaml):
        response = _get(handler)
        assert response.status_code == 200
        assert response.headers["ETag"].startswith('"') and not response.headers["ETag"].startswith(
            "W/"
        )
        assert response.headers["Cache-Control"] == "no-cache"
    assert _get(routes.json).headers["ETag"] != _get(routes.yaml).headers["ETag"]


def test_protected_routes_are_private() -> None:
    routes = _routes(auth_level=func.AuthLevel.FUNCTION, docs_key_forwarding="none")
    assert routes.json is not None

    assert _get(routes.json).headers["Cache-Control"] == "private, no-cache"


@pytest.mark.parametrize(
    "header",
    ["{etag}", "W/{etag}", '"other", {etag}', 'W/"other" , W/{etag}', "*"],
)
def test_matching_if_none_match_returns_empty_304(header: str) -> None:
    routes = _routes()
    assert routes.json is not None
    etag = _get(routes.json).headers["ETag"]

    response = _get(routes.json, header.format(etag=etag))

    assert response.status_code == 304
    assert response.get_body() == b""
    assert response.headers["ETag"] == etag
    assert response.headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("header", ['"nope"', 'W/"nope", "also-nope"', ""])
def test_non_matching_if_none_match_returns_full_body(header: str) -> None:
    routes = _routes()
    assert routes.json is not None

    response = _get(routes.json, header)

    assert response.status_code == 200
    assert json.loads(response.get_body())["openapi"]


def test_changed_representation_changes_the_etag_and_drops_the_304(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = _routes(cache_spec=False)
    assert routes.json is not None
    old = _get(routes.json).headers["ETag"]

    monkeypatch.setattr(package, "get_openapi_json", lambda **_: '{"openapi": "changed"}')

    response = _get(routes.json, old)

    assert response.status_code == 200
    assert response.headers["ETag"] != old


def test_cache_is_opt_in_and_renders_once_when_enabled(render_calls: list[str]) -> None:
    uncached = _routes()
    cached = _routes(cache_spec=True)
    assert uncached.json is not None and cached.json is not None and cached.yaml is not None

    for _ in range(3):
        _get(uncached.json)
    assert render_calls.count("get_openapi_json") == 3

    render_calls.clear()
    for _ in range(3):
        _get(cached.json)
    _get(cached.yaml)
    assert render_calls == ["get_openapi_json", "get_openapi_yaml"]


def test_invalidate_cache_forces_a_new_render(render_calls: list[str]) -> None:
    routes = _routes(cache_spec=True)
    assert routes.json is not None
    _get(routes.json)

    routes.invalidate_cache()
    _get(routes.json)

    assert render_calls.count("get_openapi_json") == 2


def test_independent_registrations_do_not_share_a_cache(render_calls: list[str]) -> None:
    first = _routes(cache_spec=True)
    second = _routes(cache_spec=True)
    assert first.json is not None and second.json is not None

    _get(first.json)
    _get(second.json)

    assert render_calls.count("get_openapi_json") == 2


def test_failed_render_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = _routes(cache_spec=True)
    assert routes.json is not None
    original = package.get_openapi_json
    state = {"fail": True}

    def flaky(*args: Any, **kwargs: Any) -> str:
        if state["fail"]:
            raise RuntimeError("boom")
        return original(*args, **kwargs)

    monkeypatch.setattr(package, "get_openapi_json", flaky)
    with pytest.raises(RuntimeError):
        _get(routes.json)

    state["fail"] = False
    assert _get(routes.json).status_code == 200


def test_concurrent_first_requests_render_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = _routes(cache_spec=True)
    assert routes.json is not None
    original = package.get_openapi_json
    count = 0
    guard = threading.Lock()

    def counted(*args: Any, **kwargs: Any) -> str:
        nonlocal count
        with guard:
            count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(package, "get_openapi_json", counted)
    handler = routes.json
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda: results.append(_get(handler).status_code)) for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [200] * 8
    assert count == 1
