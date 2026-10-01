# src/azure_functions_openapi/_warnings.py
"""Structured, machine-readable warnings for spec generation.

These types make version skew and other degraded-spec signals observable to
callers (notably CI pipelines) instead of being emitted only as human-readable
log lines. A ``SpecWarning`` carries a stable :class:`WarningCode` so downstream
tooling can gate on specific categories, and the CLI can turn their presence
into a non-zero exit code (see ``--fail-on-warnings``).

The point is to block the path where a *wrong-but-plausible* spec (for example
one produced after silently falling back from an unsupported endpoint-contract
version to the legacy validation namespace) is promoted to a build artifact
without anyone noticing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WarningCode(StrEnum):
    """Stable identifiers for structured spec-generation warnings.

    A :class:`enum.StrEnum`, so the codes serialise as plain strings.
    """

    VERSION_SKEW = "version-skew"
    AMBIGUOUS_NAMESPACE = "ambiguous-namespace"
    DUPLICATE_OPERATION = "duplicate-operation"
    SPEC_VALIDATION = "spec-validation"
    DISCOVERY_SKIPPED = "discovery-skipped"
    EMPTY_DISCOVERY = "empty-discovery"
    METHOD_BINDING_MISMATCH = "method-binding-mismatch"
    VERSION_DOWNGRADE_DROP = "version-downgrade-drop"
    SCHEMA_SUBSTITUTION = "schema-substitution"
    OPERATION_SKIPPED = "operation-skipped"


@dataclass(frozen=True)
class SpecWarning:
    """A single structured warning emitted during spec generation.

    Attributes:
        code: Stable :class:`WarningCode` identifying the warning category.
        message: Human-readable explanation of what happened.
        function_name: The affected function/operation, when known.
    """

    code: WarningCode
    message: str
    function_name: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Return a JSON-serialisable representation of the warning."""
        return {
            "code": self.code.value,
            "message": self.message,
            "function_name": self.function_name,
        }
