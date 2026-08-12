"""E2E tests for azure-functions-openapi running on a real Azure Functions host.

Usage:
    E2E_BASE_URL=https://<app>.azurewebsites.net pytest tests/e2e -v

The E2E_BASE_URL environment variable must point to the deployed Function App.
Tests are skipped automatically when the variable is not set (local unit test runs).
"""

from __future__ import annotations

import os
import time

import pytest
import requests
import yaml  # PyYAML

BASE_URL = os.environ.get("E2E_BASE_URL", "").rstrip("/")
SKIP_REASON = "E2E_BASE_URL not set — skipping real-Azure e2e tests"


def _get(path: str, **kwargs: object) -> requests.Response:
    return requests.get(f"{BASE_URL}{path}", timeout=30, **kwargs)  # type: ignore[arg-type]


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def warmup() -> None:
    """Retry /api/health until the Consumption cold-start finishes (max 2 min)."""
    if not BASE_URL:
        return
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=10)
            if r.status_code < 500:
                return
        except requests.RequestException:
            pass
        time.sleep(3)
    pytest.fail("Warmup failed: /api/health did not respond within 120 s")


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not BASE_URL, reason=SKIP_REASON)
def test_health_returns_200() -> None:
    r = _get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.skipif(not BASE_URL, reason=SKIP_REASON)
def test_openapi_json_returns_valid_spec() -> None:
    r = _get("/api/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    # Must be OpenAPI 3.x
    assert "openapi" in spec
    assert spec["openapi"].startswith("3.")
    # Must have paths
    assert "paths" in spec
    assert len(spec["paths"]) > 0
    # Known path must be present
    assert "/api/items" in spec["paths"]


@pytest.mark.skipif(not BASE_URL, reason=SKIP_REASON)
def test_openapi_yaml_returns_valid_spec() -> None:
    r = _get("/api/openapi.yaml")
    assert r.status_code == 200
    spec = yaml.safe_load(r.text)
    assert "openapi" in spec
    assert spec["openapi"].startswith("3.")
    assert "paths" in spec


@pytest.mark.skipif(not BASE_URL, reason=SKIP_REASON)
def test_swagger_ui_returns_html() -> None:
    r = _get("/api/docs")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")
    assert "swagger" in r.text.lower()


@pytest.mark.skipif(not BASE_URL, reason=SKIP_REASON)
def test_list_items_endpoint() -> None:
    r = _get("/api/items")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) > 0
    assert "id" in items[0]
    assert "name" in items[0]
