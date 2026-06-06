"""Notification request example — @openapi + @validate_http integration.

Demonstrates:
- @openapi() and @validate_http() stacked on the same handler
- Pydantic models shared between validation and OpenAPI spec
- requests= and responses= unified parameters
- Practical pattern: validate notification request and queue for delivery
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import uuid

import azure.functions as func
from azure_functions_validation import validate_http
from pydantic import BaseModel, Field

from azure_functions_openapi import get_openapi_json, get_openapi_yaml
from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.swagger_ui import render_swagger_ui

app = func.FunctionApp()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models (shared between @openapi and @validate_http)
# ---------------------------------------------------------------------------


class EmailNotificationRequest(BaseModel):
    to: list[str] = Field(..., min_length=1, description="Recipient email addresses.")
    subject: str = Field(..., min_length=1, max_length=200, description="Email subject line.")
    body_text: str = Field(..., description="Plain-text email body.")
    body_html: str | None = Field(default=None, description="Optional HTML email body.")
    priority: str = Field(default="normal", description="Priority: low, normal, high.")


class NotificationAcceptedResponse(BaseModel):
    notification_id: str = Field(..., description="Unique notification identifier.")
    status: str = Field(default="queued", description="Processing status.")
    queued_at: str = Field(..., description="ISO-8601 timestamp.")


class NotificationStatusQuery(BaseModel):
    notification_id: str = Field(..., description="Notification ID to look up.")


class NotificationStatusResponse(BaseModel):
    notification_id: str
    status: str = Field(..., description="One of: queued, sending, delivered, failed.")
    delivered_at: str | None = Field(default=None, description="Delivery timestamp.")


# ---------------------------------------------------------------------------
# In-memory store (demo only)
# ---------------------------------------------------------------------------

_notifications: dict[str, dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.function_name(name="send_notification")
@openapi(
    route="/api/notifications/email",
    method="post",
    summary="Send email notification",
    description="Validate and queue an email notification for delivery.",
    tags=["notifications"],
    requests=EmailNotificationRequest,
    response_model=NotificationAcceptedResponse,
    response={
        202: {"description": "Notification queued for delivery"},
        422: {"description": "Validation error"},
    },
    )
@app.route(route="notifications/email", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@validate_http(body=EmailNotificationRequest, response_model=NotificationAcceptedResponse)
def send_notification(req: func.HttpRequest, body: EmailNotificationRequest) -> func.HttpResponse:
    logger.info("Queuing email notification to %d recipients", len(body.to))

    notification_id = f"ntf_{uuid.uuid4().hex[:12]}"
    entry = {
        "notification_id": notification_id,
        "status": "queued",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    _notifications[notification_id] = entry

    result = NotificationAcceptedResponse(**entry)
    return func.HttpResponse(
        body=result.model_dump_json(),
        mimetype="application/json",
        status_code=202,
    )


@app.function_name(name="get_notification_status")
@openapi(
    route="/api/notifications/status",
    method="get",
    summary="Get notification status",
    description="Look up the delivery status of a previously queued notification.",
    tags=["notifications"],
    parameters=[
        {
            "name": "notification_id",
            "in": "query",
            "required": True,
            "description": "Notification ID returned from the send endpoint.",
            "schema": {"type": "string"},
        }
    ],
    response_model=NotificationStatusResponse,
    response={
        200: {"description": "Notification status"},
        404: {"description": "Notification not found"},
    },
    )
@app.route(route="notifications/status", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
@validate_http(query=NotificationStatusQuery, response_model=NotificationStatusResponse)
def get_notification_status(
    req: func.HttpRequest, query: NotificationStatusQuery
) -> NotificationStatusResponse | func.HttpResponse:
    entry = _notifications.get(query.notification_id)
    if not entry:
        return func.HttpResponse(
            '{"error": "Not found"}', mimetype="application/json", status_code=404
        )

    return NotificationStatusResponse(
        notification_id=entry["notification_id"],
        status=entry["status"],
        delivered_at=entry.get("delivered_at"),
    )


# ---------------------------------------------------------------------------
# OpenAPI / Swagger UI routes
# ---------------------------------------------------------------------------


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_spec")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="Notification API"),
        mimetype="application/json",
    )


@app.route(route="openapi.yaml", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_yaml_spec")
def openapi_yaml_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_yaml(title="Notification API"),
        mimetype="application/x-yaml",
    )


@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="swagger_ui")
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(title="Notification API")
