"""Azure-facing adapters that isolate all Azure Functions SDK coupling.

The :mod:`azure_functions_openapi.adapters.azure_functions` module is the single
boundary that reads Azure Functions SDK internals; the rest of the package stays
SDK-agnostic and consumes only the neutral surface re-exported here.
"""

from __future__ import annotations

from azure_functions_openapi.adapters.azure_functions import (
    build_function,
    extract_auth_level,
    extract_http_binding,
    get_bindings,
    get_function_name,
    get_unbuilt_user_handler,
    get_user_handler,
    is_function_builder,
    is_http_function,
    iter_functions,
)

__all__ = [
    "build_function",
    "extract_auth_level",
    "extract_http_binding",
    "get_bindings",
    "get_function_name",
    "get_unbuilt_user_handler",
    "get_user_handler",
    "is_function_builder",
    "is_http_function",
    "iter_functions",
]
