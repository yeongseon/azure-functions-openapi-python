# tests/test_report_jobs_example.py
# (file kept as test_todo_crud_example.py so CI mapping stays stable)

import importlib
import json
from typing import Any

import azure.functions as func

import azure_functions_openapi.decorator as decorator_module
from examples.report_jobs import function_app as report_function_app

_AUTH_HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer test-token"}
_AUTH_HEADER_ONLY = {"Authorization": "Bearer test-token"}


def _load_example_module() -> Any:
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    return importlib.reload(report_function_app)


def test_submit_report_valid() -> None:
    fa = _load_example_module()
    payload = {
        "report_type": "monthly_sales",
        "date_from": "2026-01-01",
        "date_to": "2026-01-31",
        "format": "csv",
    }
    req = func.HttpRequest(
        method="POST",
        url="/api/reports",
        body=json.dumps(payload).encode("utf-8"),
        params={},
        headers=_AUTH_HEADERS,
    )

    resp = fa.submit_report(req)

    assert resp.status_code == 202
    body = json.loads(resp.get_body())
    assert body["status"] == "queued"
    assert "job_id" in body
    assert "created_at" in body


def test_submit_report_invalid_json() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="POST",
        url="/api/reports",
        body=b"not json",
        params={},
        headers=_AUTH_HEADER_ONLY,
    )

    resp = fa.submit_report(req)

    assert resp.status_code == 400


def test_submit_report_unauthorized() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="POST",
        url="/api/reports",
        body=json.dumps(
            {
                "report_type": "monthly_sales",
                "date_from": "2026-01-01",
                "date_to": "2026-01-31",
            }
        ).encode("utf-8"),
        params={},
        headers={"Content-Type": "application/json"},
    )

    resp = fa.submit_report(req)

    assert resp.status_code == 401
    body = json.loads(resp.get_body())
    assert "Authorization" in body["error"] or "authorization" in body["error"].lower()


def test_get_report_status_found() -> None:
    fa = _load_example_module()
    # Submit a job first
    submit_req = func.HttpRequest(
        method="POST",
        url="/api/reports",
        body=json.dumps(
            {
                "report_type": "monthly_sales",
                "date_from": "2026-01-01",
                "date_to": "2026-01-31",
            }
        ).encode("utf-8"),
        params={},
        headers=_AUTH_HEADERS,
    )
    submit_resp = fa.submit_report(submit_req)
    job_id = json.loads(submit_resp.get_body())["job_id"]

    # Check status
    status_req = func.HttpRequest(
        method="GET",
        url=f"/api/reports/{job_id}/status",
        body=b"",
        route_params={"job_id": job_id},
        params={},
        headers=_AUTH_HEADER_ONLY,
    )
    status_resp = fa.get_report_status(status_req)

    assert status_resp.status_code == 200
    body = json.loads(status_resp.get_body())
    assert body["job_id"] == job_id
    assert body["status"] == "queued"


def test_get_report_status_not_found() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="GET",
        url="/api/reports/nonexistent/status",
        body=b"",
        route_params={"job_id": "nonexistent"},
        params={},
        headers=_AUTH_HEADER_ONLY,
    )

    resp = fa.get_report_status(req)

    assert resp.status_code == 404


def test_get_report_status_unauthorized() -> None:
    fa = _load_example_module()
    req = func.HttpRequest(
        method="GET",
        url="/api/reports/some-id/status",
        body=b"",
        route_params={"job_id": "some-id"},
        params={},
        headers={},
    )

    resp = fa.get_report_status(req)

    assert resp.status_code == 401


def test_download_report_not_ready() -> None:
    fa = _load_example_module()
    # Submit a job (status=queued, not completed)
    submit_req = func.HttpRequest(
        method="POST",
        url="/api/reports",
        body=json.dumps(
            {
                "report_type": "monthly_sales",
                "date_from": "2026-01-01",
                "date_to": "2026-01-31",
            }
        ).encode("utf-8"),
        params={},
        headers=_AUTH_HEADERS,
    )
    submit_resp = fa.submit_report(submit_req)
    job_id = json.loads(submit_resp.get_body())["job_id"]

    # Try download (should fail — not completed)
    download_req = func.HttpRequest(
        method="GET",
        url=f"/api/reports/{job_id}/download",
        body=b"",
        route_params={"job_id": job_id},
        params={},
        headers=_AUTH_HEADER_ONLY,
    )
    download_resp = fa.download_report(download_req)

    assert download_resp.status_code == 404


def test_download_report_completed() -> None:
    fa = _load_example_module()
    # Submit and manually mark completed
    submit_req = func.HttpRequest(
        method="POST",
        url="/api/reports",
        body=json.dumps(
            {
                "report_type": "monthly_sales",
                "date_from": "2026-01-01",
                "date_to": "2026-01-31",
            }
        ).encode("utf-8"),
        params={},
        headers=_AUTH_HEADERS,
    )
    submit_resp = fa.submit_report(submit_req)
    job_id = json.loads(submit_resp.get_body())["job_id"]

    # Simulate job completion
    fa._jobs[job_id]["status"] = "completed"

    download_req = func.HttpRequest(
        method="GET",
        url=f"/api/reports/{job_id}/download",
        body=b"",
        route_params={"job_id": job_id},
        params={},
        headers=_AUTH_HEADER_ONLY,
    )
    download_resp = fa.download_report(download_req)

    assert download_resp.status_code == 200
    assert b"report_type" in download_resp.get_body()


def test_openapi_spec_includes_report_paths() -> None:
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
    assert "/api/reports" in payload["paths"]
    # Verify security scheme is present
    assert "BearerAuth" in payload.get("components", {}).get("securitySchemes", {})
