from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import os
import re
import threading
from typing import Any, Literal
from urllib.parse import urlencode
import warnings

import azure.functions as func

from azure_functions_openapi.host_config import resolve_route_prefix
from azure_functions_openapi.routes import (
    DEFAULT_ROUTE_PREFIX,
    apply_host_prefix,
    normalize_route_prefix,
)
from azure_functions_openapi.swagger_ui import _DEFAULT_HSTS, render_swagger_ui

DocsHandler = Callable[[func.HttpRequest], func.HttpResponse]
RouteApp = func.FunctionApp | func.Blueprint


def _noop() -> None:
    return None


@dataclass(frozen=True, slots=True)
class DocsRoutes:
    """Handlers registered by :func:`register_openapi_routes`."""

    json: DocsHandler | None
    yaml: DocsHandler | None
    docs: DocsHandler | None
    invalidate_cache: Callable[[], None] = _noop


def register_openapi_routes(
    app: RouteApp,
    *,
    title: str,
    version: str,
    json_route: str = "openapi.json",
    yaml_route: str = "openapi.yaml",
    docs_route: str = "docs",
    route_prefix: str | None = DEFAULT_ROUTE_PREFIX,
    host_json: str | os.PathLike[str] | None = None,
    auth_level: func.AuthLevel = func.AuthLevel.ANONYMOUS,
    name_prefix: str = "openapi",
    spec_options: Mapping[str, Any] | None = None,
    enabled: bool = True,
    docs_key_forwarding: Literal["header", "query", "none"] | None = None,
    hsts: str | None = _DEFAULT_HSTS,
    send_requested_with_header: bool = True,
    cache_spec: bool = False,
) -> DocsRoutes:
    """Register opt-in JSON, YAML, and Swagger UI routes on ``app``.

    Example::

        register_openapi_routes(app, title="Orders API", version="1.0.0")

    The supplied app remains the routing authority. No routes are registered
    until this function is called, and ``enabled=False`` performs no mutation.
    For protected routes, ``docs_key_forwarding="header"`` lets the browser
    remove ``code`` from its page URL and send it only in the same-origin spec
    request's ``x-functions-key`` header, without server-side key echo.
    ``"query"`` preserves legacy spec-URL forwarding; ``"none"`` never forwards.
    The default ``None`` preserves ``"query"`` with a DeprecationWarning for
    protected routes; it will change to ``"header"`` in a future minor before 1.0.
    Anonymous routes never forward. The key must authorize both docs and JSON
    functions. The initial navigation URL can still be retained in access logs.

    ``route_prefix`` defaults to ``"/api"``. Pass ``route_prefix=None`` to resolve it once at
    registration, in this order: the ``AzureFunctionsJobHost__extensions__http__routePrefix``
    setting, ``extensions.http.routePrefix`` in ``host_json`` (default ``./host.json``), then
    ``"/api"``. Any explicit string, including ``"auto"`` (the literal ``/auto`` prefix), is
    used as given and never resolved.

    ``hsts`` and ``send_requested_with_header`` are forwarded to
    :func:`render_swagger_ui` for the docs page; see it for host and subdomain scope.

    The JSON and YAML handlers send a strong ``ETag`` and honor ``If-None-Match`` (a list of
    tags, weak tags and ``*``), answering ``304`` with an empty body. They send
    ``Cache-Control: no-cache`` (``private, no-cache`` for protected routes), so clients
    revalidate every time. ``cache_spec=True`` additionally keeps each rendered representation
    in memory for this registration only; it is never shared between apps. Call
    ``routes.invalidate_cache()`` after the app, registry or options change. A failed render
    is never cached and the next request retries.
    """
    routes = (json_route, yaml_route, docs_route)
    for route in routes:
        if not route.strip() or route.startswith("/"):
            raise ValueError("Documentation routes must be non-empty and omit the leading slash")
    if len(set(routes)) != len(routes):
        raise ValueError("Documentation routes must be distinct")
    if not isinstance(auth_level, func.AuthLevel):
        raise TypeError("auth_level must be an azure.functions.AuthLevel")
    if docs_key_forwarding not in (None, "header", "query", "none"):
        raise ValueError('docs_key_forwarding must be "header", "query", "none", or None')
    if not name_prefix.strip():
        raise ValueError("name_prefix must be non-empty")
    suffixes = tuple(_function_suffix(route) for route in routes)
    function_names = tuple(f"{name_prefix}_{suffix}" for suffix in suffixes)
    if len(set(suffixes)) != len(suffixes) or len(set(function_names)) != len(function_names):
        raise ValueError("Generated documentation function names must be distinct")

    if not enabled:
        return DocsRoutes(json=None, yaml=None, docs=None)

    if route_prefix is None:
        route_prefix = resolve_route_prefix(host_json)

    options = dict(spec_options or {})
    reserved_options = {"title", "version", "route_prefix", "app"}.intersection(options)
    if reserved_options:
        names = ", ".join(sorted(reserved_options))
        raise ValueError(f"spec_options cannot override: {names}")

    protected = auth_level is not func.AuthLevel.ANONYMOUS
    if protected and docs_key_forwarding is None:
        warnings.warn(
            "The legacy docs key-in-URL forwarding exposes reusable keys in served HTML "
            'and specification request URLs. Pass docs_key_forwarding="header" (or "none") '
            'explicitly; the default will change to "header" in a future minor release before 1.0.',
            DeprecationWarning,
            stacklevel=2,
        )

    def render_json() -> str:
        from azure_functions_openapi import get_openapi_json

        return get_openapi_json(
            title=title, version=version, route_prefix=route_prefix, app=app, **options
        )

    def render_yaml() -> str:
        from azure_functions_openapi import get_openapi_yaml

        return get_openapi_yaml(
            title=title, version=version, route_prefix=route_prefix, app=app, **options
        )

    cache_control = "private, no-cache" if protected else "no-cache"
    cache: dict[str, str] = {}
    cache_lock = threading.Lock()

    def respond(
        req: func.HttpRequest, key: str, render: Callable[[], str], mimetype: str
    ) -> func.HttpResponse:
        if cache_spec:
            with cache_lock:
                body = cache.get(key)
                if body is None:
                    body = render()
                    cache[key] = body
        else:
            body = render()
        etag = _etag(body)
        headers = {"ETag": etag, "Cache-Control": cache_control}
        if _if_none_match(req.headers.get("if-none-match"), etag):
            return func.HttpResponse(status_code=304, headers=headers)
        return func.HttpResponse(body, mimetype=mimetype, headers=headers)

    def openapi_json(req: func.HttpRequest) -> func.HttpResponse:
        return respond(req, "json", render_json, "application/json")

    def openapi_yaml(req: func.HttpRequest) -> func.HttpResponse:
        return respond(req, "yaml", render_yaml, "application/x-yaml")

    def invalidate_cache() -> None:
        with cache_lock:
            cache.clear()

    def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
        prefix = normalize_route_prefix(route_prefix)
        # json_route is registered directly as an SDK binding below (not an
        # explicit @openapi(route=...) override), so it is host-relative and
        # always gets the prefix prepended (#784) -- matching how the host
        # actually serves it, even when json_route's own first segment
        # happens to equal the configured prefix.
        openapi_url = apply_host_prefix(f"/{json_route}", prefix)
        if protected and docs_key_forwarding in (None, "query"):
            code = req.params.get("code")
            if code is not None:
                separator = "&" if "?" in openapi_url else "?"
                openapi_url = f"{openapi_url}{separator}{urlencode({'code': code})}"
        return render_swagger_ui(
            title=f"{title} Docs",
            openapi_url=openapi_url,
            forward_page_key_header=protected and docs_key_forwarding == "header",
            hsts=hsts,
            send_requested_with_header=send_requested_with_header,
        )

    registered_json = _register_handler(app, openapi_json, json_route, auth_level, name_prefix)
    registered_yaml = _register_handler(app, openapi_yaml, yaml_route, auth_level, name_prefix)
    registered_docs = _register_handler(app, swagger_ui, docs_route, auth_level, name_prefix)
    return DocsRoutes(
        json=registered_json,
        yaml=registered_yaml,
        docs=registered_docs,
        invalidate_cache=invalidate_cache,
    )


def _etag(body: str) -> str:
    return '"' + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32] + '"'


def _if_none_match(header: str | None, etag: str) -> bool:
    if header is None:
        return False
    if header.strip() == "*":
        return True
    current = etag.removeprefix("W/")
    return any(candidate.strip().removeprefix("W/") == current for candidate in header.split(","))


def _register_handler(
    app: RouteApp,
    handler: DocsHandler,
    route: str,
    auth_level: func.AuthLevel,
    name_prefix: str,
) -> DocsHandler:
    function_suffix = _function_suffix(route)
    routed = app.route(route=route, methods=["GET"], auth_level=auth_level)(handler)
    app.function_name(name=f"{name_prefix}_{function_suffix}")(routed)
    return handler


def _function_suffix(route: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", route).strip("_").lower()
