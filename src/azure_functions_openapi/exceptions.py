# src/azure_functions_openapi/exceptions.py
from __future__ import annotations


class OpenAPISpecConfigError(ValueError):
    """Raised for caller-fixable configuration errors such as an unsupported
    OpenAPI version or conflicting security scheme definitions.

    Subclasses :class:`ValueError` so existing ``except ValueError`` call-sites
    continue to work without changes.
    """


class SDKIncompatibleError(OpenAPISpecConfigError):
    """Raised when the installed ``azure-functions`` SDK is incompatible with
    ``@openapi``.

    The bridge and decorator read private ``azure-functions`` SDK internals
    (e.g. ``FunctionBuilder._function._func`` and the ``__wrapped__`` chain).
    When a future SDK release renames or restructures those attributes, this
    dedicated exception makes SDK-incompatibility failures distinguishable from
    ordinary caller-fixable configuration errors.

    Subclasses :class:`OpenAPISpecConfigError` (and therefore :class:`ValueError`)
    so existing ``except OpenAPISpecConfigError`` / ``except ValueError`` call-sites
    continue to work without changes.
    """
