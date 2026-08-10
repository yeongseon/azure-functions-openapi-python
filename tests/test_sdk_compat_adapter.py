"""Adapter-boundary SDK compatibility contract and guard tests (issue #327).

After the adapter isolation (#325), all Azure Functions SDK discovery flows
through :mod:`azure_functions_openapi.adapters.azure_functions`. This module
pins that contract against the *installed* SDK so the CI matrix
(``azure-functions`` 1.21 → latest ``<2.0``, Python 3.10–3.14) proves the
package works on every supported line before the ``<2.0.0`` ceiling is ever
relaxed.

Verified support matrix (enforced by CI; see ``pyproject.toml`` pin
``azure-functions>=1.21.0,<2.0.0`` and the README "SDK Compatibility" table):

    azure-functions | Python
    --------------- | ----------------------------
    1.21.0 (floor)  | 3.10
    1.24.0          | 3.10
    latest (<2.0)   | 3.10, 3.11, 3.12, 3.13, 3.14

Three guarantees are asserted here:

* **Mandatory private-token guard** — enumeration has no public substitute, so
  ``app._function_builders`` (and each builder's callable ``build``) must exist.
  This guard is *unconditional*: the adapter always depends on that single
  private structure, and it must fail loudly if the SDK ever drops it.
* **Contract tests through the adapter boundary** — route/method/handler
  discovery works via the public ``build()`` + ``Function`` accessors, and
  ``get_functions()`` is *never* invoked (it is non-idempotent and would poison
  the worker's indexing state).
* **Public-API-only discovery** — a minimal fake builder exposing only the
  documented public surface (no ``_function`` / ``_func`` / ``_bindings``)
  drives the full adapter, proving no finer-grained private access is needed.
"""

from __future__ import annotations

import importlib.metadata as _metadata
from typing import Any
from unittest import mock

import azure.functions as func
import pytest

from azure_functions_openapi import adapters


def _make_app() -> Any:
    """A real FunctionApp with one HTTP route, for SDK-shape contract tests."""
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="users/{id}", methods=["PUT"])
    def update_user(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=200)

    return app


# ---------------------------------------------------------------------------
# Installed-version sanity
# ---------------------------------------------------------------------------


def test_installed_sdk_is_within_supported_matrix() -> None:
    """The installed SDK must satisfy the ``>=1.21.0,<2.0.0`` pin."""
    installed = _metadata.version("azure-functions")
    major_minor = tuple(int(p) for p in installed.split(".")[:2])
    assert major_minor >= (1, 21), (
        f"azure-functions {installed} is below the >=1.21.0 floor in "
        "pyproject.toml. The floor exists because earlier releases return None "
        "from FunctionBuilder.__call__. See issue #327."
    )
    assert major_minor < (2, 0), (
        f"azure-functions {installed} is above the <2.0.0 ceiling. The ceiling "
        "is only widened after the #327 compatibility matrix is green."
    )


# ---------------------------------------------------------------------------
# Mandatory private-token guard (unconditional)
# ---------------------------------------------------------------------------


def test_function_builders_private_token_exists_and_is_shaped() -> None:
    """MANDATORY guard: ``_function_builders`` + callable ``build`` must exist.

    Enumeration has no public substitute, so this is the one private structure
    the adapter is permitted to depend on. If a future SDK removes or reshapes
    it, this test fails loudly — pointing maintainers at the adapter before
    end-users hit an import-time break.
    """
    app = _make_app()
    assert hasattr(app, "_function_builders"), (
        "FunctionApp no longer exposes '_function_builders' — the adapter's "
        "only enumeration primitive is gone. See issue #327."
    )
    builders = app._function_builders
    assert builders, "Expected at least one registered FunctionBuilder."
    for builder in builders:
        assert callable(getattr(builder, "build", None)), (
            "FunctionBuilder no longer exposes a callable 'build' — the public, "
            "idempotent enumeration primitive is gone. See issue #327."
        )


# ---------------------------------------------------------------------------
# Contract tests through the adapter boundary
# ---------------------------------------------------------------------------


def test_iter_functions_discovers_route_method_and_handler() -> None:
    """Route/method/handler discovery works through the adapter boundary."""
    app = _make_app()

    functions = adapters.iter_functions(app)

    assert len(functions) == 1
    fn = functions[0]
    assert adapters.get_function_name(fn) == "update_user"
    assert adapters.is_http_function(fn) is True
    assert callable(adapters.get_user_handler(fn))

    binding = adapters.extract_http_binding(fn)
    assert binding is not None
    assert binding.route == "users/{id}"
    assert [str(getattr(m, "value", m)).upper() for m in binding.methods] == ["PUT"]


def test_iter_functions_never_invokes_get_functions() -> None:
    """The adapter must not call the non-idempotent ``get_functions()``."""
    app = _make_app()
    sentinel = mock.Mock(side_effect=AssertionError("get_functions must never be called"))

    with mock.patch.object(app, "get_functions", sentinel):
        functions = adapters.iter_functions(app)

    assert functions, "Discovery must still succeed via the build() path."
    sentinel.assert_not_called()


def _http_binding_signature(fn: Any) -> tuple[str | None, tuple[str, ...]]:
    """Observable HTTP-binding shape (route + sorted methods) for a Function."""
    binding = adapters.extract_http_binding(fn)
    if binding is None:
        return (None, ())
    methods = tuple(sorted(str(getattr(m, "value", m)).upper() for m in binding.methods))
    return (binding.route, methods)


def test_iter_functions_is_idempotent_and_leaves_indexing_state_clean() -> None:
    """Repeated enumeration returns the same cached Function and does not poison
    the SDK's ``functions_bindings`` indexing state."""
    app = _make_app()

    first = adapters.iter_functions(app)
    second = adapters.iter_functions(app)

    # Idempotent in the way callers actually depend on: repeated enumeration
    # yields the same observable functions (stable count, names, and HTTP
    # bindings). We deliberately do NOT assert object identity (``first[0] is
    # second[0]``) — a future ``azure-functions`` release may hand back a fresh
    # ``Function`` object each call while remaining functionally idempotent, and
    # pinning identity would make the compatibility matrix needlessly fragile.
    assert len(first) == len(second)
    assert [adapters.get_function_name(f) for f in first] == [
        adapters.get_function_name(f) for f in second
    ]
    assert [_http_binding_signature(f) for f in first] == [
        _http_binding_signature(f) for f in second
    ]

    # A single get_functions() call still succeeds afterwards — proof that the
    # adapter left the worker's indexing state untouched. (get_functions itself
    # is non-idempotent, so we call it exactly once here.)
    names = [f.get_function_name() for f in app.get_functions()]
    assert "update_user" in names


# ---------------------------------------------------------------------------
# Public-API-only discovery (no private attributes beyond _function_builders)
# ---------------------------------------------------------------------------


class _FakeBinding:
    type = "httpTrigger"
    route = "ping"
    methods = ["GET"]


class _FakeFunction:
    """A Function stand-in exposing ONLY the public accessor surface."""

    def get_function_name(self) -> str:
        return "ping"

    def get_user_function(self) -> Any:
        return lambda req: req

    def get_bindings(self) -> list[Any]:
        return [_FakeBinding()]

    def is_http_function(self) -> bool:
        return True


class _FakeBuilder:
    def build(self, auth_level: Any = None) -> _FakeFunction:
        return _FakeFunction()


class _FakeApp:
    _function_builders = [_FakeBuilder()]
    auth_level = None


def test_adapter_drives_discovery_through_public_accessors_only() -> None:
    """A fake exposing only the public API drives the full adapter path.

    ``_FakeFunction`` deliberately omits ``_function`` / ``_func`` /
    ``_bindings``; if the adapter still works end-to-end, it proves discovery
    needs no private attribute beyond the ``_function_builders`` enumeration
    token.
    """
    app = _FakeApp()

    functions = adapters.iter_functions(app)

    assert len(functions) == 1
    fn = functions[0]
    assert adapters.get_function_name(fn) == "ping"
    assert adapters.is_http_function(fn) is True
    assert adapters.get_bindings(fn)[0].route == "ping"
    ping_binding = adapters.extract_http_binding(fn)
    assert ping_binding is not None
    assert ping_binding.route == "ping"
    assert callable(adapters.get_user_handler(fn))


def test_iter_functions_returns_empty_for_app_without_builders() -> None:
    """An app with no registered functions enumerates to an empty list."""

    class _EmptyApp:
        _function_builders: list[Any] = []
        auth_level = None

    assert adapters.iter_functions(_EmptyApp()) == []


def test_iter_functions_unwraps_wrapping_container_app() -> None:
    """Regression (#374): a container that wraps a FunctionApp is unwrapped.

    ``LangGraphApp`` does not subclass ``FunctionApp``; it holds the real app
    lazily and exposes it via a ``.function_app`` property. The outer object has
    no ``_function_builders`` of its own, so discovery must unwrap to the inner
    app and enumerate its builders.
    """

    class _WrapperApp:
        def __init__(self) -> None:
            self._inner = _FakeApp()

        @property
        def function_app(self) -> _FakeApp:
            return self._inner

    functions = adapters.iter_functions(_WrapperApp())

    assert len(functions) == 1
    assert adapters.get_function_name(functions[0]) == "ping"


def test_iter_functions_returns_empty_when_wrapped_app_also_empty() -> None:
    """A wrapper whose inner app has no builders still enumerates to empty."""

    class _EmptyInner:
        _function_builders: list[Any] = []
        auth_level = None

    class _WrapperApp:
        function_app = _EmptyInner()

    assert adapters.iter_functions(_WrapperApp()) == []


def test_iter_functions_skips_builder_that_fails_to_build() -> None:
    """Regression (#337): a trigger-less builder is skipped, not fatal.

    ``FunctionBuilder.build()`` raises ``ValueError`` for a function with no
    trigger. Before #337 that ``ValueError`` propagated out of
    ``iter_functions`` and aborted the entire scan, breaking the user's
    Function App at import time. The adapter must skip the unbuildable builder
    and still return the validly-built functions.
    """
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="healthy", methods=["GET"])
    def healthy(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=200)

    @app.function_name(name="orphan")  # builder with no trigger decorator
    def orphan(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("nope")

    functions = adapters.iter_functions(app)

    names = [adapters.get_function_name(fn) for fn in functions]
    assert names == ["healthy"]


def test_iter_functions_reports_skipped_builder_via_on_skip() -> None:
    """A skipped builder is surfaced through the ``on_skip`` callback (#346).

    Skipping keeps the scan alive (regression #337), but the omission must not
    vanish silently: ``iter_functions`` invokes ``on_skip(name, reason)`` for
    each unbuildable builder so callers can record a structured warning. The
    best-effort name comes from the public ``function_name`` decorator.
    """
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="healthy", methods=["GET"])
    def healthy(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=200)

    @app.function_name(name="orphan")  # builder with no trigger decorator
    def orphan(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("nope")

    skipped: list[tuple[str | None, str]] = []
    functions = adapters.iter_functions(app, on_skip=lambda n, r: skipped.append((n, r)))

    assert [adapters.get_function_name(fn) for fn in functions] == ["healthy"]
    assert len(skipped) == 1
    name, reason = skipped[0]
    assert name == "orphan"
    assert reason

    names = [adapters.get_function_name(fn) for fn in functions]
    assert names == ["healthy"]


@pytest.mark.parametrize("bad_type", ["queueTrigger", "timerTrigger", ""])
def test_extract_http_binding_ignores_non_http_triggers(bad_type: str) -> None:
    """Only httpTrigger bindings are returned; other trigger types yield None."""

    class _Binding:
        type = bad_type
        route = "x"
        methods = ["GET"]

    class _Fn:
        def get_bindings(self) -> list[Any]:
            return [_Binding()]

    assert adapters.extract_http_binding(_Fn()) is None
