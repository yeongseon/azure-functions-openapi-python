# tests/test_route_prefix_provenance.py
"""A discovered SDK binding route is host-relative, so the host prefix is
always prepended -- not deduplicated against the route's own first segment
(issue #784).

apply_route_prefix() treats any path already starting with the configured
prefix as "already prefixed" -- an intentional convenience for an explicit
@openapi(route=...) override, so authors can write either "/api/users" or
"users" and get the same result. Azure Functions SDK bindings have no such
convenience: the host composes the served URL as
``routePrefix + '/' + routeTemplate`` unconditionally (confirmed against the
official host routing implementation referenced in the issue), so
route="api/users" under host prefix "api" is served at "/api/api/users", not
"/api/users". These tests exercise real azure.functions SDK bindings (not
mocked apply_route_prefix() calls) end to end, covering both the bridge
app-scan path and the decorator-time auto-detection path, the documentation
helper's own routes, and the preserved explicit-override compatibility.
"""

from __future__ import annotations

import json
from typing import Any

import azure.functions as func
import pytest

from azure_functions_openapi import (
    clear_openapi_registry,
    generate_openapi_spec,
    openapi,
    register_openapi_routes,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _request(path: str) -> func.HttpRequest:
    return func.HttpRequest(
        method="GET", url=f"https://example.invalid{path}", headers={}, params={}, body=b""
    )


class TestDiscoveredRoutePrefixing:
    def test_discovered_route_gets_prefix_prepended_unconditionally(self) -> None:
        # Given: route="api/users" shares a literal first segment with the
        # configured host prefix "api".
        app = func.FunctionApp()

        @openapi(summary="List users")
        @app.route(route="api/users", methods=["GET"])
        def users(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("[]")

        # When: the completed app is scanned.
        spec = generate_openapi_spec(app=app, route_prefix="/api", strict=True)

        # Then: both segments appear -- the prefix is not deduplicated away.
        assert list(spec["paths"]) == ["/api/api/users"]

    def test_discovered_route_exactly_equal_to_prefix_generates_both_segments(self) -> None:
        app = func.FunctionApp()

        @openapi(summary="root")
        @app.route(route="api", methods=["GET"])
        def root(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("ok")

        spec = generate_openapi_spec(app=app, route_prefix="/api", strict=True)

        assert list(spec["paths"]) == ["/api/api"]

    def test_custom_prefix_with_normalized_slashes(self) -> None:
        app = func.FunctionApp()

        @openapi(summary="custom prefix")
        @app.route(route="v1/widgets", methods=["GET"])
        def widgets(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("ok")

        # A trailing slash and a missing leading slash on route_prefix must
        # normalize the same way as the default prefix does.
        spec = generate_openapi_spec(app=app, route_prefix="v1/", strict=True)

        assert list(spec["paths"]) == ["/v1/v1/widgets"]

    def test_disabled_host_prefix_leaves_discovered_route_unchanged(self) -> None:
        app = func.FunctionApp()

        @openapi(summary="no prefix")
        @app.route(route="api/users", methods=["GET"])
        def users(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("[]")

        spec = generate_openapi_spec(app=app, route_prefix="", strict=True)

        assert list(spec["paths"]) == ["/api/users"]

    def test_outermost_openapi_auto_detects_binding_as_host_relative(self) -> None:
        # Given: @openapi is outermost and can see the binding directly, with
        # no app scan at all -- a different code path (decorator-time
        # auto-detection, not the bridge's app-scan backfill) from the other
        # tests in this class.
        app = func.FunctionApp()

        @openapi(summary="outermost")
        @app.route(route="api/items", methods=["GET"])
        def items(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("ok")

        # When: generating WITHOUT passing app= (decorator-time metadata only).
        spec = generate_openapi_spec(route_prefix="/api", strict=True)

        # Then: still host-relative, not deduplicated.
        assert list(spec["paths"]) == ["/api/api/items"]

    def test_repeated_scan_does_not_accumulate_additional_prefixes(self) -> None:
        app = func.FunctionApp()

        @openapi(summary="repeat")
        @app.route(route="api/items", methods=["GET"])
        def items(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("ok")

        first = generate_openapi_spec(app=app, route_prefix="/api", strict=True)
        second = generate_openapi_spec(app=app, route_prefix="/api", strict=True)

        assert list(first["paths"]) == list(second["paths"]) == ["/api/api/items"]

    def test_validate_http_discovered_route_is_also_host_relative(self) -> None:
        # Given: an endpoint discovered purely through the endpoint-metadata
        # convention (no @openapi at all) -- the "has_enrichment" bridge path.
        from azure_functions_openapi.bridge import _HANDLER_METADATA_ATTR

        app = func.FunctionApp()

        def handler(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("ok")

        setattr(
            handler,
            _HANDLER_METADATA_ATTR,
            {"endpoint": {"version": 1, "request_body": {"type": "object"}}},
        )
        app.route(route="api/orders", methods=["POST"])(handler)

        # When
        spec = generate_openapi_spec(app=app, route_prefix="/api", strict=True)

        # Then
        assert list(spec["paths"]) == ["/api/api/orders"]


class TestExplicitRouteOverrideCompatibilityPreserved:
    def test_explicit_openapi_route_still_dedupes_against_the_prefix(self) -> None:
        # Given: the documented explicit-override compatibility -- an author
        # may write @openapi(route=...) with or without the prefix already
        # included and get the same result either way.
        app = func.FunctionApp()

        @openapi(route="/api/legacy", summary="explicit override")
        @app.route(route="legacy-impl", methods=["GET"])
        def legacy(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("ok")

        # When
        spec = generate_openapi_spec(app=app, route_prefix="/api", strict=True)

        # Then: unchanged -- the explicit route is not host-relative, so it
        # keeps the dedup-on-prefix-match compatibility behavior.
        assert list(spec["paths"]) == ["/api/legacy"]

    def test_explicit_openapi_route_without_prefix_still_gets_one(self) -> None:
        app = func.FunctionApp()

        @openapi(route="legacy", summary="explicit override, no prefix written")
        @app.route(route="legacy-impl", methods=["GET"])
        def legacy(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("ok")

        spec = generate_openapi_spec(app=app, route_prefix="/api", strict=True)

        assert list(spec["paths"]) == ["/api/legacy"]

    def test_explicit_override_and_discovered_binding_do_not_collide_on_registry_key(
        self,
    ) -> None:
        # Given: an explicit @openapi(route=...) override whose route happens
        # to share a literal prefix segment, registered alongside a SEPARATE
        # handler whose route is genuinely discovered from its own binding --
        # the exact combination that made both resolve to the same registry
        # key ("get::/api/api/users") before #797's fix, silently dropping
        # one operation via reg.set().
        app = func.FunctionApp()

        @app.route(route="users_impl_a", methods=["GET"])
        @openapi(route="/api/users", summary="Explicit override handler")
        def handler_a(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("a")

        @openapi(summary="Discovered binding handler")
        @app.route(route="api/users", methods=["GET"])
        def handler_b(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("b")

        # When
        spec = generate_openapi_spec(app=app, route_prefix="/api", strict=True)

        # Then: both operations survive as distinct paths, matching their
        # own provenance -- the explicit override still dedupes, and the
        # discovered binding still always-prepends.
        assert sorted(spec["paths"]) == ["/api/api/users", "/api/users"]

    def test_json_route_sharing_prefix_segment_is_fetched_at_its_real_host_url(self) -> None:
        # Given: register_openapi_routes()'s own json_route is registered
        # directly as an SDK binding (host-relative), sharing the "api"
        # prefix segment the way the issue's own reproduction does.
        app = func.FunctionApp()

        @openapi(summary="List users")
        @app.route(route="api/users", methods=["GET"])
        def users(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("[]", mimetype="application/json")

        routes = register_openapi_routes(
            app,
            title="Prefix example",
            version="1.0.0",
            route_prefix="/api",
            json_route="api/openapi.json",
        )
        assert routes.docs is not None
        assert routes.json is not None

        # When: the docs page is rendered.
        html = routes.docs(_request("/api/docs")).get_body().decode()

        # Then: the embedded fetch URL matches the real host-served path,
        # not a deduplicated one that would 404 against the actual host.
        assert 'url: "/api/api/openapi.json"' in html

        # And: that URL is exactly where generate_openapi_spec() documents
        # the same binding's own route as being served.
        spec = json.loads(routes.json(_request("/api/api/openapi.json")).get_body())
        assert list(spec["paths"]) == ["/api/api/users"]
