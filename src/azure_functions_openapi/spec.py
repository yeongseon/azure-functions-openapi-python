# src/azure_functions_openapi/spec.py
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, get_origin
import warnings

from pydantic import BaseModel
import yaml

from azure_functions_openapi._warnings import SpecWarning, WarningCode
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.registry import registry as _default_registry
from azure_functions_openapi.routes import (
    ALL_HTTP_METHODS,
    BODYLESS_HTTP_METHODS,
    DEFAULT_ROUTE_PREFIX,
    STANDARD_OPENAPI_METHODS,
    apply_route_prefix,
    normalize_route_prefix,
)
from azure_functions_openapi.utils import hoist_inline_defs, model_to_schema, type_to_schema

logger = logging.getLogger(__name__)


OPENAPI_VERSION_3_0 = "3.0.0"
OPENAPI_VERSION_3_1 = "3.1.0"
OPENAPI_VERSION_3_2 = "3.2.0"
DEFAULT_OPENAPI_INFO_DESCRIPTION = (
    "Auto-generated OpenAPI documentation. Markdown supported in descriptions (CommonMark)."
)


# Auth-level inference (#482). Azure Functions declares a per-route auth policy
# via ``@app.route(auth_level=...)``. When ``infer_auth_level`` is enabled, that
# policy is translated into an OpenAPI security requirement + scheme so users do
# not have to repeat it in ``@openapi(...)``. The scheme name is a stable
# documented constant so downstream tooling can reference it.
AZURE_FUNCTION_KEY_SCHEME_NAME = "AzureFunctionKey"
_AZURE_FUNCTION_KEY_SCHEME: dict[str, Any] = {
    "type": "apiKey",
    "in": "header",
    "name": "x-functions-key",
}


def _infer_auth_security(
    auth_level: Any,
) -> tuple[list[dict[str, list[str]]], dict[str, dict[str, Any]]] | None:
    """Map a normalized ``auth_level`` to an OpenAPI (security, scheme) pair.

    ``auth_level`` is the lowercase ``AuthLevel`` value captured on the binding
    by the bridge scan (``"anonymous"`` / ``"function"`` / ``"admin"``).

    * ``"anonymous"`` -> ``None`` (the endpoint is public; inject nothing).
    * ``"function"`` / ``"admin"`` -> an ``apiKey`` ``x-functions-key`` scheme.
      Both levels are satisfied by a function/master key sent in the
      ``x-functions-key`` header, so they share one scheme.
    * Anything else (unknown/missing) -> ``None`` so an SDK change never
      fabricates a wrong requirement.
    """
    if auth_level in ("function", "admin"):
        return (
            [{AZURE_FUNCTION_KEY_SCHEME_NAME: []}],
            {AZURE_FUNCTION_KEY_SCHEME_NAME: dict(_AZURE_FUNCTION_KEY_SCHEME)},
        )
    return None


def get_openapi_registry() -> dict[str, dict[str, Any]]:
    """Return a snapshot of the process-wide OpenAPI metadata registry.

    This is the default source consulted by :func:`generate_openapi_spec` when no
    explicit ``registry`` is injected. It delegates to the registry module's
    singleton so that the spec generator never has to import the decorator (and,
    transitively, the Azure Functions SDK); callers wanting isolation should pass
    an explicit :class:`~azure_functions_openapi.registry.OpenAPIRegistry` instead.
    """
    return _default_registry.snapshot()


def _ensure_default_response(
    responses: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    """Ensure *responses* contains at least one entry.

    If *responses* already contains a concrete (non-``"default"``) entry this
    function is a no-op.  When it is empty — or contains only the OpenAPI
    ``"default"`` fallback entry — a generic ``200 Successful Response`` entry is
    added using *schema* when provided, or a plain ``{type: object}`` schema
    otherwise, so every operation advertises at least one concrete status.

    Parameters:
        responses: The responses dict being built for the current operation.
            Modified **in place**.
        schema: Optional JSON-Schema dict to embed under
            ``content.application/json.schema``.  Defaults to
            ``{"type": "object"}``.
    """
    if any(status != "default" for status in responses):
        return
    resolved_schema: dict[str, Any] = schema if schema is not None else {"type": "object"}
    responses["200"] = {
        "description": "Successful Response",
        "content": {"application/json": {"schema": resolved_schema}},
    }


def _operation_id_for(
    provided_id: str | None,
    method: str,
    logical_name: str,
    methods_expanded: bool,
) -> str:
    """Return a unique ``operationId`` for one emitted method operation.

    When an explicit ``operation_id`` is provided but the (unspecified) method
    was auto-expanded to the full HTTP set, the same id would otherwise be
    reused across every emitted operation, producing duplicate ``operationId``
    values that violate the OpenAPI spec (an error under ``strict=True`` and
    rejected by many tools). Suffix the provided id with the method in that
    case; the auto-generated fallback is already per-method unique.
    """
    if provided_id:
        return f"{provided_id}_{method}" if methods_expanded else provided_id
    return f"{method}_{logical_name}"


def _convert_nullable_to_type_array(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert OpenAPI 3.0 nullable to 3.1 type array syntax."""
    result = schema.copy()

    if result.get("nullable") is True and "type" in result:
        original_type = result["type"]
        if isinstance(original_type, str):
            result["type"] = [original_type, "null"]
        elif isinstance(original_type, list) and "null" not in original_type:
            result["type"] = original_type + ["null"]
        del result["nullable"]

    return result


def _convert_schema_to_3_1(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively convert a schema from OpenAPI 3.0 to 3.1 format."""
    if not isinstance(schema, dict):
        return schema

    result = _convert_nullable_to_type_array(schema)

    if "example" in result and "examples" not in result:
        result["examples"] = [result.pop("example")]

    if "properties" in result:
        result["properties"] = {
            k: _convert_schema_to_3_1(v) for k, v in result["properties"].items()
        }

    if "items" in result:
        result["items"] = _convert_schema_to_3_1(result["items"])

    if "allOf" in result:
        result["allOf"] = [_convert_schema_to_3_1(s) for s in result["allOf"]]

    if "anyOf" in result:
        result["anyOf"] = [_convert_schema_to_3_1(s) for s in result["anyOf"]]

    if "oneOf" in result:
        result["oneOf"] = [_convert_schema_to_3_1(s) for s in result["oneOf"]]

    if "additionalProperties" in result and isinstance(result["additionalProperties"], dict):
        result["additionalProperties"] = _convert_schema_to_3_1(result["additionalProperties"])

    return result


def _convert_schemas_to_3_1(schemas: dict[str, Any]) -> dict[str, Any]:
    """Convert all schemas in components to OpenAPI 3.1 format."""
    return {name: _convert_schema_to_3_1(schema) for name, schema in schemas.items()}


def _has_3_1_only_constructs(schema: dict[str, Any]) -> bool:
    """Check if a schema contains constructs incompatible with OpenAPI 3.0.

    Detects:
    - ``anyOf`` containing ``{"type": "null"}`` (Pydantic v2 nullable pattern)
    - ``type`` as a list (JSON Schema 2020-12 / OpenAPI 3.1 syntax)
    """
    if not isinstance(schema, dict):
        return False

    # type as list is 3.1-only
    if isinstance(schema.get("type"), list):
        return True

    # anyOf containing {type: "null"} is the Pydantic v2 nullable pattern
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        for item in any_of:
            if isinstance(item, dict) and item.get("type") == "null":
                return True

    # Recurse into nested structures
    for key in ("properties", "items", "allOf", "anyOf", "oneOf", "additionalProperties", "$defs"):
        val = schema.get(key)
        if isinstance(val, dict):
            if key == "properties":
                for prop_schema in val.values():
                    if isinstance(prop_schema, dict) and _has_3_1_only_constructs(prop_schema):
                        return True
            elif _has_3_1_only_constructs(val):
                return True
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and _has_3_1_only_constructs(item):
                    return True

    return False


def _check_schemas_3_0_compatible(schemas: dict[str, Any], strict: bool) -> list[str]:
    """Check component schemas for OpenAPI 3.1-only constructs when targeting 3.0.

    Returns a list of warning messages for incompatible schemas.
    In strict mode, raises OpenAPISpecConfigError if any are found.
    """
    warnings: list[str] = []
    for name, schema in schemas.items():
        if _has_3_1_only_constructs(schema):
            warnings.append(
                f"Schema '{name}' contains OpenAPI 3.1-only constructs "
                f"(e.g., anyOf with null type) incompatible with OpenAPI 3.0. "
                f"Use openapi_version='3.1.0' (default) or provide a manual "
                f"3.0-compatible schema instead of a Pydantic model."
            )

    if strict and warnings:
        raise OpenAPISpecConfigError(
            "OpenAPI 3.0 compatibility error:\n" + "\n".join(f"  - {w}" for w in warnings)
        )

    return warnings


def _convert_operation_schemas_to_3_1(paths: dict[str, Any]) -> dict[str, Any]:
    """Apply 3.1 schema conversion to inline schemas in operations.

    Converts schemas in:
    - requestBody.content.*.schema
    - responses.*.content.*.schema and .itemSchema
    - parameters[].schema
    """
    for _path, methods in paths.items():
        for _method, operation in methods.items():
            if not isinstance(operation, dict):
                continue

            # requestBody
            rb = operation.get("requestBody")
            if isinstance(rb, dict):
                content = rb.get("content")
                if isinstance(content, dict):
                    for _media, media_obj in content.items():
                        if isinstance(media_obj, dict) and "schema" in media_obj:
                            media_obj["schema"] = _convert_schema_to_3_1(media_obj["schema"])

            # responses
            responses = operation.get("responses")
            if isinstance(responses, dict):
                for _status, resp in responses.items():
                    if not isinstance(resp, dict):
                        continue
                    content = resp.get("content")
                    if isinstance(content, dict):
                        for _media, media_obj in content.items():
                            if not isinstance(media_obj, dict):
                                continue
                            for _schema_key in _MEDIA_SCHEMA_KEYS:
                                if _schema_key in media_obj:
                                    media_obj[_schema_key] = _convert_schema_to_3_1(
                                        media_obj[_schema_key]
                                    )

            # parameters
            for param in operation.get("parameters", []):
                if not isinstance(param, dict):
                    continue
                if "schema" in param:
                    param["schema"] = _convert_schema_to_3_1(param["schema"])
                # querystring parameters (OpenAPI 3.2) carry a content map
                # instead of a bare schema.
                param_content = param.get("content")
                if isinstance(param_content, dict):
                    for _media, media_obj in param_content.items():
                        if isinstance(media_obj, dict) and "schema" in media_obj:
                            media_obj["schema"] = _convert_schema_to_3_1(media_obj["schema"])

    return paths


# Media Type Object keys (OpenAPI 3.2 adds ``itemSchema`` for sequential/
# streaming media types such as ``text/event-stream``; see #473). Both
# positions may carry a Pydantic model / generic alias / inline JSON Schema
# and are resolved to a ``$ref`` (or hoisted defs) the same way.
_MEDIA_SCHEMA_KEYS = ("schema", "itemSchema")


def _resolve_media_schema(
    raw_schema: Any,
    components: dict[str, Any],
    hoist_flat_schemas: bool,
) -> Any:
    """Resolve a media-type schema value into an emittable JSON Schema.

    Handles the three shorthands accepted in a ``content.<media>.schema`` or
    ``content.<media>.itemSchema`` position: a Pydantic ``BaseModel`` subclass,
    a generic collection alias (e.g. ``list[Model]``), or a raw inline
    JSON-Schema dict.
    """
    if isinstance(raw_schema, type) and issubclass(raw_schema, BaseModel):
        # Unified per-status model shorthand (#410): resolve the model to a
        # $ref here, where the components registry is available.
        return model_to_schema(raw_schema, components)
    if get_origin(raw_schema) is not None:
        # Generic collection alias shorthand (#450), e.g. list[Model]: resolve
        # via TypeAdapter to a valid array schema; hoist_inline_defs expects a
        # dict JSON-Schema and would break on a raw alias.
        return type_to_schema(raw_schema, components)
    return hoist_inline_defs(raw_schema, components, hoist_flat=hoist_flat_schemas)


def generate_openapi_spec(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_1,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
    strict: bool = False,
    registry: OpenAPIRegistry | None = None,
    hoist_flat_schemas: bool = False,
    infer_auth_level: bool = False,
    servers: list[dict[str, Any]] | None = None,
    contact: dict[str, Any] | None = None,
    license: dict[str, Any] | None = None,
    external_docs: dict[str, Any] | None = None,
    tags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Compile an OpenAPI specification from the registry.

    Parameters:
        title: API title
        version: API version
        openapi_version: OpenAPI specification version ("3.0.0", "3.1.0", or "3.2.0")
        description: Description for the OpenAPI info object
        security_schemes: Security scheme definitions for components.securitySchemes.
            Example: {"BearerAuth": {"type": "http", "scheme": "bearer"}}
        route_prefix: HTTP route prefix from ``host.json``
            (``extensions.http.routePrefix``). Defaults to ``"/api"``. Pass
            ``""`` for hosts that disable the prefix or a custom value such
            as ``"/v1"``. Routes that already start with the prefix are not
            re-prefixed.
        strict: When ``True``, raise on any registry entry processing failure
            instead of logging and skipping. Useful for CI/build-time
            validation where a missing path should fail the build.
        hoist_flat_schemas: When ``True`` (opt-in, #375), structured flat
            schemas (objects/arrays with no inline ``$defs``) are promoted into
            ``components.schemas`` under their ``title`` and replaced with a
            ``$ref``, deduplicating schemas reused across endpoints. Defaults to
            ``False`` to preserve the verbatim inline-schema behaviour.
        infer_auth_level: When ``True`` (opt-in, #482), derive an OpenAPI
            security requirement from each operation's Azure Functions
            ``auth_level`` (captured on the binding during the metadata scan).
            ``FUNCTION``/``ADMIN`` map to an ``apiKey`` ``x-functions-key``
            scheme named ``AzureFunctionKey``; ``ANONYMOUS`` injects nothing.
            Inference is only applied to operations that supply no explicit
            ``@openapi(security=...)`` — user-declared security always wins.
            Requires the FunctionApp-scan path (e.g. CLI ``module:variable``);
            a plain ``@openapi``-only registry carries no ``auth_level``.
            Defaults to ``False`` for full backward compatibility.
        servers: Optional list of OpenAPI Server Objects emitted at the
            document's top-level ``servers`` field (#494). When ``None``, no
            ``servers`` key is added.
        contact: Optional Contact Object merged into ``info.contact`` (#494).
        license: Optional License Object merged into ``info.license`` (#494).
        external_docs: Optional External Documentation Object emitted at the
            document's top-level ``externalDocs`` field (#494).
        tags: Optional list of top-level Tag Objects emitted at the document's
            ``tags`` field (#494). Distinct from per-operation ``tags``.

    Returns:
        OpenAPI specification dictionary
    """
    if openapi_version not in (OPENAPI_VERSION_3_0, OPENAPI_VERSION_3_1, OPENAPI_VERSION_3_2):
        raise OpenAPISpecConfigError(
            f"Unsupported OpenAPI version: {openapi_version}. Supported: "
            f"{OPENAPI_VERSION_3_0}, {OPENAPI_VERSION_3_1}, {OPENAPI_VERSION_3_2}"
        )

    normalized_prefix = normalize_route_prefix(route_prefix)

    try:
        if registry is not None:
            registry_entries = registry.snapshot()
        else:
            registry_entries = get_openapi_registry()
        # Duplicate operations are fully recomputed by the loop below, so clear
        # the channel first: a collision resolved since a prior generation must
        # not linger on the (process-wide or injected) registry and resurface
        # here (#393).
        _diag_registry = registry if registry is not None else _default_registry
        _diag_registry.clear_duplicate_operations()
        _diag_registry.clear_downgrade_drops()
        paths: dict[str, dict[str, Any]] = {}
        components: dict[str, Any] = {"schemas": {}}

        for func_name, meta in registry_entries.items():
            try:
                logical_name = meta.get("function_name") or func_name
                # route & method --------------------------------------------------
                raw_path = f"/{(meta.get('route') or logical_name).lstrip('/')}"
                path = apply_route_prefix(raw_path, normalized_prefix)
                # An unspecified method (``None``) expands to the full HTTP set
                # ONLY when there is binding evidence that the Azure runtime
                # answers every method (an ``@app.route`` binding that omits
                # ``methods=``), recorded as ``_expand_all_methods`` at
                # registration. A bare ``@openapi`` with no binding leaves the
                # method unresolved and emits a single ``get`` operation, and an
                # explicit method is emitted as a single operation, unchanged.
                raw_method = meta.get("method")
                if raw_method is None:
                    if meta.get("_expand_all_methods"):
                        methods_to_emit = list(ALL_HTTP_METHODS)
                        methods_expanded = True
                    else:
                        methods_to_emit = ["get"]
                        methods_expanded = False
                else:
                    methods_to_emit = [str(raw_method).lower()]
                    methods_expanded = False

                # responses -------------------------------------------------------
                responses: dict[str, Any] = {}
                for status, detail in meta.get("response", {}).items():
                    resp = dict(detail)
                    resp.setdefault("description", "")
                    resp_content = resp.get("content")
                    if isinstance(resp_content, dict):
                        hoisted_content: dict[str, Any] = {}
                        for media, media_obj in resp_content.items():
                            if isinstance(media_obj, dict) and any(
                                key in media_obj for key in _MEDIA_SCHEMA_KEYS
                            ):
                                new_media_obj = dict(media_obj)
                                for schema_key in _MEDIA_SCHEMA_KEYS:
                                    if schema_key in new_media_obj:
                                        new_media_obj[schema_key] = _resolve_media_schema(
                                            new_media_obj[schema_key],
                                            components,
                                            hoist_flat_schemas,
                                        )
                                if (
                                    "itemSchema" in new_media_obj
                                    and openapi_version != OPENAPI_VERSION_3_2
                                ):
                                    # itemSchema is an OpenAPI 3.2-only media
                                    # key; on a pre-3.2 target its streaming
                                    # semantics are lost. Route this through the
                                    # same structured downgrade-drop channel used
                                    # for operation-level drops (#479/#492) so
                                    # ``collect_spec_warnings`` /
                                    # ``--fail-on-warnings`` can observe the lost
                                    # 3.2 contract, and preserve the user-facing
                                    # RuntimeWarning using the *same* message
                                    # string (single source, no divergent text).
                                    downgrade_message = (
                                        f"Response media type '{media}' for "
                                        f"function '{func_name}' uses "
                                        f"'itemSchema', which is an OpenAPI 3.2 "
                                        f"feature for sequential/streaming media "
                                        f"types, but the target openapi_version "
                                        f"is {openapi_version}. The field is "
                                        f"emitted as-is but may not be understood "
                                        f"by 3.0/3.1 tooling. Use "
                                        f"openapi_version='3.2.0' for streaming "
                                        f"responses."
                                    )
                                    _diag_registry.add_downgrade_drop(
                                        downgrade_message
                                    )
                                    warnings.warn(
                                        downgrade_message,
                                        RuntimeWarning,
                                        stacklevel=2,
                                    )
                                media_obj = new_media_obj
                            hoisted_content[media] = media_obj
                        resp["content"] = hoisted_content
                    responses[str(status)] = resp

                if meta.get("response_model"):
                    try:
                        model_schema = model_to_schema(meta["response_model"], components)
                        target_status = "200"
                        for status_key in responses:
                            key = str(status_key)
                            if key.isdigit() and 200 <= int(key) < 300:
                                target_status = key
                                break

                        if target_status not in responses:
                            responses[target_status] = {
                                "description": "Successful Response",
                                "content": {"application/json": {"schema": model_schema}},
                            }
                        else:
                            content = responses[target_status].setdefault("content", {})
                            if not isinstance(content, dict):
                                content = {}
                                responses[target_status]["content"] = content

                            json_content = content.setdefault("application/json", {})
                            if not isinstance(json_content, dict):
                                json_content = {}
                                content["application/json"] = json_content

                            json_content.setdefault("schema", model_schema)
                    except Exception as e:
                        logger.warning(
                            f"Failed to generate response schema for {func_name}: {str(e)}"
                        )
                        _ensure_default_response(responses)

                _ensure_default_response(responses)

                # Method-independent operation pieces, computed once and then
                # deep-copied per emitted method so the OpenAPI 3.1 conversion
                # (which mutates operation schemas in place) never aliases across
                # path-item entries.
                # parameters ------------------------------------------------------
                parameters: list[dict[str, Any]] = meta.get("parameters", [])
                op_parameters: list[dict[str, Any]] | None = None
                if parameters:
                    op_parameters = [
                        {
                            **param,
                            "schema": hoist_inline_defs(
                                param["schema"],
                                components,
                                hoist_flat=hoist_flat_schemas,
                            ),
                        }
                        if isinstance(param, dict) and "schema" in param
                        else param
                        for param in parameters
                    ]

                # querystring (OpenAPI 3.2 only) ---------------------------------
                qs_model = meta.get("querystring_model")
                qs_schema = meta.get("querystring_schema")
                has_querystring = qs_model is not None or qs_schema is not None

                # Count querystring entries supplied through the raw
                # ``parameters`` escape hatch so gating/validation covers both
                # the dedicated ``querystring=`` surface and manual parameters.
                raw_querystring_count = sum(
                    1
                    for p in (op_parameters or [])
                    if isinstance(p, dict) and p.get("in") == "querystring"
                )
                total_querystring = raw_querystring_count + (1 if has_querystring else 0)

                if total_querystring and openapi_version != OPENAPI_VERSION_3_2:
                    raise OpenAPISpecConfigError(
                        f"querystring parameters require openapi_version="
                        f"'{OPENAPI_VERSION_3_2}', got '{openapi_version}' "
                        f"(function '{logical_name}')."
                    )

                if has_querystring:
                    qs_media_type = meta.get(
                        "querystring_media_type", "application/x-www-form-urlencoded"
                    )
                    if qs_model is not None:
                        qs_resolved = model_to_schema(qs_model, components)
                    else:
                        qs_resolved = hoist_inline_defs(
                            qs_schema, components, hoist_flat=hoist_flat_schemas
                        )
                    qs_param = {
                        "in": "querystring",
                        "content": {qs_media_type: {"schema": qs_resolved}},
                    }
                    if op_parameters is None:
                        op_parameters = []
                    op_parameters.append(qs_param)

                # Validation: querystring must not coexist with 'query' params,
                # and at most one querystring parameter may appear per operation.
                if op_parameters:
                    has_query_param = any(
                        isinstance(p, dict) and p.get("in") == "query"
                        for p in op_parameters
                    )
                    qs_total = sum(
                        1
                        for p in op_parameters
                        if isinstance(p, dict) and p.get("in") == "querystring"
                    )
                    if qs_total > 1:
                        raise OpenAPISpecConfigError(
                            f"Operation for '{logical_name}' declares multiple "
                            f"'querystring' parameters; at most one is allowed."
                        )
                    if qs_total and has_query_param:
                        raise OpenAPISpecConfigError(
                            f"Operation for '{logical_name}' mixes 'query' and "
                            f"'querystring' parameters, which OpenAPI 3.2 forbids."
                        )

                # security --------------------------------------------------------
                security: list[dict[str, list[str]]] = meta.get("security", [])
                # Infer from auth_level only when the operation declares no
                # explicit security (user-declared security always wins) and the
                # opt-in flag is set (#482). The binding-captured ``_auth_level``
                # is only present on the FunctionApp-scan path.
                if infer_auth_level and not security:
                    _inferred = _infer_auth_security(meta.get("_auth_level"))
                    if _inferred is not None:
                        security = _inferred[0]

                # requestBody schema (POST/PUT/PATCH/DELETE) ----------------------
                request_body_obj: dict[str, Any] | None = None
                required = meta.get("request_body_required", True)
                if meta.get("request_body"):
                    request_body_obj = {
                        "required": required,
                        "content": {
                            "application/json": {
                                "schema": hoist_inline_defs(
                                    meta["request_body"],
                                    components,
                                    hoist_flat=hoist_flat_schemas,
                                )
                            }
                        },
                    }
                elif meta.get("request_model"):
                    try:
                        request_body_obj = {
                            "required": required,
                            "content": {
                                "application/json": {
                                    "schema": model_to_schema(meta["request_model"], components)
                                }
                            },
                        }
                    except Exception as e:
                        logger.warning(
                            f"Failed to generate request schema for {func_name}: {str(e)}"
                        )
                        request_body_obj = {
                            "required": required,
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }

                for method in methods_to_emit:
                    # operation object --------------------------------------------
                    op: dict[str, Any] = {
                        "summary": meta.get("summary", ""),
                        "description": meta.get("description", ""),
                        "operationId": _operation_id_for(
                            meta.get("operation_id"), method, logical_name, methods_expanded
                        ),
                        "tags": meta.get("tags") or ["default"],
                        "responses": copy.deepcopy(responses),
                    }
                    if op_parameters is not None:
                        op["parameters"] = copy.deepcopy(op_parameters)
                    if security:
                        op["security"] = security

                    # requestBody: only body-bearing methods, and never on an
                    # auto-expanded GET/HEAD/DELETE (OpenAPI leaves the body
                    # undefined there and many tools reject it). ``query`` (3.2)
                    # is safe/idempotent but explicitly carries a request
                    # payload, so it is body-bearing too.
                    body_methods = {"post", "put", "patch", "delete", "query"}
                    if methods_expanded:
                        body_methods -= BODYLESS_HTTP_METHODS
                    if request_body_obj is not None and method in body_methods:
                        op["requestBody"] = copy.deepcopy(request_body_obj)

                    # merge into paths — detect duplicate path+method registrations
                    path_item = paths.setdefault(path, {})
                    if method in path_item:
                        _dup_msg = (
                            f"Duplicate operation: {method.upper()} {path} — "
                            "only the last @openapi registration will appear in the spec"
                        )
                        if strict:
                            raise OpenAPISpecConfigError(_dup_msg)
                        logger.warning("OpenAPI spec: %s", _dup_msg)
                        _dup_registry = registry if registry is not None else _default_registry
                        _dup_registry.add_duplicate_operation(method, path)
                    path_item[method] = op

            except OpenAPISpecConfigError:
                # Configuration contract violations (e.g. querystring misuse)
                # must always surface, regardless of strict mode.
                raise
            except (KeyError, TypeError, ValueError):
                if strict:
                    logger.error("Failed to process function %s (strict mode)", func_name)
                    raise
                logger.exception("Failed to process function %s", func_name)
                continue

        spec: dict[str, Any] = {
            "openapi": openapi_version,
            "info": {
                "title": title,
                "version": version,
                "description": description,
            },
            "paths": paths,
        }

        if openapi_version in (OPENAPI_VERSION_3_1, OPENAPI_VERSION_3_2):
            spec["info"]["summary"] = title
            _convert_operation_schemas_to_3_1(paths)

        # Top-level and info metadata passthrough (#494). Each field is emitted
        # only when supplied; contact/license nest under ``info`` while
        # servers/externalDocs/tags sit at the document root.
        if contact is not None:
            spec["info"]["contact"] = contact
        if license is not None:
            spec["info"]["license"] = license
        if servers is not None:
            spec["servers"] = servers
        if external_docs is not None:
            spec["externalDocs"] = external_docs
        if tags is not None:
            spec["tags"] = tags

        # Merge security schemes: explicit param + per-operation schemes from registry.
        # Raises OpenAPISpecConfigError on collision (same name, different definition).
        all_security_schemes: dict[str, dict[str, Any]] = {}
        if security_schemes:
            all_security_schemes.update(security_schemes)
        for _fn, meta in registry_entries.items():
            scheme = meta.get("security_scheme")
            if isinstance(scheme, dict):
                for name, definition in scheme.items():
                    if name in all_security_schemes and all_security_schemes[name] != definition:
                        raise OpenAPISpecConfigError(
                            f"Conflicting security scheme definition for '{name}': "
                            f"existing={all_security_schemes[name]!r}, "
                            f"new={definition!r}"
                        )
                    all_security_schemes[name] = definition
            # Add the inferred Azure function-key scheme for operations that
            # relied on auth_level inference (#482). Only when the operation
            # declared neither explicit security nor an explicit scheme, and
            # only if the name is free — a user scheme of the same name always
            # wins (no collision error is raised for the inferred default).
            if (
                infer_auth_level
                and not meta.get("security")
                and not meta.get("security_scheme")
            ):
                _inferred = _infer_auth_security(meta.get("_auth_level"))
                if _inferred is not None:
                    for name, definition in _inferred[1].items():
                        all_security_schemes.setdefault(name, definition)

        if all_security_schemes:
            components["securitySchemes"] = all_security_schemes

        if components.get("schemas"):
            if openapi_version in (OPENAPI_VERSION_3_1, OPENAPI_VERSION_3_2):
                components["schemas"] = _convert_schemas_to_3_1(components["schemas"])
            elif openapi_version == OPENAPI_VERSION_3_0:
                compat_warnings = _check_schemas_3_0_compatible(components["schemas"], strict)
                for w in compat_warnings:
                    logger.warning("OpenAPI 3.0 compatibility: %s", w)
        if components.get("schemas") or components.get("securitySchemes"):
            spec["components"] = components

        spec = _normalize_spec_output(spec)

        validation_warnings = _validate_spec(spec)
        # Custom (non-standard) HTTP methods are validated above as ordinary
        # operations, then relocated: under 3.2 into each path item's
        # ``additionalOperations`` map, and under 3.0/3.1 dropped (the format has
        # no way to express them) with a warning.
        # Custom-method restructuring and query removal are the two constructs
        # that vanish on a pre-3.2 downgrade. Record them on the registry's
        # downgrade-drop channel so ``collect_spec_warnings`` / ``--fail-on-warnings``
        # can observe silent API-contract loss (#479), in addition to logging.
        downgrade_drops = _restructure_additional_operations(spec, openapi_version)
        downgrade_drops.extend(_drop_unsupported_query(spec, openapi_version))
        validation_warnings.extend(downgrade_drops)
        for drop in downgrade_drops:
            _diag_registry.add_downgrade_drop(drop)
        for warning in validation_warnings:
            logger.warning("OpenAPI spec validation: %s", warning)

        if strict and validation_warnings:
            raise OpenAPISpecConfigError(
                "Strict mode: generated spec has validation errors:\n"
                + "\n".join(f"  - {w}" for w in validation_warnings)
            )

        logger.info(
            f"Generated OpenAPI {openapi_version} spec with {len(paths)} paths "
            f"for {len(registry_entries)} functions"
        )
        return spec

    except OpenAPISpecConfigError:
        raise
    except Exception as e:
        if strict and isinstance(e, (KeyError, TypeError, ValueError)):
            raise
        logger.error(f"Failed to generate OpenAPI specification: {str(e)}")
        raise RuntimeError("Failed to generate OpenAPI specification") from e


_PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


def _validate_spec(spec: dict[str, Any]) -> list[str]:
    """Post-generation validation of the OpenAPI spec.

    Returns a list of warning messages.  The caller (``generate_openapi_spec``)
    logs them and raises ``OpenAPISpecConfigError`` when ``strict=True``.

    Checks performed:
    - ``operationId`` is unique across the whole spec.
    - ``operationId`` is not an empty string.
    - ``(name, in)`` pairs are unique within each operation.
    - ``parameter['in']`` is one of path / query / header / cookie.
    - Path parameters have ``required: true``.
    - Route template variables have matching ``in: 'path'`` parameters.
    - No extra ``in: 'path'`` parameters absent from the route template.
    - Response status keys are 100–599 or ``'default'``.
    """
    _VALID_PARAM_LOCATIONS = {"path", "query", "header", "cookie"}

    def _valid_response_status(status: str) -> bool:
        if status == "default":
            return True
        # Wildcard range codes (OpenAPI 3.x §4.8.16): 1XX-5XX, case-insensitive
        upper = status.upper()
        if len(upper) == 3 and upper[0] in "12345" and upper[1:] == "XX":
            return True
        return status.isdigit() and 100 <= int(status) <= 599

    warnings: list[str] = []
    seen_operation_ids: dict[str, str] = {}  # operationId → "METHOD path"

    for path, methods in spec.get("paths", {}).items():
        template_vars = set(_PATH_PARAM_RE.findall(path))

        for method, operation in methods.items():
            op_label = f"{method.upper()} {path}"

            # --- operationId uniqueness + non-empty ---
            op_id = operation.get("operationId")
            if op_id is not None:
                if op_id == "":
                    warnings.append(f"Empty operationId in {op_label}")
                elif op_id in seen_operation_ids:
                    warnings.append(
                        f"Duplicate operationId '{op_id}': "
                        f"used by {seen_operation_ids[op_id]} and {op_label}"
                    )
                else:
                    seen_operation_ids[op_id] = op_label

            # --- parameter validation ---
            params = operation.get("parameters", [])
            path_param_names: set[str] = set()
            seen_param_keys: set[tuple[str, str]] = set()

            for param in params:
                name = param.get("name", "")
                location = param.get("in", "")
                key = (name, location)

                if key in seen_param_keys:
                    warnings.append(f"Duplicate parameter ({location}:{name}) in {op_label}")
                seen_param_keys.add(key)

                if location not in _VALID_PARAM_LOCATIONS:
                    warnings.append(
                        f"Invalid parameter location '{location}' for '{name}' in {op_label}; "
                        f"must be one of: {', '.join(sorted(_VALID_PARAM_LOCATIONS))}"
                    )

                if location == "path":
                    path_param_names.add(name)
                    if not param.get("required", False):
                        warnings.append(f"Path parameter '{name}' in {op_label} must be required")

            # --- template var ↔ path parameter matching ---
            missing = template_vars - path_param_names
            for var in sorted(missing):
                warnings.append(
                    f"Route template variable '{{{var}}}' in {op_label} "
                    "has no matching path parameter definition"
                )

            extra = path_param_names - template_vars
            for var in sorted(extra):
                warnings.append(
                    f"Path parameter '{var}' in {op_label} is not present in route template"
                )

            # --- response status validation ---
            for status in operation.get("responses", {}):
                if not _valid_response_status(str(status)):
                    warnings.append(
                        f"Invalid response status '{status}' in {op_label}; "
                        "must be an integer 100–599 or 'default'"
                    )

    return warnings


def _normalize_spec_output(spec: dict[str, Any]) -> dict[str, Any]:
    """Sort paths, schemas, and securitySchemes for deterministic output."""
    components = spec.get("components") or {}
    if "schemas" in components:
        components["schemas"] = dict(sorted(components["schemas"].items()))
    if "securitySchemes" in components:
        components["securitySchemes"] = dict(sorted(components["securitySchemes"].items()))
    if components:
        spec["components"] = components
    if "paths" in spec:
        spec["paths"] = dict(sorted(spec["paths"].items()))
    return spec



def _drop_unsupported_query(spec: dict[str, Any], openapi_version: str) -> list[str]:
    """Drop ``query`` operations from pre-3.2 specs (#472).

    The ``query`` HTTP method is a first-class path-item operation field only in
    OpenAPI 3.2. Under 3.0/3.1 there is no way to represent it, so any ``query``
    operation is removed and a warning message is returned. Under 3.2 (and for
    paths without a ``query`` operation) nothing is changed and an empty list is
    returned.
    """
    if openapi_version == OPENAPI_VERSION_3_2:
        return []
    warnings: list[str] = []
    for path, path_item in spec.get("paths", {}).items():
        if isinstance(path_item, dict) and "query" in path_item:
            path_item.pop("query")
            warnings.append(
                f"The 'query' HTTP method on {path} requires OpenAPI 3.2; "
                f"dropped from the {openapi_version} spec"
            )
    return warnings


# Path-item fields that are NOT non-standard operations and therefore must never
# be moved into ``additionalOperations``. ``query`` is a first-class OpenAPI 3.2
# operation field, so it is never treated as an additionalOperations candidate;
# its removal on pre-3.2 targets is owned by the dedicated query-compat step
# (``_drop_unsupported_query``, #472), keeping that concern in one place. The
# remaining entries are the OpenAPI path-item metadata fields.
_RESERVED_PATH_ITEM_FIELDS: frozenset[str] = frozenset(
    {"summary", "description", "servers", "parameters", "$ref", "query", "additionalOperations"}
)


def _restructure_additional_operations(
    spec: dict[str, Any], openapi_version: str
) -> list[str]:
    """Relocate non-standard HTTP method operations (#471).

    Operations keyed by a method outside :data:`STANDARD_OPENAPI_METHODS`
    cannot appear as ordinary path-item fields. Under OpenAPI 3.2 they are moved
    into the path item's ``additionalOperations`` map (keyed by the uppercased
    method name); under 3.0/3.1 they are removed because the format cannot
    represent them.

    Returns a list of human-readable warning messages for methods dropped from a
    pre-3.2 spec (empty for 3.2, and for specs with only standard methods).
    """
    warnings: list[str] = []
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        custom_methods = sorted(
            method
            for method, operation in path_item.items()
            if method not in STANDARD_OPENAPI_METHODS
            and method not in _RESERVED_PATH_ITEM_FIELDS
            and isinstance(operation, dict)
        )
        if not custom_methods:
            continue

        if openapi_version == OPENAPI_VERSION_3_2:
            additional = path_item.setdefault("additionalOperations", {})
            for method in custom_methods:
                additional[method.upper()] = path_item.pop(method)
            path_item["additionalOperations"] = dict(sorted(additional.items()))
        else:
            for method in custom_methods:
                path_item.pop(method)
                warnings.append(
                    f"Non-standard HTTP method '{method.upper()}' on {path} requires "
                    f"OpenAPI 3.2 (additionalOperations); dropped from the "
                    f"{openapi_version} spec"
                )

    return warnings


def get_openapi_json(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_1,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
    strict: bool = False,
    registry: OpenAPIRegistry | None = None,
    hoist_flat_schemas: bool = False,
    infer_auth_level: bool = False,
) -> str:
    """Return the spec as pretty-printed JSON (UTF-8).

    Parameters:
        title: API title
        version: API version
        openapi_version: OpenAPI specification version ("3.0.0", "3.1.0", or "3.2.0")
        description: Description for the OpenAPI info object
        security_schemes: Security scheme definitions for components.securitySchemes.
        route_prefix: HTTP route prefix from ``host.json``
            (``extensions.http.routePrefix``). Defaults to ``"/api"``. Pass
            ``""`` for hosts that disable the prefix or a custom value such
            as ``"/v1"``.
        strict: When ``True``, raise on any registry entry processing failure.
        registry: Inject a custom :class:`OpenAPIRegistry` instead of the shared
            global one. Defaults to ``None`` (the process-wide registry).
        hoist_flat_schemas: When ``True`` (opt-in, #375), structured flat
            schemas are promoted into ``components.schemas``. Defaults to
            ``False`` to preserve the existing generated spec shape.
        infer_auth_level: When ``True`` (opt-in, #482), derive OpenAPI security
            from each operation's Azure Functions ``auth_level``. Defaults to
            ``False``. See :func:`generate_openapi_spec` for details.

    Returns:
        OpenAPI spec in JSON format.
    """
    try:
        spec = generate_openapi_spec(
            title,
            version,
            openapi_version,
            description=description,
            security_schemes=security_schemes,
            route_prefix=route_prefix,
            strict=strict,
            hoist_flat_schemas=hoist_flat_schemas,
            infer_auth_level=infer_auth_level,
            registry=registry,
        )
        return json.dumps(spec, indent=2, ensure_ascii=False)
    except OpenAPISpecConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to generate OpenAPI JSON: {str(e)}")
        raise RuntimeError("Failed to generate OpenAPI JSON") from e


def get_openapi_yaml(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_1,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
    strict: bool = False,
    registry: OpenAPIRegistry | None = None,
    hoist_flat_schemas: bool = False,
    infer_auth_level: bool = False,
) -> str:
    """Return the spec as YAML.

    Parameters:
        title: API title
        version: API version
        openapi_version: OpenAPI specification version ("3.0.0", "3.1.0", or "3.2.0")
        description: Description for the OpenAPI info object
        security_schemes: Security scheme definitions for components.securitySchemes.
        route_prefix: HTTP route prefix from ``host.json``
            (``extensions.http.routePrefix``). Defaults to ``"/api"``. Pass
            ``""`` for hosts that disable the prefix or a custom value such
            as ``"/v1"``.
        strict: When ``True``, raise on any registry entry processing failure.
        registry: Inject a custom :class:`OpenAPIRegistry` instead of the shared
            global one. Defaults to ``None`` (the process-wide registry).
        hoist_flat_schemas: When ``True`` (opt-in, #375), structured flat
            schemas are promoted into ``components.schemas``. Defaults to
            ``False`` to preserve the existing generated spec shape.
        infer_auth_level: When ``True`` (opt-in, #482), derive OpenAPI security
            from each operation's Azure Functions ``auth_level``. Defaults to
            ``False``. See :func:`generate_openapi_spec` for details.

    Returns:
        OpenAPI spec in YAML format.
    """
    try:
        spec = generate_openapi_spec(
            title,
            version,
            openapi_version,
            description=description,
            security_schemes=security_schemes,
            route_prefix=route_prefix,
            strict=strict,
            hoist_flat_schemas=hoist_flat_schemas,
            infer_auth_level=infer_auth_level,
            registry=registry,
        )
        return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)
    except OpenAPISpecConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to generate OpenAPI YAML: {str(e)}")
        raise RuntimeError("Failed to generate OpenAPI YAML") from e


# Human-readable messages for each structured skew warning code. Kept here (not
# on the enum) so the wording can evolve without touching the stable code values.
_SKEW_MESSAGES: dict[WarningCode, str] = {
    WarningCode.VERSION_SKEW: (
        "Endpoint contract version is unsupported; the endpoint namespace was "
        "rejected and the operation was generated from the HTTP binding alone, "
        "so it may not match the intended contract."
    ),
    WarningCode.AMBIGUOUS_NAMESPACE: (
        "Validation metadata could not be merged: the short function name is "
        "shared across modules. Registered a standalone endpoint instead."
    ),
}

# Discovery-skipped is not a skew signal, so its message lives outside
# ``_SKEW_MESSAGES``. The recorded SDK ``reason`` (which itself names the
# function) is appended by :func:`_collect_discovery_warnings` for attribution.
_DISCOVERY_SKIPPED_MESSAGE = (
    "A function builder could not be built during discovery and was omitted from the spec"
)

# Empty-discovery is distinct from a builder-build failure (#380): the scanned
# application object exposed no builders at all, so no per-builder failure
# occurred. It carries its own message so ``--fail-on-warnings`` users are not
# told a builder "could not be built" when none was ever present.
_EMPTY_DISCOVERY_MESSAGE = "No function builders were discovered on the scanned application object"


# Duplicate-operation is a merge-time collision, not a skew signal: two
# registrations resolve to the same METHOD path and the last one silently
# overwrites the earlier operation. The recorded ``METHOD path`` is appended by
# :func:`_collect_duplicate_operation_warnings` for attribution.
_DUPLICATE_OPERATION_MESSAGE = (
    "A duplicate METHOD path collision dropped an operation; only the last "
    "@openapi registration appears in the spec"
)

# Method/binding mismatch is authored disagreement, not a skew signal: an
# explicit ``@openapi(method=...)`` names a verb the HTTP binding does not serve,
# so the generated operation cannot be reached at runtime.
_METHOD_BINDING_MISMATCH_MESSAGE = (
    "The explicit @openapi(method=...) is not served by the function's HTTP "
    "binding; the generated operation cannot be reached at runtime"
)


@dataclass(frozen=True)
class SpecReport:
    """An OpenAPI spec plus the structured warnings emitted while generating it.

    ``spec`` is byte-for-byte the same mapping :func:`generate_openapi_spec`
    returns; ``warnings`` surfaces version skew, namespace fallbacks, and
    post-generation validation issues that would otherwise only appear in logs.
    Consumers (notably CI) can inspect ``warnings`` to fail a build before a
    wrong-but-plausible spec is promoted to an artifact.
    """

    spec: dict[str, Any]
    warnings: tuple[SpecWarning, ...] = field(default_factory=tuple)


def _collect_skew_warnings(registry: OpenAPIRegistry | None = None) -> list[SpecWarning]:
    """Derive skew warnings from ``_skew_flags`` recorded on registry entries.

    The bridge scanner tags entries at scan time; this re-derives structured
    warnings from a registry snapshot deterministically (entries sorted by key,
    codes already stored in sorted order) with no global accumulator. When
    ``registry`` is provided its snapshot is used instead of the global one, so
    warnings stay isolated to the same registry the spec was built from.
    """
    collected: list[SpecWarning] = []
    snapshot = registry.snapshot() if registry is not None else get_openapi_registry()
    for key, entry in sorted(snapshot.items()):
        flags = entry.get("_skew_flags") or []
        function_name = entry.get("function_name") or key
        for code_value in flags:
            code = WarningCode(code_value)
            collected.append(
                SpecWarning(
                    code=code,
                    message=_SKEW_MESSAGES.get(code, code.value),
                    function_name=function_name,
                )
            )
    return collected


def _collect_discovery_warnings(
    registry: OpenAPIRegistry | None = None,
) -> list[SpecWarning]:
    """Derive discovery-skipped warnings from the registry's recorded skips.

    The scan adapter records every function builder it could not build (see
    :meth:`OpenAPIRegistry.add_discovery_warning`); this turns each recorded
    ``(function_name, reason)`` into a structured :class:`SpecWarning` so a
    silently omitted endpoint is observable to CI. When ``registry`` is provided
    its skips are used, keeping warnings isolated to the same registry the spec
    was built from; otherwise the process-wide global registry is consulted.
    """
    reg = registry if registry is not None else _default_registry
    return [
        SpecWarning(
            code=WarningCode.DISCOVERY_SKIPPED,
            message=f"{_DISCOVERY_SKIPPED_MESSAGE}: {reason}",
            function_name=function_name,
        )
        for function_name, reason in reg.discovery_warnings
    ]


def _collect_empty_discovery_warnings(
    registry: OpenAPIRegistry | None = None,
) -> list[SpecWarning]:
    """Derive empty-discovery warnings from the registry's recorded empty scans.

    A scanned application object that exposes no function builders (#380) is a
    distinct condition from a builder-build failure, so it gets its own
    :class:`WarningCode.EMPTY_DISCOVERY` rather than reusing the builder-failure
    template. When ``registry`` is provided its records are used, keeping
    warnings isolated to the same registry the spec was built from.
    """
    reg = registry if registry is not None else _default_registry
    return [
        SpecWarning(
            code=WarningCode.EMPTY_DISCOVERY,
            message=f"{_EMPTY_DISCOVERY_MESSAGE} ({app_repr})",
            function_name=None,
        )
        for app_repr in reg.empty_discoveries
    ]


def _collect_duplicate_operation_warnings(
    registry: OpenAPIRegistry | None = None,
) -> list[SpecWarning]:
    """Derive duplicate-operation warnings from the registry's recorded collisions.

    When two ``@openapi`` registrations resolve to the same ``METHOD path`` the
    spec generator keeps only the last operation and drops the earlier one (#386);
    :meth:`OpenAPIRegistry.add_duplicate_operation` records each such collision
    during generation. This turns each recorded ``METHOD path`` into a structured
    :class:`WarningCode.DUPLICATE_OPERATION` so ``--fail-on-warnings`` can observe
    a silently dropped operation instead of it only appearing in the logs. When
    ``registry`` is provided its records are used, keeping warnings isolated to the
    same registry the spec was built from.
    """
    reg = registry if registry is not None else _default_registry
    return [
        SpecWarning(
            code=WarningCode.DUPLICATE_OPERATION,
            message=f"{_DUPLICATE_OPERATION_MESSAGE}: {operation}",
            function_name=None,
        )
        for operation in reg.duplicate_operations
    ]


def _collect_downgrade_drop_warnings(
    registry: OpenAPIRegistry | None = None,
) -> list[SpecWarning]:
    """Derive version-downgrade-drop warnings from the registry's recorded drops.

    When a spec is generated for a pre-3.2 target, custom-method operations and
    ``query`` operations cannot be represented and are removed (#471, #472);
    :meth:`OpenAPIRegistry.add_downgrade_drop` records each removal during
    generation. This turns each recorded drop into a structured
    :class:`WarningCode.VERSION_DOWNGRADE_DROP` so ``--fail-on-warnings`` can
    observe silently lost API contract instead of it only appearing in the logs
    (#479). When ``registry`` is provided its records are used, keeping warnings
    isolated to the same registry the spec was built from.
    """
    reg = registry if registry is not None else _default_registry
    return [
        SpecWarning(
            code=WarningCode.VERSION_DOWNGRADE_DROP,
            message=message,
            function_name=None,
        )
        for message in reg.downgrade_drops
    ]


def _collect_binding_mismatch_warnings(
    registry: OpenAPIRegistry | None = None,
) -> list[SpecWarning]:
    """Derive method/binding mismatch warnings from stamped registry entries.

    The bridge scanner stamps ``_binding_methods`` (the binding's method set) on
    entries whose method was set by an explicit ``@openapi(method=...)`` rather
    than inferred from the binding. When that explicit method is absent from the
    binding's served verbs the generated operation is unreachable at runtime, so
    a :class:`WarningCode.METHOD_BINDING_MISMATCH` is surfaced. Entries with an
    unspecified binding (no ``_binding_methods`` stamp) are never flagged: the
    runtime answers every verb, so nothing can contradict the authored method.
    Ordering is deterministic (entries sorted by registry key).
    """
    collected: list[SpecWarning] = []
    snapshot = registry.snapshot() if registry is not None else get_openapi_registry()
    for key, entry in sorted(snapshot.items()):
        binding_methods = entry.get("_binding_methods")
        if not binding_methods:
            continue
        method = entry.get("method")
        if method is None:
            continue
        if str(method).lower() in {str(m).lower() for m in binding_methods}:
            continue
        collected.append(
            SpecWarning(
                code=WarningCode.METHOD_BINDING_MISMATCH,
                message=_METHOD_BINDING_MISMATCH_MESSAGE,
                function_name=entry.get("function_name") or key,
            )
        )
    return collected


def generate_openapi_report(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_1,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
    strict: bool = False,
    registry: OpenAPIRegistry | None = None,
    hoist_flat_schemas: bool = False,
) -> SpecReport:
    """Generate the spec together with structured, machine-readable warnings.

    Mirrors :func:`generate_openapi_spec` and returns the identical spec mapping
    alongside a tuple of :class:`~azure_functions_openapi._warnings.SpecWarning`.
    Warnings combine scan-time skew signals (version skew, namespace fallback,
    ambiguous namespace) with post-generation spec validation findings, so a
    caller can gate a build on their presence without parsing log output.

    Parameters mirror :func:`generate_openapi_spec`.

    Returns:
        A :class:`SpecReport` with ``spec`` and a deterministic ``warnings`` tuple.
    """
    spec = generate_openapi_spec(
        title,
        version,
        openapi_version,
        description=description,
        security_schemes=security_schemes,
        route_prefix=route_prefix,
        strict=strict,
        hoist_flat_schemas=hoist_flat_schemas,
        registry=registry,
    )
    warnings_list = collect_spec_warnings(spec, registry=registry)
    return SpecReport(spec=spec, warnings=warnings_list)


def collect_spec_warnings(
    spec: dict[str, Any], registry: OpenAPIRegistry | None = None
) -> tuple[SpecWarning, ...]:
    """Derive the deterministic warning tuple for an already-generated spec.

    Combines scan-time skew signals (version skew, namespace fallback, ambiguous
    namespace) read from the registry with post-generation spec-validation
    findings. Exposed separately so the CLI can pair it with a spec it generated
    (or mocked) without regenerating.

    Parameters:
        spec: The generated OpenAPI document to validate.
        registry: Optional injected registry whose snapshot the skew warnings
            are derived from. Defaults to the process-wide global registry so
            the warnings match the spec built from that same registry.

    Returns:
        A deterministic tuple of :class:`SpecWarning`.
    """
    warnings_list: list[SpecWarning] = _collect_skew_warnings(registry)
    warnings_list.extend(_collect_discovery_warnings(registry))
    warnings_list.extend(_collect_empty_discovery_warnings(registry))
    warnings_list.extend(_collect_duplicate_operation_warnings(registry))
    warnings_list.extend(_collect_downgrade_drop_warnings(registry))
    warnings_list.extend(_collect_binding_mismatch_warnings(registry))
    for message in _validate_spec(spec):
        warnings_list.append(SpecWarning(code=WarningCode.SPEC_VALIDATION, message=message))
    return tuple(warnings_list)
