# src/azure_functions_openapi/__init__.py
from typing import Any

from azure_functions_openapi._warnings import SpecWarning, WarningCode
import azure_functions_openapi.bridge as _bridge
from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    openapi,
    register_openapi_metadata,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError, SDKIncompatibleError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    OPENAPI_VERSION_3_0,
    OPENAPI_VERSION_3_1,
    OPENAPI_VERSION_3_2,
    SpecReport,
    generate_openapi_report,
    get_openapi_json,
    get_openapi_yaml,
)
from azure_functions_openapi.spec import generate_openapi_spec as _generate_openapi_spec
from azure_functions_openapi.swagger_ui import render_swagger_ui
from azure_functions_openapi.types import OpenAPIOperationMetadata

__version__ = "0.29.0"
scan_endpoint_metadata = _bridge.scan_endpoint_metadata
scan_validation_metadata = _bridge.scan_validation_metadata


def generate_openapi_spec(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_1,
    description: str = (
        "Auto-generated OpenAPI documentation. Markdown supported in descriptions (CommonMark)."
    ),
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
    if app is not None:
        _bridge.scan_endpoint_metadata(app, route_prefix=route_prefix, registry=registry)
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
