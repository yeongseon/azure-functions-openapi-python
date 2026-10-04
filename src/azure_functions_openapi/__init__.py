# src/azure_functions_openapi/__init__.py
import sys
import warnings

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
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
)
from azure_functions_openapi.swagger_ui import render_swagger_ui
from azure_functions_openapi.types import OpenAPIOperationMetadata

__version__ = "0.28.0"
scan_endpoint_metadata = _bridge.scan_endpoint_metadata
scan_validation_metadata = _bridge.scan_validation_metadata

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


if sys.version_info < (3, 11):
    warnings.warn(
        "azure-functions-openapi will drop support for Python 3.10 in its next minor release. "
        "Python 3.10 reaches end of life in October 2026; upgrade to Python 3.11 "
        "or newer to keep receiving updates.",
        FutureWarning,
        stacklevel=2,
    )
