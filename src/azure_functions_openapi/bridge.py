from __future__ import annotations

from collections.abc import Iterable
import copy
import logging
from typing import Any, get_origin

from pydantic import BaseModel

from azure_functions_openapi._validation_contract import (
    HANDLER_METADATA_ATTR,
    SUPPORTED_VALIDATION_VERSIONS,
    VALIDATION_NAMESPACE,
)
from azure_functions_openapi.decorator import register_openapi_metadata
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import canonical_function_id, registry
from azure_functions_openapi.routes import DEFAULT_ROUTE_PREFIX, normalize_route_prefix
from azure_functions_openapi.utils import type_to_schema

logger = logging.getLogger(__name__)


def _is_base_model_type(model: Any) -> bool:
    return isinstance(model, type) and issubclass(model, BaseModel)


def _normalize_method(method: Any) -> str:
    if method is None:
        return "get"
    value = getattr(method, "value", method)
    return str(value).lower()


def _normalize_path(
    route: str | None,
    function_name: str,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
) -> str:
    """Compose a path key for the OpenAPI registry from a binding route.

    ``route_prefix`` mirrors ``host.json`` ``extensions.http.routePrefix`` so
    that scans stay consistent with the runtime URLs Azure Functions actually
    serves. Pass ``""`` for hosts that disable the prefix and any other
    value (e.g. ``"/v1"``) for custom prefixes.
    """
    prefix = normalize_route_prefix(route_prefix)
    raw = (route or function_name or "").strip()
    if not raw:
        raw = function_name
    if not raw.startswith("/"):
        raw = f"/{raw}"
    if not prefix:
        return raw
    if raw == prefix or raw.startswith(f"{prefix}/"):
        return raw
    return f"{prefix}{raw}"


def _extract_http_binding(function_obj: Any) -> Any | None:
    for binding in getattr(function_obj, "_bindings", []):
        if str(getattr(binding, "type", "")).lower() == "httptrigger":
            return binding
    return None


def _extract_methods(binding: Any) -> list[str]:
    methods = getattr(binding, "methods", None)
    if methods is None:
        return ["get"]
    if isinstance(methods, str):
        return [_normalize_method(methods)]
    if isinstance(methods, Iterable):
        normalized = [_normalize_method(item) for item in methods]
        return normalized or ["get"]
    return ["get"]


def _merge_parameters(
    existing: list[dict[str, Any]],
    discovered: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = list(existing)
    index_by_key: dict[tuple[str, str], int] = {
        (str(item.get("in", "")), str(item.get("name", ""))): i
        for i, item in enumerate(existing)
        if isinstance(item, dict)
    }
    for param in discovered:
        key = (str(param.get("in", "")), str(param.get("name", "")))
        if key not in index_by_key:
            index_by_key[key] = len(merged)
            merged.append(param)
            continue
        current = merged[index_by_key[key]]
        if current != param:
            raise OpenAPISpecConfigError(
                "Conflicting parameter schema for "
                f"'{key[0]}:{key[1]}' discovered from validation metadata"
            )
    return merged


def _models_conflict(existing: dict[str, Any], discovered: dict[str, Any]) -> bool:
    existing_response = existing.get("response_model")
    discovered_response = discovered.get("response_model")
    if (
        existing_response is not None
        and discovered_response is not None
        and existing_response is not discovered_response
    ):
        return True

    existing_request_body = existing.get("request_body")
    discovered_request_body = discovered.get("request_body")
    if (
        existing_request_body is not None
        and discovered_request_body is not None
        and existing_request_body != discovered_request_body
    ):
        return True

    try:
        _merge_parameters(existing.get("parameters", []), discovered.get("parameters", []))
    except OpenAPISpecConfigError:
        return True

    return False


def _merge_into_existing(existing: dict[str, Any], discovered: dict[str, Any]) -> None:
    if _models_conflict(existing, discovered):
        raise OpenAPISpecConfigError("Conflicting validation and OpenAPI models for endpoint")

    if not existing.get("request_body") and discovered.get("request_body"):
        existing["request_body"] = discovered["request_body"]

    if not existing.get("response_model") and discovered.get("response_model"):
        existing["response_model"] = discovered["response_model"]

    existing_params = existing.get("parameters", [])
    discovered_params = discovered.get("parameters", [])
    existing["parameters"] = _merge_parameters(existing_params, discovered_params)


def _field_type_to_schema(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if origin in (list, tuple, set):
        return {"type": "array"}
    schema = type_to_schema(annotation)
    if "$defs" in schema:
        schema = dict(schema)
        schema.pop("$defs", None)
    return schema


def _model_to_parameters(model_cls: type, location: str) -> list[dict[str, Any]]:
    if not hasattr(model_cls, "model_fields"):
        raise TypeError(
            f"Expected Pydantic model with model_fields, got {type(model_cls).__name__}"
        )

    required_fields = getattr(model_cls, "model_fields", {})
    required_names = {
        name
        for name, field in required_fields.items()
        if getattr(field, "is_required", lambda: False)()
    }
    params: list[dict[str, Any]] = []
    for name, field in required_fields.items():
        schema = _field_type_to_schema(getattr(field, "annotation", Any))
        params.append(
            {
                "name": name,
                "in": location,
                "required": location == "path" or name in required_names,
                "schema": schema,
            }
        )
    return params


def _discovered_operation(
    function_name: str, metadata: dict[str, Any], path: str, method: str
) -> dict[str, Any]:
    request_body = type_to_schema(metadata["body"]) if metadata.get("body") is not None else None
    parameters: list[dict[str, Any]] = []
    if metadata.get("query") is not None:
        parameters.extend(_model_to_parameters(metadata["query"], "query"))
    if metadata.get("path") is not None:
        parameters.extend(_model_to_parameters(metadata["path"], "path"))
    if metadata.get("headers") is not None:
        parameters.extend(_model_to_parameters(metadata["headers"], "header"))
    return {
        "function_name": function_name,
        "route": path,
        "method": method,
        "request_body": request_body,
        "parameters": parameters,
        "response_model": metadata.get("response_model"),
    }


# Maximum decorator depth to walk when chasing ``__wrapped__``.
_MAX_WRAPPED_DEPTH = 16

# Backward-compatible alias for the convention attribute name.
_HANDLER_METADATA_ATTR = HANDLER_METADATA_ATTR


def _read_validation_hints(handler: Any) -> dict[str, Any] | None:
    """Read validation hints from a handler using the convention attribute.

    Walks the ``__wrapped__`` chain (outer → inner) looking for the first
    handler that carries ``_azure_functions_metadata["validation"]``.  This
    ensures that metadata set by an inner decorator is still discovered even
    when additional decorators (e.g. ``@functools.wraps``) wrap the handler.

    Version policy (``version`` is nested inside the ``validation`` payload):
    * Missing ``version`` key -> accepted as v1 (backward-compatible).
    * Present and supported → accepted.
    * Present but malformed or unsupported → ``logger.warning()`` + continue walking.

    Returns a *deep copy* of the validation dict so callers cannot mutate
    the original handler attribute.
    """
    current: Any = handler
    for _ in range(_MAX_WRAPPED_DEPTH):
        toolkit_meta = getattr(current, HANDLER_METADATA_ATTR, None)
        if isinstance(toolkit_meta, dict):
            hints = toolkit_meta.get(VALIDATION_NAMESPACE)
            if isinstance(hints, dict):
                # --- version gate (version is nested in the namespace payload) ---
                raw_version = hints.get("version")
                if raw_version is not None and (
                    type(raw_version) is not int
                    or raw_version not in SUPPORTED_VALIDATION_VERSIONS
                ):
                    logger.warning(
                        "Skipping metadata on %r: unsupported version %r (supported: %s)",
                        current,
                        raw_version,
                        ", ".join(str(v) for v in sorted(SUPPORTED_VALIDATION_VERSIONS)),
                    )
                    # Continue walking; an inner handler may have valid metadata.
                    wrapped = getattr(current, "__wrapped__", None)
                    if wrapped is None or wrapped is current:
                        break
                    current = wrapped
                    continue
                return copy.deepcopy(hints)

        # Walk the __wrapped__ chain.
        wrapped = getattr(current, "__wrapped__", None)
        if wrapped is None or wrapped is current:
            break
        current = wrapped

    return None


def scan_validation_metadata(app: Any, route_prefix: str = DEFAULT_ROUTE_PREFIX) -> None:
    """Scan function builders for validation metadata and register OpenAPI operations.

    This function reads the convention-based ``_azure_functions_metadata``
    attribute (namespace ``"validation"``) from each handler.  No import from
    ``azure-functions-validation`` is required.

    ``route_prefix`` mirrors ``host.json`` ``extensions.http.routePrefix``
    (default ``"/api"``). Pass ``""`` for hosts that disable the prefix or
    a custom value such as ``"/v1"`` to match a non-default deployment.
    """
    builders = getattr(app, "_function_builders", None)
    if not builders:
        logger.debug("No function builders found on app; skipping validation scan")
        return

    for builder in builders:
        function_obj = getattr(builder, "_function", None)
        if function_obj is None:
            continue
        function_name = str(getattr(function_obj, "_name", ""))
        handler = getattr(function_obj, "_func", None)
        if handler is None:
            continue
        metadata = _read_validation_hints(handler)
        if metadata is None:
            continue

        canonical_id = canonical_function_id(handler)

        binding = _extract_http_binding(function_obj)
        if binding is None:
            logger.debug(
                "Function '%s' has validation metadata but is not HTTP triggered", function_name
            )
            continue

        path = _normalize_path(getattr(binding, "route", None), function_name, route_prefix)
        methods = _extract_methods(binding)

        for method in methods:
            discovered = _discovered_operation(function_name, metadata, path, method)
            endpoint_key = f"{method}::{path}"

            with registry.lock:
                # Resolve the target entry by, in order of trust:
                #   1. canonical callable identity (collision-free),
                #   2. the OpenAPI endpoint key (method::path),
                #   3. the short function name (backward-compatible fallback).
                target = registry.find_by_function_id(canonical_id)
                match_kind = "canonical @openapi id"

                if target is None:
                    target = registry.get(endpoint_key)
                    match_kind = "OpenAPI endpoint"

                if target is None:
                    # Short-name fallback: refuse to merge when the name is
                    # ambiguous (shared across modules) to avoid silently
                    # attaching metadata to the wrong handler.
                    if registry.count_by_function_name(function_name) > 1:
                        logger.warning(
                            "Refusing to merge validation metadata by ambiguous "
                            "short name '%s': multiple @openapi entries share this "
                            "name across modules. Registering a standalone endpoint "
                            "instead.",
                            function_name,
                        )
                    else:
                        target = registry.get(function_name)
                        match_kind = "short-name fallback"

                if target is not None:
                    _merge_into_existing(target, discovered)
                    logger.debug(
                        "Merged validation metadata via %s into endpoint '%s'",
                        match_kind,
                        endpoint_key,
                    )
                    continue

            register_openapi_metadata(
                path=path,
                method=method,
                request_body=discovered.get("request_body"),
                response_model=discovered.get("response_model")
                if _is_base_model_type(discovered.get("response_model"))
                else None,
                parameters=discovered.get("parameters") or None,
            )
            logger.debug("Registered validation metadata for endpoint '%s'", endpoint_key)
