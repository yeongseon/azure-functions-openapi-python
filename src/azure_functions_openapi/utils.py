# src/azure_functions_openapi/utils.py
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, cast, get_origin

from pydantic import BaseModel, TypeAdapter

from azure_functions_openapi.exceptions import OpenAPISpecConfigError

logger = logging.getLogger(__name__)


def _rewrite_ref(ref: str) -> str:
    if ref.startswith("#/$defs/"):
        return ref.replace("#/$defs/", "#/components/schemas/")
    if ref.startswith("#/definitions/"):
        return ref.replace("#/definitions/", "#/components/schemas/")
    return ref


def _rewrite_refs(obj: Any) -> Any:
    if isinstance(obj, dict):
        rewritten: dict[str, Any] = {}
        for key, value in obj.items():
            if key == "$ref" and isinstance(value, str):
                rewritten[key] = _rewrite_ref(value)
            else:
                rewritten[key] = _rewrite_refs(value)
        return rewritten
    if isinstance(obj, list):
        return [_rewrite_refs(item) for item in obj]
    return obj


def _pop_definitions(schema: dict[str, Any]) -> dict[str, Any]:
    definitions: dict[str, Any] = {}
    for key in ("$defs", "definitions"):
        value = schema.pop(key, None)
        if isinstance(value, dict):
            definitions.update(value)
    return definitions


def _collect_schemas(schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    normalized = cast(dict[str, Any], _rewrite_refs(schema))
    definitions = _pop_definitions(normalized)
    collected: dict[str, dict[str, Any]] = {}

    queue: list[tuple[str, Any]] = list(definitions.items())
    while queue:
        name, definition = queue.pop(0)
        if not isinstance(definition, dict):
            continue
        definition = cast(dict[str, Any], _rewrite_refs(definition))
        nested = _pop_definitions(definition)
        if nested:
            queue.extend(list(nested.items()))
        collected[name] = definition

    return normalized, collected


def _resolve_name_collision(
    name: str,
    schema: dict[str, Any],
    existing: dict[str, dict[str, Any]],
) -> str:
    if name not in existing:
        return name
    if existing[name] == schema:
        return name
    index = 2
    while True:
        candidate = f"{name}_{index}"
        if candidate not in existing:
            logger.warning(
                "Schema name collision while hoisting $defs: %r already exists in "
                "components.schemas with different content; emitting deterministic "
                "alias %r instead. Rename the producer model to silence this warning.",
                name,
                candidate,
            )
            return candidate
        if existing[candidate] == schema:
            return candidate
        index += 1


def _rewrite_refs_with_map(obj: Any, name_map: dict[str, str]) -> Any:
    if not name_map:
        return obj
    if isinstance(obj, dict):
        rewritten: dict[str, Any] = {}
        for key, value in obj.items():
            if key == "$ref" and isinstance(value, str):
                if value.startswith("#/components/schemas/"):
                    ref_name = value.split("#/components/schemas/", 1)[1]
                    if ref_name in name_map:
                        rewritten[key] = f"#/components/schemas/{name_map[ref_name]}"
                        continue
                rewritten[key] = value
            else:
                rewritten[key] = _rewrite_refs_with_map(value, name_map)
        return rewritten
    if isinstance(obj, list):
        return [_rewrite_refs_with_map(item, name_map) for item in obj]
    return obj


def _needs_hoisting(obj: Any) -> bool:
    """Return ``True`` if *obj* contains an inline ``$defs``/``definitions`` block
    or a local ``#/$defs/`` / ``#/definitions/`` ``$ref`` anywhere in the tree.

    Flat schemas (no nested definitions and no local refs) return ``False`` so
    callers can short-circuit and embed them verbatim without copying.
    """
    if isinstance(obj, dict):
        if "$defs" in obj or "definitions" in obj:
            return True
        for key, value in obj.items():
            if (
                key == "$ref"
                and isinstance(value, str)
                and (value.startswith("#/$defs/") or value.startswith("#/definitions/"))
            ):
                return True
            if _needs_hoisting(value):
                return True
        return False
    if isinstance(obj, list):
        return any(_needs_hoisting(item) for item in obj)
    return False


_FLAT_COMPOSITION_KEYS = ("properties", "items", "anyOf", "oneOf", "allOf")


def _schema_short_hash(schema: dict[str, Any]) -> str:
    """Return a stable 8-char hash of a schema's canonical JSON form."""
    canonical = json.dumps(schema, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def _is_hoistable_flat_schema(schema: Any) -> bool:
    """Return ``True`` for a flat schema worth promoting to ``components``.

    Precondition: the caller has already established the schema is *flat* --
    ``_needs_hoisting(schema) is False`` -- so this only classifies whether a
    flat schema is *structured* enough to hoist (and never re-walks the tree).
    Structured means an object with ``properties``, a dict/map object using a
    schema-valued ``additionalProperties``, or a schema using a composition
    keyword such as ``items``/``anyOf``. Trivial scalars like
    ``{"type": "string"}`` (and ``additionalProperties: true``) are left inline
    to avoid noisy, single-use component entries.
    """
    if not isinstance(schema, dict):
        return False
    if "$ref" in schema:
        return False
    if any(key in schema for key in _FLAT_COMPOSITION_KEYS):
        return True
    # dict/map schemas emit a schema-valued ``additionalProperties`` (not a bool).
    return isinstance(schema.get("additionalProperties"), dict)


def _flat_schema_name(schema: dict[str, Any]) -> str:
    """Derive a component name for a flat schema.

    Prefers the schema's ``title`` (the natural name Pydantic emits); falls back
    to a deterministic ``InlineSchema_<hash>`` for anonymous schemas so identical
    schemas dedupe to the same component.
    """
    title = schema.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return f"InlineSchema_{_schema_short_hash(schema)}"


def _hoist_flat_schema(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    """Promote a flat schema into ``components.schemas`` and return a ``$ref``.

    Reuses :func:`_resolve_name_collision` so a name reused with differing
    content gets a deterministic alias, exactly like the ``$defs`` and model
    paths. Identical schemas registered under the same name dedupe to one entry.
    """
    schemas = components.setdefault("schemas", {})
    normalized = cast(dict[str, Any], _rewrite_refs(schema))
    name = _flat_schema_name(normalized)
    resolved = _resolve_name_collision(name, normalized, schemas)
    if resolved not in schemas:
        schemas[resolved] = normalized
    return {"$ref": f"#/components/schemas/{resolved}"}


def hoist_inline_defs(schema: Any, components: dict[str, Any], *, hoist_flat: bool = False) -> Any:
    """Hoist inline ``$defs`` from a raw JSON Schema into ``components['schemas']``.

    Producer-authored ``endpoint`` schemas embed nested-model definitions inline
    as ``$defs`` with local ``#/$defs/{Model}`` refs. This lifts each definition
    into the shared ``components.schemas`` section (resolving name collisions the
    same way :func:`model_to_schema` does) and rewrites refs to
    ``#/components/schemas/{Model}``. The root schema itself stays **inline** (a
    raw endpoint body has no canonical component name), but any of its refs that
    point at renamed definitions are rewritten.

    Flat schemas -- those with no ``$defs`` and no local ``#/$defs/`` refs -- are
    returned unchanged by default, preserving the verbatim behaviour from #311.
    When *hoist_flat* is ``True`` (opt-in, #375), a structured flat schema is also
    promoted into ``components.schemas`` under its ``title`` (or a deterministic
    ``InlineSchema_<hash>`` when anonymous) and replaced with a ``$ref``, so the
    same flat schema reused across endpoints is deduplicated the way model-class
    schemas already are. Trivial scalar schemas are always left inline.

    The input *schema* is never mutated; :func:`_collect_schemas` rebuilds every
    nested structure via :func:`_rewrite_refs` before any in-place ``pop``.
    """
    if not isinstance(schema, dict) or not _needs_hoisting(schema):
        if hoist_flat and _is_hoistable_flat_schema(schema):
            return _hoist_flat_schema(cast(dict[str, Any], schema), components)
        return schema

    normalized_root, definitions = _collect_schemas(schema)
    if not definitions:
        return normalized_root

    schemas = components.setdefault("schemas", {})

    name_map: dict[str, str] = {}
    for name, definition in definitions.items():
        resolved_name = _resolve_name_collision(name, definition, schemas)
        if resolved_name != name:
            name_map[name] = resolved_name

    if name_map:
        definitions = {
            name_map.get(name, name): cast(
                dict[str, Any], _rewrite_refs_with_map(definition, name_map)
            )
            for name, definition in definitions.items()
        }
        normalized_root = cast(dict[str, Any], _rewrite_refs_with_map(normalized_root, name_map))

    for name, definition in definitions.items():
        if name not in schemas or schemas[name] != definition:
            schemas[name] = definition

    return normalized_root


def model_to_schema(model_cls: Any, components: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return OpenAPI schema from a Pydantic model class.
    Parameters:
        model_cls: Pydantic model class.
        components: OpenAPI components dict to register schemas.
    Returns:
        dict[str, Any]: Schema with $ref to components.schemas.
    """

    if components is None:
        raise OpenAPISpecConfigError(
            "model_to_schema() requires a 'components' dict; got None. "
            "Pass the components dict from generate_openapi_spec() or provide an empty one."
        )

    if isinstance(model_cls, type) and issubclass(model_cls, BaseModel):
        schema = model_cls.model_json_schema(ref_template="#/components/schemas/{model}")
    else:
        if get_origin(model_cls) is None:
            raise TypeError(
                "model_to_schema expects a Pydantic v2 BaseModel subclass "
                "(missing model_json_schema). Pydantic v1 is not supported."
            )
        return type_to_schema(model_cls, components)

    schemas = components.setdefault("schemas", {})

    normalized, definitions = _collect_schemas(schema)
    local_schemas: dict[str, dict[str, Any]] = {model_cls.__name__: normalized}
    local_schemas.update(definitions)

    name_map: dict[str, str] = {}
    for name, local_schema in local_schemas.items():
        resolved_name = _resolve_name_collision(name, local_schema, schemas)
        if resolved_name != name:
            name_map[name] = resolved_name

    if name_map:
        updated_local_schemas: dict[str, dict[str, Any]] = {}
        for name, local_schema in local_schemas.items():
            final_name = name_map.get(name, name)
            rewritten_schema = cast(dict[str, Any], _rewrite_refs_with_map(local_schema, name_map))
            updated_local_schemas[final_name] = rewritten_schema
        local_schemas = updated_local_schemas

    for name, local_schema in local_schemas.items():
        if name not in schemas or schemas[name] != local_schema:
            schemas[name] = local_schema

    root_name = name_map.get(model_cls.__name__, model_cls.__name__)
    return {"$ref": f"#/components/schemas/{root_name}"}


def type_to_schema(type_hint: Any, components: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(type_hint, type) and issubclass(type_hint, BaseModel):
        if components is None:
            return type_hint.model_json_schema()
        return model_to_schema(type_hint, components)

    schema = TypeAdapter(type_hint).json_schema()
    if components is None:
        return schema

    schemas = components.setdefault("schemas", {})
    normalized, definitions = _collect_schemas(schema)

    name_map: dict[str, str] = {}
    for name, local_schema in definitions.items():
        resolved_name = _resolve_name_collision(name, local_schema, schemas)
        if resolved_name != name:
            name_map[name] = resolved_name

    if name_map:
        normalized = cast(dict[str, Any], _rewrite_refs_with_map(normalized, name_map))
        updated_definitions: dict[str, dict[str, Any]] = {}
        for name, local_schema in definitions.items():
            final_name = name_map.get(name, name)
            updated_definitions[final_name] = cast(
                dict[str, Any],
                _rewrite_refs_with_map(local_schema, name_map),
            )
        definitions = updated_definitions

    for name, local_schema in definitions.items():
        if name not in schemas or schemas[name] != local_schema:
            schemas[name] = local_schema

    return normalized


def validate_route_path(route: Any) -> bool:
    """Validate route path format for security.

    Parameters:
        route: Route path to validate.
    Returns:
        bool: True if route is valid, False otherwise.
    """
    if not route or not isinstance(route, str):
        return False

    # Check for dangerous patterns
    dangerous_patterns = [
        r"\.\.",  # Path traversal
        r"<script",  # XSS attempts
        r"javascript:",  # JavaScript injection
        r"data:",  # Data URI injection
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, route, re.IGNORECASE):
            return False

    # Allow alphanumeric, hyphens, underscores, slashes, and curly braces for path parameters
    # Whitespace is intentionally disallowed for route consistency and safety.
    if not re.match(r"^/?[a-zA-Z0-9_\-/{}]*$", route):
        return False
    # Validate brace structure
    if not _validate_path_param_braces(route):
        return False

    return True


_PARAM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_path_param_braces(route: str) -> bool:
    """Return False if brace structure is malformed (empty, nested, or invalid identifier)."""
    i = 0
    while i < len(route):
        if route[i] == "{":
            j = route.find("}", i + 1)
            if j == -1:
                return False  # unclosed {
            name = route[i + 1 : j]
            if not name or "{" in name or "}" in name or not _PARAM_NAME_RE.match(name):
                return False
            i = j + 1
        elif route[i] == "}":
            return False  # stray }
        else:
            i += 1
    return True


def sanitize_operation_id(operation_id: Any) -> str:
    """Sanitize operation ID to prevent injection attacks.

    Parameters:
        operation_id: Operation ID to sanitize.
    Returns:
        str: Sanitized operation ID.
    """
    if not operation_id or not isinstance(operation_id, str):
        return ""

    # Replace runs of non-identifier chars with underscores (preserves hyphens → _),
    # then strip leading/trailing underscores.
    sanitized = re.sub(r"[^a-zA-Z0-9_]+", "_", operation_id).strip("_")

    # Ensure it starts with a letter
    if sanitized and not sanitized[0].isalpha():
        sanitized = "op_" + sanitized

    return sanitized
