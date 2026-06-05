# src/azure_functions_openapi/cli.py
from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys

from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.spec import (
    DEFAULT_OPENAPI_INFO_DESCRIPTION,
    OPENAPI_VERSION_3_0,
    OPENAPI_VERSION_3_1,
    generate_openapi_spec,
)


def _import_app_module(app: str) -> None:
    """Import a user module to trigger @openapi decorator registration.

    Accepts either ``module_name`` or ``module_name:variable`` format.
    When the ``variable`` part is provided it is validated to exist on the
    imported module so that typos are caught early.

    Parameters:
        app: Module import path, optionally with a ``:variable`` suffix.

    Raises:
        ImportError: If the module cannot be found or fails to import.
        AttributeError: If the named variable does not exist on the module.
    """
    module_name, _, variable = app.partition(":")
    module_name = module_name.strip()
    if not module_name:
        raise ValueError(f"Invalid --app value: {app!r}. Expected 'module' or 'module:variable'.")
    mod = importlib.import_module(module_name)
    if variable:
        variable = variable.strip()
        if not hasattr(mod, variable):
            raise AttributeError(
                f"Module '{module_name}' has no attribute '{variable}'. "
                f"Check the variable name after the colon in --app {app!r}."
            )


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
        # Import user module first so @openapi decorators populate the registry.
        if getattr(args, "app", None):
            try:
                _import_app_module(args.app)
            except (ImportError, ValueError, AttributeError) as e:
                print(
                    f"Error: Could not import module from --app {args.app!r}: {e}",
                    file=sys.stderr,
                )
                return 1

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
        )
        # Check for empty paths before serialising — gives a clear signal
        # instead of silently producing a spec with no routes.
        if not spec.get("paths"):
            print(
                "Warning: No routes found in the OpenAPI registry. "
                "The generated spec contains no paths.\n"
                "Hint: use --app <module> to import your function app before generating "
                "(e.g. --app function_app or --app function_app:app).",
                file=sys.stderr,
            )
            if getattr(args, "fail_on_empty_paths", False) is True:
                return 1

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
