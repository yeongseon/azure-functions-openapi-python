"""Read-side contract for the shared ``endpoint`` namespace metadata.

Producer packages (``azure-functions-validation``, ``azure-functions-langgraph``,
...) write a self-contained, OpenAPI-ready payload onto handlers under the
``_azure_functions_metadata`` convention attribute, namespace ``"endpoint"``.
Unlike the ``validation`` namespace (which carries user-defined Pydantic model
*classes*), the ``endpoint`` payload is entirely JSON Schema, so this consumer
needs **no** import of the producing package and no access to the user's models.

This module mirrors the *shape the bridge reads* as a ``TypedDict`` so the
consumed contract is explicit and type-checked. The producer's canonical schema
lives in ``azure-functions-validation`` (``schemas/endpoint.schema.json``); the
two packages release independently, so this read-side mirror keeps the
consumer's expectations pinned even as producers evolve.
"""

from __future__ import annotations

from typing import Any, TypedDict

# Convention attribute name shared across every Azure Functions toolkit package.
HANDLER_METADATA_ATTR = "_azure_functions_metadata"

# Namespace owned by the shared endpoint contract.
ENDPOINT_NAMESPACE = "endpoint"

# Payload ``version`` values this consumer understands.
SUPPORTED_ENDPOINT_VERSIONS: frozenset[int] = frozenset({1})


class _EndpointMetadataRequired(TypedDict):
    """Keys present on every endpoint payload."""

    version: int


class EndpointMetadata(_EndpointMetadataRequired, total=False):
    """The ``endpoint`` namespace payload read from ``HANDLER_METADATA_ATTR``.

    All schema fields are self-contained JSON Schema dicts (no model classes).
    Pydantic ``$defs`` are kept unresolved by the producer (refs point at
    ``#/$defs/{Model}``); this consumer is the sole ``$ref``-collision authority.
    """

    request_body: dict[str, Any] | None
    request_body_required: bool
    parameters: list[dict[str, Any]]
    responses: dict[str, dict[str, Any]] | None
