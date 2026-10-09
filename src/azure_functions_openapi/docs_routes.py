from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from typing import Any

import azure.functions as func

from azure_functions_openapi.routes import (
    DEFAULT_ROUTE_PREFIX,
    apply_route_prefix,
    normalize_route_prefix,
)
from azure_functions_openapi.swagger_ui import render_swagger_ui

DocsHandler = Callable[[func.HttpRequest], func.HttpResponse]
RouteApp = func.FunctionApp | func.Blueprint


@dataclass(frozen=True, slots=True)
class DocsRoutes:
    """Handlers registered by :func:`register_openapi_routes`."""

    json: DocsHandler | None
    yaml: DocsHandler | None
    docs: DocsHandler | None


def register_openapi_routes(
    app: RouteApp,
    *,
    title: str,
    version: str,
    json_route: str = "openapi.json",
    yaml_route: str = "openapi.yaml",
    docs_route: str = "docs",
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
    auth_level: func.AuthLevel = func.AuthLevel.ANONYMOUS,
    name_prefix: str = "openapi",
    spec_options: Mapping[str, Any] | None = None,
    enabled: bool = True,
) -> DocsRoutes:
    """Register opt-in JSON, YAML, and Swagger UI routes on ``app``.

    Example::

        register_openapi_routes(app, title="Orders API", version="1.0.0")

    The supplied app remains the routing authority. No routes are registered
    until this function is called, and ``enabled=False`` performs no mutation.
    """
    routes = (json_route, yaml_route, docs_route)
    for route in routes:
        if not route.strip() or route.startswith("/"):
            raise ValueError("Documentation routes must be non-empty and omit the leading slash")
    if len(set(routes)) != len(routes):
        raise ValueError("Documentation routes must be distinct")
    if not isinstance(auth_level, func.AuthLevel):
        raise TypeError("auth_level must be an azure.functions.AuthLevel")
    if not name_prefix.strip():
        raise ValueError("name_prefix must be non-empty")

    if not enabled:
        return DocsRoutes(json=None, yaml=None, docs=None)

    options = dict(spec_options or {})
    reserved_options = {"title", "version", "route_prefix", "app"}.intersection(options)
    if reserved_options:
        names = ", ".join(sorted(reserved_options))
        raise ValueError(f"spec_options cannot override: {names}")

    def openapi_json(_req: func.HttpRequest) -> func.HttpResponse:
        from azure_functions_openapi import get_openapi_json

        return func.HttpResponse(
            get_openapi_json(
                title=title,
                version=version,
                route_prefix=route_prefix,
                app=app,
                **options,
            ),
            mimetype="application/json",
        )

    def openapi_yaml(_req: func.HttpRequest) -> func.HttpResponse:
        from azure_functions_openapi import get_openapi_yaml

        return func.HttpResponse(
            get_openapi_yaml(
                title=title,
                version=version,
                route_prefix=route_prefix,
                app=app,
                **options,
            ),
            mimetype="application/x-yaml",
        )

    def swagger_ui(_req: func.HttpRequest) -> func.HttpResponse:
        prefix = normalize_route_prefix(route_prefix)
        openapi_url = apply_route_prefix(f"/{json_route}", prefix)
        return render_swagger_ui(title=f"{title} Docs", openapi_url=openapi_url)

    registered_json = _register_handler(app, openapi_json, json_route, auth_level, name_prefix)
    registered_yaml = _register_handler(app, openapi_yaml, yaml_route, auth_level, name_prefix)
    registered_docs = _register_handler(app, swagger_ui, docs_route, auth_level, name_prefix)
    return DocsRoutes(json=registered_json, yaml=registered_yaml, docs=registered_docs)


def _register_handler(
    app: RouteApp,
    handler: DocsHandler,
    route: str,
    auth_level: func.AuthLevel,
    name_prefix: str,
) -> DocsHandler:
    function_suffix = re.sub(r"[^0-9A-Za-z]+", "_", route).strip("_").lower()
    routed = app.route(route=route, methods=["GET"], auth_level=auth_level)(handler)
    app.function_name(name=f"{name_prefix}_{function_suffix}")(routed)
    return handler
