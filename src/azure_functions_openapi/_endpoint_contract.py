"""Read-side model for the ``endpoint`` namespace metadata convention.

Producer packages (``azure-functions-validation``, ``azure-functions-langgraph``,
...) write a self-contained, OpenAPI-ready payload onto handlers under the
``_azure_functions_metadata`` convention attribute, namespace ``"endpoint"``.
Unlike the ``validation`` namespace (which carries user-defined Pydantic model
*classes*), the ``endpoint`` payload is entirely JSON Schema, so this consumer
needs **no** import of the producing package and no access to the user's models.

This module mirrors the *shape the bridge reads* as a ``TypedDict`` so this
package's local read model is explicit and type-checked. The ``endpoint``
namespace is a **versioned plain-dict convention**, not a shared or hosted
schema owned by any single package: each package keeps its own local
read/write model of the same convention and they release independently. This
read-side mirror pins the versioned dict this package accepts
(``SUPPORTED_ENDPOINT_VERSIONS``) even as producers evolve.
"""

from __future__ import annotations

import copy
import re
from typing import Any, NotRequired, TypedDict

# Convention attribute name shared across every Azure Functions toolkit package.
HANDLER_METADATA_ATTR = "_azure_functions_metadata"

# Namespace name for the versioned endpoint metadata convention.
ENDPOINT_NAMESPACE = "endpoint"

# Payload ``version`` values this consumer understands.
SUPPORTED_ENDPOINT_VERSIONS: frozenset[int] = frozenset({1, 2})


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


class EndpointMediaV2(TypedDict):
    """One v2 representation; sequential item semantics are not supported."""

    schema: dict[str, Any]


class EndpointHeaderV2(EndpointMediaV2):
    """A response header schema, never a literal runtime header value."""

    description: NotRequired[str]


class EndpointResponseV2(TypedDict):
    """An empty content map explicitly declares a body-less response."""

    content: dict[str, EndpointMediaV2]
    description: NotRequired[str]
    headers: NotRequired[dict[str, EndpointHeaderV2]]


class EndpointMetadataV2(_EndpointMetadataRequired, total=False):
    """Independent read-side mirror; request hints retain their v1 shape."""

    request_body: dict[str, Any] | None
    request_body_required: bool
    parameters: list[dict[str, Any]]
    responses: dict[str, EndpointResponseV2]


_NAME_CHARS = r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
_HEADER_NAME = _NAME_CHARS
_MEDIA_TYPE = f"{_NAME_CHARS}/{_NAME_CHARS}"


def _unknown_fields(value: dict[str, Any], allowed: set[str], location: str) -> list[str]:
    return [
        f"endpoint v2 {location}: ignored unknown field {key!r}; "
        "use a supported field or x-* extension"
        for key in value
        if key not in allowed and not (isinstance(key, str) and key.startswith("x-"))
    ]


def _read_schema_entries(
    entries: Any, *, headers: bool, location: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse media/header objects once, dropping an invalid response as a unit."""
    diagnostics: list[str] = []
    if not isinstance(entries, dict):
        return None, [f"endpoint v2 {location}: expected a mapping; response skipped"]
    parsed: dict[str, Any] = {}
    seen: set[str] = set()
    for name, entry in entries.items():
        entry_location = f"{location}.{name}"
        valid_name = isinstance(name, str) and bool(
            re.fullmatch(_HEADER_NAME if headers else _MEDIA_TYPE, name)
        )
        if not valid_name or (headers and (name.lower() in seen or name.lower() == "content-type")):
            return None, diagnostics + [
                f"endpoint v2 {entry_location}: invalid or duplicate name; response skipped"
            ]
        seen.add(name.lower())
        if not isinstance(entry, dict) or not isinstance(entry.get("schema"), dict):
            return None, diagnostics + [
                f"endpoint v2 {entry_location}.schema: required dictionary; response skipped"
            ]
        allowed = {"schema", "description"} if headers else {"schema"}
        diagnostics.extend(_unknown_fields(entry, allowed, entry_location))
        normalized = {"schema": copy.deepcopy(entry["schema"])}
        if headers and "description" in entry:
            if not isinstance(entry["description"], str):
                return None, diagnostics + [
                    f"endpoint v2 {entry_location}.description: expected string; response skipped"
                ]
            normalized["description"] = entry["description"]
        parsed[name] = normalized
    return parsed, diagnostics


def read_v2_responses(endpoint: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], list[str]]:
    """Translate allowlisted v2 fields without mutating producer-owned data."""
    diagnostics = _unknown_fields(
        endpoint,
        {"version", "request_body", "request_body_required", "parameters", "responses"},
        "payload",
    )
    responses: dict[int, dict[str, Any]] = {}
    raw = endpoint.get("responses", {})
    if not isinstance(raw, dict):
        return responses, diagnostics + [
            "endpoint v2 responses: expected mapping; responses skipped"
        ]
    for status, detail in raw.items():
        location = f"responses.{status}"
        if not isinstance(status, str) or re.fullmatch(r"[2-5][0-9]{2}", status) is None:
            diagnostics.append(f"endpoint v2 {location}: expected status string 200-599; skipped")
            continue
        if not isinstance(detail, dict):
            diagnostics.append(f"endpoint v2 {location}: expected response mapping; skipped")
            continue
        diagnostics.extend(_unknown_fields(detail, {"description", "content", "headers"}, location))
        if "schema" in detail:
            diagnostics.append(
                f"endpoint v2 {location}.schema: legacy field forbidden; use content; skipped"
            )
            continue
        description = detail.get("description", "")
        if not isinstance(description, str):
            diagnostics.append(f"endpoint v2 {location}.description: expected string; skipped")
            continue
        content, messages = _read_schema_entries(
            detail.get("content"), headers=False, location=f"{location}.content"
        )
        diagnostics.extend(messages)
        if content is None:
            continue
        if status in {"204", "205", "304"} and content:
            diagnostics.append(
                f"endpoint v2 {location}.content: status forbids a body; use {{}}; skipped"
            )
            continue
        header_map, messages = _read_schema_entries(
            detail.get("headers", {}), headers=True, location=f"{location}.headers"
        )
        diagnostics.extend(messages)
        if header_map is None:
            continue
        response: dict[str, Any] = {"description": description}
        if content:
            response["content"] = content
        if header_map:
            response["headers"] = header_map
        responses[int(status)] = response
    return responses, diagnostics
