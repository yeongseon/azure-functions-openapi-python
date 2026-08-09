"""CLI unified one-shot discovery wiring (issue #326).

The ``generate`` command imports ``--app`` (triggering ``@openapi`` decorators)
and, when an explicit ``module:variable`` is given, resolves the ``FunctionApp``
object and runs :func:`scan_endpoint_metadata` on it. This closes the DX gap
where endpoint-metadata producers (``@validate_http``, langgraph, third-party)
were silently missing from the generated spec.

These tests assert the CLI-generated spec (``module:app`` form) includes:

* decorator-registered endpoints (``@openapi`` / :func:`register_openapi_metadata`),
* endpoint-metadata endpoints (discovered via the scan), and
* both together (mixed),

plus that the **module-only** form imports without scanning and prints a note,
and that repeated registry merge of the same handler metadata is idempotent
(no duplicate paths/operations) — verified at the registry layer, independent
of SDK enumeration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from azure_functions_openapi.bridge import _HANDLER_METADATA_ATTR, scan_endpoint_metadata
from azure_functions_openapi.cli import handle_generate
from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    register_openapi_metadata,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


# A representative flat endpoint payload (all JSON Schema, no model classes).
FLAT_ENDPOINT: dict[str, Any] = {
    "version": 1,
    "request_body": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    "request_body_required": True,
    "responses": {
        "200": {"schema": {"type": "object", "properties": {"id": {"type": "integer"}}}},
    },
}


class MockBinding:
    def __init__(self, route: str, methods: list[str] | None, type: str = "httpTrigger") -> None:
        self.route = route
        self.methods = methods
        self.type = type


class MockFunction:
    def __init__(self, name: str, func: Any, bindings: list[Any]) -> None:
        self._name = name
        self._func = func
        self._bindings = bindings

    def get_function_name(self) -> str:
        return self._name

    def get_user_function(self) -> Any:
        return self._func

    def get_bindings(self) -> list[Any]:
        return self._bindings

    def is_http_function(self) -> bool:
        return any(str(getattr(b, "type", "")).lower() == "httptrigger" for b in self._bindings)


class MockBuilder:
    def __init__(self, function: MockFunction) -> None:
        self._function = function

    def build(self, auth_level: Any = None) -> MockFunction:
        return self._function


class MockApp:
    def __init__(self, builders: list[MockBuilder]) -> None:
        self._function_builders = builders


def _endpoint_app(
    *,
    name: str = "create_user",
    route: str = "users",
    methods: list[str] | None = None,
) -> MockApp:
    """Build a FunctionApp-like object whose handler carries endpoint metadata."""

    def handler(req: Any) -> Any:
        return req

    setattr(handler, _HANDLER_METADATA_ATTR, {"endpoint": FLAT_ENDPOINT})
    binding = MockBinding(route=route, methods=methods or ["POST"])
    fn = MockFunction(name=name, func=handler, bindings=[binding])
    return MockApp([MockBuilder(fn)])


def _empty_app() -> MockApp:
    """A FunctionApp-like object with no discoverable metadata handlers."""
    return MockApp([])


def _generate_args(app: str, output: Path) -> Any:
    args = mock.Mock()
    args.title = "Test API"
    args.version = "1.0.0"
    args.description = None
    args.format = "json"
    args.output = str(output)
    args.pretty = False
    args.openapi_version = "3.1"
    args.route_prefix = "/api"
    args.strict = False
    args.fail_on_empty_paths = False
    args.app = app
    return args


def _run_generate(
    app: str, resolved: MockApp | None, variable_given: bool, output: Path
) -> dict[str, Any]:
    args = _generate_args(app, output)
    with mock.patch(
        "azure_functions_openapi.cli._import_app_module",
        return_value=(resolved, variable_given),
    ):
        result = handle_generate(args)
    assert result == 0
    data: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
    return data


# ---------------------------------------------------------------------------
# module:variable form — endpoint metadata discovery is wired in
# ---------------------------------------------------------------------------


def test_endpoint_only_app_is_discovered_via_module_variable(tmp_path: Path) -> None:
    """An endpoint-metadata-only app yields its route through CLI discovery."""
    app = _endpoint_app(route="users", methods=["POST"])
    spec = _run_generate("function_app:app", app, True, tmp_path / "openapi.json")
    assert "/api/users" in spec["paths"]
    assert "post" in spec["paths"]["/api/users"]


def test_decorator_only_app_is_included_via_module_variable(tmp_path: Path) -> None:
    """Decorator-registered routes (populated on import) appear in the spec."""
    # Simulate an @openapi decorator firing during module import.
    register_openapi_metadata(path="/api/items", method="get", summary="List items")
    spec = _run_generate("function_app:app", _empty_app(), True, tmp_path / "openapi.json")
    assert "/api/items" in spec["paths"]
    assert "get" in spec["paths"]["/api/items"]


def test_mixed_decorator_and_endpoint_routes_both_present(tmp_path: Path) -> None:
    """Decorator-only and endpoint-metadata routes converge into one spec."""
    register_openapi_metadata(path="/api/items", method="get", summary="List items")
    app = _endpoint_app(route="users", methods=["POST"])
    spec = _run_generate("function_app:app", app, True, tmp_path / "openapi.json")
    assert "/api/items" in spec["paths"]
    assert "/api/users" in spec["paths"]


# ---------------------------------------------------------------------------
# module-only form — import only, no scan, explicit note
# ---------------------------------------------------------------------------


def test_module_only_form_skips_scan_and_prints_note(tmp_path: Path) -> None:
    """Without a ':variable', discovery is skipped and a note is emitted."""
    register_openapi_metadata(path="/api/items", method="get", summary="List items")
    args = _generate_args("function_app", tmp_path / "openapi.json")
    with mock.patch(
        "azure_functions_openapi.cli._import_app_module",
        return_value=(None, False),
    ) as mock_import:
        with mock.patch("azure_functions_openapi.cli.scan_endpoint_metadata") as mock_scan:
            with mock.patch("builtins.print") as mock_print:
                result = handle_generate(args)

    assert result == 0
    mock_import.assert_called_once_with("function_app")
    mock_scan.assert_not_called()
    printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
    assert "metadata discovery skipped" in printed
    # Decorator-only routes are still present (they registered on import).
    spec = json.loads((tmp_path / "openapi.json").read_text(encoding="utf-8"))
    assert "/api/items" in spec["paths"]


# ---------------------------------------------------------------------------
# Registry-merge idempotency (independent of SDK enumeration)
# ---------------------------------------------------------------------------


def test_repeated_scan_is_registry_merge_idempotent() -> None:
    """Merging the same discovered metadata twice must not duplicate paths."""
    app = _endpoint_app(route="users", methods=["POST"])

    scan_endpoint_metadata(app, route_prefix="/api")
    from azure_functions_openapi.spec import generate_openapi_spec

    first = generate_openapi_spec("API", "1.0.0")

    # Re-run discovery on the same app: build() is idempotent and the registry
    # merges by function id, so no duplicate path/operation may be created.
    scan_endpoint_metadata(app, route_prefix="/api")
    second = generate_openapi_spec("API", "1.0.0")

    assert first["paths"] == second["paths"]
    assert list(second["paths"]["/api/users"].keys()) == ["post"]
