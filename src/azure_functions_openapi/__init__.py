# src/azure_functions_openapi/__init__.py
import json
from typing import Any
import warnings

import yaml

from azure_functions_openapi._warnings import SpecWarning, WarningCode
import azure_functions_openapi.bridge as _bridge
from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    openapi,
    register_openapi_metadata,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError, SDKIncompatibleError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.registry import registry as _default_registry
from azure_functions_openapi.spec import (
    DEFAULT_OPENAPI_INFO_DESCRIPTION,
    OPENAPI_VERSION_3_0,
    OPENAPI_VERSION_3_1,
    OPENAPI_VERSION_3_2,
    SpecReport,
)
from azure_functions_openapi.spec import generate_openapi_report as _generate_openapi_report
from azure_functions_openapi.spec import generate_openapi_spec as _generate_openapi_spec
from azure_functions_openapi.swagger_ui import render_swagger_ui
from azure_functions_openapi.types import OpenAPIOperationMetadata

__version__ = "0.29.1"
scan_endpoint_metadata = _bridge.scan_endpoint_metadata
scan_validation_metadata = _bridge.scan_validation_metadata


def _prepare_generation(
    app: object | None,
    route_prefix: str,
    registry: OpenAPIRegistry | None,
) -> tuple[SpecWarning, ...]:
    """Scan an app and diagnose registry routes that still lack binding evidence."""
    if app is not None:
        _bridge.scan_endpoint_metadata(app, route_prefix=route_prefix, registry=registry)

    active_registry = registry if registry is not None else _default_registry
    unresolved = tuple(
        SpecWarning(
            code=WarningCode.UNRESOLVED_ROUTE,
            message=(
                f"Route for '{entry.get('function_name') or key}' could not be verified; "
                "if this function uses a custom route, pass app=... (or route=...)."
            ),
            function_name=entry.get("function_name") or key,
        )
        for key, entry in active_registry.snapshot().items()
        if entry.get("route") is None and not entry.get("_route_evidence")
    )
    for item in unresolved:
        warnings.warn(item.message, RuntimeWarning, stacklevel=3)
    return unresolved


def generate_openapi_spec(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_1,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = "/api",
    strict: bool = False,
    registry: OpenAPIRegistry | None = None,
    hoist_flat_schemas: bool = False,
    infer_auth_level: bool = False,
    servers: list[dict[str, Any]] | None = None,
    contact: dict[str, Any] | None = None,
    license: dict[str, Any] | None = None,
    external_docs: dict[str, Any] | None = None,
    tags: list[dict[str, Any]] | None = None,
    app: object | None = None,
) -> dict[str, Any]:
    """Compile a spec, optionally reconciling routes from a FunctionApp first."""
    _prepare_generation(app, route_prefix, registry)
    return _generate_openapi_spec(
        title=title,
        version=version,
        openapi_version=openapi_version,
        description=description,
        security_schemes=security_schemes,
        route_prefix=route_prefix,
        strict=strict,
        registry=registry,
        hoist_flat_schemas=hoist_flat_schemas,
        infer_auth_level=infer_auth_level,
        servers=servers,
        contact=contact,
        license=license,
        external_docs=external_docs,
        tags=tags,
    )


def get_openapi_json(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_1,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = "/api",
    strict: bool = False,
    registry: OpenAPIRegistry | None = None,
    hoist_flat_schemas: bool = False,
    infer_auth_level: bool = False,
    servers: list[dict[str, Any]] | None = None,
    contact: dict[str, Any] | None = None,
    license: dict[str, Any] | None = None,
    external_docs: dict[str, Any] | None = None,
    tags: list[dict[str, Any]] | None = None,
    app: object | None = None,
) -> str:
    """Return JSON after optionally reconciling routes from a completed FunctionApp."""
    try:
        spec = generate_openapi_spec(
            title,
            version,
            openapi_version,
            description,
            security_schemes,
            route_prefix,
            strict,
            registry,
            hoist_flat_schemas,
            infer_auth_level,
            servers,
            contact,
            license,
            external_docs,
            tags,
            app,
        )
        return json.dumps(spec, indent=2, ensure_ascii=False)
    except OpenAPISpecConfigError:
        raise
    except Exception as error:
        raise RuntimeError("Failed to generate OpenAPI JSON") from error


def get_openapi_yaml(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_1,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = "/api",
    strict: bool = False,
    registry: OpenAPIRegistry | None = None,
    hoist_flat_schemas: bool = False,
    infer_auth_level: bool = False,
    servers: list[dict[str, Any]] | None = None,
    contact: dict[str, Any] | None = None,
    license: dict[str, Any] | None = None,
    external_docs: dict[str, Any] | None = None,
    tags: list[dict[str, Any]] | None = None,
    app: object | None = None,
) -> str:
    """Return YAML after optionally reconciling routes from a completed FunctionApp."""
    try:
        spec = generate_openapi_spec(
            title,
            version,
            openapi_version,
            description,
            security_schemes,
            route_prefix,
            strict,
            registry,
            hoist_flat_schemas,
            infer_auth_level,
            servers,
            contact,
            license,
            external_docs,
            tags,
            app,
        )
        return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)
    except OpenAPISpecConfigError:
        raise
    except Exception as error:
        raise RuntimeError("Failed to generate OpenAPI YAML") from error


def generate_openapi_report(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_1,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = "/api",
    strict: bool = False,
    registry: OpenAPIRegistry | None = None,
    hoist_flat_schemas: bool = False,
    infer_auth_level: bool = False,
    servers: list[dict[str, Any]] | None = None,
    contact: dict[str, Any] | None = None,
    license: dict[str, Any] | None = None,
    external_docs: dict[str, Any] | None = None,
    tags: list[dict[str, Any]] | None = None,
    app: object | None = None,
) -> SpecReport:
    """Return a spec report after optionally reconciling a completed FunctionApp."""
    unresolved = _prepare_generation(app, route_prefix, registry)
    report = _generate_openapi_report(
        title,
        version,
        openapi_version,
        description,
        security_schemes,
        route_prefix,
        strict,
        registry,
        hoist_flat_schemas,
        infer_auth_level,
        servers,
        contact,
        license,
        external_docs,
        tags,
    )
    return SpecReport(spec=report.spec, warnings=(*report.warnings, *unresolved))


__all__ = [
    "__version__",
    "OPENAPI_VERSION_3_0",
    "OPENAPI_VERSION_3_1",
    "OPENAPI_VERSION_3_2",
    "OpenAPISpecConfigError",
    "SDKIncompatibleError",
    "OpenAPIOperationMetadata",
    "OpenAPIRegistry",
    "SpecReport",
    "SpecWarning",
    "WarningCode",
    "clear_openapi_registry",
    "generate_openapi_report",
    "generate_openapi_spec",
    "get_openapi_json",
    "get_openapi_yaml",
    "openapi",
    "register_openapi_metadata",
    "render_swagger_ui",
    "scan_endpoint_metadata",
    "scan_validation_metadata",
]
