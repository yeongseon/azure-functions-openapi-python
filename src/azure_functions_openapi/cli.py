# src/azure_functions_openapi/cli.py
from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys

from azure_functions_openapi.bridge import scan_endpoint_metadata
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    DEFAULT_OPENAPI_INFO_DESCRIPTION,
    OPENAPI_VERSION_3_0,
    OPENAPI_VERSION_3_1,
    collect_spec_warnings,
    generate_openapi_spec,
)


def _import_app_module(app: str) -> tuple[object | None, bool]:
    """Import a user module to trigger @openapi decorator registration.

    Accepts either ``module_name`` or ``module_name:variable`` format.
    When the ``variable`` part is provided it is resolved on the imported
    module and returned so the caller can run endpoint-metadata discovery on
    the live ``FunctionApp`` object. No variable-name guessing is performed:
    metadata discovery only runs when an explicit ``:variable`` is supplied.

    Parameters:
        app: Module import path, optionally with a ``:variable`` suffix.

    Returns:
        A ``(resolved_app, variable_given)`` tuple. ``resolved_app`` is the
        named attribute when a ``:variable`` suffix is present, otherwise
        ``None``. ``variable_given`` records whether a ``:variable`` suffix
        was supplied so the caller can emit an accurate discovery note.

    Raises:
        ValueError: If the ``--app`` value is malformed (empty module, a
            trailing ``:`` with no variable name, or a ``:variable`` that
            resolves to ``None``).
        ImportError: If the module cannot be found or fails to import.
        AttributeError: If the named variable does not exist on the module.
    """
    module_name, sep, variable = app.partition(":")
    module_name = module_name.strip()
    if not module_name:
        raise ValueError(f"Invalid --app value: {app!r}. Expected 'module' or 'module:variable'.")
    mod = importlib.import_module(module_name)
    if not sep:
        # No ``:variable`` suffix supplied — module-only import.
        return None, False
    variable = variable.strip()
    if not variable:
        raise ValueError(
            f"Invalid --app value: {app!r}. Expected a non-empty variable name after "
            "the ':' (e.g. 'function_app:app')."
        )
    if not hasattr(mod, variable):
        raise AttributeError(
            f"Module '{module_name}' has no attribute '{variable}'. "
            f"Check the variable name after the colon in --app {app!r}."
        )
    resolved = getattr(mod, variable)
    if resolved is None:
        raise ValueError(
            f"Variable '{variable}' resolved to None in --app {app!r}; expected a "
            "FunctionApp object for endpoint-metadata discovery."
        )
    return resolved, True


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Azure Functions OpenAPI CLI Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate OpenAPI spec (registry populated at runtime — no --app needed
  # when this command runs inside the same process that loaded your app)
  azure-functions-openapi generate --title "My API" --version "1.0.0"

  # Import your function app module so @openapi decorators are registered
  azure-functions-openapi generate --app function_app --title "My API"

  # module:variable format: module is imported, variable existence is validated
  azure-functions-openapi generate --app function_app:app --title "My API"

  # Generate and save to file
  azure-functions-openapi generate --output openapi.json --format json
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Generate command
    generate_parser = subparsers.add_parser("generate", help="Generate OpenAPI specification")
    generate_parser.add_argument(
        "--app",
        metavar="MODULE[:VARIABLE]",
        help=(
            "Python module to import before generating the spec "
            "(e.g. 'function_app' or 'function_app:app'). "
            "Importing the module executes @openapi decorators so that "
            "all routes are visible to the generator."
        ),
    )
    generate_parser.add_argument("--title", default="API", help="API title (default: API)")
    generate_parser.add_argument("--version", default="1.0.0", help="API version (default: 1.0.0)")
    generate_parser.add_argument(
        "--description",
        default=None,
        help=(
            "API description placed in info.description (Markdown supported, "
            "CommonMark). When omitted, the library default is used."
        ),
    )
    generate_parser.add_argument("--output", "-o", help="Output file path")
    generate_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "yaml"],
        default="json",
        help="Output format (default: json)",
    )
    generate_parser.add_argument("--pretty", "-p", action="store_true", help="Pretty print output")
    generate_parser.add_argument(
        "--fail-on-empty-paths",
        action="store_true",
        default=False,
        help="Exit with code 1 if the generated spec contains no paths.",
    )
    generate_parser.add_argument(
        "--openapi-version",
        choices=["3.0", "3.1"],
        default="3.1",
        help="OpenAPI version (default: 3.1)",
    )
    generate_parser.add_argument(
        "--route-prefix",
        default="/api",
        help=(
            "HTTP route prefix from host.json extensions.http.routePrefix "
            "(default: /api). Pass an empty string for hosts that disable "
            "the prefix, or a custom value such as /v1 for a custom deployment."
        ),
    )
    generate_parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help=(
            "Fail on any malformed registry entry instead of skipping it. "
            "Recommended for CI pipelines where a missing path should break the build."
        ),
    )
    generate_parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        default=False,
        help=(
            "Exit with code 2 if the generator emits any structured warnings "
            "(version skew, namespace fallback, or spec-validation issues). "
            "Use in CI to stop a wrong-but-plausible spec from being published."
        ),
    )
    generate_parser.add_argument(
        "--isolate-app",
        action="store_true",
        default=False,
        help=(
            "Scan the --app FunctionApp into a fresh, app-scoped registry "
            "instead of the shared global one. Requires --app 'module:variable'. "
            "Use when several apps are imported in one process to keep each "
            "spec limited to its own routes and avoid cross-app leakage."
        ),
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "generate":
            return handle_generate(args)
        else:
            print(f"Unknown command: {args.command}")
            return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def handle_generate(args: argparse.Namespace) -> int:
    """Handle generate command."""
    try:
        # An app-scoped registry keeps a --isolate-app run limited to the routes
        # of the given FunctionApp, avoiding cross-app leakage when several apps
        # are imported in one process. Left None for the default shared-global flow.
        active_registry: OpenAPIRegistry | None = None
        isolate = getattr(args, "isolate_app", False) is True
        # Fail closed: an explicit --isolate-app that cannot be honored must not
        # silently produce a non-isolated spec with a success exit code (#391).
        if isolate and not getattr(args, "app", None):
            print(
                "Error: --isolate-app requires --app 'module:variable' to scope "
                "the spec to a single FunctionApp, but no --app was given.",
                file=sys.stderr,
            )
            return 1
        # Import user module first so @openapi decorators populate the registry.
        # When an explicit ``module:variable`` is given, resolve the FunctionApp
        # object and run endpoint-metadata discovery so producers that register
        # only via the ``endpoint`` namespace (e.g. @validate_http) are included.
        if getattr(args, "app", None):
            try:
                resolved_app, variable_given = _import_app_module(args.app)
            except (ImportError, ValueError, AttributeError) as e:
                print(
                    f"Error: Could not import module from --app {args.app!r}: {e}",
                    file=sys.stderr,
                )
                return 1

            if variable_given and resolved_app is not None:
                if isolate:
                    active_registry = OpenAPIRegistry()
                # One-shot discovery through the #325 adapter. `build()` is
                # idempotent; we never call the non-idempotent `get_functions()`.
                scan_endpoint_metadata(
                    resolved_app,
                    route_prefix=getattr(args, "route_prefix", "/api"),
                    registry=active_registry,
                )
            else:
                if isolate:
                    # Fail closed: honoring --isolate-app is impossible without a
                    # resolvable FunctionApp variable, and silently falling back
                    # to the shared global registry would emit a non-isolated
                    # spec with a success exit code (#391).
                    print(
                        "Error: --isolate-app cannot be honored — it requires "
                        f"--app 'module:variable', but {args.app!r} has no "
                        "':variable'. Refusing to fall back to the shared global "
                        "registry (pass e.g. 'function_app:app').",
                        file=sys.stderr,
                    )
                    return 1
                print(
                    "Note: metadata discovery skipped — no ':variable' given in "
                    f"--app {args.app!r}. Only @openapi-decorated routes were "
                    "registered on import. Pass 'module:variable' (e.g. "
                    "function_app:app) to also discover endpoint-metadata routes.",
                    file=sys.stderr,
                )

        openapi_version = (
            OPENAPI_VERSION_3_1 if args.openapi_version == "3.1" else OPENAPI_VERSION_3_0
        )

        description = getattr(args, "description", None)
        if not isinstance(description, str):
            description = DEFAULT_OPENAPI_INFO_DESCRIPTION

        spec = generate_openapi_spec(
            args.title,
            args.version,
            openapi_version,
            description=description,
            route_prefix=getattr(args, "route_prefix", "/api"),
            strict=getattr(args, "strict", False),
            registry=active_registry,
        )
        warnings = collect_spec_warnings(spec, registry=active_registry)
        # Surface structured warnings (version skew / namespace fallback /
        # spec-validation) as JSON lines on stderr so CI can parse them, and
        # gate the exit code on them when --fail-on-warnings is set.
        if warnings:
            import json as _json

            for warning in warnings:
                print(
                    _json.dumps(warning.to_dict(), ensure_ascii=False),
                    file=sys.stderr,
                )
        # Check for empty paths before serialising — gives a clear signal
        # instead of silently producing a spec with no routes.
        if not spec.get("paths"):
            hint = (
                "Hint: your function app imported cleanly but exposes no "
                "@openapi-decorated routes, so there is nothing to document."
                if getattr(args, "app", None)
                else (
                    "Hint: use --app <module> to import your function app before "
                    "generating (e.g. --app function_app or --app function_app:app)."
                )
            )
            print(
                "Warning: No routes found in the OpenAPI registry. "
                "The generated spec contains no paths.\n" + hint,
                file=sys.stderr,
            )
            if getattr(args, "fail_on_empty_paths", False) is True:
                return 1

        # --fail-on-warnings gate: short-circuit BEFORE writing any artifact,
        # so a wrong-but-plausible spec is never emitted (warnings were already
        # surfaced to stderr above for CI to parse). Placed AFTER the empty-paths
        # block so its diagnostic hint still prints and --fail-on-empty-paths
        # (exit 1) stays reachable when warnings and empty paths coincide.
        if getattr(args, "fail_on_warnings", False) is True and warnings:
            return 2

        if args.format == "json":
            import json

            indent = 2 if getattr(args, "pretty", False) else None
            content = json.dumps(spec, indent=indent, ensure_ascii=False)
        else:
            import yaml

            content = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(content, encoding="utf-8")
            print(f"OpenAPI specification written to {output_path}")
        else:
            print(content)

        return 0
    except OpenAPISpecConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Failed to generate OpenAPI specification: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
