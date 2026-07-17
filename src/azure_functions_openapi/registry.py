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
        """Return the live entry stored under *key*, or ``None`` if absent."""
        return self._entries.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        """Store *value* under *key*. Caller must hold :attr:`lock`."""
        self._entries[key] = value

    def setdefault(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        """Insert *value* under *key* if absent; return the stored entry.

        Caller must hold :attr:`lock`.
        """
        return self._entries.setdefault(key, value)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a deep copy of all entries, taken under :attr:`lock`."""
        with self._lock:
            return copy.deepcopy(self._entries)

    def clear(self) -> None:
        """Remove all entries, under :attr:`lock`."""
        with self._lock:
            self._entries.clear()


# Process-wide singleton. The ``@openapi`` decorator records metadata at import
# time — before any application object exists — so a shared instance is required.
registry = OpenAPIRegistry()
