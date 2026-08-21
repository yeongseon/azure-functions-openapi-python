# src/azure_functions_openapi/openapi.py
"""Deprecation shim for the renamed ``spec`` submodule.

Importing from ``azure_functions_openapi.openapi`` is preserved for
backward compatibility with code written against versions <= 0.17.x.
The canonical location is :mod:`azure_functions_openapi.spec`.

Scheduled for removal in 1.0. See issue #194.
"""

from __future__ import annotations

import warnings

from azure_functions_openapi.spec import (
    DEFAULT_OPENAPI_INFO_DESCRIPTION,
    OPENAPI_VERSION_3_0,
    OPENAPI_VERSION_3_1,
    OPENAPI_VERSION_3_2,
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
)

warnings.warn(
    "Importing from azure_functions_openapi.openapi is deprecated; "
    "use azure_functions_openapi.spec instead. "
    "The shim is scheduled for removal in 1.0 (see issue #194).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "DEFAULT_OPENAPI_INFO_DESCRIPTION",
    "OPENAPI_VERSION_3_0",
    "OPENAPI_VERSION_3_1",
    "OPENAPI_VERSION_3_2",
    "generate_openapi_spec",
    "get_openapi_json",
    "get_openapi_yaml",
]
