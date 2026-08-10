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
from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    openapi,
    register_openapi_metadata,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.registry import registry as default_registry
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
        "isolate_app": False,
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

    def test_empty_paths_hint_survives_and_priority_preserved(
        self, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # #353: when warnings AND empty paths coincide, the --fail-on-warnings
        # gate must not pre-empt the empty-paths diagnostic. The hint must still
        # print, --fail-on-empty-paths must remain reachable (exit 1), and no
        # artifact may be written.
        app = MockApp([_UnbuildableBuilder("orphan")])
        scan_endpoint_metadata(app)
        out = tmp_path / "openapi.json"
        rc = handle_generate(
            _args(
                fail_on_warnings=True,
                fail_on_empty_paths=True,
                output=str(out),
            )
        )
        assert rc == 1
        assert not out.exists()
        assert "Hint: use --app" in capsys.readouterr().err

    def test_empty_paths_hint_adapts_when_app_was_provided(
        self, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # When the user already passed --app, the circular "use --app" hint is
        # misleading; the diagnostic should instead explain that the app
        # imported cleanly but exposes no @openapi-decorated routes.
        # Use a real importable module with no ':variable' so the import
        # succeeds (discovery is skipped) and the registry stays empty.
        out = tmp_path / "openapi.json"
        rc = handle_generate(
            _args(app="os", fail_on_empty_paths=True, output=str(out))
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "Hint: use --app" not in err
        assert "no" in err and "@openapi-decorated routes" in err


# ---------------------------------------------------------------------------
# #386: duplicate-operation warnings for METHOD path collisions
# ---------------------------------------------------------------------------


def _dup_entry(function_name: str) -> dict[str, Any]:
    return {
        "function_name": function_name,
        "route": "dup",
        "method": "post",
        "response": {"200": {"description": "OK"}},
    }


class TestDuplicateOperationWarnings:
    """Two registrations colliding on the same METHOD path must surface a
    structured duplicate-operation warning; only the last operation wins, and
    ``--fail-on-warnings`` must observe the silently dropped operation (#386)."""

    @staticmethod
    def _colliding_registry() -> OpenAPIRegistry:
        reg = OpenAPIRegistry()
        # Distinct registry keys that both resolve to POST /api/dup, so the
        # spec merge (not the registry) is what collapses them.
        reg.set("first", _dup_entry("first"))
        reg.set("second", _dup_entry("second"))
        return reg

    def test_duplicate_yields_single_structured_warning(self) -> None:
        reg = self._colliding_registry()
        spec = generate_openapi_spec(registry=reg)
        dups = [
            w
            for w in collect_spec_warnings(spec, registry=reg)
            if w.code == WarningCode.DUPLICATE_OPERATION
        ]
        assert len(dups) == 1
        assert "POST /api/dup" in dups[0].message

    def test_last_operation_wins_in_spec(self) -> None:
        reg = self._colliding_registry()
        spec = generate_openapi_spec(registry=reg)
        # The merge keeps exactly one POST operation for the shared path.
        path_item = spec["paths"]["/api/dup"]
        assert list(path_item.keys()) == ["post"]
        # "Last wins" must be verified, not just "one survives": the surviving
        # operation must be the second registration, so its operationId reflects
        # ``second`` rather than the overwritten ``first``.
        assert path_item["post"]["operationId"] == "post_second"

    def test_strict_mode_still_raises(self) -> None:
        reg = self._colliding_registry()
        with pytest.raises(OpenAPISpecConfigError):
            generate_openapi_spec(registry=reg, strict=True)

    def test_no_duplicate_warning_without_collision(self) -> None:
        reg = OpenAPIRegistry()
        reg.set("only", _dup_entry("only"))
        spec = generate_openapi_spec(registry=reg)
        codes = {w.code for w in collect_spec_warnings(spec, registry=reg)}
        assert WarningCode.DUPLICATE_OPERATION not in codes

    def test_fail_on_warnings_catches_dropped_operation(self) -> None:
        # The global CLI path must exit non-zero: a silently dropped operation
        # is exactly what --fail-on-warnings exists to catch.
        default_registry.set("first", _dup_entry("first"))
        default_registry.set("second", _dup_entry("second"))
        assert handle_generate(_args(fail_on_warnings=True)) == 2

    def test_resolved_collision_not_carried_to_next_generation(self) -> None:
        # #393: diagnostics are run-scoped. A DUPLICATE_OPERATION observed in one
        # generation must not linger on the registry and resurface after the
        # collision is resolved, even when the same (long-lived) registry is
        # reused for a second generation.
        reg = self._colliding_registry()
        first = collect_spec_warnings(generate_openapi_spec(registry=reg), registry=reg)
        assert any(w.code == WarningCode.DUPLICATE_OPERATION for w in first)

        # Resolve the collision by moving one operation to a distinct path, then
        # regenerate against the SAME registry.
        reg.set("second", {**_dup_entry("second"), "route": "dup-fixed"})
        second = collect_spec_warnings(generate_openapi_spec(registry=reg), registry=reg)
        assert not any(w.code == WarningCode.DUPLICATE_OPERATION for w in second)

    def test_programmatic_reregistration_is_last_writer_wins(self) -> None:
        # #397 (by design): a method+path pair is a single OpenAPI operation, so
        # re-registering it replaces the prior entry rather than raising. This
        # powers the scan-then-enrich pattern where the bridge seeds a minimal
        # entry and the caller overrides it with richer metadata. Exactly one
        # entry survives, and it is the last registration.
        reg = OpenAPIRegistry()
        register_openapi_metadata(
            path="/api/dup", method="POST", summary="first", registry=reg
        )
        register_openapi_metadata(
            path="/api/dup", method="POST", summary="second", registry=reg
        )
        snapshot = reg.snapshot()
        assert len(snapshot) == 1
        assert snapshot["post::/api/dup"]["summary"] == "second"
        # A single surviving entry means no duplicate-operation warning: there is
        # no second operation for the shared path to collide with.
        spec = generate_openapi_spec(registry=reg)
        codes = {w.code for w in collect_spec_warnings(spec, registry=reg)}
        assert WarningCode.DUPLICATE_OPERATION not in codes


# ---------------------------------------------------------------------------
# #381: app-scoped (isolated) registry
# ---------------------------------------------------------------------------


def _decorated_app(
    *,
    fn_name: str,
    route: str,
    method: str = "POST",
    summary: str = "",
) -> MockApp:
    """Build a MockApp whose single handler carries a plain ``@openapi`` entry.

    Decorating registers a canonical entry in the *global* registry at call
    time (mirroring import-time registration), while the returned app exposes
    an HTTP binding so the scanner can reconcile it. A distinct ``__qualname__``
    keeps each handler's ``_function_id`` unique across apps.
    """

    def handler(req: Any) -> Any:
        return req

    # Rename BEFORE decorating: @openapi keys the global entry by ``__name__``
    # and derives ``_function_id`` from ``__qualname__`` at decoration time, so
    # distinct names are required to avoid two apps colliding on one entry.
    handler.__name__ = fn_name
    handler.__qualname__ = f"_decorated_app.<locals>.{fn_name}"
    decorated = openapi(summary=summary, method=method, route=route)(handler)
    binding = MockBinding(route=route, methods=[method.upper()])
    fn = MockFunction(name=fn_name, func=decorated, bindings=[binding])
    return MockApp([MockBuilder(fn)])


def _binding_only_app(
    *,
    fn_name: str,
    route: str,
    method: str = "POST",
    qual_prefix: str = "_binding_only_app.<locals>",
    func: Any = None,
) -> MockApp:
    """Build a MockApp whose handler is decorated WITHOUT method/route.

    Unlike :func:`_decorated_app`, ``@openapi`` records a ``method=None`` /
    ``route=None`` canonical entry; the HTTP verb and path come only from the
    binding. This is the shape that makes reconciliation *explode* the canonical
    into a per-method ``method::path`` entry and delete the original key, which is
    the precondition for the #388 isolated re-scan phantom regression.

    Passing ``func`` reuses an already-decorated handler (same ``_function_id``),
    so a Blueprint and the app that registers it can be modelled as two builders
    over one handler.
    """
    if func is None:

        def handler(req: Any) -> Any:
            return req

        handler.__name__ = fn_name
        handler.__qualname__ = f"{qual_prefix}.{fn_name}"
        func = openapi(summary=fn_name)(handler)
    binding = MockBinding(route=route, methods=[method.upper()])
    fn = MockFunction(name=fn_name, func=func, bindings=[binding])
    return MockApp([MockBuilder(fn)])


class TestIsolatedRegistry:
    def test_isolated_scan_excludes_other_apps_openapi(self) -> None:
        # Two apps register @openapi entries globally at decoration time. An
        # isolated scan of app_a must document ONLY app_a's route, never leaking
        # app_b's globally-registered entry into app_a's spec (#381).
        app_a = _decorated_app(fn_name="a_handler", route="a/one", summary="A")
        _decorated_app(fn_name="b_handler", route="b/one", summary="B")

        iso = OpenAPIRegistry()
        scan_endpoint_metadata(app_a, registry=iso)
        spec = generate_openapi_spec(registry=iso)

        assert "/api/a/one" in spec["paths"]
        assert "/api/b/one" not in spec["paths"]

    def test_global_default_scan_still_sees_all_entries(self) -> None:
        # Baseline: without an injected registry, the shared global registry is
        # used, so a global generate still reflects every registered route.
        _decorated_app(fn_name="a_handler", route="a/one")
        app_b = _decorated_app(fn_name="b_handler", route="b/one")

        scan_endpoint_metadata(app_b)
        spec = generate_openapi_spec()

        # Both @openapi entries were registered globally at decoration time.
        assert "/api/a/one" in spec["paths"]
        assert "/api/b/one" in spec["paths"]

    def test_isolated_scan_leaves_global_registry_untouched(self) -> None:
        app_a = _decorated_app(fn_name="a_handler", route="a/one")
        iso = OpenAPIRegistry()
        scan_endpoint_metadata(app_a, registry=iso)

        # Seeding deep-copies the global entry into the isolated registry; the
        # global one must remain intact for a subsequent global generate.
        global_spec = generate_openapi_spec()
        assert "/api/a/one" in global_spec["paths"]

    def test_discovery_warnings_isolated_to_target_registry(self) -> None:
        # An unbuildable builder scanned into an isolated registry records its
        # discovery-skipped warning on that registry, not the global one.
        app = _decorated_app(fn_name="a_handler", route="a/one")
        app._function_builders.append(_UnbuildableBuilder("orphan"))

        iso = OpenAPIRegistry()
        scan_endpoint_metadata(app, registry=iso)

        iso_spec = generate_openapi_spec(registry=iso)
        iso_warnings = collect_spec_warnings(iso_spec, registry=iso)
        global_warnings = collect_spec_warnings(generate_openapi_spec())

        assert any(w.code == WarningCode.DISCOVERY_SKIPPED for w in iso_warnings)
        assert not any(
            w.code == WarningCode.DISCOVERY_SKIPPED for w in global_warnings
        )

    def test_programmatic_entries_not_seeded_into_isolated_registry(self) -> None:
        # Programmatic register_openapi_metadata entries are not tied to any
        # scanned app object and must never leak into an isolated app spec.
        register_openapi_metadata(path="/api/prog", method="GET", summary="prog")
        app_a = _decorated_app(fn_name="a_handler", route="a/one")

        iso = OpenAPIRegistry()
        scan_endpoint_metadata(app_a, registry=iso)
        spec = generate_openapi_spec(registry=iso)

        assert "/api/a/one" in spec["paths"]
        assert "/api/prog" not in spec["paths"]

    def test_isolated_rescan_is_idempotent(self) -> None:
        # #388 regression: scanning the SAME app twice into one isolated registry
        # must not fabricate a phantom endpoint. Reconciliation explodes the
        # seeded method=None canonical into a method::path entry and deletes the
        # original key; a second scan that re-seeds purely because that key is
        # gone would resurrect a stale route=None canonical, which spec.py then
        # documents as GET /api/<function-name>. Seeding must be idempotent.
        app = _binding_only_app(fn_name="handler_one", route="users/create")
        iso = OpenAPIRegistry()

        scan_endpoint_metadata(app, registry=iso)
        first = generate_openapi_spec(registry=iso)
        assert sorted(first["paths"]) == ["/api/users/create"]

        scan_endpoint_metadata(app, registry=iso)
        second = generate_openapi_spec(registry=iso)
        # No phantom: the second scan yields byte-for-byte the same paths.
        assert sorted(second["paths"]) == ["/api/users/create"]
        assert "/api/handler_one" not in second["paths"]

    def test_isolated_shared_handler_scan_no_phantom(self) -> None:
        # #388 regression, single-call form: a Blueprint and the app that
        # registers it expose the SAME handler, so a single isolated generate
        # scans that handler twice (once per builder). Sharing one _function_id
        # must still reconcile to one operation -- not seed a phantom that also
        # trips a duplicate operationId during validation.
        def handler(req: Any) -> Any:
            return req

        handler.__name__ = "bph"
        handler.__qualname__ = "test_shared.bph"
        decorated = openapi(summary="bph")(handler)
        blueprint = _binding_only_app(fn_name="bph", route="bp/one", func=decorated)
        app = _binding_only_app(fn_name="bph", route="bp/one", func=decorated)

        iso = OpenAPIRegistry()
        scan_endpoint_metadata(blueprint, registry=iso)
        scan_endpoint_metadata(app, registry=iso)
        spec = generate_openapi_spec(registry=iso)

        assert sorted(spec["paths"]) == ["/api/bp/one"]
        assert sorted(spec["paths"]["/api/bp/one"]) == ["post"]


class TestCliIsolateApp:
    def test_isolate_app_ignored_without_variable(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # --isolate-app requires 'module:variable'. With a bare module it is a
        # no-op that warns and falls back to the global registry.
        rc = handle_generate(_args(app="os", isolate_app=True))
        assert rc == 0
        assert "--isolate-app ignored" in capsys.readouterr().err

    def test_isolate_app_scopes_spec_to_selected_app(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # End-to-end: a module exposing two apps generates a spec for only the
        # selected app when --isolate-app is set.
        module_src = (
            "from typing import Any\n"
            "from azure_functions_openapi.decorator import openapi\n"
            "from tests.test_spec_warnings import (\n"
            "    MockApp, MockBinding, MockBuilder, MockFunction,\n"
            ")\n"
            "\n"
            "def _mk(fn_name, route):\n"
            "    def handler(req: Any) -> Any:\n"
            "        return req\n"
            "    handler.__name__ = fn_name\n"
            "    handler.__qualname__ = 'twoapp_' + fn_name\n"
            "    decorated = openapi(summary=fn_name, method='POST', route=route)(handler)\n"
            "    b = MockBinding(route=route, methods=['POST'])\n"
            "    f = MockFunction(name=fn_name, func=decorated, bindings=[b])\n"
            "    return MockApp([MockBuilder(f)])\n"
            "\n"
            "app_a = _mk('twoapp_a', 'a/one')\n"
            "app_b = _mk('twoapp_b', 'b/one')\n"
        )
        mod_path = tmp_path / "twoapp_iso.py"
        mod_path.write_text(module_src, encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))

        out = tmp_path / "a.json"
        rc = handle_generate(
            _args(app="twoapp_iso:app_a", isolate_app=True, output=str(out))
        )
        assert rc == 0
        spec = json.loads(out.read_text(encoding="utf-8"))
        assert "/api/a/one" in spec["paths"]
        assert "/api/b/one" not in spec["paths"]
