# tests/test_notification_request_example.py
# (file kept as test_with_validation_example.py so CI mapping stays stable)

import importlib
import json
from typing import Any

import azure.functions as func
import pytest

try:
    import azure_functions_openapi.decorator as decorator_module
    from examples.notification_request import function_app as notification_function_app

    HAS_VALIDATION = True
except ImportError:
    HAS_VALIDATION = False

pytestmark = pytest.mark.skipif(
    not HAS_VALIDATION,
    reason="azure-functions-validation not installed",
)


def _load_example_module() -> Any:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    return importlib.reload(notification_function_app)


def test_send_notification_valid() -> None:
    fa = _load_example_module()
    payload = {
        "to": ["user@example.com"],
        "subject": "Test notification",
        "body_text": "Hello, this is a test.",
        "priority": "high",
    }
    req = func.HttpRequest(
        method="POST",
        url="/api/notifications/email",
        body=json.dumps(payload).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )

    resp = fa.send_notification(req)

    assert resp.status_code == 202
    body = json.loads(resp.get_body())
    assert body["status"] == "queued"
    assert "notification_id" in body
    assert "queued_at" in body


def test_send_notification_invalid_body() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="POST",
        url="/api/notifications/email",
        body=json.dumps({"to": []}).encode("utf-8"),  # empty to list
        params={},
        headers={"Content-Type": "application/json"},
    )

    resp = fa.send_notification(req)

    assert resp.status_code == 422
    body = json.loads(resp.get_body())
    assert "detail" in body


def test_send_notification_no_body() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="POST",
        url="/api/notifications/email",
        body=b"",
        params={},
        headers={},
    )

    resp = fa.send_notification(req)

    assert resp.status_code in (400, 422)


def test_get_notification_status_found() -> None:
    fa = _load_example_module()
    # Send a notification first
    send_req = func.HttpRequest(
        method="POST",
        url="/api/notifications/email",
        body=json.dumps(
            {
                "to": ["user@example.com"],
                "subject": "Test",
                "body_text": "Hello",
            }
        ).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )
    send_resp = fa.send_notification(send_req)
    notification_id = json.loads(send_resp.get_body())["notification_id"]

    # Look up status
    status_req = func.HttpRequest(
        method="GET",
        url="/api/notifications/status",
        body=b"",
        params={"notification_id": notification_id},
        headers={},
    )
    status_resp = fa.get_notification_status(status_req)

    assert status_resp.status_code == 200
    body = json.loads(status_resp.get_body())
    assert body["notification_id"] == notification_id
    assert body["status"] == "queued"


def test_get_notification_status_not_found() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="GET",
        url="/api/notifications/status",
        body=b"",
        params={"notification_id": "ntf_nonexistent"},
        headers={},
    )

    resp = fa.get_notification_status(req)

    assert resp.status_code == 404


def test_openapi_spec_includes_notification_paths() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="GET",
        url="/api/openapi.json",
        body=b"",
        params={},
        headers={},
    )

    resp = fa.openapi_spec(req)

    assert resp.status_code == 200
    payload = json.loads(resp.get_body())
    assert "/api/notifications/email" in payload["paths"]
