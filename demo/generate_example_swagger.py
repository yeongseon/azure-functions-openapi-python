"""Generate a self-contained Swagger UI HTML page from any examples/* module.

Usage:
    hatch run python demo/generate_example_swagger.py \
        --example webhook_receiver \
        --title "Webhook Receiver API" \
        --output-dir demo/.preview/webhook_receiver

The script clears the OpenAPI registry, imports the example module (which
registers all @openapi decorators via side-effect), then writes:

    <output-dir>/openapi.json
    <output-dir>/index.html  (Swagger UI, fully expanded)

Run once per example — in a separate subprocess per example so the
process-global OpenAPI registry never leaks between runs. Do NOT call
reload() because some examples (e.g. partner_import_bridge) call
scan_validation_metadata(app) at module level — a second execution
would conflict with the first import's registrations.
"""

from __future__ import annotations

import argparse
from importlib import import_module
from pathlib import Path
import sys

from azure_functions_openapi import get_openapi_json
import azure_functions_openapi.decorator as decorator_module
from azure_functions_openapi.swagger_ui import render_swagger_ui

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _expand_swagger_ui(html: str) -> str:
    """Patch Swagger UI config to expand all operations on load.

    Raises ValueError if the expected anchor string is not found so that
    a template change is caught immediately rather than silently producing
    collapsed screenshots.
    """
    anchor = "layout: 'BaseLayout',"
    if anchor not in html:
        raise ValueError(
            f"_expand_swagger_ui: anchor {anchor!r} not found in Swagger UI template. "
            "The template may have changed — update the anchor string."
        )
    expanded_layout = (
        "layout: 'BaseLayout',\n"
        "            docExpansion: 'full',\n"
        "            defaultModelsExpandDepth: -1,\n"
        "            tryItOutEnabled: false,\n"
        "            supportedSubmitMethods: [],"
    )
    return html.replace(anchor, expanded_layout)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Swagger UI HTML from an examples/* module."
    )
    parser.add_argument(
        "--example",
        required=True,
        help="Example subdirectory name, e.g. 'webhook_receiver'",
    )
    parser.add_argument(
        "--title",
        required=True,
        help="API title to pass to get_openapi_json/yaml",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write openapi.json and index.html into",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clear the process-global registry before importing.
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()

    module_path = f"examples.{args.example}.function_app"
    import_module(module_path)

    openapi_json = get_openapi_json(title=args.title, version="1.0.0")
    swagger_response = render_swagger_ui(
        title=args.title,
        openapi_url="/openapi.json",
    )

    (output_dir / "openapi.json").write_text(openapi_json, encoding="utf-8")
    (output_dir / "index.html").write_text(
        _expand_swagger_ui(swagger_response.get_body().decode("utf-8")),
        encoding="utf-8",
    )

    print(f"[generate_example_swagger] {args.example}: wrote to {output_dir}")


if __name__ == "__main__":
    main()
