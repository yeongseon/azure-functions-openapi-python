# src/azure_functions_openapi/registry.py
"""Ownership of the OpenAPI operation-metadata registry.

Historically the registry lived as module-level globals (``_openapi_registry``
dict plus a ``threading.RLock``) inside :mod:`azure_functions_openapi.decorator`,
which mixed the public decorator surface with global mutable state. Extracting
it into a dedicated :class:`OpenAPIRegistry` object clarifies ownership, keeps
the locking discipline in one place, and makes it possible to reason about (and
in tests, isolate) registry state independently of the decorator.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
import copy
import inspect
import threading
from typing import Any
import uuid

# Attribute stamped by :func:`ensure_canonical_identity` on dynamically-created
# handlers so :func:`canonical_function_id` can keep same-qualname closures
# distinct (#392).
_OPENAPI_UID_ATTR = "_openapi_uid"


class OpenAPIRegistry:
    """Thread-safe container for OpenAPI operation metadata.

    Entries are keyed by function name (from the ``@openapi`` decorator) or by
    ``"{method}::{path}"`` (from :func:`register_openapi_metadata`). All mutating
    access must be performed while holding :attr:`lock`; use :meth:`snapshot` to
    obtain a safe deep copy for read-only consumers such as the spec generator.
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}
        self._discovery_warnings: list[tuple[str | None, str]] = []
        self._empty_discoveries: list[str] = []
        self._duplicate_operations: list[str] = []
        self._downgrade_drops: list[str] = []
        self._lock = threading.RLock()

    @property
    def lock(self) -> AbstractContextManager[bool]:
        """Re-entrant lock guarding registry access.

        Callers that need a read-modify-write transaction (for example the
        validation bridge, which reads an entry, merges into it, then may
        register a new one) should hold this lock across the whole sequence::

            with registry.lock:
                entry = registry.get(key)
                ...
        """
        return self._lock

    @property
    def entries(self) -> dict[str, dict[str, Any]]:
        """The live mapping of registry entries.

        Returns the underlying dict (not a copy); mutating it must be done while
        holding :attr:`lock`. Prefer :meth:`snapshot` when a detached copy is
        acceptable.
        """
        return self._entries

    def get(self, key: str) -> dict[str, Any] | None:
        """Return the live entry stored under *key*, or ``None`` if absent.

        The returned dict is the *live* entry (not a copy). Callers that need a
        consistent read-modify-write view must hold :attr:`lock` across the
        whole ``get`` → mutate sequence; use :meth:`snapshot` when a detached
        copy is acceptable.
        """
        with self._lock:
            return self._entries.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        """Store *value* under *key*.

        Acquires :attr:`lock` internally. Because the lock is re-entrant, this
        stays safe when the caller already holds it for a larger transaction.
        """
        with self._lock:
            self._entries[key] = value

    def setdefault(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        """Insert *value* under *key* if absent; return the stored entry.

        Acquires :attr:`lock` internally (re-entrant, so nesting inside an
        outer ``with registry.lock:`` transaction is safe).
        """
        with self._lock:
            return self._entries.setdefault(key, value)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a deep copy of all entries, taken under :attr:`lock`."""
        with self._lock:
            return copy.deepcopy(self._entries)

    def clear(self) -> None:
        """Remove all entries and diagnostics, under :attr:`lock`."""
        with self._lock:
            self._entries.clear()
            self.clear_diagnostics()

    def clear_diagnostics(self) -> None:
        """Clear all discovery/empty/duplicate diagnostics, leaving entries intact.

        Diagnostic channels have *different lifetimes*, and this method is the
        blanket reset that empties all of them:

        * ``DUPLICATE_OPERATION`` is *run-scoped*. :func:`generate_openapi_spec`
          recomputes it on every pass and clears only that channel at entry (via
          :meth:`clear_duplicate_operations`), so a collision resolved between two
          runs does not linger on the process-wide singleton (#393).
        * ``DISCOVERY_SKIPPED`` / ``EMPTY_DISCOVERY`` are *scan-lifetime*. They are
          recorded during app discovery and are **not** auto-reset by spec
          generation (neither :func:`generate_openapi_spec` nor
          :func:`generate_openapi_report` calls this method). On a long-lived,
          reused registry these entries persist across generations; a caller that
          wants a clean slate must invoke this method (or :meth:`clear`) or use a
          fresh registry.
        """
        with self._lock:
            self._discovery_warnings.clear()
            self._empty_discoveries.clear()
            self._duplicate_operations.clear()
            self._downgrade_drops.clear()

    def clear_duplicate_operations(self) -> None:
        """Clear only the duplicate-operation channel, under :attr:`lock`.

        Duplicate operations are fully recomputed on every
        :func:`generate_openapi_spec` pass, so that generator clears this channel
        at entry to avoid reporting a collision that a prior generation observed
        but the current registry state no longer produces (#393).
        """
        with self._lock:
            self._duplicate_operations.clear()

    def clear_downgrade_drops(self) -> None:
        """Clear only the version-downgrade-drop channel, under :attr:`lock`.

        Downgrade drops are fully recomputed on every
        :func:`generate_openapi_spec` pass (they depend on the requested target
        ``openapi_version``), so that generator clears this channel at entry to
        avoid reporting a drop that a prior generation observed but the current
        target version no longer produces.
        """
        with self._lock:
            self._downgrade_drops.clear()

    def find_by_function_id(
        self, function_id: str, method: str | None = None
    ) -> dict[str, Any] | None:
        """Return an entry whose ``_function_id`` equals *function_id*.

        ``@openapi`` records a canonical ``_function_id`` (see
        :func:`canonical_function_id`) for every entry, so a handler can be
        resolved by identity regardless of how its short name collides with
        other modules.

        Historically this was a *collision-free* one-to-one lookup, but the
        per-method explode introduced in #359 makes ``_function_id`` **one to
        many**: a single handler bound to several HTTP methods produces one
        ``{method}::{path}`` entry per method, all sharing the same
        ``_function_id``. Passing *method* disambiguates that case: an entry
        whose ``method`` equals *method* is preferred, falling back to a
        ``method=None`` (un-exploded canonical) entry when no exact match
        exists. With *method* left ``None`` the first matching entry is returned
        (used only to detect the un-exploded canonical before exploding).

        Returns ``None`` if no entry matches. Caller should hold :attr:`lock`
        when the result is used for a read-modify-write transaction.
        """
        with self._lock:
            method_none_fallback: dict[str, Any] | None = None
            for entry in self._entries.values():
                if entry.get("_function_id") != function_id:
                    continue
                if method is None:
                    return entry
                entry_method = entry.get("method")
                if entry_method is not None and str(entry_method).lower() == method.lower():
                    return entry
                if entry_method is None and method_none_fallback is None:
                    method_none_fallback = entry
            return method_none_fallback

    def count_by_function_name(self, function_name: str) -> int:
        """Return how many entries carry ``function_name`` as their name.

        Used to detect ambiguous short-name fallbacks (two handlers sharing a
        short name across modules) so callers can refuse to merge silently.
        """
        with self._lock:
            return sum(
                1 for entry in self._entries.values() if entry.get("function_name") == function_name
            )

    def add_discovery_warning(self, function_name: str | None, reason: str) -> None:
        """Record that a function builder was skipped during discovery.

        The adapter enumeration path (:func:`iter_functions`) skips any builder
        whose ``build()`` raises ``ValueError`` (a user-app state such as a
        trigger missing from its bindings). Historically that skip was only
        logged at debug and vanished; recording it here lets the spec generator
        surface a structured ``discovery-skipped`` warning so CI can notice that
        an endpoint silently fell out of the spec.

        Identical ``(function_name, reason)`` skips are deduplicated so repeated
        scans (e.g. an app and its Blueprint, or a module re-import) do not spam
        the same warning line — mirroring the idempotent merge of :attr:`entries`.
        """
        with self._lock:
            record = (function_name, reason)
            if record not in self._discovery_warnings:
                self._discovery_warnings.append(record)

    @property
    def discovery_warnings(self) -> list[tuple[str | None, str]]:
        """Return the recorded ``(function_name, reason)`` skips, deduplicated.

        The result is sorted deterministically (unnamed skips first, then by
        name and reason) so downstream warning collection is reproducible, the
        same guarantee :func:`_collect_skew_warnings` gives skew warnings.
        """
        with self._lock:
            return sorted(
                self._discovery_warnings,
                key=lambda record: (record[0] is not None, record[0] or "", record[1]),
            )

    def add_empty_discovery(self, app_repr: str) -> None:
        """Record that a scanned application object exposed no function builders.

        This is a *different* condition from a builder-build failure recorded by
        :meth:`add_discovery_warning`: no individual builder failed -- the app
        simply had nothing to enumerate (#380). Keeping it on its own channel
        lets the spec generator surface a distinct ``empty-discovery`` warning
        instead of mislabelling it as a builder failure. Identical ``app_repr``
        values are deduplicated, mirroring :meth:`add_discovery_warning`.
        """
        with self._lock:
            if app_repr not in self._empty_discoveries:
                self._empty_discoveries.append(app_repr)

    @property
    def empty_discoveries(self) -> list[str]:
        """Return the recorded empty-app type names, deduplicated and sorted."""
        with self._lock:
            return sorted(self._empty_discoveries)

    def add_duplicate_operation(self, method: str, path: str) -> None:
        """Record that two registrations collided on the same ``METHOD path``.

        When two ``@openapi`` registrations resolve to the same HTTP method and
        path, the spec generator keeps only the last operation and drops the
        earlier one (non-strict mode). Historically that drop was only logged,
        so ``--fail-on-warnings`` could not observe a silently vanished
        operation. Recording it here lets the generator surface a structured
        ``duplicate-operation`` warning. Identical ``METHOD path`` collisions are
        deduplicated, mirroring :meth:`add_discovery_warning`.
        """
        with self._lock:
            record = f"{method.upper()} {path}"
            if record not in self._duplicate_operations:
                self._duplicate_operations.append(record)

    @property
    def duplicate_operations(self) -> list[str]:
        """Return the recorded ``METHOD path`` collisions, deduplicated and sorted."""
        with self._lock:
            return sorted(self._duplicate_operations)

    def add_downgrade_drop(self, message: str) -> None:
        """Record that a construct was dropped when downgrading the spec version.

        When generating a spec for an *older* target ``openapi_version``, the
        generator restructures or removes constructs the older version cannot
        express (unsupported query parameters, ``additionalOperations``, and the
        3.2 ``itemSchema`` media key). Historically those drops were only logged,
        so ``--fail-on-warnings`` could not observe silently vanished API
        contract. Recording them here lets the generator surface a structured
        ``version-downgrade-drop`` warning. Identical messages are deduplicated,
        mirroring :meth:`add_duplicate_operation`.
        """
        with self._lock:
            if message not in self._downgrade_drops:
                self._downgrade_drops.append(message)

    @property
    def downgrade_drops(self) -> list[str]:
        """Return the recorded downgrade-drop messages, deduplicated and sorted."""
        with self._lock:
            return sorted(self._downgrade_drops)


# Process-wide singleton. The ``@openapi`` decorator records metadata at import
# time — before any application object exists — so a shared instance is required.
registry = OpenAPIRegistry()


def canonical_function_id(handler: Any) -> str:
    """Compute a stable, collision-free identity for a handler callable.

    Unwraps decorator layers (``functools.wraps`` sets ``__wrapped__``) so that
    an inner handler and any wrappers resolve to the same identity, then keys by
    fully-qualified name: ``f"{module}.{qualname}"``. Both the ``@openapi``
    decorator (when recording ``_function_id``) and the SDK bridge (when looking
    an entry back up) use this helper, so they always agree on identity even
    when two handlers share a short ``__name__`` across different modules.
    """
    target = inspect.unwrap(handler) if callable(handler) else handler
    module = getattr(target, "__module__", "") or ""
    qualname = getattr(target, "__qualname__", None) or getattr(target, "__name__", "") or ""
    base = f"{module}.{qualname}"
    # Dynamically-created handlers (factory/closure) share a qualname such as
    # ``factory.<locals>.handler`` across every factory call, so the qualified
    # name alone collapses distinct handlers onto one registry entry (#392).
    # When :func:`ensure_canonical_identity` has stamped a per-object token on
    # the handler, fold it in to keep those handlers distinct. Module-level
    # functions carry no token and keep their plain ``module.qualname`` identity.
    token = getattr(target, _OPENAPI_UID_ATTR, None)
    if token is not None:
        return f"{base}#{token}"
    return base


def ensure_canonical_identity(handler: Any) -> str:
    """Stamp a stable per-object identity token, then return the canonical id.

    Factory/closure handlers share their ``__qualname__`` (for example
    ``factory.<locals>.handler``) across every factory invocation, so
    :func:`canonical_function_id` alone maps two distinct handlers to one
    registry entry and silently drops one (#392). The ``@openapi`` decorator
    calls this at decoration time for such handlers: it attaches a
    process-local ``uuid4`` token to the unwrapped callable, which
    :func:`canonical_function_id` (used by both the decorator and the SDK
    bridge on the *same* handler object) then folds into the identity so the
    two handlers stay distinct.

    Module-level functions (no ``<locals>`` in their qualname) are left
    untouched so their identity is unchanged. Handlers that reject attribute
    assignment (an unusual immutable callable) simply keep the plain qualified
    identity — a best-effort fallback rather than a hard failure.
    """
    target = inspect.unwrap(handler) if callable(handler) else handler
    qualname = getattr(target, "__qualname__", "") or ""
    if "<locals>" in qualname and getattr(target, _OPENAPI_UID_ATTR, None) is None:
        try:
            setattr(target, _OPENAPI_UID_ATTR, uuid.uuid4().hex)
        except (AttributeError, TypeError):  # pragma: no cover - immutable callables
            pass
    return canonical_function_id(handler)
