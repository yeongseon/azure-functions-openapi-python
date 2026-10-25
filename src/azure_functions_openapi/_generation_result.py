from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from azure_functions_openapi._warnings import SpecWarning


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Invocation-owned findings; final validation is deferred until a report is requested."""

    spec: dict[str, Any]
    diagnostics: tuple[SpecWarning, ...]
    validation_messages: tuple[str, ...]
    traversal_changed: bool
