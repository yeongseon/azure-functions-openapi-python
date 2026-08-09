"""Tests for structured spec-generation warnings and the CLI exit-code gate.

Covers issue #318: version skew and namespace fallback must be observable as
structured warnings and, under ``--fail-on-warnings``, must fail a CI build so a
wrong-but-plausible spec is never promoted to an artifact.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from typing import Any

from pydantic import BaseModel
import pytest

from azure_functions_openapi._warnings import SpecWarning, WarningCode
from azure_functions_openapi.bridge import scan_endpoint_metadata
from azure_functions_openapi.cli import handle_generate
from azure_functions_openapi.decorator import clear_openapi_registry
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    collect_spec_warnings,
    generate_openapi_report,
    generate_openapi_spec,
)

# ---------------------------------------------------------------------------
# Mock Azure Functions app scaffolding
# ---------------------------------------------------------------------------


class MockBinding:
    def __init__(self, route: str, methods: list[str], type: str = "httpTrigger") -> None:
        self.route = route
        self.methods = methods
        self.type = type


class MockFunction:
    def __init__(self, name: str, func: Any, bindings: list[Any]) -> None:
        self._name = name
        self._func = func
        self._bindings = bindings

    # Public accessors mirroring azure.functions Function; the adapter reads the
    # function exclusively through these (never the underscored fields).
    def get_function_name(self) -> str:
        return self._name

    def get_user_function(self) -> Any:
        return self._func

    def get_bindings(self) -> list[Any]:
        return self._bindings

    def is_http_function(self) -> bool:
        return any(
            str(getattr(b, "type", "")).lower() == "httptrigger" for b in self._bindings
        )


class MockBuilder:
    def __init__(self, function: MockFunction) -> None:
        self._function = function

    # Public, idempotent build() mirroring FunctionBuilder.build; the adapter
    # enumerates via _function_builders + this method (never get_functions()).
    def build(self, auth_level: Any = None) -> MockFunction:
        return self._function


class MockApp:
    def __init__(self, builders: list[Any]) -> None:
        self._function_builders = builders


class _Body(BaseModel):
    name: str


def _make_app(
    namespaces: dict[str, Any],
    *,
    name: str = "create_user",
    route: str = "users",
    methods: list[str] | None = None,
) -> MockApp:
    def handler(req: Any) -> Any:
        return req

    setattr(handler, "_azure_functions_metadata", namespaces)
    binding = MockBinding(route=route, methods=methods or ["POST"])
    fn = MockFunction(name=name, func=handler, bindings=[binding])
    return MockApp([MockBuilder(fn)])


def _skewed_namespaces() -> dict[str, Any]:
    """Endpoint namespace present but at an unsupported version, plus a valid
    validation namespace — the exact shape that triggers a silent fallback."""
    return {
        "endpoint": {"version": 99, "request_body": {"type": "object"}},
        "validation": {"version": 1, "body": _Body},
    }


def _clean_namespaces() -> dict[str, Any]:
    return {"endpoint": {"version": 1, "request_body": {"type": "object"}}}


@pytest.fixture(autouse=True)
def _isolate_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


# ---------------------------------------------------------------------------
# SpecWarning / WarningCode value object
# ---------------------------------------------------------------------------


class TestSpecWarning:
    def test_warning_code_serialises_as_plain_string(self) -> None:
        assert WarningCode.VERSION_SKEW.value == "version-skew"
        assert str(WarningCode.NAMESPACE_FALLBACK) == "namespace-fallback"

    def test_to_dict_is_json_serialisable(self) -> None:
        warning = SpecWarning(
            code=WarningCode.VERSION_SKEW,
            message="skewed",
            function_name="post::/api/users",
        )
        payload = warning.to_dict()
        assert payload == {
            "code": "version-skew",
            "message": "skewed",
            "function_name": "post::/api/users",
        }
        # Round-trips through json without a custom encoder.
        assert json.loads(json.dumps(payload)) == payload

    def test_warning_is_frozen(self) -> None:
        warning = SpecWarning(code=WarningCode.SPEC_VALIDATION, message="x")
        # Frozen dataclasses raise FrozenInstanceError (an AttributeError
        # subclass); assert the narrow type so unrelated failures don't pass.
        with pytest.raises(dataclasses.FrozenInstanceError):
            warning.message = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# generate_openapi_report
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_report_spec_matches_generate_openapi_spec(self) -> None:
        scan_endpoint_metadata(_make_app(_clean_namespaces()))
        report = generate_openapi_report()
        # Regenerating the plain spec from the same registry must be identical.
        assert report.spec == generate_openapi_spec()

    def test_clean_endpoint_has_no_warnings(self) -> None:
        scan_endpoint_metadata(_make_app(_clean_namespaces()))
        report = generate_openapi_report()
        assert report.warnings == ()

    def test_version_skew_surfaces_structured_warnings(self) -> None:
        scan_endpoint_metadata(_make_app(_skewed_namespaces()))
        report = generate_openapi_report()
        codes = {w.code for w in report.warnings}
        assert WarningCode.VERSION_SKEW in codes
        assert WarningCode.NAMESPACE_FALLBACK in codes
        # Every warning is attributed to the affected operation.
        assert all(w.function_name for w in report.warnings)

    def test_warnings_are_deterministic(self) -> None:
        scan_endpoint_metadata(_make_app(_skewed_namespaces()))
        first = generate_openapi_report().warnings
        second = generate_openapi_report().warnings
        assert first == second


# ---------------------------------------------------------------------------
# #344: injected-registry isolation for report/warnings
# ---------------------------------------------------------------------------


class TestReportRegistryIsolation:
    """Report/warnings must honor an injected registry and never leak skew
    warnings from a polluted global registry (#344)."""

    @staticmethod
    def _clean_registry() -> OpenAPIRegistry:
        isolated = OpenAPIRegistry()
        isolated.set(
            "get::/api/isolated",
            {
                "function_name": "isolated",
                "route": "isolated",
                "method": "get",
                "response": {"200": {"description": "OK"}},
            },
        )
        return isolated

    def test_report_ignores_global_skew_when_registry_injected(self) -> None:
        # Pollute the global registry with version-skew + namespace fallback.
        scan_endpoint_metadata(_make_app(_skewed_namespaces()))
        # Sanity: the default (global) path surfaces the skew.
        global_codes = {w.code for w in generate_openapi_report().warnings}
        assert WarningCode.VERSION_SKEW in global_codes
        # An injected clean registry must not inherit the global skew.
        report = generate_openapi_report(registry=self._clean_registry())
        isolated_codes = {w.code for w in report.warnings}
        assert WarningCode.VERSION_SKEW not in isolated_codes
        assert WarningCode.NAMESPACE_FALLBACK not in isolated_codes

    def test_collect_spec_warnings_honors_injected_registry(self) -> None:
        scan_endpoint_metadata(_make_app(_skewed_namespaces()))
        isolated = self._clean_registry()
        spec = generate_openapi_spec(registry=isolated)
        isolated_codes = {w.code for w in collect_spec_warnings(spec, registry=isolated)}
        assert WarningCode.VERSION_SKEW not in isolated_codes
        assert WarningCode.NAMESPACE_FALLBACK not in isolated_codes
        # Without injection, the same spec still reflects the global skew.
        assert any(
            w.code == WarningCode.VERSION_SKEW for w in collect_spec_warnings(spec)
        )


# ---------------------------------------------------------------------------
# #346: discovery-skipped warnings for unbuildable function builders
# ---------------------------------------------------------------------------


class _UnbuildableBuilder:
    """Mimics a FunctionBuilder whose build() raises (e.g. a trigger-less
    function) so the adapter skips it during discovery."""

    def __init__(self, name: str) -> None:
        # Mirror the real FunctionBuilder, which holds the pre-build name on a
        # private ``_function`` (the only place a failed builder's name lives).
        self._function = MockFunction(name=name, func=lambda req: req, bindings=[])

    def build(self, auth_level: Any = None) -> Any:
        raise ValueError(
            f"Function {self._function.get_function_name()} does not have a trigger"
        )


class TestDiscoverySkippedWarnings:
    """An unbuildable builder must surface a structured discovery-skipped
    warning without aborting the scan (#346)."""

    def test_skipped_builder_surfaces_discovery_warning(self) -> None:
        app = _make_app(_clean_namespaces())
        # Append a trigger-less builder alongside the valid one.
        app._function_builders.append(_UnbuildableBuilder("orphan"))

        scan_endpoint_metadata(app)
        report = generate_openapi_report()

        skipped = [
            w for w in report.warnings if w.code == WarningCode.DISCOVERY_SKIPPED
        ]
        assert len(skipped) == 1
        assert skipped[0].function_name == "orphan"
        # The valid endpoint is still present in the spec (scan not aborted).
        assert report.spec["paths"]

    def test_discovery_warning_honors_injected_registry(self) -> None:
        app = _make_app(_clean_namespaces())
        app._function_builders.append(_UnbuildableBuilder("orphan"))
        scan_endpoint_metadata(app)
        # An injected clean registry has recorded no skips of its own.
        isolated = OpenAPIRegistry()
        spec = generate_openapi_spec(registry=isolated)
        isolated_codes = {
            w.code for w in collect_spec_warnings(spec, registry=isolated)
        }
        assert WarningCode.DISCOVERY_SKIPPED not in isolated_codes
        # The global path still reports the skip.
        assert any(
            w.code == WarningCode.DISCOVERY_SKIPPED
            for w in collect_spec_warnings(spec)
        )

    def test_repeated_scans_do_not_duplicate_discovery_warning(self) -> None:
        # Re-scanning the same app (idempotent like entry registration) must
        # not accumulate duplicate discovery-skipped warnings (#352).
        app = _make_app(_clean_namespaces())
        app._function_builders.append(_UnbuildableBuilder("orphan"))

        scan_endpoint_metadata(app)
        scan_endpoint_metadata(app)
        scan_endpoint_metadata(app)
        report = generate_openapi_report()

        skipped = [
            w for w in report.warnings if w.code == WarningCode.DISCOVERY_SKIPPED
        ]
        assert len(skipped) == 1

    def test_discovery_warning_message_carries_sdk_reason(self) -> None:
        # The build() failure reason must be surfaced in the warning message so
        # operators can act on it, not just a fixed generic string (#352).
        app = _make_app(_clean_namespaces())
        app._function_builders.append(_UnbuildableBuilder("orphan"))
        scan_endpoint_metadata(app)
        report = generate_openapi_report()

        skipped = [
            w for w in report.warnings if w.code == WarningCode.DISCOVERY_SKIPPED
        ]
        assert len(skipped) == 1
        assert "does not have a trigger" in skipped[0].message


# ---------------------------------------------------------------------------
# CLI --fail-on-warnings exit-code gate
# ---------------------------------------------------------------------------


def _args(**overrides: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "title": "API",
        "version": "1.0.0",
        "openapi_version": "3.1",
        "description": None,
        "route_prefix": "/api",
        "strict": False,
        "fail_on_empty_paths": False,
        "fail_on_warnings": False,
        "format": "json",
        "pretty": False,
        "output": None,
        "app": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestCliFailOnWarnings:
    def test_returns_zero_with_warnings_when_flag_absent(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scan_endpoint_metadata(_make_app(_skewed_namespaces()))
        assert handle_generate(_args(fail_on_warnings=False)) == 0
        # Warnings are surfaced on stderr as pure JSON lines (no human-readable
        # prefix) so CI can parse them with jsonlines/jq.
        err_lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
        assert err_lines
        payloads = [json.loads(ln) for ln in err_lines]
        assert any(p.get("code") == "version-skew" for p in payloads)

    def test_returns_two_with_warnings_when_flag_set(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scan_endpoint_metadata(_make_app(_skewed_namespaces()))
        assert handle_generate(_args(fail_on_warnings=True)) == 2

    def test_returns_zero_without_warnings_even_with_flag(self) -> None:
        scan_endpoint_metadata(_make_app(_clean_namespaces()))
        assert handle_generate(_args(fail_on_warnings=True)) == 0

    def test_fail_on_warnings_does_not_write_output(self, tmp_path: Any) -> None:
        # The gate must short-circuit BEFORE the artifact is written, so a
        # wrong-but-plausible spec is never emitted (#345).
        scan_endpoint_metadata(_make_app(_skewed_namespaces()))
        out = tmp_path / "openapi.json"
        rc = handle_generate(_args(fail_on_warnings=True, output=str(out)))
        assert rc == 2
        assert not out.exists()

    def test_output_written_when_flag_absent(self, tmp_path: Any) -> None:
        # Without the gate, warnings do not block the artifact.
        scan_endpoint_metadata(_make_app(_skewed_namespaces()))
        out = tmp_path / "openapi.json"
        rc = handle_generate(_args(fail_on_warnings=False, output=str(out)))
        assert rc == 0
        assert out.exists()
