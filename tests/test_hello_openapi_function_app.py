# tests/test_webhook_receiver_example.py
# (file kept as test_hello_openapi_function_app.py so CI mapping stays stable)

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib
import json
from typing import Any
from unittest.mock import patch

import azure.functions as func

import azure_functions_openapi.decorator as decorator_module
from examples.webhook_receiver import function_app


def _load_example_module() -> Any:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    mod = importlib.reload(function_app)
    # Reset in-memory stores across tests
    mod._recent_deliveries.clear()
    mod._seen_delivery_ids.clear()
    return mod


def _make_signature(payload: bytes, timestamp: str, secret: str) -> str:
    signed_content = f"{timestamp}.{payload.decode()}".encode()
    return "sha256=" + hmac.new(secret.encode(), signed_content, hashlib.sha256).hexdigest()


def test_receive_webhook_valid() -> None:
    fa = _load_example_module()
    payload = {
        "event_type": "order.completed",
        "source": "shopify",
        "occurred_at": "2026-04-12T00:00:00Z",
        "data": {"order_id": "12345"},
    }
    req = func.HttpRequest(
        method="POST",
        url="/api/webhooks/orders",
        body=json.dumps(payload).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )

    resp = fa.receive_order_webhook(req)

    assert resp.status_code == 202
    body = json.loads(resp.get_body())
    assert body["status"] == "accepted"
    assert "delivery_id" in body
    assert "received_at" in body


def test_receive_webhook_invalid_json() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="POST",
        url="/api/webhooks/orders",
        body=b"not json",
        params={},
        headers={},
    )

    resp = fa.receive_order_webhook(req)

    assert resp.status_code == 400
    assert "Invalid JSON" in json.loads(resp.get_body())["error"]


def test_receive_webhook_missing_required_fields() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="POST",
        url="/api/webhooks/orders",
        body=json.dumps({"data": {}}).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )

    resp = fa.receive_order_webhook(req)

    assert resp.status_code == 400
    assert "required" in json.loads(resp.get_body())["error"]


def test_receive_webhook_non_object_body() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="POST",
        url="/api/webhooks/orders",
        body=json.dumps([1, 2, 3]).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )

    resp = fa.receive_order_webhook(req)

    assert resp.status_code == 400
    assert "JSON object" in json.loads(resp.get_body())["error"]


def test_receive_webhook_signature_valid() -> None:
    fa = _load_example_module()

    payload = json.dumps(
        {
            "event_type": "order.completed",
            "source": "shopify",
            "occurred_at": "2026-04-12T00:00:00Z",
            "data": {},
        }
    ).encode("utf-8")
    secret = "test-secret"
    timestamp = datetime.now(timezone.utc).isoformat()
    sig = _make_signature(payload, timestamp, secret)

    req = func.HttpRequest(
        method="POST",
        url="/api/webhooks/orders",
        body=payload,
        params={},
        headers={
            "Content-Type": "application/json",
            "X-Signature": sig,
            "X-Webhook-Timestamp": timestamp,
        },
    )

    with patch.dict("os.environ", {"WEBHOOK_SECRET": secret}):
        resp = fa.receive_order_webhook(req)

    assert resp.status_code == 202


def test_receive_webhook_signature_invalid() -> None:
    fa = _load_example_module()
    timestamp = datetime.now(timezone.utc).isoformat()
    req = func.HttpRequest(
        method="POST",
        url="/api/webhooks/orders",
        body=json.dumps(
            {
                "event_type": "order.completed",
                "source": "shopify",
                "occurred_at": "2026-04-12T00:00:00Z",
                "data": {},
            }
        ).encode("utf-8"),
        params={},
        headers={
            "Content-Type": "application/json",
            "X-Signature": "sha256=bad",
            "X-Webhook-Timestamp": timestamp,
        },
    )

    with patch.dict("os.environ", {"WEBHOOK_SECRET": "test-secret"}):
        resp = fa.receive_order_webhook(req)

    assert resp.status_code == 401
    assert "signature" in json.loads(resp.get_body())["error"].lower()


def test_receive_webhook_missing_timestamp() -> None:
    """When WEBHOOK_SECRET is set, X-Webhook-Timestamp is required."""
    fa = _load_example_module()
    req = func.HttpRequest(
        method="POST",
        url="/api/webhooks/orders",
        body=json.dumps(
            {
                "event_type": "order.completed",
                "source": "shopify",
                "occurred_at": "2026-04-12T00:00:00Z",
                "data": {},
            }
        ).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json", "X-Signature": "sha256=abc"},
    )

    with patch.dict("os.environ", {"WEBHOOK_SECRET": "test-secret"}):
        resp = fa.receive_order_webhook(req)

    assert resp.status_code == 401
    assert "Timestamp" in json.loads(resp.get_body())["error"]


def test_receive_webhook_stale_timestamp() -> None:
    """Webhooks older than 5 minutes are rejected."""
    fa = _load_example_module()
    secret = "test-secret"
    old_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    payload = json.dumps(
        {
            "event_type": "order.completed",
            "source": "shopify",
            "occurred_at": "2026-04-12T00:00:00Z",
            "data": {},
        }
    ).encode("utf-8")
    sig = _make_signature(payload, old_timestamp, secret)

    req = func.HttpRequest(
        method="POST",
        url="/api/webhooks/orders",
        body=payload,
        params={},
        headers={
            "Content-Type": "application/json",
            "X-Signature": sig,
            "X-Webhook-Timestamp": old_timestamp,
        },
    )

    with patch.dict("os.environ", {"WEBHOOK_SECRET": secret}):
        resp = fa.receive_order_webhook(req)

    assert resp.status_code == 401
    assert "expired" in json.loads(resp.get_body())["error"].lower()


def test_receive_webhook_naive_timestamp_rejected() -> None:
    """Timestamps without timezone info are rejected as 401."""
    fa = _load_example_module()
    secret = "test-secret"
    naive_timestamp = "2026-04-12T00:00:00"  # No timezone
    payload = json.dumps(
        {
            "event_type": "order.completed",
            "source": "shopify",
            "occurred_at": "2026-04-12T00:00:00Z",
            "data": {},
        }
    ).encode("utf-8")
    sig = _make_signature(payload, naive_timestamp, secret)

    req = func.HttpRequest(
        method="POST",
        url="/api/webhooks/orders",
        body=payload,
        params={},
        headers={
            "Content-Type": "application/json",
            "X-Signature": sig,
            "X-Webhook-Timestamp": naive_timestamp,
        },
    )

    with patch.dict("os.environ", {"WEBHOOK_SECRET": secret}):
        resp = fa.receive_order_webhook(req)

    assert resp.status_code == 401
    assert "timezone" in json.loads(resp.get_body())["error"].lower()


def test_receive_webhook_duplicate_delivery_id() -> None:
    """Duplicate X-Delivery-Id headers are rejected with 409."""
    fa = _load_example_module()
    delivery_id = "dlv-unique-123"
    payload = json.dumps(
        {
            "event_type": "order.completed",
            "source": "shopify",
            "occurred_at": "2026-04-12T00:00:00Z",
            "data": {},
        }
    ).encode("utf-8")

    def make_req() -> func.HttpRequest:
        return func.HttpRequest(
            method="POST",
            url="/api/webhooks/orders",
            body=payload,
            params={},
            headers={
                "Content-Type": "application/json",
                "X-Delivery-Id": delivery_id,
            },
        )

    # First request succeeds
    resp1 = fa.receive_order_webhook(make_req())
    assert resp1.status_code == 202

    # Second request with same delivery ID is rejected
    resp2 = fa.receive_order_webhook(make_req())
    assert resp2.status_code == 409
    assert "Duplicate" in json.loads(resp2.get_body())["error"]


def test_openapi_json_response() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(method="GET", url="/api/openapi.json", body=b"", params={}, headers={})
    resp = fa.openapi_spec(req)

    assert resp.status_code == 200
    payload = json.loads(resp.get_body())
    assert "paths" in payload
    assert "/api/webhooks/orders" in payload["paths"]


def test_openapi_yaml_response() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(method="GET", url="/api/openapi.yaml", body=b"", params={}, headers={})
    resp = fa.openapi_yaml_spec(req)

    assert resp.status_code == 200
    assert b"openapi:" in resp.get_body()
    assert b"paths:" in resp.get_body()
