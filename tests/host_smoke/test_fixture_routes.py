# tests/host_smoke/test_fixture_routes.py
"""Fast regression guard for #786.

tests/host_smoke/function_app.py's /openapi.json handler must document the
function's actual bound route ('/api/custom_name', from @app.function_name),
not the pre-rename decorator-time name ('/api/python_handler_name') the
function was defined under. The real-host CI job (`host-smoke` in
.github/workflows/ci-test.yml) exercised the live '/api/custom_name' route
directly and never noticed the generated document disagreed with it.

This test imports the fixture module directly (the same technique the
issue's own reproduction used) so it runs in milliseconds as part of the
normal test suite, without requiring the real Functions host, Azurite, or
Core Tools that the `host-smoke` CI job spins up. Reverting the fix (dropping
app=app from get_openapi_json() in function_app.py) makes
test_fixture_handler_documents_the_route_it_actually_serves fail.
"""

from __future__ import annotations

from collections.abc import Iterator
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import azure.functions as func
import pytest

from azure_functions_openapi import generate_openapi_spec
from azure_functions_openapi.decorator import clear_openapi_registry

FIXTURE_PATH = Path(__file__).parent / "function_app.py"


def _load_fixture_module() -> ModuleType:
    # A unique synthetic name avoids colliding with the several other
    # examples/*/function_app.py modules this repository also ships.
    module_spec = importlib.util.spec_from_file_location(
        "host_smoke_function_app_under_test", FIXTURE_PATH
    )
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _get(url: str) -> func.HttpRequest:
    return func.HttpRequest(method="GET", url=url, headers={}, params={}, body=b"")


@pytest.fixture
def fixture_module() -> Iterator[ModuleType]:
    clear_openapi_registry()
    try:
        yield _load_fixture_module()
    finally:
        clear_openapi_registry()


class TestHostSmokeFixtureDocumentsItsLiveRoute:
    def test_decorator_time_discovery_alone_sees_the_pre_rename_route(
        self, fixture_module: ModuleType
    ) -> None:
        """Out of scope per #786, documented here as the reason app= is
        required: decorator-time inference cannot see @app.function_name
        applied above a later @openapi, since @openapi infers its route when
        it itself executes, before the outer decorator renames the function.
        """
        paths = generate_openapi_spec()["paths"]
        assert list(paths) == ["/api/python_handler_name"]

    def test_app_scan_resolves_the_actual_bound_route(self, fixture_module: ModuleType) -> None:
        paths = generate_openapi_spec(app=fixture_module.app)["paths"]
        assert list(paths) == ["/api/custom_name"]

    def test_fixture_handler_documents_the_route_it_actually_serves(
        self, fixture_module: ModuleType
    ) -> None:
        response = fixture_module.openapi_spec(_get("http://127.0.0.1:7071/api/openapi.json"))
        spec = json.loads(response.get_body())

        assert "/api/custom_name" in spec["paths"]
        assert "/api/python_handler_name" not in spec["paths"]

    def test_custom_name_route_responds_with_the_expected_body(
        self, fixture_module: ModuleType
    ) -> None:
        response = fixture_module.python_handler_name(_get("http://127.0.0.1:7071/api/custom_name"))
        assert json.loads(response.get_body()) == {"function_name": "custom_name"}
