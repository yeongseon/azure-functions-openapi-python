from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

import azure_functions_openapi as api
from azure_functions_openapi import cli
from azure_functions_openapi import spec as compiler
from azure_functions_openapi._warnings import WarningCode
from azure_functions_openapi.registry import OpenAPIRegistry


def test_report_keeps_generation_events_when_publication_is_overwritten() -> None:
    # Given: another invocation replaces the compatibility snapshot at publication.
    class InterleavedRegistry(OpenAPIRegistry):
        def add_downgrade_drop(self, message: str) -> None:
            super().add_downgrade_drop(message)
            self.clear_downgrade_drops()

    registry = InterleavedRegistry()
    registry.set("custom", {"route": "custom", "method": "purge"})
    # When
    report = compiler.generate_openapi_report(registry=registry)
    # Then
    assert [warning.code for warning in report.warnings] == [WarningCode.VERSION_DOWNGRADE_DROP]


def test_cli_keeps_local_events_after_registry_publication(tmp_path: Path) -> None:
    # Given
    class InterleavedRegistry(OpenAPIRegistry):
        def add_downgrade_drop(self, message: str) -> None:
            super().add_downgrade_drop(message)
            self.clear_downgrade_drops()

    registry = InterleavedRegistry()
    registry.set("custom", {"route": "custom", "method": "purge"})
    artifact = tmp_path / "spec.yaml"
    args = argparse.Namespace(
        title="API",
        version="1",
        openapi_version="3.1",
        app=None,
        format="yaml",
        output=str(artifact),
        fail_on_warnings=True,
    )
    # When
    with (
        patch.object(compiler, "_default_registry", registry),
        patch.object(cli, "_prepare_generation", return_value=()),
    ):
        code = cli.handle_generate(args)
    # Then
    assert code == 2
    assert not artifact.exists()


@pytest.mark.parametrize("serializer", [compiler.get_openapi_json, compiler.get_openapi_yaml])
def test_runtime_serialization_never_adds_final_validation(serializer: Callable[..., str]) -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set("custom", {"route": "custom", "method": "purge"})
    # When
    with patch.object(compiler, "_validate_spec", wraps=compiler._validate_spec) as validate:
        serializer(registry=registry, openapi_version="3.2.0")
    # Then
    assert validate.call_count == 1


@pytest.mark.parametrize("target", ["3.0.0", "3.1.0", "3.2.0"])
@pytest.mark.parametrize("method", ["get", "query", "purge"])
def test_report_validates_again_only_when_operation_traversal_changes(
    target: str, method: str
) -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set("operation", {"route": "operation", "method": method})
    # When
    with patch.object(compiler, "_validate_spec", wraps=compiler._validate_spec) as validate:
        report = compiler.generate_openapi_report(registry=registry, openapi_version=target)
    # Then
    changed = method == "purge" or (method == "query" and target != "3.2.0")
    assert validate.call_count == (2 if changed else 1)
    assert report.warnings == compiler.collect_spec_warnings(report.spec, registry)


def test_final_validation_names_first_operation_after_custom_relocation() -> None:
    # Given: relocation changes which duplicate operation is encountered first.
    registry = OpenAPIRegistry()
    registry.set("custom", {"route": "same", "method": "purge", "operation_id": "shared"})
    registry.set("standard", {"route": "same", "method": "get", "operation_id": "shared"})
    # When
    report = compiler.generate_openapi_report(registry=registry, openapi_version="3.2.0")
    # Then
    assert report.warnings == compiler.collect_spec_warnings(report.spec, registry)
    assert [w.message for w in report.warnings] == [
        "Duplicate operationId 'shared': used by GET /api/same and PURGE /api/same"
    ]


def test_public_collection_validates_report_spec_modified_after_generation() -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set("operation", {"route": "operation"})
    report = compiler.generate_openapi_report(registry=registry)
    report.spec["paths"]["/api/operation"]["get"]["operationId"] = ""
    # When
    collected = compiler.collect_spec_warnings(report.spec, registry)
    # Then
    assert report.warnings == ()
    assert [(w.code, w.message) for w in collected] == [
        (WarningCode.SPEC_VALIDATION, "Empty operationId in GET /api/operation")
    ]


def test_item_schema_runtime_and_structured_messages_match() -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set(
        "events",
        {
            "route": "events",
            "response": {
                200: {"content": {"text/event-stream": {"itemSchema": {"type": "string"}}}}
            },
        },
    )
    # When
    with pytest.warns(RuntimeWarning) as runtime:
        report = compiler.generate_openapi_report(registry=registry)
    # Then
    assert [w.message for w in report.warnings] == [str(w.message) for w in runtime]
    assert report.spec["paths"]["/api/events"]["get"]["responses"]["200"]["content"][
        "text/event-stream"
    ]["itemSchema"] == {"type": "string"}


@pytest.mark.parametrize("empty_gate,expected", [(False, 2), (True, 1)])
def test_cli_warning_gate_preserves_exit_precedence_and_existing_artifact(
    tmp_path: Path, empty_gate: bool, expected: int
) -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.add_empty_discovery("EmptyApp")
    artifact = tmp_path / "spec.json"
    artifact.write_text("previous", encoding="utf-8")
    args = argparse.Namespace(
        title="API",
        version="1",
        openapi_version="3.1",
        app=None,
        format="json",
        output=str(artifact),
        fail_on_warnings=True,
        fail_on_empty_paths=empty_gate,
    )
    # When
    with (
        patch.object(cli, "default_registry", registry),
        patch.object(compiler, "_default_registry", registry),
        patch.object(cli, "_prepare_generation", return_value=()),
    ):
        code = cli.handle_generate(args)
    # Then
    assert code == expected
    assert artifact.read_text(encoding="utf-8") == "previous"


def test_facade_unresolved_routes_remain_advisory_in_cli(tmp_path: Path) -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set("implicit", {"function_name": "implicit"})
    with pytest.warns(RuntimeWarning):
        report = api.generate_openapi_report(registry=registry)
    unresolved = tuple(w for w in report.warnings if w.code == WarningCode.UNRESOLVED_ROUTE)
    artifact = tmp_path / "spec.json"
    args = argparse.Namespace(
        title="API",
        version="1",
        openapi_version="3.1",
        app=None,
        format="json",
        output=str(artifact),
        fail_on_warnings=True,
    )
    # When
    with (
        patch.object(compiler, "_default_registry", registry),
        patch.object(cli, "_prepare_generation", return_value=unresolved),
    ):
        code = cli.handle_generate(args)
    # Then
    assert len(unresolved) == 1
    assert code == 0
    assert artifact.is_file()
