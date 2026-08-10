# src/azure_functions_openapi/spec.py
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any

import yaml

from azure_functions_openapi._warnings import SpecWarning, WarningCode
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.registry import registry as _default_registry
from azure_functions_openapi.routes import (
    ALL_HTTP_METHODS,
    BODYLESS_HTTP_METHODS,
    DEFAULT_ROUTE_PREFIX,
    apply_route_prefix,
    normalize_route_prefix,
)
from azure_functions_openapi.utils import hoist_inline_defs, model_to_schema

logger = logging.getLogger(__name__)


OPENAPI_VERSION_3_0 = "3.0.0"
OPENAPI_VERSION_3_1 = "3.1.0"
DEFAULT_OPENAPI_INFO_DESCRIPTION = (
    "Auto-generated OpenAPI documentation. Markdown supported in descriptions (CommonMark)."
)


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

    If *responses* is non-empty this function is a no-op.  When it is empty
    a generic ``200 Successful Response`` entry is added using *schema* when
    provided, or a plain ``{type: object}`` schema otherwise.

    Parameters:
        responses: The responses dict being built for the current operation.
            Modified **in place**.
        schema: Optional JSON-Schema dict to embed under
            ``content.application/json.schema``.  Defaults to
            ``{"type": "object"}``.
    """
    if responses:
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
    - responses.*.content.*.schema
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
                            if isinstance(media_obj, dict) and "schema" in media_obj:
                                media_obj["schema"] = _convert_schema_to_3_1(media_obj["schema"])

            # parameters
            for param in operation.get("parameters", []):
                if isinstance(param, dict) and "schema" in param:
                    param["schema"] = _convert_schema_to_3_1(param["schema"])

    return paths


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
) -> dict[str, Any]:
    """
    Compile an OpenAPI specification from the registry.

    Parameters:
        title: API title
        version: API version
        openapi_version: OpenAPI specification version ("3.0.0" or "3.1.0")
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

    Returns:
        OpenAPI specification dictionary
    """
    if openapi_version not in (OPENAPI_VERSION_3_0, OPENAPI_VERSION_3_1):
        raise OpenAPISpecConfigError(
            f"Unsupported OpenAPI version: {openapi_version}. Supported: "
            f"{OPENAPI_VERSION_3_0}, {OPENAPI_VERSION_3_1}"
        )

    normalized_prefix = normalize_route_prefix(route_prefix)

    try:
        if registry is not None:
            registry_entries = registry.snapshot()
        else:
            registry_entries = get_openapi_registry()
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
                            if isinstance(media_obj, dict) and "schema" in media_obj:
                                media_obj = {
                                    **media_obj,
                                    "schema": hoist_inline_defs(
                                        media_obj["schema"],
                                        components,
                                        hoist_flat=hoist_flat_schemas,
                                    ),
                                }
                            hoisted_content[media] = media_obj
                        resp["content"] = hoisted_content
                    responses[str(status)] = resp

                if meta.get("response_model"):
                    try:
                        model_schema = model_to_schema(meta["response_model"], components)
                        target_status = "200"
                        for status_key in responses:
                            if str(status_key).startswith("2"):
                                target_status = str(status_key)
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

                # security --------------------------------------------------------
                security: list[dict[str, list[str]]] = meta.get("security", [])

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
                    # undefined there and many tools reject it).
                    body_methods = {"post", "put", "patch", "delete"}
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

        if openapi_version == OPENAPI_VERSION_3_1:
            spec["info"]["summary"] = title
            _convert_operation_schemas_to_3_1(paths)

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

        if all_security_schemes:
            components["securitySchemes"] = all_security_schemes

        if components.get("schemas"):
            if openapi_version == OPENAPI_VERSION_3_1:
                components["schemas"] = _convert_schemas_to_3_1(components["schemas"])
            elif openapi_version == OPENAPI_VERSION_3_0:
                compat_warnings = _check_schemas_3_0_compatible(components["schemas"], strict)
                for w in compat_warnings:
                    logger.warning("OpenAPI 3.0 compatibility: %s", w)
        if components.get("schemas") or components.get("securitySchemes"):
            spec["components"] = components

        spec = _normalize_spec_output(spec)

        validation_warnings = _validate_spec(spec)
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
) -> str:
    """Return the spec as pretty-printed JSON (UTF-8).

    Parameters:
        title: API title
        version: API version
        openapi_version: OpenAPI specification version ("3.0.0" or "3.1.0")
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
    ) -> str:
    """Return the spec as YAML.

    Parameters:
        title: API title
        version: API version
        openapi_version: OpenAPI specification version ("3.0.0" or "3.1.0")
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
        "Endpoint contract version is unsupported; the operation was generated "
        "from a fallback namespace and may not match the intended contract."
    ),
    WarningCode.NAMESPACE_FALLBACK: (
        "Endpoint namespace was present but rejected; fell back to the legacy "
        "validation namespace for OpenAPI generation."
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
_EMPTY_DISCOVERY_MESSAGE = (
    "No function builders were discovered on the scanned application object"
)


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
    warnings_list.extend(_collect_binding_mismatch_warnings(registry))
    for message in _validate_spec(spec):
        warnings_list.append(SpecWarning(code=WarningCode.SPEC_VALIDATION, message=message))
    return tuple(warnings_list)
