"""Generation-time versus final-document diagnostics for #819."""

from __future__ import annotations

import copy
import json
import warnings

import pytest

from azure_functions_openapi._warnings import SpecWarning, WarningCode
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    collect_spec_warnings,
    generate_openapi_spec,
    get_openapi_json,
)


@pytest.fixture
def mixed_registry() -> OpenAPIRegistry:
    registry = OpenAPIRegistry()
    registry.set(
        "skew",
        {
            "route": "skew",
            "method": "post",
            "_skew_flags": ["version-skew"],
            "_binding_methods": ["GET"],
            "request_model": dict,
        },
    )
    for key in ("first", "second", "third"):
        registry.set(key, {"route": "duplicate", "method": "get"})
    registry.set("skipped", {"route": "skipped", "parameters": 123})
    registry.set("custom", {"route": "custom", "method": "purge"})
    registry.set("query", {"route": "query", "method": "query"})
    for _ in range(2):
        registry.add_discovery_warning("orphan", "missing trigger")
        registry.add_empty_discovery("EmptyApp")
    return registry


def test_mixed_diagnostic_channel_order_and_dedup(mixed_registry: OpenAPIRegistry) -> None:
    # Given / When
    spec = generate_openapi_spec(
        registry=mixed_registry, openapi_version="3.1.0", license={"name": ""}
    )
    actual = collect_spec_warnings(spec, mixed_registry)
    # Then
    assert actual == (
        SpecWarning(
            WarningCode.VERSION_SKEW,
            "Endpoint contract version is unsupported; the endpoint namespace was "
            "rejected and the operation was generated from the HTTP binding alone, "
            "so it may not match the intended contract.",
            function_name="skew",
        ),
        SpecWarning(
            WarningCode.DISCOVERY_SKIPPED,
            "A function builder could not be built during discovery and was omitted "
            "from the spec: missing trigger",
            function_name="orphan",
        ),
        SpecWarning(
            WarningCode.EMPTY_DISCOVERY,
            "No function builders were discovered on the scanned application object (EmptyApp)",
        ),
        SpecWarning(
            WarningCode.DUPLICATE_OPERATION,
            "A duplicate METHOD path collision dropped an operation; only the last "
            "@openapi registration appears in the spec: GET /api/duplicate",
        ),
        SpecWarning(
            WarningCode.VERSION_DOWNGRADE_DROP,
            "Non-standard HTTP method 'PURGE' on /api/custom requires OpenAPI 3.2 "
            "(additionalOperations); dropped from the 3.1.0 spec",
        ),
        SpecWarning(
            WarningCode.VERSION_DOWNGRADE_DROP,
            "The 'query' HTTP method on /api/query requires OpenAPI 3.2; "
            "dropped from the 3.1.0 spec",
        ),
        SpecWarning(
            WarningCode.SCHEMA_SUBSTITUTION,
            "Explicit request model replaced by a generic object schema "
            "(model_to_schema expects a Pydantic v2 BaseModel subclass "
            "(missing model_json_schema). Pydantic v1 is not supported.)",
            function_name="skew",
            path="/api/skew",
            method="POST",
            location="request body",
        ),
        SpecWarning(
            WarningCode.OPERATION_SKIPPED,
            "skipped: operation omitted from the spec "
            "(TypeError(\"'int' object is not iterable\"))",
            function_name="skipped",
        ),
        SpecWarning(
            WarningCode.METHOD_BINDING_MISMATCH,
            "The explicit @openapi(method=...) is not served by the function's HTTP "
            "binding; the generated operation cannot be reached at runtime",
            function_name="skew",
        ),
        SpecWarning(WarningCode.SPEC_VALIDATION, "License Object must define a non-empty 'name'"),
    )
    assert spec["paths"]["/api/duplicate"]["get"]["operationId"] == "get_third"


@pytest.mark.parametrize("method", ["purge", "query"])
@pytest.mark.parametrize("version", ["3.0.0", "3.1.0", "3.2.0"])
def test_pre_drop_validation_is_not_final_document_validation(
    method: str,
    version: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set(
        "invalid",
        {"route": "invalid", "method": method, "response": {700: {"description": "invalid"}}},
    )
    message = (
        f"Invalid response status '700' in {method.upper()} /api/invalid; "
        "must be an integer 100–599 or 'default'"
    )
    # When
    spec = generate_openapi_spec(registry=registry, openapi_version=version)
    # Then: generation validates before unsupported operations disappear.
    assert "OpenAPI spec validation: " + message in caplog.messages
    actual = collect_spec_warnings(spec, registry)
    if version == "3.2.0":
        path_item = spec["paths"]["/api/invalid"]
        op = path_item["query"] if method == "query" else path_item["additionalOperations"]["PURGE"]
        assert op["responses"] == {"700": {"description": "invalid"}}
        assert actual == (SpecWarning(WarningCode.SPEC_VALIDATION, message),)
    else:
        assert spec["paths"]["/api/invalid"] == {}
        assert [w.code for w in actual] == [WarningCode.VERSION_DOWNGRADE_DROP]
    with pytest.raises(OpenAPISpecConfigError) as caught:
        generate_openapi_spec(registry=registry, openapi_version=version, strict=True)
    assert message in str(caught.value)


@pytest.mark.parametrize("version", ["3.0.0", "3.1.0", "3.2.0"])
def test_item_schema_runtime_and_structured_warning_equivalence(version: str) -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set(
        "events",
        {
            "route": "events",
            "method": "get",
            "response": {
                200: {
                    "description": "Events",
                    "content": {"text/event-stream": {"itemSchema": {"type": "string"}}},
                }
            },
        },
    )
    # When: even strict mode currently retains pre-3.2 itemSchema.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        spec = generate_openapi_spec(registry=registry, openapi_version=version, strict=True)
    # Then
    assert spec["paths"]["/api/events"]["get"]["responses"]["200"]["content"] == {
        "text/event-stream": {"itemSchema": {"type": "string"}},
    }
    expected = (
        []
        if version == "3.2.0"
        else [
            "Response media type 'text/event-stream' for function 'events' uses 'itemSchema', "
            "which is an OpenAPI 3.2 feature for sequential/streaming media types, but the target "
            f"openapi_version is {version}. The field is emitted as-is but may not be understood "
            "by 3.0/3.1 tooling. Use openapi_version='3.2.0' for streaming responses.",
        ]
    )
    assert [(w.category, str(w.message)) for w in caught] == [(RuntimeWarning, m) for m in expected]
    assert collect_spec_warnings(spec, registry) == tuple(
        SpecWarning(WarningCode.VERSION_DOWNGRADE_DROP, m) for m in expected
    )


def test_collect_validates_the_supplied_document(mixed_registry: OpenAPIRegistry) -> None:
    # Given
    spec = generate_openapi_spec(registry=mixed_registry)
    baseline = collect_spec_warnings(spec, mixed_registry)
    altered = copy.deepcopy(spec)
    altered["paths"]["/api/skew"]["post"]["responses"]["700"] = {"description": "bad"}
    # When
    actual = collect_spec_warnings(altered, mixed_registry)
    # Then
    assert actual == (
        *baseline,
        SpecWarning(
            WarningCode.SPEC_VALIDATION,
            "Invalid response status '700' in POST /api/skew; "
            "must be an integer 100–599 or 'default'",
        ),
    )


def test_alternating_generation_is_byte_identical(mixed_registry: OpenAPIRegistry) -> None:
    # Given
    entries = mixed_registry.snapshot()
    baseline_bytes: dict[str, bytes] = {}
    baseline_warnings: dict[str, tuple[SpecWarning, ...]] = {}
    # When / Then: each version is visited twice, including 3.0 after 3.2.
    for version in ("3.0.0", "3.1.0", "3.2.0", "3.0.0", "3.1.0", "3.2.0", "3.0.0"):
        output = get_openapi_json(registry=mixed_registry, openapi_version=version).encode("utf-8")
        spec = generate_openapi_spec(registry=mixed_registry, openapi_version=version)
        actual = collect_spec_warnings(spec, mixed_registry)
        assert output == baseline_bytes.setdefault(version, output)
        assert actual == baseline_warnings.setdefault(version, actual)
        assert sum(w.code == WarningCode.VERSION_DOWNGRADE_DROP for w in actual) == (
            0 if version == "3.2.0" else 2
        )
    assert mixed_registry.snapshot() == entries


def test_alternating_versions_reset_python_and_structured_warnings() -> None:
    # Given
    registry = OpenAPIRegistry()
    registry.set(
        "events",
        {
            "route": "events",
            "method": "get",
            "response": {
                200: {
                    "content": {
                        "text/event-stream": {"itemSchema": {"type": "string", "nullable": True}}
                    },
                }
            },
        },
    )
    outputs: dict[str, bytes] = {}
    diagnostics: dict[str, tuple[SpecWarning, ...]] = {}
    # When / Then
    for version in ("3.0.0", "3.1.0", "3.2.0", "3.0.0", "3.1.0", "3.2.0"):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            output = get_openapi_json(registry=registry, openapi_version=version).encode()
        actual = collect_spec_warnings(json.loads(output), registry)
        assert output == outputs.setdefault(version, output)
        assert actual == diagnostics.setdefault(version, actual)
        assert [(w.category, str(w.message)) for w in caught] == [
            (RuntimeWarning, w.message) for w in actual
        ]
        assert len(actual) == (0 if version == "3.2.0" else 1)


def test_corrected_entries_clear_all_generation_diagnostics(
    mixed_registry: OpenAPIRegistry,
) -> None:
    # Given
    first = generate_openapi_spec(registry=mixed_registry)
    assert {w.code for w in collect_spec_warnings(first, mixed_registry)} >= {
        WarningCode.DUPLICATE_OPERATION,
        WarningCode.VERSION_DOWNGRADE_DROP,
        WarningCode.SCHEMA_SUBSTITUTION,
        WarningCode.OPERATION_SKIPPED,
    }
    for key in mixed_registry.snapshot():
        mixed_registry.set(key, {"route": key, "method": "get"})
    # When
    corrected = generate_openapi_spec(registry=mixed_registry, strict=True)
    # Then: discovery diagnostics have scan lifetime, not generation lifetime.
    assert [w.code for w in collect_spec_warnings(corrected, mixed_registry)] == [
        WarningCode.DISCOVERY_SKIPPED,
        WarningCode.EMPTY_DISCOVERY,
    ]
