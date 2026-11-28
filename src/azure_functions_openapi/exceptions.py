# src/azure_functions_openapi/exceptions.py
from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass


class OpenAPISpecConfigError(ValueError):
    """Raised for caller-fixable configuration errors such as an unsupported
    OpenAPI version or conflicting security scheme definitions.

    Subclasses :class:`ValueError` so existing ``except ValueError`` call-sites
    continue to work without changes.
    """


@dataclass(unsafe_hash=True)
class UnsupportedRouteTemplateError(ValueError):
    """Raised when an Azure route cannot be represented faithfully in OpenAPI."""

    function_name: str
    route: str
    token: str

    def __setattr__(self, name: str, value: object) -> None:
        # Route fields stay read-only, but BaseException machinery (add_note,
        # __traceback__, __cause__) must remain assignable, so frozen=True
        # cannot be used here.
        # Re-assigning an identical value is allowed so pickle and copy, which
        # restore the instance state, keep working.
        if name in ("function_name", "route", "token") and self.__dict__.get(name, value) != value:
            raise FrozenInstanceError(f"cannot assign to field {name!r}")
        super().__setattr__(name, value)

    def __str__(self) -> str:
        return (
            f"Function '{self.function_name}' uses unsupported Azure route token "
            f"'{{{self.token}}}' in route '{self.route}'. Supported route parameters are "
            "'{name}', '{name:int}', and '{name:alpha}'."
        )


class SDKIncompatibleError(OpenAPISpecConfigError):
    """Raised when the installed ``azure-functions`` SDK is incompatible with
    ``@openapi``.

    The Azure Functions SDK discovery adapter reads private SDK internals
    behind the public ``FunctionBuilder.build`` primitive (and callers walk the
    ``__wrapped__`` chain). When a future SDK release renames or restructures
    those internals, this dedicated exception makes SDK-incompatibility failures
    distinguishable from ordinary caller-fixable configuration errors.

    Subclasses :class:`OpenAPISpecConfigError` (and therefore :class:`ValueError`)
    so existing ``except OpenAPISpecConfigError`` / ``except ValueError`` call-sites
    continue to work without changes.
    """
