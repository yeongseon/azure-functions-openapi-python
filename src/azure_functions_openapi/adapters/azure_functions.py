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
   ``_function_builders`` is the primary SDK-private token we keep, and it lives
   exclusively in this module. ``Blueprint`` is a ``DecoratorApi`` and exposes
   ``_function_builders`` identically, so raw Blueprints, registered Blueprints,
   and ``FunctionApp`` instances all enumerate through this one path.

2. **Per-function reads are entirely public.** Once a builder is built into a
   ``Function``, the name, user handler, bindings, HTTP-ness, and trigger are all
   available through documented public accessors — no ``_function`` / ``_func`` /
   ``_bindings`` access is required for a built function. The **one** exception is
   :func:`_best_effort_builder_name`, which reads a *failed* builder's
   ``_function`` solely to attribute a ``discovery-skipped`` warning (a builder
   that never built exposes no public name); that read is guarded and falls back
   to ``None``. See its docstring for the rationale.

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


_WRAPPED_APP_ATTRS = ("function_app", "_function_app", "app", "_app")


def _unwrap_function_app(app: Any) -> Any | None:
    """Return an inner ``FunctionApp``-like object wrapped by *app*, or ``None``.

    Some container apps do **not** subclass ``FunctionApp``; they hold the real
    app and expose it through a property (e.g. ``LangGraphApp.function_app``).
    When the outer object exposes no builders of its own, look for a wrapped
    inner app that does — without importing the wrapper type. Only an inner
    object that actually carries a non-empty ``_function_builders`` list is
    accepted, and the outer object itself is never returned, so this can never
    loop or mistake an unrelated attribute for the app.
    """
    for attr in _WRAPPED_APP_ATTRS:
        inner = getattr(app, attr, None)
        if inner is None or inner is app:
            continue
        if getattr(inner, "_function_builders", None):
            return inner
    return None


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
    skipped rather than raising. Returns an empty list when *app* exposes
    no builders (e.g. an app with no registered functions). When the app
    itself carries no builders but wraps a real
    ``FunctionApp`` via a property (e.g. ``LangGraphApp.function_app``), the
    inner app is unwrapped and enumerated (#374); a truly empty app still
    returns an empty list, matching the previous "skip quietly" behaviour.

    When *on_skip* is provided it is invoked as ``on_skip(function_name, reason)``
    for each skipped builder (name is best-effort and may be ``None`` when the
    pre-build name is unavailable), letting callers record the omission as a
    structured warning instead of losing it to a debug log.
    """
    builders = getattr(app, "_function_builders", None)
    if not builders:
        # #374: the object may be a container that wraps a real FunctionApp
        # (e.g. LangGraphApp exposes it via a ``.function_app`` property) rather
        # than subclassing it. Unwrap to the inner app before giving up.
        inner = _unwrap_function_app(app)
        if inner is not None:
            app = inner
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


def get_unbuilt_user_handler(builder: Any) -> Callable[..., Any] | None:
    """Return a builder's user handler *without* building it, or ``None``.

    When ``@openapi`` is applied below ``@app.route`` (a valid ordering that
    0.20.0 accepted), the builder has no trigger yet and
    :meth:`FunctionBuilder.build` raises ``ValueError``. The underlying user
    handler still lives on the builder's ``_function`` and is reachable via the
    public :meth:`Function.get_user_function` accessor on that wrapped object.
    This mirrors the defensive, guarded read in :func:`_best_effort_builder_name`
    so a shape change never breaks decoration; it simply falls back to ``None``.

    Inspecting the builder here has no side effects, so a later
    :meth:`FunctionBuilder.build` (once the outer ``@app.route`` applies the
    trigger) remains valid and idempotent.
    """
    function = getattr(builder, "_function", None)
    get_user_function = getattr(function, "get_user_function", None)
    if not callable(get_user_function):
        return None
    try:
        handler = get_user_function()
    except Exception:  # pragma: no cover - defensive; handler is best-effort
        return None
    return handler if callable(handler) else None


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


def extract_auth_level(binding: Any) -> str | None:
    """Return the HTTP-trigger binding's ``auth_level`` as a lowercase string.

    Azure Functions exposes the per-route auth level (declared via
    ``@app.route(auth_level=...)``) on the HTTP-trigger binding as an
    ``AuthLevel`` enum (e.g. ``AuthLevel.FUNCTION``). We normalize it to the
    enum's lowercase string value (``"anonymous"`` / ``"function"`` /
    ``"admin"``) so downstream consumers never import the SDK enum. Returns
    ``None`` when the binding carries no ``auth_level`` (e.g. a non-trigger
    binding), guarding every read so an SDK shape change degrades to ``None``
    rather than raising.
    """
    level = getattr(binding, "auth_level", None)
    if level is None:
        return None
    value = getattr(level, "value", level)
    return str(value).lower()
