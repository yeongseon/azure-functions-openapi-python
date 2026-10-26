from __future__ import annotations

from collections.abc import Iterator
import importlib
import json
from pathlib import Path
import sys

import azure.functions as func
import pytest

from azure_functions_openapi import clear_openapi_registry, generate_openapi_report
from azure_functions_openapi.cli import main
from azure_functions_openapi.registry import registry


@pytest.fixture
def two_apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[func.FunctionApp, ...]]:
    # Given: separate imported modules contain identically named handlers.
    clear_openapi_registry()
    monkeypatch.syspath_prepend(str(tmp_path))
    names = ("scope_app_a", "scope_app_b")
    for name in names:
        (tmp_path / f"{name}.py").write_text(
            "import azure.functions as func\n"
            "from azure_functions_openapi.decorator import openapi\n"
            "app = func.FunctionApp()\n"
            f"@openapi(summary='{name}')\n"
            f"@app.route(route='{name}', methods=['GET'])\n"
            "def handler(req):\n"
            "    return func.HttpResponse('ok')\n",
            encoding="utf-8",
        )
    apps = tuple(importlib.import_module(name).app for name in names)
    yield apps
    clear_openapi_registry()
    for name in names:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("selected", [0, 1])
def test_report_contains_only_selected_app_when_handler_names_collide(
    two_apps: tuple[func.FunctionApp, ...], selected: int
) -> None:
    before = registry.snapshot()
    # When: the public facade generates a report for one completed app.
    report = generate_openapi_report(app=two_apps[selected], strict=True)
    # Then: only that app is documented, with its own metadata and no global mutation.
    path = f"/api/scope_app_{'ab'[selected]}"
    assert set(report.spec["paths"]) == {path}
    assert report.spec["paths"][path]["get"]["summary"] == f"scope_app_{'ab'[selected]}"
    assert not report.warnings
    assert registry.snapshot() == before


@pytest.mark.parametrize("isolate", [False, True])
def test_cli_contains_only_selected_app_when_both_modules_are_imported(
    two_apps: tuple[func.FunctionApp, ...],
    capsys: pytest.CaptureFixture[str],
    isolate: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When: CLI generation selects an app, with or without the legacy isolation flag.
    args = ["generate", "--app", "scope_app_a:app", "--format", "json"]
    if isolate:
        args.append("--isolate-app")
    monkeypatch.setattr(sys, "argv", ["azure-functions-openapi", *args])
    result = main()
    # Then: selected-app CLI and Python facade agree.
    captured = capsys.readouterr()
    assert result == 0, captured.err
    assert set(json.loads(captured.out)["paths"]) == {"/api/scope_app_a"}


def test_report_keeps_global_collection_when_no_app_is_selected(
    two_apps: tuple[func.FunctionApp, ...],
) -> None:
    # When: the caller deliberately generates from the process-wide registry.
    report = generate_openapi_report()
    # Then: legacy module-only aggregation remains available, with collision diagnostics.
    assert set(report.spec["paths"]) == {"/api/scope_app_a", "/api/scope_app_b"}
    assert any("operationId" in warning.message for warning in report.warnings)
