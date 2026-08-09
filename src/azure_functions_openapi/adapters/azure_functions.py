"""Azure Functions SDK discovery adapter.

This is the **single** place in the package that is allowed to touch Azure
Functions SDK internals. Everything else (spec generation, the registry, the
validation bridge) consumes the neutral, fully-public surface exposed here.

Two SDK facts shape this module:

1. **Enumeration has no public, side-effect-free alternative.**
   ``FunctionRegister.get_functions()`` is *not* idempotent: it funnels through
   ``validate_function_names()``, which accumulates into ``self.functions_bindings``
   and only initializes that dict when it is falsy (``function_app.py``, verified
   on azure-functions 1.21–1.25). Calling it more than once raises
   ``ValueError: Function <name> does not have a unique function name``. Because
   :func:`azure_functions_openapi.bridge.scan_endpoint_metadata` is meant to run
   at import time inside ``function_app.py``, calling ``get_functions()`` there
   would poison ``functions_bindings`` and then the Azure worker's own indexing
   (which also calls ``get_functions()``) would raise — the user's Function App
   would fail to boot. **We therefore never call ``get_functions()``.**

   The only enumeration primitive left is reading ``app._function_builders`` and
   calling the *public*, idempotent :meth:`FunctionBuilder.build`. ``build`` runs
   the guarded, apply-once ``_validate_function`` and returns the *same*
   ``Function`` instance on every call, without touching ``functions_bindings``.
   ``_function_builders`` is thus the one — and only — SDK-private token we keep,
   and it lives exclusively in this module. ``Blueprint`` is a ``DecoratorApi``
   and exposes ``_function_builders`` identically, so raw Blueprints, registered
   Blueprints, and ``FunctionApp`` instances all enumerate through this one path.

2. **Per-function reads are entirely public.** Once a builder is built into a
   ``Function``, the name, user handler, bindings, HTTP-ness, and trigger are all
   available through documented public accessors — no ``_function`` / ``_func`` /
   ``_bindings`` access is required anywhere.

See issue #325 for the full rationale and empirical reproduction.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any, cast

from azure.functions.decorators.function_app import Function, FunctionBuilder

from azure_functions_openapi.exceptions import SDKIncompatibleError

_logger = logging.getLogger(__name__)

_HTTP_TRIGGER_TYPE = "httptrigger"


def is_function_builder(obj: Any) -> bool:
    """Return whether *obj* is an Azure Functions ``FunctionBuilder``.

    Centralizes the SDK-type check so callers never import ``FunctionBuilder``
    themselves.
    """
    return isinstance(obj, FunctionBuilder)


def build_function(builder: Any, auth_level: Any = None) -> Function:
    """Build a single ``FunctionBuilder`` into a ``Function`` (idempotent).

    Wraps :meth:`FunctionBuilder.build`, the public, side-effect-free primitive
    that returns the same cached ``Function`` on every call. Raises
    :class:`SDKIncompatibleError` if the installed SDK does not expose ``build``
    or it fails structurally, so incompatibility surfaces as an actionable error
    rather than an opaque ``AttributeError``.
    """
    try:
        return cast(Function, builder.build(auth_level))
    except AttributeError as exc:  # pragma: no cover - depends on SDK internals
        raise SDKIncompatibleError(
            "Unable to build a FunctionBuilder via the public build() API; the "
            "installed azure-functions SDK appears incompatible with @openapi. "
            "Please report this issue at "
            "https://github.com/yeongseon/azure-functions-openapi-python/issues "
            f"with your azure-functions version. (underlying error: {exc})"
        ) from exc


def iter_functions(
    app: Any, on_skip: Callable[[str | None, str], None] | None = None
) -> list[Function]:
    """Enumerate the built ``Function`` objects registered on *app*.

    Enumerates via the SDK-private ``_function_builders`` list (the only
    private token we are forced to read — see the module docstring) and the
    *public*, idempotent :meth:`FunctionBuilder.build`. It deliberately does
    **not** call ``FunctionApp.get_functions()``, which is non-idempotent and
    would poison the app's ``functions_bindings`` indexing state and break the
    user's Function App at boot.

    Skips any builder whose :meth:`FunctionBuilder.build` raises ``ValueError``
    (e.g. a function with no trigger, or a trigger not present in its bindings).
    Such a function is a *user app state*, not an SDK incompatibility, so it is
    logged at debug and omitted rather than aborting the whole scan. Returns an
    empty list when *app* exposes no builders (e.g. an app with no registered
    functions), matching the previous "skip quietly" behaviour.

    When *on_skip* is provided it is invoked as ``on_skip(function_name, reason)``
    for each skipped builder (name is best-effort and may be ``None`` when the
    pre-build name is unavailable), letting callers record the omission as a
    structured warning instead of losing it to a debug log.
    """
    builders = getattr(app, "_function_builders", None)
    if not builders:
        return []
    auth_level = getattr(app, "auth_level", None)
    functions: list[Function] = []
    for builder in builders:
        try:
            functions.append(build_function(builder, auth_level))
        except ValueError as exc:  # no trigger / trigger not in bindings
            _logger.debug("Skipping unbuildable function during discovery: %s", exc)
            if on_skip is not None:
                on_skip(_best_effort_builder_name(builder), str(exc))
    return functions


def _best_effort_builder_name(builder: Any) -> str | None:
    """Best-effort function name for a builder that failed to build.

    A builder whose ``build()`` raises never produces a ``Function``, so the
    public per-function accessors are unavailable. The name a user assigned via
    ``@function_name`` still lives on the builder's ``_function``; this reads it
    defensively for the sole purpose of attributing a ``discovery-skipped``
    warning. It is the one place besides ``_function_builders`` enumeration that
    reaches for a private token, and only for an already-skipped builder — every
    lookup is guarded and falls back to ``None`` so a shape change never breaks
    discovery; the skip is still recorded, just without a name.
    """
    function = getattr(builder, "_function", None)
    getter = getattr(function, "get_function_name", None)
    if not callable(getter):
        return None
    try:
        name = getter()
    except Exception:  # pragma: no cover - defensive; name is best-effort only
        return None
    return str(name) if name is not None else None


def get_function_name(function: Any) -> str:
    """Return the function's registered name via the public accessor."""
    return str(function.get_function_name())


def get_user_handler(function: Any) -> Any:
    """Return the user's handler callable via the public accessor."""
    return function.get_user_function()


def get_bindings(function: Any) -> list[Any]:
    """Return the function's bindings via the public accessor."""
    return list(function.get_bindings())


def is_http_function(function: Any) -> bool:
    """Return whether the function is HTTP-triggered via the public accessor."""
    return bool(function.is_http_function())


def extract_http_binding(function: Any) -> Any | None:
    """Return the function's HTTP-trigger binding, or ``None`` if it has none.

    Scans the public :meth:`Function.get_bindings` result for the HTTP-trigger
    binding, mirroring the previous private ``_bindings`` scan but without any
    SDK-private access.
    """
    for binding in get_bindings(function):
        if str(getattr(binding, "type", "")).lower() == _HTTP_TRIGGER_TYPE:
            return binding
    return None
