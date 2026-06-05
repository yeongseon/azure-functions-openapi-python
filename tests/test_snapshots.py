# tests/test_snapshots.py
"""Golden-file snapshot tests for generated OpenAPI specs.

Run with UPDATE_SNAPSHOTS=1 pytest tests/test_snapshots.py to regenerate.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

import azure_functions_openapi.decorator as decorator_module
from azure_functions_openapi.spec import generate_openapi_spec

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
UPDATE = os.environ.get("UPDATE_SNAPSHOTS", "").strip() not in ("", "0", "false", "no")


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    """Ensure the OpenAPI registry is empty before and after every snapshot test.

    Without this, routes registered by other test modules (test_openapi.py, etc.)
    bleed into snapshot tests run later in the same session, causing false mismatches.
    """
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    yield
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()


def _reload_example(module_path: str) -> None:
    """Clear registry and reload an example module to repopulate it.

    Skips the test if an optional dependency required by the example is not
    installed (e.g. ``azure-functions-validation`` for the notification_request
    example).
    """
    with decorator_module._registry_lock:
        decorator_module._openapi_registry.clear()
    try:
        mod = importlib.import_module(module_path)
        importlib.reload(mod)
    except ImportError as exc:
        pytest.skip(f"Skipping: optional dependency not installed ({exc})")


def _assert_snapshot(spec: dict[str, Any], snapshot_name: str) -> None:
    """Compare *spec* against the golden file, or write it when UPDATE=1."""
    snapshot_path = SNAPSHOTS_DIR / snapshot_name
    actual = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"

    if UPDATE:
        snapshot_path.write_text(actual, encoding="utf-8")
        pytest.skip(f"Snapshot updated: {snapshot_path.name}")
        return

    if not snapshot_path.exists():
        pytest.fail(
            f"Snapshot file missing: {snapshot_path}. Run with UPDATE_SNAPSHOTS=1 to create it."
        )

    expected = snapshot_path.read_text(encoding="utf-8")
    if actual != expected:
        # Provide a useful diff in the failure message.
        actual_obj = json.loads(actual)
        expected_obj = json.loads(expected)
        pytest.fail(
            f"Snapshot mismatch for {snapshot_name}.\n"
            f"Expected paths: {sorted(expected_obj.get('paths', {}).keys())}\n"
            f"Actual   paths: {sorted(actual_obj.get('paths', {}).keys())}\n"
            "Re-run with UPDATE_SNAPSHOTS=1 if this change is intentional.",
        )


class TestWebhookReceiverSnapshot:
    """Snapshot tests for the webhook_receiver example spec."""

    def test_openapi_3_0_spec(self) -> None:
        """webhook_receiver OpenAPI 3.0 spec matches golden file."""
        _reload_example("examples.webhook_receiver.function_app")
        spec = generate_openapi_spec("Webhook Receiver API", "1.0.0", openapi_version="3.0.0")
        _assert_snapshot(spec, "webhook_receiver_openapi.json")

    def test_paths_are_deterministically_ordered(self) -> None:
        """Paths must be in sorted order (deterministic output)."""
        _reload_example("examples.webhook_receiver.function_app")
        spec = generate_openapi_spec("Webhook Receiver API", "1.0.0")
        path_keys = list(spec["paths"].keys())
        assert path_keys == sorted(path_keys), f"Paths are not sorted: {path_keys}"

    def test_schemas_are_deterministically_ordered(self) -> None:
        """Component schemas must be in sorted order."""
        _reload_example("examples.webhook_receiver.function_app")
        spec = generate_openapi_spec("Webhook Receiver API", "1.0.0")
        schema_keys = list(spec.get("components", {}).get("schemas", {}).keys())
        assert schema_keys == sorted(schema_keys), f"Schemas are not sorted: {schema_keys}"


class TestReportJobsSnapshot:
    """Snapshot tests for the report_jobs example spec."""

    def test_openapi_3_0_spec(self) -> None:
        """report_jobs OpenAPI 3.0 spec matches golden file."""
        _reload_example("examples.report_jobs.function_app")
        spec = generate_openapi_spec("Report Jobs API", "1.0.0", openapi_version="3.0.0")
        _assert_snapshot(spec, "report_jobs_openapi.json")

    def test_paths_are_deterministically_ordered(self) -> None:
        """Paths must be in sorted order."""
        _reload_example("examples.report_jobs.function_app")
        spec = generate_openapi_spec("Report Jobs API", "1.0.0")
        path_keys = list(spec["paths"].keys())
        assert path_keys == sorted(path_keys), f"Paths are not sorted: {path_keys}"

    def test_schemas_are_deterministically_ordered(self) -> None:
        """Component schemas must be in sorted order."""
        _reload_example("examples.report_jobs.function_app")
        spec = generate_openapi_spec("Report Jobs API", "1.0.0")
        schema_keys = list(spec.get("components", {}).get("schemas", {}).keys())
        assert schema_keys == sorted(schema_keys), f"Schemas are not sorted: {schema_keys}"


class TestNotificationRequestSnapshot:
    """Snapshot tests for the notification_request example spec."""

    def test_openapi_3_0_spec(self) -> None:
        """notification_request OpenAPI 3.0 spec matches golden file."""
        _reload_example("examples.notification_request.function_app")
        spec = generate_openapi_spec("Notification API", "1.0.0", openapi_version="3.0.0")
        _assert_snapshot(spec, "notification_request_openapi.json")

    def test_paths_are_deterministically_ordered(self) -> None:
        """Paths must be in sorted order."""
        _reload_example("examples.notification_request.function_app")
        spec = generate_openapi_spec("Notification API", "1.0.0")
        path_keys = list(spec["paths"].keys())
        assert path_keys == sorted(path_keys), f"Paths are not sorted: {path_keys}"


class TestWebhookReceiverSnapshot31:
    """Snapshot tests for the webhook_receiver example spec (OpenAPI 3.1.0)."""

    def test_openapi_3_1_spec(self) -> None:
        """webhook_receiver OpenAPI 3.1 spec matches golden file."""
        _reload_example("examples.webhook_receiver.function_app")
        spec = generate_openapi_spec("Webhook Receiver API", "1.0.0", openapi_version="3.1.0")
        _assert_snapshot(spec, "webhook_receiver_openapi_31.json")

    def test_openapi_version_field_is_3_1(self) -> None:
        """Emitted 'openapi' field must be '3.1.0'."""
        _reload_example("examples.webhook_receiver.function_app")
        spec = generate_openapi_spec("Webhook Receiver API", "1.0.0", openapi_version="3.1.0")
        assert spec["openapi"] == "3.1.0"


class TestReportJobsSnapshot31:
    """Snapshot tests for the report_jobs example spec (OpenAPI 3.1.0)."""

    def test_openapi_3_1_spec(self) -> None:
        """report_jobs OpenAPI 3.1 spec matches golden file."""
        _reload_example("examples.report_jobs.function_app")
        spec = generate_openapi_spec("Report Jobs API", "1.0.0", openapi_version="3.1.0")
        _assert_snapshot(spec, "report_jobs_openapi_31.json")

    def test_openapi_version_field_is_3_1(self) -> None:
        """Emitted 'openapi' field must be '3.1.0'."""
        _reload_example("examples.report_jobs.function_app")
        spec = generate_openapi_spec("Report Jobs API", "1.0.0", openapi_version="3.1.0")
        assert spec["openapi"] == "3.1.0"


class TestNotificationRequestSnapshot31:
    """Snapshot tests for the notification_request example spec (OpenAPI 3.1.0)."""

    def test_openapi_3_1_spec(self) -> None:
        """notification_request OpenAPI 3.1 spec matches golden file."""
        _reload_example("examples.notification_request.function_app")
        spec = generate_openapi_spec("Notification API", "1.0.0", openapi_version="3.1.0")
        _assert_snapshot(spec, "notification_request_openapi_31.json")

    def test_openapi_version_field_is_3_1(self) -> None:
        """Emitted 'openapi' field must be '3.1.0'."""
        _reload_example("examples.notification_request.function_app")
        spec = generate_openapi_spec("Notification API", "1.0.0", openapi_version="3.1.0")
        assert spec["openapi"] == "3.1.0"


class TestPartnerImportBridgeSnapshot:
    """Snapshot tests for the partner_import_bridge example spec."""

    def test_openapi_3_0_spec(self) -> None:
        """partner_import_bridge OpenAPI 3.0 spec matches golden file."""
        _reload_example("examples.partner_import_bridge.function_app")
        spec = generate_openapi_spec("Partner Import API", "1.0.0", openapi_version="3.0.0")
        _assert_snapshot(spec, "partner_import_bridge_openapi.json")

    def test_paths_are_deterministically_ordered(self) -> None:
        """Paths must be in sorted order."""
        _reload_example("examples.partner_import_bridge.function_app")
        spec = generate_openapi_spec("Partner Import API", "1.0.0")
        path_keys = list(spec["paths"].keys())
        assert path_keys == sorted(path_keys), f"Paths are not sorted: {path_keys}"

    def test_schemas_are_deterministically_ordered(self) -> None:
        """Component schemas must be in sorted order."""
        _reload_example("examples.partner_import_bridge.function_app")
        spec = generate_openapi_spec("Partner Import API", "1.0.0")
        schema_keys = list(spec.get("components", {}).get("schemas", {}).keys())
        assert schema_keys == sorted(schema_keys), f"Schemas are not sorted: {schema_keys}"


class TestPartnerImportBridgeSnapshot31:
    """Snapshot tests for the partner_import_bridge example spec (OpenAPI 3.1.0)."""

    def test_openapi_3_1_spec(self) -> None:
        """partner_import_bridge OpenAPI 3.1 spec matches golden file."""
        _reload_example("examples.partner_import_bridge.function_app")
        spec = generate_openapi_spec("Partner Import API", "1.0.0", openapi_version="3.1.0")
        _assert_snapshot(spec, "partner_import_bridge_openapi_31.json")

    def test_openapi_version_field_is_3_1(self) -> None:
        """Emitted 'openapi' field must be '3.1.0'."""
        _reload_example("examples.partner_import_bridge.function_app")
        spec = generate_openapi_spec("Partner Import API", "1.0.0", openapi_version="3.1.0")
        assert spec["openapi"] == "3.1.0"
