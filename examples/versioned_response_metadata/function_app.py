"""Versioned response metadata example — response media types and headers.

Demonstrates:
- a ``version: 2`` endpoint metadata payload attached to a handler
- a versioned vendor media type (``application/vnd.example.v2+json``) on ``201``
- documented ``Location`` and ``ETag`` response headers
- ``scan_endpoint_metadata(app)`` compiling the payload into the OpenAPI operation
- documented headers vs headers the handler really emits (the library never adds them)
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any, TypeVar

import azure.functions as func
from pydantic import BaseModel, Field

from azure_functions_openapi import get_openapi_json, scan_endpoint_metadata
from azure_functions_openapi.swagger_ui import render_swagger_ui

app = func.FunctionApp()

F = TypeVar("F", bound=Callable[..., Any])

INVOICE_MEDIA_TYPE = "application/vnd.example.v2+json"


class Invoice(BaseModel):
    invoice_id: str = Field(..., description="Invoice identifier.")
    total_cents: int = Field(..., description="Invoice total in cents.")


# The producer convention is a plain dict under ``_azure_functions_metadata``;
# it does not import azure-functions-openapi (see docs/extending/producer-guide.md).
ENDPOINT_METADATA: dict[str, Any] = {
    "version": 2,
    "request_body": {
        "type": "object",
        "properties": {"total_cents": {"type": "integer"}},
        "required": ["total_cents"],
    },
    "request_body_required": True,
    "responses": {
        "201": {
            "description": "Invoice created",
            "content": {INVOICE_MEDIA_TYPE: {"schema": Invoice.model_json_schema()}},
            "headers": {
                "Location": {
                    "description": "URL of the created invoice.",
                    "schema": {"type": "string"},
                },
                "ETag": {"description": "Entity tag of the invoice.", "schema": {"type": "string"}},
            },
        },
        "400": {
            "description": "Invalid request",
            "content": {"application/problem+json": {"schema": {"type": "object"}}},
        },
    },
}


def with_endpoint_metadata(payload: dict[str, Any]) -> Callable[[F], F]:
    """Attach the producer metadata; apply it *below* ``@app.route``."""

    def decorate(func_: F) -> F:
        setattr(func_, "_azure_functions_metadata", {"endpoint": payload})
        return func_

    return decorate


@app.function_name(name="create_invoice")
@app.route(route="invoices", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@with_endpoint_metadata(ENDPOINT_METADATA)
def create_invoice(req: func.HttpRequest) -> func.HttpResponse:
    try:
        total_cents = int(req.get_json()["total_cents"])
    except (ValueError, KeyError, TypeError):
        return func.HttpResponse(
            json.dumps({"title": "Invalid request", "status": 400}),
            mimetype="application/problem+json",
            status_code=400,
        )
    invoice = Invoice(invoice_id="inv_1", total_cents=total_cents)
    # The OpenAPI headers above are documentation only. The handler must set
    # the real response headers itself.
    return func.HttpResponse(
        invoice.model_dump_json(),
        mimetype=INVOICE_MEDIA_TYPE,
        status_code=201,
        headers={"Location": "/api/invoices/inv_1", "ETag": '"v1"'},
    )


scan_endpoint_metadata(app)


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_spec")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="Versioned Response Metadata API"), mimetype="application/json"
    )


@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="swagger_ui")
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(title="Versioned Response Metadata API")
