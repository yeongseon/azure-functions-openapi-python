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


class OpenAPIRegistry:
    """Thread-safe container for OpenAPI operation metadata.

    Entries are keyed by function name (from the ``@openapi`` decorator) or by
    ``"{method}::{path}"`` (from :func:`register_openapi_metadata`). All mutating
    access must be performed while holding :attr:`lock`; use :meth:`snapshot` to
    obtain a safe deep copy for read-only consumers such as the spec generator.
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}
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
        """Remove all entries, under :attr:`lock`."""
        with self._lock:
            self._entries.clear()

    def find_by_function_id(self, function_id: str) -> dict[str, Any] | None:
        """Return the entry whose ``_function_id`` equals *function_id*.

        This is the collision-free lookup path: ``@openapi`` records a
        canonical ``_function_id`` (see :func:`canonical_function_id`) for every
        entry, so a handler can be resolved by identity regardless of how its
        short name collides with other modules. Returns ``None`` if no entry
        matches. Caller should hold :attr:`lock` when the result is used for a
        read-modify-write transaction.
        """
        with self._lock:
            for entry in self._entries.values():
                if entry.get("_function_id") == function_id:
                    return entry
        return None

    def count_by_function_name(self, function_name: str) -> int:
        """Return how many entries carry ``function_name`` as their name.

        Used to detect ambiguous short-name fallbacks (two handlers sharing a
        short name across modules) so callers can refuse to merge silently.
        """
        with self._lock:
            return sum(
                1
                for entry in self._entries.values()
                if entry.get("function_name") == function_name
            )


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
    return f"{module}.{qualname}"
