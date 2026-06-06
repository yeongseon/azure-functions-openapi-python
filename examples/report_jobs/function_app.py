"""Report jobs example — complex async job pattern with security.

Demonstrates:
- @openapi() with security, security_scheme (Bearer token)
- Multiple routes with path parameters
- request_body_required
- generate_openapi_spec()
- render_swagger_ui() with custom_csp, enable_client_logging
- Practical pattern: submit report → poll status → download result
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
import logging
from typing import Any
import uuid

import azure.functions as func
from pydantic import BaseModel, Field

from azure_functions_openapi import (
    OPENAPI_VERSION_3_1,
    generate_openapi_spec,
    get_openapi_json,
)
from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.swagger_ui import render_swagger_ui

app = func.FunctionApp()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ReportFormat(str, Enum):
    csv = "csv"
    pdf = "pdf"
    xlsx = "xlsx"


class ReportRequest(BaseModel):
    report_type: str = Field(..., description="Report type, e.g. 'monthly_sales'.")
    date_from: str = Field(..., description="Start date (ISO-8601).")
    date_to: str = Field(..., description="End date (ISO-8601).")
    format: ReportFormat = Field(default=ReportFormat.csv, description="Output format.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional filters.")


class ReportJobResponse(BaseModel):
    job_id: str = Field(..., description="Unique job identifier.")
    status: str = Field(default="queued", description="Job status.")
    created_at: str = Field(..., description="ISO-8601 timestamp.")


class ReportStatusResponse(BaseModel):
    job_id: str
    status: str = Field(..., description="One of: queued, processing, completed, failed.")
    progress_pct: int = Field(default=0, description="Progress percentage (0-100).")
    download_url: str | None = Field(default=None, description="Available when status=completed.")
    error: str | None = Field(default=None, description="Error message when status=failed.")


# ---------------------------------------------------------------------------
# In-memory store (demo only)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict[str, Any]] = {}

_BEARER_SCHEME = {
    "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "API key or JWT token",
    }
}
_BEARER_SECURITY = [{"BearerAuth": []}]


def _check_bearer_auth(req: func.HttpRequest) -> func.HttpResponse | None:
    """Validate Bearer token from the Authorization header.

    Returns an error response if the token is missing or malformed.
    In production, replace the token check with JWT verification or
    a lookup against your auth provider.
    """
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return func.HttpResponse(
            json.dumps({"error": "Missing or invalid Authorization header"}),
            mimetype="application/json",
            status_code=401,
        )
    token = auth_header[len("Bearer ") :]
    if not token:
        return func.HttpResponse(
            json.dumps({"error": "Empty bearer token"}),
            mimetype="application/json",
            status_code=401,
        )
    # In production: verify JWT signature, expiry, audience, etc.
    logger.info("Authenticated request with bearer token")
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@openapi(
    route="/api/reports",
    method="post",
    summary="Submit a report job",
    description="Queue a new report generation job. Returns a job ID for status polling.",
    tags=["reports"],
    request_model=ReportRequest,
    response_model=ReportJobResponse,
    response={
        202: {"description": "Report job queued"},
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
    },
    security=_BEARER_SECURITY,
    security_scheme=_BEARER_SCHEME,
    )
@app.route(route="reports", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_report(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _check_bearer_auth(req)
    if auth_error:
        return auth_error
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}), mimetype="application/json", status_code=400
        )

    job_id = f"rpt_{uuid.uuid4().hex[:12]}"
    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request": body,
        "progress_pct": 0,
        "download_url": None,
        "error": None,
    }
    _jobs[job_id] = job
    logger.info("Report job queued: %s", job_id)

    return func.HttpResponse(
        json.dumps({"job_id": job_id, "status": "queued", "created_at": job["created_at"]}),
        mimetype="application/json",
        status_code=202,
    )


@openapi(
    route="/api/reports/{job_id}/status",
    method="get",
    summary="Get report job status",
    description="Poll the status of a previously submitted report job.",
    tags=["reports"],
    parameters=[
        {
            "name": "job_id",
            "in": "path",
            "required": True,
            "description": "The report job identifier.",
            "schema": {"type": "string"},
        }
    ],
    response_model=ReportStatusResponse,
    response={
        200: {"description": "Job status"},
        401: {"description": "Unauthorized"},
        404: {"description": "Job not found"},
    },
    security=_BEARER_SECURITY,
    security_scheme=_BEARER_SCHEME,
    )
@app.route(route="reports/{job_id}/status", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_report_status(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _check_bearer_auth(req)
    if auth_error:
        return auth_error
    job_id = req.route_params.get("job_id", "")
    job = _jobs.get(job_id)
    if not job:
        return func.HttpResponse(
            json.dumps({"error": "Job not found"}), mimetype="application/json", status_code=404
        )

    return func.HttpResponse(
        json.dumps(
            {
                "job_id": job["job_id"],
                "status": job["status"],
                "progress_pct": job["progress_pct"],
                "download_url": job["download_url"],
                "error": job["error"],
            }
        ),
        mimetype="application/json",
        status_code=200,
    )


@openapi(
    route="/api/reports/{job_id}/download",
    method="get",
    summary="Download report",
    description=(
        "Download the generated report file. Only available when job status is 'completed'."
    ),
    tags=["reports"],
    parameters=[
        {
            "name": "job_id",
            "in": "path",
            "required": True,
            "description": "The report job identifier.",
            "schema": {"type": "string"},
        }
    ],
    response={
        200: {"description": "Report file contents"},
        401: {"description": "Unauthorized"},
        404: {"description": "Job not found or not completed"},
    },
    security=_BEARER_SECURITY,
    security_scheme=_BEARER_SCHEME,
)
@app.route(route="reports/{job_id}/download", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def download_report(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _check_bearer_auth(req)
    if auth_error:
        return auth_error
    job_id = req.route_params.get("job_id", "")
    job = _jobs.get(job_id)
    if not job or job["status"] != "completed":
        return func.HttpResponse(
            json.dumps({"error": "Report not available"}),
            mimetype="application/json",
            status_code=404,
        )

    # In production: return actual file from blob storage
    return func.HttpResponse(
        body="report_type,date_from,date_to\nmonthly_sales,2026-01-01,2026-01-31\n",
        mimetype="text/csv",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# OpenAPI / Swagger UI routes
# ---------------------------------------------------------------------------


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_spec")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="Report Jobs API", version="1.0.0"),
        mimetype="application/json",
    )


@app.route(route="openapi.yaml", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_yaml_spec")
def openapi_yaml_spec(req: func.HttpRequest) -> func.HttpResponse:
    spec = generate_openapi_spec(
        title="Report Jobs API",
        version="1.0.0",
        openapi_version=OPENAPI_VERSION_3_1,
    )
    import yaml  # type: ignore[import-untyped]

    return func.HttpResponse(
        yaml.dump(spec, default_flow_style=False, sort_keys=False),
        mimetype="application/x-yaml",
    )


@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="swagger_ui")
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(
        title="Report Jobs API",
        custom_csp=(
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self'"
        ),
        enable_client_logging=True,
    )
