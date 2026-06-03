# src/azure_functions_openapi/spec.py
from __future__ import annotations

import json
import logging
from typing import Any

import yaml

from azure_functions_openapi.decorator import get_openapi_registry
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.routes import (
    DEFAULT_ROUTE_PREFIX,
    apply_route_prefix,
    normalize_route_prefix,
)
from azure_functions_openapi.utils import model_to_schema

logger = logging.getLogger(__name__)


OPENAPI_VERSION_3_0 = "3.0.0"
OPENAPI_VERSION_3_1 = "3.1.0"
DEFAULT_OPENAPI_INFO_DESCRIPTION = (
    "Auto-generated OpenAPI documentation. Markdown supported in descriptions (CommonMark)."
)


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


def _convert_anyof_null_to_nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert Pydantic v2 ``anyOf`` nullable patterns to OpenAPI 3.0 ``nullable``.

    Pydantic v2 emits ``{"anyOf": [{"type": "string"}, {"type": "null"}]}``
    for ``Optional[str]``.  OpenAPI 3.0 represents this as
    ``{"type": "string", "nullable": true}``.

    Only converts the pattern when *exactly* two elements are present and one
    of them is ``{"type": "null"}``.  More complex unions are left unchanged.
    """
    result = schema.copy()
    any_of = result.get("anyOf")
    if not isinstance(any_of, list) or len(any_of) != 2:
        return result

    null_entries = [s for s in any_of if isinstance(s, dict) and s.get("type") == "null"]
    non_null_entries = [s for s in any_of if isinstance(s, dict) and s.get("type") != "null"]

    if len(null_entries) == 1 and len(non_null_entries) == 1:
        non_null = non_null_entries[0]
        del result["anyOf"]
        result.update(non_null)
        result["nullable"] = True

    return result


def _convert_schema_to_3_0(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively downgrade a JSON Schema 2020-12 / OpenAPI 3.1 schema to 3.0.

    Handles:
    - ``anyOf: [{type: T}, {type: null}]`` → ``{type: T, nullable: true}``
    - ``type: [T, "null"]`` array → ``{type: T, nullable: true}``
    - ``examples`` array → ``example`` (first element)
    - ``const`` → ``enum: [value]``
    """
    if not isinstance(schema, dict):
        return schema

    result = _convert_anyof_null_to_nullable(schema)

    # type: ["string", "null"] → {type: "string", nullable: true}
    type_val = result.get("type")
    if isinstance(type_val, list):
        non_null = [t for t in type_val if t != "null"]
        has_null = "null" in type_val
        if len(non_null) == 1:
            result["type"] = non_null[0]
            if has_null:
                result["nullable"] = True
        elif len(non_null) == 0 and has_null:
            result["type"] = "string"
            result["nullable"] = True

    # examples → example (3.0 uses singular; always remove examples)
    if "examples" in result:
        examples = result.pop("examples")
        if "example" not in result and isinstance(examples, list) and examples:
            result["example"] = examples[0]

    # const → enum (3.0 doesn't have const)
    if "const" in result:
        result["enum"] = [result.pop("const")]

    # Recurse into nested structures
    if "properties" in result:
        result["properties"] = {
            k: _convert_schema_to_3_0(v) for k, v in result["properties"].items()
        }

    if "items" in result:
        result["items"] = _convert_schema_to_3_0(result["items"])

    if "allOf" in result:
        result["allOf"] = [_convert_schema_to_3_0(s) for s in result["allOf"]]

    if "anyOf" in result:
        result["anyOf"] = [_convert_schema_to_3_0(s) for s in result["anyOf"]]

    if "oneOf" in result:
        result["oneOf"] = [_convert_schema_to_3_0(s) for s in result["oneOf"]]

    if "additionalProperties" in result and isinstance(result["additionalProperties"], dict):
        result["additionalProperties"] = _convert_schema_to_3_0(result["additionalProperties"])

    return result


def _convert_schemas_to_3_0(schemas: dict[str, Any]) -> dict[str, Any]:
    """Convert all schemas in components to OpenAPI 3.0 format."""
    return {name: _convert_schema_to_3_0(schema) for name, schema in schemas.items()}


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


def generate_openapi_spec(
    title: str = "API",
    version: str = "1.0.0",
    openapi_version: str = OPENAPI_VERSION_3_0,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
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
        registry = get_openapi_registry()
        paths: dict[str, dict[str, Any]] = {}
        components: dict[str, Any] = {"schemas": {}}

        for func_name, meta in registry.items():
            try:
                logical_name = meta.get("function_name") or func_name
                # route & method --------------------------------------------------
                raw_path = f"/{(meta.get('route') or logical_name).lstrip('/')}"
                path = apply_route_prefix(raw_path, normalized_prefix)
                method = (meta.get("method") or "get").lower()

                # responses -------------------------------------------------------
                responses: dict[str, Any] = {}
                for status, detail in meta.get("response", {}).items():
                    resp = dict(detail)
                    resp.setdefault("description", "")
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

                # operation object ------------------------------------------------
                op: dict[str, Any] = {
                    "summary": meta.get("summary", ""),
                    "description": meta.get("description", ""),
                    "operationId": meta.get("operation_id") or f"{method}_{logical_name}",
                    "tags": meta.get("tags") or ["default"],
                    "responses": responses,
                }

                # parameters ------------------------------------------------------
                parameters: list[dict[str, Any]] = meta.get("parameters", [])
                if parameters:
                    op["parameters"] = parameters

                # security --------------------------------------------------------
                security: list[dict[str, list[str]]] = meta.get("security", [])
                if security:
                    op["security"] = security

                # requestBody (POST/PUT/PATCH/DELETE) --------------------------
                if method in {"post", "put", "patch", "delete"}:
                    required = meta.get("request_body_required", True)
                    if meta.get("request_body"):
                        op["requestBody"] = {
                            "required": required,
                            "content": {"application/json": {"schema": meta["request_body"]}},
                        }
                    elif meta.get("request_model"):
                        try:
                            op["requestBody"] = {
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
                            op["requestBody"] = {
                                "required": required,
                                "content": {"application/json": {"schema": {"type": "object"}}},
                            }

                # merge into paths (support multiple methods per route) ----------
                paths.setdefault(path, {})[method] = op

            except (KeyError, TypeError, ValueError):
                logger.exception("Failed to process function %s", func_name)
                # Continue processing other functions
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

        # Merge security schemes: explicit param + per-operation schemes from registry.
        # Raises OpenAPISpecConfigError on collision (same name, different definition).
        all_security_schemes: dict[str, dict[str, Any]] = {}
        if security_schemes:
            all_security_schemes.update(security_schemes)
        for _fn, meta in registry.items():
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
            if openapi_version == OPENAPI_VERSION_3_0:
                components["schemas"] = _convert_schemas_to_3_0(components["schemas"])
            elif openapi_version == OPENAPI_VERSION_3_1:
                components["schemas"] = _convert_schemas_to_3_1(components["schemas"])

        if components.get("schemas") or components.get("securitySchemes"):
            spec["components"] = components

        spec = _normalize_spec_output(spec)

        logger.info(
            f"Generated OpenAPI {openapi_version} spec with {len(paths)} paths "
            f"for {len(registry)} functions"
        )
        return spec

    except OpenAPISpecConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to generate OpenAPI specification: {str(e)}")
        raise RuntimeError("Failed to generate OpenAPI specification") from e


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
    openapi_version: str = OPENAPI_VERSION_3_0,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
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
    openapi_version: str = OPENAPI_VERSION_3_0,
    description: str = DEFAULT_OPENAPI_INFO_DESCRIPTION,
    security_schemes: dict[str, dict[str, Any]] | None = None,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
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
        )
        return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)
    except OpenAPISpecConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to generate OpenAPI YAML: {str(e)}")
        raise RuntimeError("Failed to generate OpenAPI YAML") from e
