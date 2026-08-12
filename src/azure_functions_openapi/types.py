"""Public data types for programmatic OpenAPI metadata registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OpenAPIOperationMetadata:
    """Schema for a single OpenAPI operation registered programmatically.

    This is the public contract for external packages to register endpoints.
    The internal registry format is an implementation detail.
    """

    path: str
    method: str
    operation_id: str | None = None
    summary: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=lambda: ["default"])
    request_model: type | None = None
    request_body: dict[str, Any] | None = None
    request_body_required: bool = True
    response_model: type | None = None
    response: dict[int, dict[str, Any]] = field(default_factory=dict)
    parameters: list[dict[str, Any]] = field(default_factory=list)
    security: list[dict[str, list[str]]] = field(default_factory=list)
    security_scheme: dict[str, dict[str, Any]] = field(default_factory=dict)
