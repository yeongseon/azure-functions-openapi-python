from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import sys

from azure_functions_openapi._warnings import SpecWarning, WarningCode
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.host_config import _read_route_prefix
from azure_functions_openapi.routes import DEFAULT_ROUTE_PREFIX, normalize_route_prefix


def _resolve_cli_route_prefix(args: argparse.Namespace) -> tuple[str, tuple[SpecWarning, ...]]:
    path = Path("host.json")
    app_target = getattr(args, "app", None)
    if isinstance(app_target, str):
        module = sys.modules.get(app_target.partition(":")[0].strip())
        module_file = getattr(module, "__file__", None)
        if isinstance(module_file, str):
            path = Path(module_file).parent / "host.json"

    requested = getattr(args, "route_prefix", None)
    if not isinstance(requested, str):
        requested = DEFAULT_ROUTE_PREFIX
    if requested == "auto":
        setting = "AzureFunctionsJobHost__extensions__http__routePrefix"
        if setting in os.environ:
            return normalize_route_prefix(os.environ[setting]), ()
        configured, reason = _read_route_prefix(path)
        if reason is not None:
            raise OpenAPISpecConfigError(
                f"Cannot use {path} for --route-prefix auto: {reason}. "
                "Fix the file or pass --route-prefix explicitly."
            )
        return DEFAULT_ROUTE_PREFIX if configured is None else configured, ()

    prefix = normalize_route_prefix(requested)
    configured, _ = _read_route_prefix(path)
    if configured is None or configured == prefix:
        return prefix, ()
    return prefix, (
        SpecWarning(
            code=WarningCode.ROUTE_PREFIX_MISMATCH,
            message=(
                f"Effective route prefix {prefix!r} differs from {path} routePrefix "
                f"{configured!r}. Use --route-prefix {shlex.quote(configured)} "
                "or --route-prefix auto to match the host."
            ),
        ),
    )
