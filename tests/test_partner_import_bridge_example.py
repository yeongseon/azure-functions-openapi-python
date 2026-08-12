# tests/test_partner_import_bridge_example.py

import importlib
import json
from typing import Any

import azure.functions as func
import pytest

try:
    import azure_functions_openapi.decorator as decorator_module
    from examples.partner_import_bridge import function_app as bridge_function_app

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
    mod = importlib.reload(bridge_function_app)
    # Reset in-memory stores across tests
    mod._import_history.clear()
    mod._partner_records.clear()
    return mod


def test_import_partners_valid() -> None:
    fa = _load_example_module()
    payload = {
        "source": "erp-system",
        "records": [
            {"partner_id": "P001", "name": "Acme Corp", "data": {"tier": "gold"}},
            {"partner_id": "P002", "name": "Globex Inc"},
        ],
    }
    req = func.HttpRequest(
        method="POST",
        url="/api/partners/import",
        body=json.dumps(payload).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )

    resp = fa.import_partners(req)

    assert resp.status_code == 200
    body = json.loads(resp.get_body())
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert body["status"] == "completed"
    assert "batch_id" in body


def test_import_partners_dry_run() -> None:
    fa = _load_example_module()
    payload = {
        "source": "erp-system",
        "records": [
            {"partner_id": "P001", "name": "Acme Corp"},
        ],
        "dry_run": True,
    }
    req = func.HttpRequest(
        method="POST",
        url="/api/partners/import",
        body=json.dumps(payload).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )

    resp = fa.import_partners(req)

    assert resp.status_code == 200
    body = json.loads(resp.get_body())
    assert body["status"] == "dry_run"
    assert body["imported"] == 1
    # Verify nothing was actually persisted
    assert len(fa._partner_records) == 0


def test_import_partners_duplicates_skipped() -> None:
    fa = _load_example_module()
    # Import once
    payload = {
        "source": "erp-system",
        "records": [
            {"partner_id": "P001", "name": "Acme Corp"},
        ],
    }
    req = func.HttpRequest(
        method="POST",
        url="/api/partners/import",
        body=json.dumps(payload).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )
    fa.import_partners(req)

    # Import again with same partner_id
    payload2 = {
        "source": "erp-system",
        "records": [
            {"partner_id": "P001", "name": "Acme Corp Updated"},
            {"partner_id": "P003", "name": "New Partner"},
        ],
    }
    req2 = func.HttpRequest(
        method="POST",
        url="/api/partners/import",
        body=json.dumps(payload2).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )
    resp2 = fa.import_partners(req2)

    body = json.loads(resp2.get_body())
    assert body["imported"] == 1
    assert body["skipped"] == 1


def test_import_partners_invalid_body() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="POST",
        url="/api/partners/import",
        body=json.dumps({"source": "erp", "records": []}).encode("utf-8"),  # empty records
        params={},
        headers={"Content-Type": "application/json"},
    )

    resp = fa.import_partners(req)

    assert resp.status_code == 422


def test_get_import_history() -> None:
    fa = _load_example_module()
    # Import some records first
    payload = {
        "source": "erp-system",
        "records": [
            {"partner_id": "P001", "name": "Acme Corp"},
        ],
    }
    req = func.HttpRequest(
        method="POST",
        url="/api/partners/import",
        body=json.dumps(payload).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )
    fa.import_partners(req)

    # Get history
    history_req = func.HttpRequest(
        method="GET",
        url="/api/partners/import/history",
        body=b"",
        params={},
        headers={},
    )
    resp = fa.get_import_history(history_req)

    assert resp.status_code == 200
    history = json.loads(resp.get_body())
    assert len(history) == 1
    assert history[0]["source"] == "erp-system"


def test_purge_partners_authorized() -> None:
    fa = _load_example_module()
    # Import some data first
    payload = {
        "source": "erp-system",
        "records": [
            {"partner_id": "P001", "name": "Acme Corp"},
            {"partner_id": "P002", "name": "Globex Inc"},
        ],
    }
    req = func.HttpRequest(
        method="POST",
        url="/api/partners/import",
        body=json.dumps(payload).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )
    fa.import_partners(req)

    # Purge with API key
    purge_req = func.HttpRequest(
        method="DELETE",
        url="/api/partners/purge",
        body=b"",
        params={},
        headers={"X-API-Key": "test-api-key"},
    )
    resp = fa.purge_partners(purge_req)

    assert resp.status_code == 200
    body = json.loads(resp.get_body())
    assert body["purged"] == 2
    assert body["status"] == "completed"
    assert len(fa._partner_records) == 0


def test_purge_partners_unauthorized() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="DELETE",
        url="/api/partners/purge",
        body=b"",
        params={},
        headers={},
    )

    resp = fa.purge_partners(req)

    assert resp.status_code == 401
    body = json.loads(resp.get_body())
    assert "X-API-Key" in body["error"]


def test_openapi_spec_includes_partner_paths() -> None:
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
    assert "paths" in payload
    # Bridge should register the import endpoint from @validate_http
    assert "/api/partners/import" in payload["paths"]
    # Programmatic registration
    assert "/api/partners/import/history" in payload["paths"]
    assert "/api/partners/purge" in payload["paths"]
    # Security scheme should be present
    assert "ApiKeyAuth" in payload.get("components", {}).get("securitySchemes", {})
