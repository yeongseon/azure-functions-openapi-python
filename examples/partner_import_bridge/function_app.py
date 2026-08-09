"""Partner import bridge example — bridge pattern with register_openapi_metadata.

Demonstrates:
- register_openapi_metadata() for dynamically registered routes
- OpenAPIOperationMetadata dataclass
- scan_endpoint_metadata(app) bridge integration
- request_body_required parameter
- Practical pattern: partner data import with batch processing
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any
import uuid

import azure.functions as func
from azure_functions_validation import validate_http
from pydantic import BaseModel, Field

from azure_functions_openapi import (
    OpenAPIOperationMetadata,
    get_openapi_json,
    register_openapi_metadata,
    scan_endpoint_metadata,
)
from azure_functions_openapi.swagger_ui import render_swagger_ui

app = func.FunctionApp()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PartnerRecord(BaseModel):
    partner_id: str = Field(..., description="External partner identifier.")
    name: str = Field(..., description="Partner display name.")
    data: dict[str, Any] = Field(default_factory=dict, description="Arbitrary partner data.")


class ImportBatchRequest(BaseModel):
    source: str = Field(..., description="Import source system identifier.")
    records: list[PartnerRecord] = Field(..., min_length=1, description="Records to import.")
    dry_run: bool = Field(default=False, description="If true, validate without persisting.")


class ImportBatchResponse(BaseModel):
    batch_id: str = Field(..., description="Unique batch identifier.")
    imported: int = Field(..., description="Number of records imported.")
    skipped: int = Field(default=0, description="Number of records skipped (duplicates).")
    status: str = Field(default="completed", description="Batch status.")
    created_at: str = Field(..., description="ISO-8601 timestamp.")


class ImportHistoryResponse(BaseModel):
    batch_id: str
    source: str
    record_count: int
    status: str
    created_at: str


# ---------------------------------------------------------------------------
# In-memory store (demo only)
# ---------------------------------------------------------------------------

_import_history: list[dict[str, Any]] = []
_partner_records: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Routes (decorated with @validate_http — bridge auto-registers OpenAPI)
# ---------------------------------------------------------------------------


@app.function_name(name="import_partners")
@app.route(route="partners/import", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@validate_http(body=ImportBatchRequest, response_model=ImportBatchResponse)
def import_partners(req: func.HttpRequest, body: ImportBatchRequest) -> ImportBatchResponse:
    logger.info("Importing %d partner records from %s", len(body.records), body.source)

    imported = 0
    skipped = 0
    for record in body.records:
        if record.partner_id in _partner_records and not body.dry_run:
            skipped += 1
            continue
        if not body.dry_run:
            _partner_records[record.partner_id] = record.model_dump()
        imported += 1

    batch_id = f"imp_{uuid.uuid4().hex[:12]}"
    entry = {
        "batch_id": batch_id,
        "source": body.source,
        "record_count": len(body.records),
        "imported": imported,
        "skipped": skipped,
        "status": "dry_run" if body.dry_run else "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _import_history.append(entry)

    return ImportBatchResponse(
        batch_id=batch_id,
        imported=imported,
        skipped=skipped,
        status=entry["status"],
        created_at=entry["created_at"],
    )


@app.function_name(name="import_history")
@app.route(route="partners/import/history", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_import_history(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(_import_history),
        mimetype="application/json",
        status_code=200,
    )


@app.function_name(name="purge_partners")
@app.route(route="partners/purge", methods=["DELETE"], auth_level=func.AuthLevel.ANONYMOUS)
def purge_partners(req: func.HttpRequest) -> func.HttpResponse:
    """Remove all imported partner records."""
    api_key = req.headers.get("X-API-Key", "")
    if not api_key:
        return func.HttpResponse(
            json.dumps({"error": "Missing X-API-Key header"}),
            mimetype="application/json",
            status_code=401,
        )

    count = len(_partner_records)
    _partner_records.clear()
    logger.info("Purged %d partner records", count)

    return func.HttpResponse(
        json.dumps({"purged": count, "status": "completed"}),
        mimetype="application/json",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Bridge: auto-register OpenAPI metadata from @validate_http decorators
# When azure-functions-validation exposes handler metadata,
# scan_endpoint_metadata(app) picks it up automatically. For versions
# that do not yet export metadata, register manually below.
# ---------------------------------------------------------------------------

scan_endpoint_metadata(app)


# ---------------------------------------------------------------------------
# Programmatic metadata registration
# ---------------------------------------------------------------------------

# Register the import endpoint (uses @validate_http with Pydantic models)
register_openapi_metadata(
    path="/api/partners/import",
    method="POST",
    summary="Import partner records",
    description="Batch import partner records from an external source.",
    tags=["partners"],
    request_model=ImportBatchRequest,
    response_model=ImportBatchResponse,
    response={200: {"description": "Import completed"}},
)

# Register the history endpoint that doesn't use @validate_http
register_openapi_metadata(
    path="/api/partners/import/history",
    method="GET",
    summary="Get import history",
    description="Retrieve the history of all partner import batches.",
    tags=["partners"],
    response={200: {"description": "List of import batches"}},
)

# Demonstrate OpenAPIOperationMetadata as a structured alternative
_bulk_delete_meta = OpenAPIOperationMetadata(
    path="/api/partners/purge",
    method="DELETE",
    summary="Purge all partner data",
    description="Remove all imported partner records. Use with caution.",
    tags=["partners"],
    request_body_required=False,
    response={
        200: {"description": "All records purged"},
        401: {"description": "Unauthorized"},
    },
    security=[{"ApiKeyAuth": []}],
    security_scheme={
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
    },
)
register_openapi_metadata(**vars(_bulk_delete_meta))


# ---------------------------------------------------------------------------
# OpenAPI / Swagger UI routes
# ---------------------------------------------------------------------------


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_spec")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="Partner Import API"),
        mimetype="application/json",
    )


@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="swagger_ui")
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(title="Partner Import API")
