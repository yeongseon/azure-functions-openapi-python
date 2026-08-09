from __future__ import annotations

from collections.abc import Iterable
import copy
import logging
from typing import Any, get_origin
import warnings

from pydantic import BaseModel

from azure_functions_openapi import adapters
from azure_functions_openapi._endpoint_contract import (
    ENDPOINT_NAMESPACE,
    SUPPORTED_ENDPOINT_VERSIONS,
)
from azure_functions_openapi._validation_contract import (
    HANDLER_METADATA_ATTR,
    SUPPORTED_VALIDATION_VERSIONS,
    VALIDATION_NAMESPACE,
)
from azure_functions_openapi.decorator import register_openapi_metadata
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import canonical_function_id, registry
from azure_functions_openapi.routes import (
    ALL_HTTP_METHODS,
    BODYLESS_HTTP_METHODS,
    DEFAULT_ROUTE_PREFIX,
    normalize_route_prefix,
)
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


def _extract_http_binding(function: Any) -> Any | None:
    return adapters.extract_http_binding(function)


def _extract_methods(binding: Any) -> tuple[list[str], bool]:
    """Return ``(methods, expanded)`` for an HTTP binding.

    ``expanded`` is ``True`` only when ``methods=`` was *unspecified* (``None``)
    and we therefore expanded to the full :data:`ALL_HTTP_METHODS` set to match
    Azure runtime semantics (unspecified methods respond to every HTTP method).
    An explicit ``methods=[]`` is a *different* signal from omitting ``methods=``
    entirely: it is an explicit (non-expanded) choice, so it is not expanded and
    falls back to a single ``get`` operation for a usable spec.
    """
    methods = getattr(binding, "methods", None)
    if methods is None:
        return list(ALL_HTTP_METHODS), True
    if isinstance(methods, str):
        return [_normalize_method(methods)], False
    if isinstance(methods, Iterable):
        normalized = [_normalize_method(item) for item in methods]
        return (normalized or ["get"]), False
    return ["get"], False


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

    existing_response = existing.get("response") or {}
    discovered_response = discovered.get("response") or {}
    if isinstance(existing_response, dict) and isinstance(discovered_response, dict):
        for status, detail in discovered_response.items():
            if status in existing_response and existing_response[status] != detail:
                return True

    return False


def _merge_into_existing(existing: dict[str, Any], discovered: dict[str, Any]) -> None:
    if _models_conflict(existing, discovered):
        raise OpenAPISpecConfigError("Conflicting validation and OpenAPI models for endpoint")

    if not existing.get("request_body") and discovered.get("request_body"):
        existing["request_body"] = discovered["request_body"]
        if "request_body_required" in discovered:
            existing["request_body_required"] = discovered["request_body_required"]

    if not existing.get("response_model") and discovered.get("response_model"):
        existing["response_model"] = discovered["response_model"]

    discovered_response = discovered.get("response")
    if isinstance(discovered_response, dict) and discovered_response:
        existing_response = existing.get("response")
        if not isinstance(existing_response, dict):
            existing_response = {}
        for status, detail in discovered_response.items():
            existing_response.setdefault(status, detail)
        existing["response"] = existing_response

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


def _discovered_operation_from_endpoint(
    function_name: str, endpoint: dict[str, Any], path: str, method: str
) -> dict[str, Any]:
    """Build a discovered-operation dict from the self-contained ``endpoint`` payload.

    Unlike :func:`_discovered_operation`, every schema field here is already a
    JSON Schema dict authored by the producer, so no Pydantic model access is
    needed. The producer's ``responses`` map is ``{"<status>": {"schema": ...}}``;
    we wrap each entry into a full OpenAPI response object so the spec generator
    can embed it verbatim.
    """
    raw_request_body = endpoint.get("request_body")
    request_body = raw_request_body if isinstance(raw_request_body, dict) else None

    raw_parameters = endpoint.get("parameters")
    parameters = (
        [p for p in raw_parameters if isinstance(p, dict)]
        if isinstance(raw_parameters, list)
        else []
    )

    response: dict[int, dict[str, Any]] = {}
    raw_responses = endpoint.get("responses")
    if isinstance(raw_responses, dict):
        for status, detail in raw_responses.items():
            if not isinstance(detail, dict):
                continue
            try:
                # Reject booleans explicitly: ``bool`` is a subclass of ``int``,
                # so ``int(True)``/``int(False)`` would silently become 1/0.
                if isinstance(status, bool):
                    raise TypeError
                status_code = int(status)
            except (TypeError, ValueError):
                logger.warning(
                    "Skipping endpoint response with non-integer status %r on %r",
                    status,
                    function_name,
                )
                continue
            schema = detail.get("schema")
            response[status_code] = {
                "description": detail.get("description", ""),
                "content": {"application/json": {"schema": schema}},
            }

    return {
        "function_name": function_name,
        "route": path,
        "method": method,
        "request_body": request_body,
        "request_body_required": (
            endpoint["request_body_required"]
            if isinstance(endpoint.get("request_body_required"), bool)
            else True
        ),
        "parameters": parameters,
        "response": response,
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
                    type(raw_version) is not int or raw_version not in SUPPORTED_VALIDATION_VERSIONS
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


def _read_endpoint_hints(handler: Any) -> dict[str, Any] | None:
    """Read shared ``endpoint`` namespace metadata from a handler.

    Mirrors :func:`_read_validation_hints` but targets the self-contained
    ``endpoint`` namespace (pure JSON Schema, no model classes). Walks the
    ``__wrapped__`` chain (outer -> inner) for the first handler carrying
    ``_azure_functions_metadata["endpoint"]``.

    Version policy (``version`` is a required key on the endpoint payload):
    * Present and supported -> accepted.
    * Missing, malformed, or unsupported -> ``logger.warning()`` + continue walking.

    Returns a *deep copy* so callers cannot mutate the handler attribute.
    """
    current: Any = handler
    for _ in range(_MAX_WRAPPED_DEPTH):
        toolkit_meta = getattr(current, HANDLER_METADATA_ATTR, None)
        if isinstance(toolkit_meta, dict):
            hints = toolkit_meta.get(ENDPOINT_NAMESPACE)
            if isinstance(hints, dict):
                raw_version = hints.get("version")
                if type(raw_version) is not int or raw_version not in SUPPORTED_ENDPOINT_VERSIONS:
                    logger.warning(
                        "Skipping endpoint metadata on %r: unsupported version %r (supported: %s)",
                        current,
                        raw_version,
                        ", ".join(str(v) for v in sorted(SUPPORTED_ENDPOINT_VERSIONS)),
                    )
                    wrapped = getattr(current, "__wrapped__", None)
                    if wrapped is None or wrapped is current:
                        break
                    current = wrapped
                    continue
                return copy.deepcopy(hints)

        wrapped = getattr(current, "__wrapped__", None)
        if wrapped is None or wrapped is current:
            break
        current = wrapped

    return None


def _has_endpoint_namespace(handler: Any) -> bool:
    """Return whether *any* handler in the wrapped chain carries an ``endpoint`` namespace.

    Unlike :func:`_read_endpoint_hints`, this ignores version validity: it reports
    mere *presence* of ``_azure_functions_metadata["endpoint"]`` as a dict. It lets
    the scan loop distinguish "no endpoint contract at all" from "endpoint contract
    present but rejected (e.g. unsupported version)", so a silent downgrade to the
    ``validation`` namespace can be surfaced to the user.
    """
    current: Any = handler
    for _ in range(_MAX_WRAPPED_DEPTH):
        toolkit_meta = getattr(current, HANDLER_METADATA_ATTR, None)
        if isinstance(toolkit_meta, dict) and isinstance(
            toolkit_meta.get(ENDPOINT_NAMESPACE), dict
        ):
            return True
        wrapped = getattr(current, "__wrapped__", None)
        if wrapped is None or wrapped is current:
            break
        current = wrapped
    return False


def scan_endpoint_metadata(app: Any, route_prefix: str = DEFAULT_ROUTE_PREFIX) -> None:
    """Scan function builders for toolkit metadata and register OpenAPI operations.

    Reads the convention-based ``_azure_functions_metadata`` attribute from each
    handler, preferring the self-contained ``"endpoint"`` namespace and falling
    back to the ``"validation"`` namespace. No import from
    ``azure-functions-validation`` is required.

    ``route_prefix`` mirrors ``host.json`` ``extensions.http.routePrefix``
    (default ``"/api"``). Pass ``""`` for hosts that disable the prefix or
    a custom value such as ``"/v1"`` to match a non-default deployment.
    """
    functions = adapters.iter_functions(app)
    if not functions:
        logger.debug("No function builders found on app; skipping validation scan")
        return

    for function in functions:
        function_name = adapters.get_function_name(function)
        handler = adapters.get_user_handler(function)
        if handler is None:
            continue
        endpoint_hints = _read_endpoint_hints(handler)
        metadata = None if endpoint_hints is not None else _read_validation_hints(handler)
        if endpoint_hints is None and metadata is None:
            continue

        if endpoint_hints is None and metadata is not None and _has_endpoint_namespace(handler):
            logger.warning(
                "Function '%s' carries an unsupported or malformed endpoint "
                "namespace; falling back to the validation namespace for OpenAPI "
                "generation. The generated spec may differ from the intended "
                "endpoint contract.",
                function_name,
            )

        canonical_id = canonical_function_id(handler)

        binding = _extract_http_binding(function)
        if binding is None:
            logger.debug(
                "Function '%s' has validation metadata but is not HTTP triggered", function_name
            )
            continue

        path = _normalize_path(getattr(binding, "route", None), function_name, route_prefix)
        methods, methods_expanded = _extract_methods(binding)

        for method in methods:
            if endpoint_hints is not None:
                discovered = _discovered_operation_from_endpoint(
                    function_name, endpoint_hints, path, method
                )
            elif metadata is not None:
                discovered = _discovered_operation(function_name, metadata, path, method)
            else:  # pragma: no cover - guarded above (endpoint or metadata is set)
                continue

            # When methods= was unspecified and we auto-expanded to every HTTP
            # method, drop the request body from GET/HEAD/DELETE operations:
            # OpenAPI leaves a body there semantically undefined and many tools
            # reject it. Explicitly requested methods are left untouched.
            if methods_expanded and method in BODYLESS_HTTP_METHODS:
                discovered["request_body"] = None
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

            if endpoint_hints is not None:
                register_openapi_metadata(
                    path=path,
                    method=method,
                    request_body=discovered.get("request_body"),
                    request_body_required=discovered.get("request_body_required", True),
                    response=discovered.get("response") or None,
                    parameters=discovered.get("parameters") or None,
                )
            else:
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


def scan_validation_metadata(app: Any, route_prefix: str = DEFAULT_ROUTE_PREFIX) -> None:
    """Deprecated alias for :func:`scan_endpoint_metadata`.

    The scanner now primarily consumes the namespace-neutral ``"endpoint"``
    contract (the ``"validation"`` namespace is only a fallback), so the
    ``scan_validation_metadata`` name is a misnomer. Use
    :func:`scan_endpoint_metadata` instead. This alias forwards unchanged and
    will be removed in a future minor release.
    """
    warnings.warn(
        "scan_validation_metadata() is deprecated; use scan_endpoint_metadata() "
        "instead. It will be removed in a future minor release.",
        DeprecationWarning,
        stacklevel=2,
    )
    scan_endpoint_metadata(app, route_prefix)
