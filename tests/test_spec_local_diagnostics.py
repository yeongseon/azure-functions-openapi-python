from __future__ import annotations

from typing import Never, TypedDict
import warnings

from pydantic import BaseModel, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema
import pytest

from azure_functions_openapi._warnings import SpecWarning, WarningCode
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec


class _FailureEntry(TypedDict, total=False):
    route: str
    response_model: type
    parameters: int
    response: dict[int, dict[str, str]]
    querystring_schema: dict[str, str]


def _generation_snapshot(
    registry: OpenAPIRegistry,
) -> tuple[list[str], list[str], list[SpecWarning], list[str]]:
    return (
        registry.duplicate_operations,
        registry.downgrade_drops,
        registry.schema_substitutions,
        registry.skipped_operations,
    )


def _seed_previous_snapshot(registry: OpenAPIRegistry) -> None:
    registry.add_duplicate_operation("get", "/previous")
    registry.add_downgrade_drop("previous drop")
    registry.add_schema_substitution(SpecWarning(WarningCode.SCHEMA_SUBSTITUTION, "previous"))
    registry.add_skipped_operation("previous: skipped")


def test_snapshot_is_unchanged_during_interleaved_registry_generations() -> None:
    # Given: the outer run has already encountered all four event types when
    # schema generation yields control to another application's generation.
    outer = OpenAPIRegistry()
    inner = OpenAPIRegistry()
    _seed_previous_snapshot(outer)
    previous = _generation_snapshot(outer)
    inner.set("custom", {"route": "inner", "method": "purge"})
    inner_spec = generate_openapi_spec(registry=inner)
    inner_warnings = collect_spec_warnings(inner_spec, inner)
    observed: list[tuple[list[str], list[str], list[SpecWarning], list[str]]] = []

    class InterleavingModel(BaseModel):
        value: str

        @classmethod
        def __get_pydantic_json_schema__(
            cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
        ) -> JsonSchemaValue:
            observed.append(_generation_snapshot(outer))
            generate_openapi_spec(registry=inner, openapi_version="3.2.0", strict=True)
            observed.append(_generation_snapshot(outer))
            return handler(core_schema)

    for key in ("first", "second", "third"):
        outer.set(key, {"route": "duplicate", "method": "get"})
    outer.set("skipped", {"route": "skipped", "parameters": 123})
    outer.set("substituted", {"route": "substituted", "method": "post", "request_model": dict})
    outer.set(
        "events",
        {
            "route": "events",
            "response": {
                200: {"content": {"text/event-stream": {"itemSchema": {"type": "string"}}}}
            },
        },
    )
    outer.set("interleave", {"route": "interleave", "response_model": InterleavingModel})
    # When
    with pytest.warns(RuntimeWarning):
        spec = generate_openapi_spec(registry=outer)
    # Then: no live accumulator leaks through the compatibility boundary.
    assert observed == [previous, previous]
    assert [w.code for w in inner_warnings] == [WarningCode.VERSION_DOWNGRADE_DROP]
    assert _generation_snapshot(inner) == ([], [], [], [])
    assert {w.code for w in collect_spec_warnings(spec, outer)} == {
        WarningCode.DUPLICATE_OPERATION,
        WarningCode.VERSION_DOWNGRADE_DROP,
        WarningCode.SCHEMA_SUBSTITUTION,
        WarningCode.OPERATION_SKIPPED,
    }


def test_repaired_entry_regeneration_replaces_every_channel_with_empty_snapshot() -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set("broken", {"route": "broken", "parameters": 123})
    generate_openapi_spec(registry=registry)
    _seed_previous_snapshot(registry)
    registry.add_discovery_warning("orphan", "missing trigger")
    registry.add_empty_discovery("EmptyApp")
    registry.set("broken", {"route": "repaired", "method": "get"})
    # When
    spec = generate_openapi_spec(registry=registry, strict=True)
    # Then
    assert _generation_snapshot(registry) == ([], [], [], [])
    assert [w.code for w in collect_spec_warnings(spec, registry)] == [
        WarningCode.DISCOVERY_SKIPPED,
        WarningCode.EMPTY_DISCOVERY,
    ]


@pytest.mark.parametrize("failure", ["duplicate", "schema", "malformed", "validation", "config"])
def test_failed_generation_publishes_only_events_recorded_before_failure(failure: str) -> None:
    # Given: itemSchema warns even under strict mode, before the later failure.
    registry = OpenAPIRegistry()
    _seed_previous_snapshot(registry)
    registry.set(
        "events",
        {
            "route": "events",
            "response": {
                200: {"content": {"text/event-stream": {"itemSchema": {"type": "string"}}}}
            },
        },
    )
    entries: dict[str, _FailureEntry] = {
        "duplicate": {"route": "events"},
        "schema": {"route": "broken", "response_model": dict},
        "malformed": {"route": "broken", "parameters": 123},
        "validation": {"route": "broken", "response": {700: {}}},
        "config": {"route": "broken", "querystring_schema": {"type": "string"}},
    }
    registry.set("broken", dict(entries[failure]))
    # When
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises((OpenAPISpecConfigError, TypeError)):
            generate_openapi_spec(registry=registry, strict=True)
    # Then: the fatal event itself was never recorded by strict generation.
    assert _generation_snapshot(registry) == ([], [str(caught[0].message)], [], [])


def test_strict_downgrade_failure_publishes_completed_drop_collection() -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set("custom", {"route": "custom", "method": "purge"})
    registry.set("query", {"route": "query", "method": "query"})
    spec = generate_openapi_spec(registry=registry)
    expected = collect_spec_warnings(spec, registry)
    _seed_previous_snapshot(registry)
    # When
    with pytest.raises(OpenAPISpecConfigError):
        generate_openapi_spec(registry=registry, strict=True)
    # Then
    assert collect_spec_warnings(spec, registry) == expected


def test_non_strict_configuration_failure_publishes_partial_snapshot() -> None:
    # Given
    registry = OpenAPIRegistry()
    for key in ("first", "second"):
        registry.set(key, {"route": "duplicate"})
    registry.set("substituted", {"route": "substituted", "response_model": dict})
    registry.set("skipped", {"route": "skipped", "parameters": 123})
    spec = generate_openapi_spec(registry=registry)
    expected = collect_spec_warnings(spec, registry)
    registry.set("invalid", {"route": "invalid", "querystring_schema": {"type": "object"}})
    # When
    with pytest.raises(OpenAPISpecConfigError):
        generate_openapi_spec(registry=registry)
    # Then
    assert collect_spec_warnings(spec, registry) == expected


def test_runtime_warning_promoted_to_error_still_publishes_drop() -> None:
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
    with pytest.warns(RuntimeWarning):
        generate_openapi_spec(registry=registry)
    expected = _generation_snapshot(registry)
    _seed_previous_snapshot(registry)
    # When
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with pytest.raises(RuntimeError) as caught:
            generate_openapi_spec(registry=registry)
    # Then
    assert isinstance(caught.value.__cause__, RuntimeWarning)
    assert _generation_snapshot(registry) == expected


def test_failure_before_compilation_preserves_previous_snapshot() -> None:
    # Given
    registry = OpenAPIRegistry()
    _seed_previous_snapshot(registry)
    previous = _generation_snapshot(registry)
    # When
    with pytest.raises(OpenAPISpecConfigError):
        generate_openapi_spec(registry=registry, openapi_version="unsupported")
    # Then
    assert _generation_snapshot(registry) == previous


@pytest.mark.parametrize("strict", [False, True])
def test_failed_entry_snapshot_preserves_previous_diagnostics(strict: bool) -> None:
    # Given
    class UnreadableRegistry(OpenAPIRegistry):
        def snapshot(self) -> Never:
            raise ValueError("cannot copy entries")

    registry = UnreadableRegistry()
    _seed_previous_snapshot(registry)
    previous = _generation_snapshot(registry)
    # When
    with pytest.raises(ValueError if strict else RuntimeError):
        generate_openapi_spec(registry=registry, strict=strict)
    # Then
    assert _generation_snapshot(registry) == previous
