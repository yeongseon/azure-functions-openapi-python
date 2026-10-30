from __future__ import annotations

import json
import os
from pathlib import Path
import warnings

from azure_functions_openapi.routes import DEFAULT_ROUTE_PREFIX, normalize_route_prefix


def _read_route_prefix(path: Path) -> tuple[str | None, str | None]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, str(error)

    match document:
        case {"extensions": {"http": {"routePrefix": str(prefix)}}}:
            return normalize_route_prefix(prefix), None
        case {"extensions": {"http": {"routePrefix": _}}}:
            return None, "extensions.http.routePrefix must be a string"
        case _:
            return None, None


def resolve_route_prefix(host_json: str | os.PathLike[str] | None = None) -> str:
    """Resolve a normalized prefix from the app setting, host.json, or the /api default."""
    setting = "AzureFunctionsJobHost__extensions__http__routePrefix"
    if setting in os.environ:
        return normalize_route_prefix(os.environ[setting])
    path = Path(host_json) if host_json is not None else Path("host.json")
    prefix, reason = _read_route_prefix(path)
    if reason is not None:
        warnings.warn(
            f"Could not read route prefix from {path}: {reason}; using {DEFAULT_ROUTE_PREFIX!r}.",
            RuntimeWarning,
            stacklevel=2,
        )
    return normalize_route_prefix(DEFAULT_ROUTE_PREFIX) if prefix is None else prefix
