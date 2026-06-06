"""Webhook receiver example — representative use of @openapi.

Demonstrates:
- @openapi() with summary, description, tags, request_model, response_model, response
- get_openapi_json(), get_openapi_yaml()
- render_swagger_ui()
- Practical pattern: accept inbound webhook events and return 202 Accepted
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from typing import Any
import uuid

import azure.functions as func
from pydantic import BaseModel, Field

from azure_functions_openapi import get_openapi_json, get_openapi_yaml
from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.swagger_ui import render_swagger_ui

app = func.FunctionApp()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class WebhookEvent(BaseModel):
    event_type: str = Field(..., description="Event type, e.g. 'order.completed'.")
    source: str = Field(..., description="Origin system, e.g. 'shopify'.")
    occurred_at: str = Field(..., description="ISO-8601 timestamp of event occurrence.")
    data: dict[str, Any] = Field(default_factory=dict, description="Arbitrary event payload.")


class WebhookAcceptedResponse(BaseModel):
    delivery_id: str = Field(..., description="Unique delivery identifier.")
    status: str = Field(default="accepted", description="Processing status.")
    received_at: str = Field(..., description="ISO-8601 timestamp of receipt.")


# ---------------------------------------------------------------------------
# In-memory store (demo only)
# ---------------------------------------------------------------------------

_recent_deliveries: list[dict[str, Any]] = []
_seen_delivery_ids: set[str] = set()

# Maximum age (seconds) for webhook timestamp before rejection
_MAX_WEBHOOK_AGE_SECONDS = 300  # 5 minutes


def _verify_signature(payload: bytes, timestamp: str, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature bound to timestamp."""
    signed_content = f"{timestamp}.{payload.decode()}".encode()
    expected = "sha256=" + hmac.new(secret.encode(), signed_content, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@openapi(
    route="/api/webhooks/orders",
    method="post",
    summary="Receive order webhook",
    description=(
        "Accepts an inbound webhook event for asynchronous processing.\n\n"
        "If `WEBHOOK_SECRET` is set, the `X-Signature` header is verified "
        "using HMAC-SHA256 (bound to `X-Webhook-Timestamp`) before the "
        "payload is accepted. Stale timestamps (>5 min) are rejected.\n\n"
        "Duplicate deliveries are rejected via the `X-Delivery-Id` header."
    ),
    tags=["webhooks"],
    request_model=WebhookEvent,
    response_model=WebhookAcceptedResponse,
    response={
        202: {"description": "Webhook accepted for processing"},
        400: {"description": "Invalid request payload"},
        401: {"description": "Invalid webhook signature or expired timestamp"},
        409: {"description": "Duplicate delivery (replay)"},
    },
    )
@app.route(route="webhooks/orders", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def receive_order_webhook(req: func.HttpRequest) -> func.HttpResponse:
    # --- Replay protection: delivery ID deduplication ---
    delivery_header_id = req.headers.get("X-Delivery-Id", "")
    if delivery_header_id and delivery_header_id in _seen_delivery_ids:
        logger.warning("Duplicate delivery ID rejected: %s", delivery_header_id)
        return func.HttpResponse(
            body=json.dumps({"error": "Duplicate delivery"}),
            mimetype="application/json",
            status_code=409,
        )

    # --- Signature verification ---
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if secret:
        sig = req.headers.get("X-Signature", "")
        timestamp = req.headers.get("X-Webhook-Timestamp", "")

        # Reject missing timestamp when signature verification is enabled
        if not timestamp:
            return func.HttpResponse(
                body=json.dumps({"error": "Missing X-Webhook-Timestamp header"}),
                mimetype="application/json",
                status_code=401,
            )

        # Reject stale webhooks
        try:
            ts = datetime.fromisoformat(timestamp)
            if ts.tzinfo is None:
                return func.HttpResponse(
                    body=json.dumps({"error": "X-Webhook-Timestamp must include timezone"}),
                    mimetype="application/json",
                    status_code=401,
                )
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if abs(age) > _MAX_WEBHOOK_AGE_SECONDS:
                logger.warning("Webhook timestamp too old: %s (age=%.0fs)", timestamp, age)
                return func.HttpResponse(
                    body=json.dumps({"error": "Webhook timestamp expired"}),
                    mimetype="application/json",
                    status_code=401,
                )
        except ValueError:
            return func.HttpResponse(
                body=json.dumps({"error": "Invalid X-Webhook-Timestamp format"}),
                mimetype="application/json",
                status_code=401,
            )

        if not _verify_signature(req.get_body(), timestamp, sig, secret):
            logger.warning("Webhook signature verification failed")
            return func.HttpResponse(
                body=json.dumps({"error": "Invalid signature"}),
                mimetype="application/json",
                status_code=401,
            )
    # --- Parse body ---
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            body=json.dumps({"error": "Invalid JSON body"}),
            mimetype="application/json",
            status_code=400,
        )

    if not isinstance(body, dict):
        return func.HttpResponse(
            body=json.dumps({"error": "Request body must be a JSON object"}),
            mimetype="application/json",
            status_code=400,
        )

    event_type = body.get("event_type", "")
    source = body.get("source", "")
    if not event_type or not source:
        return func.HttpResponse(
            body=json.dumps({"error": "event_type and source are required"}),
            mimetype="application/json",
            status_code=400,
        )

    logger.info("Received webhook: event_type=%s source=%s", event_type, source)

    # Track delivery ID for deduplication
    if delivery_header_id:
        _seen_delivery_ids.add(delivery_header_id)

    entry = {
        "delivery_id": f"dlv_{uuid.uuid4().hex[:12]}",
        "status": "accepted",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    _recent_deliveries.append(entry)

    return func.HttpResponse(
        body=json.dumps(entry),
        mimetype="application/json",
        status_code=202,
    )


# ---------------------------------------------------------------------------
# OpenAPI / Swagger UI routes
# ---------------------------------------------------------------------------


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_spec")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="Webhook Receiver API"),
        mimetype="application/json",
    )


@app.route(route="openapi.yaml", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_yaml_spec")
def openapi_yaml_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_yaml(title="Webhook Receiver API"),
        mimetype="application/x-yaml",
    )


@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="swagger_ui")
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(title="Webhook Receiver API")
