from __future__ import annotations

from collections.abc import Iterable
import copy
import logging
from typing import Any, cast, get_origin
import warnings

from azure_functions_openapi import adapters
from azure_functions_openapi._endpoint_contract import (
    ENDPOINT_NAMESPACE,
    HANDLER_METADATA_ATTR,
    SUPPORTED_ENDPOINT_VERSIONS,
)
from azure_functions_openapi._warnings import WarningCode
from azure_functions_openapi.decorator import (
    _infer_doc_metadata,
    _infer_response_from_return,
    register_openapi_metadata,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import (
    OpenAPIRegistry,
    canonical_function_id,
)
from azure_functions_openapi.registry import (
    registry as _global_registry,
)
from azure_functions_openapi.routes import (
    ALL_HTTP_METHODS,
    BODYLESS_HTTP_METHODS,
    DEFAULT_ROUTE_PREFIX,
    normalize_route_prefix,
)
from azure_functions_openapi.utils import type_to_schema

logger = logging.getLogger(__name__)


def _tag_skew(entry: dict[str, Any], codes: Iterable[WarningCode]) -> None:
    """Attach structured skew codes to a registry entry (deterministic order).

    Stores the codes under the private ``_skew_flags`` key as a sorted list of
    string values so :func:`generate_openapi_report` can re-derive structured
    :class:`~azure_functions_openapi._warnings.SpecWarning` objects from the
    registry snapshot without any global accumulator.
    """
    codes = list(codes)
    if not codes:
        return
    merged: set[str] = {str(flag) for flag in entry.get("_skew_flags", ())}
    merged.update(code.value for code in codes)
    entry["_skew_flags"] = sorted(merged)


def _stamp_auth_level(entry: dict[str, Any], auth_level: str | None) -> None:
    """Record the binding's normalized ``auth_level`` on a registry entry.

    Stored under the private ``_auth_level`` key (lowercase ``AuthLevel`` value)
    so :func:`azure_functions_openapi.spec.generate_openapi_spec` can optionally
    derive an OpenAPI security requirement from it when ``infer_auth_level`` is
    enabled. A ``None`` level (non-HTTP binding, or an SDK that does not expose
    ``auth_level``) is not stamped, leaving the entry untouched.
    """
    if auth_level is None:
        return
    entry["_auth_level"] = auth_level


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
    # An inferred response (P1-A return-type inference) is the lowest-precedence
    # source, so it never conflicts with discovered validation metadata — the
    # latter simply supersedes it in :func:`_merge_into_existing`.
    response_inferred = bool(existing.get("_response_inferred"))
    existing_response = existing.get("response_model")
    discovered_response = discovered.get("response_model")
    if (
        not response_inferred
        and existing_response is not None
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
    if (
        not response_inferred
        and isinstance(existing_response, dict)
        and isinstance(discovered_response, dict)
    ):
        for status, detail in discovered_response.items():
            if status in existing_response and existing_response[status] != detail:
                return True

    return False


def _merge_into_existing(existing: dict[str, Any], discovered: dict[str, Any]) -> None:
    if _models_conflict(existing, discovered):
        raise OpenAPISpecConfigError("Conflicting validation and OpenAPI models for endpoint")

    # Return-type inference (P1-A) is the lowest-precedence response source. When
    # discovered validation/explicit metadata carries any response, it supersedes
    # the inferred one entirely rather than gap-filling around it.
    if existing.get("_response_inferred") and (
        discovered.get("response_model") or discovered.get("response")
    ):
        existing["response_model"] = None
        existing["response"] = {}
        existing.pop("_response_inferred", None)

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


def _discovered_operation_from_endpoint(
    function_name: str, endpoint: dict[str, Any], path: str, method: str
) -> dict[str, Any]:
    """Build a discovered-operation dict from the self-contained ``endpoint`` payload.

    Every schema field here is already a
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


def _read_endpoint_hints(handler: Any) -> dict[str, Any] | None:
    """Read shared ``endpoint`` namespace metadata from a handler.

    Reads the self-contained ``endpoint`` namespace (pure JSON Schema, no model
    classes). Walks the
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


def _seed_canonical_entry(reg: OpenAPIRegistry, function_id: str) -> None:
    """Copy a handler's canonical ``@openapi`` entries into an isolated registry.

    In isolated mode (#381) the target ``reg`` starts empty, but a handler's
    ``@openapi`` metadata was recorded into the *global* registry at import time.
    This copies every global entry whose ``_function_id`` matches *function_id*
    (deep-copied so later reconciliation cannot mutate the global) into ``reg``
    under its original key, so the reconciliation logic resolves it exactly as it
    would against the global registry.

    Programmatic ``register_openapi_metadata`` entries carry a
    ``"programmatic.*"`` ``_function_id`` and are not tied to any scanned app
    object, so they are never seeded into an isolated app-scoped spec. A handler
    already reconciled into ``reg`` is left untouched: idempotency is judged by
    ``_function_id`` identity, not registry-key presence, because reconciliation
    rewrites the seeded ``method=None`` canonical into per-method ``method::path``
    keys and deletes the original key (#358). Re-seeding on a later scan solely
    because that original key vanished would resurrect a stale ``route=None``
    ghost entry that spec.py then documents as a phantom endpoint (#388 regression).
    """
    if function_id.startswith("programmatic."):
        return
    # Acquire the two registry locks sequentially, never nested. Snapshot the
    # matching global entries (deep-copied eagerly) under the global lock only,
    # then release it before writing into ``reg`` under its own lock. Holding
    # both locks at once risked deadlock for future call paths and lengthened
    # contention across the deepcopy/iteration; splitting the phases avoids both.
    with _global_registry.lock:
        seeds = {
            key: copy.deepcopy(entry)
            for key, entry in _global_registry.entries.items()
            if entry.get("_function_id") == function_id
        }
    with reg.lock:
        # Idempotency guard keyed on identity, not key presence: if ANY entry for
        # this handler already lives in ``reg`` (including an exploded
        # ``method::path`` entry whose original ``method=None`` key was deleted
        # during reconciliation) the handler is already seeded. Re-seeding would
        # reintroduce the stale canonical as a phantom endpoint on re-scan (#388).
        if reg.find_by_function_id(function_id) is not None:
            return
        for key, entry in seeds.items():
            reg.set(key, entry)


def scan_endpoint_metadata(
    app: Any,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
    registry: OpenAPIRegistry | None = None,
) -> None:
    """Scan function builders for toolkit metadata and register OpenAPI operations.

    Reads the convention-based ``_azure_functions_metadata`` attribute from each
    handler, preferring the self-contained ``"endpoint"`` namespace and falling
    back to the ``"validation"`` namespace. No import from
    ``azure-functions-validation`` is required.

    ``route_prefix`` mirrors ``host.json`` ``extensions.http.routePrefix``
    (default ``"/api"``). Pass ``""`` for hosts that disable the prefix or
    a custom value such as ``"/v1"`` to match a non-default deployment.

    ``registry`` selects the target :class:`OpenAPIRegistry`. When ``None``
    (the default) the process-wide global registry is used, preserving the
    common single-app ``function_app.py`` layout. When an isolated registry is
    injected (the CLI ``--isolate-app`` path, #381), each discovered handler's
    canonical ``@openapi`` entry is seeded from the global registry into the
    isolated one before reconciliation, so the generated spec contains only the
    selected app's operations rather than every ``@openapi`` imported from the
    module. Programmatic ``register_openapi_metadata`` entries (which are not
    tied to any app object) are never seeded into an isolated registry.
    """
    reg = registry if registry is not None else _global_registry
    isolated = reg is not _global_registry
    # Discovery skips are recorded on the *selected* registry so the skips and
    # entries stay together (mirroring the #344 skew-warning isolation fix).
    #
    # ``skipped`` tracks whether any builder failed to build: ``iter_functions``
    # returns an empty list both when no builders exist AND when every builder
    # fails (each firing ``on_skip`` without appending). Only the former is a
    # true empty discovery -- see the ``EMPTY_DISCOVERY`` guard below.
    skipped = False

    def _on_skip(name: str | None, reason: str) -> None:
        nonlocal skipped
        skipped = True
        reg.add_discovery_warning(name, reason)

    functions = adapters.iter_functions(app, on_skip=_on_skip)
    if not functions:
        logger.debug("No function builders found on app; skipping validation scan")
        # #373/#380: an app that exposes no discoverable functions is recorded on
        # the dedicated empty-discovery channel (not the builder-failure channel)
        # so ``--fail-on-warnings`` catches it as a distinct ``empty-discovery``
        # signal. Guard on ``not skipped``: when builders existed but all failed
        # to build, ``on_skip`` already recorded per-builder DISCOVERY_SKIPPED
        # warnings, so emitting EMPTY_DISCOVERY too would be semantically wrong
        # (builders were present) and would double-trip ``--fail-on-warnings``.
        # Whether the *final* spec paths are empty is decided by the CLI's
        # post-generation check, since the process-wide registry may already
        # hold paths from other decorated apps.
        if not skipped:
            reg.add_empty_discovery(type(app).__name__)
        return

    for function in functions:
        function_name = adapters.get_function_name(function)
        handler = adapters.get_user_handler(function)
        if handler is None:
            continue

        endpoint_hints = _read_endpoint_hints(handler)
        has_enrichment = endpoint_hints is not None
        # Endpoint namespace present but rejected (unsupported/malformed
        # version): no enrichment is consumed. We still surface a structured
        # VERSION_SKEW warning on the binding-derived operation so a degraded,
        # wrong-but-plausible spec stays observable (e.g. via
        # --fail-on-warnings) instead of silently producing an empty spec.
        # There is no longer a validation-namespace fallback to consume.
        endpoint_skew = endpoint_hints is None and _has_endpoint_namespace(handler)

        # Binding-first (#364): the Azure @app.route binding is the source of
        # truth for route + method. Resolve it before anything else -- a handler
        # without an HTTP binding has no concrete operations to register.
        binding = _extract_http_binding(function)
        if binding is None:
            if has_enrichment:
                logger.debug(
                    "Function '%s' has validation metadata but is not HTTP triggered",
                    function_name,
                )
            continue

        methods, methods_expanded = _extract_methods(binding)
        # Store the raw binding route (prefix NOT applied). spec.py re-applies
        # apply_route_prefix to meta["route"], and that call is idempotent, so
        # the reason for keeping the raw value is not to avoid double-prefixing
        # but to keep meta["route"] as the binding's source-of-truth route rather
        # than a pre-normalized path that already folds in the prefix.
        raw_route = getattr(binding, "route", None)
        # Per-route auth level (declared via ``@app.route(auth_level=...)``)
        # lives on the HTTP-trigger binding, not the app default. Capture it as
        # a normalized lowercase string so spec.py can optionally infer an
        # OpenAPI security requirement from it (#482).
        auth_level = adapters.extract_auth_level(binding)

        canonical_id = canonical_function_id(handler)

        # Seed-on-scan (#381): in isolated mode the target registry starts empty,
        # so the handler's canonical @openapi entry (registered globally at import
        # time) must be copied in before reconciliation — otherwise a plain
        # @openapi handler would resolve to nothing and be dropped. Only this
        # app's handlers are seeded, which is exactly what scopes the spec.
        if isolated:
            _seed_canonical_entry(reg, canonical_id)

        # Resolve the canonical @openapi entry once (it does not vary per
        # method). When @openapi decorates the handler BELOW @app.route, the
        # decorator cannot see the HTTP binding and registers the entry with
        # method=None; we then explode that entry into one operation per bound
        # method instead of merging every method into it, which would otherwise
        # collapse the generated spec to a single GET (#358).
        with reg.lock:
            canonical_target = reg.find_by_function_id(canonical_id)
            explode_canonical = (
                canonical_target is not None and canonical_target.get("method") is None
            )
            # An explicit @openapi(method=...) that the binding does not serve is
            # a mismatch: stamp the binding's specified method set on the entry so
            # spec.py can flag the unreachable operation (#362/#368). Unspecified
            # (auto-expanded) bindings serve every verb, so they are never stamped
            # and never contradict the authored method.
            if (
                not explode_canonical
                and canonical_target is not None
                and canonical_target.get("method") is not None
                and not methods_expanded
            ):
                canonical_target["_binding_methods"] = list(methods)

        # Path key. Enrichment handlers key off the binding route (the runtime
        # truth). A plain @openapi entry may carry an explicit route= override
        # registered before the binding was visible, so honour it when present
        # (mirrors the pre-#364 plain-reconcile path).
        if has_enrichment:
            path = _normalize_path(raw_route, function_name, route_prefix)
        else:
            entry_route = canonical_target.get("route") if canonical_target is not None else None
            entry_name = (
                canonical_target.get("function_name") if canonical_target is not None else None
            ) or function_name
            path = _normalize_path(entry_route or raw_route, entry_name, route_prefix)

        # Return-type inference (P1-A): for a bare ``@app.route`` handler with no
        # ``@openapi`` entry and no validation enrichment, infer the 200 response
        # from the handler's return annotation. Gated off when a canonical entry
        # exists (decorator-time inference already ran), when validation
        # enrichment is present (higher precedence), or under version skew (keep
        # the degraded bare op observable). Computed once — it does not vary per
        # method.
        inferred_response_model: Any = None
        inferred_response: dict[int | str, dict[str, Any]] | None = None
        inferred_summary = ""
        inferred_description = ""
        if canonical_target is None and endpoint_hints is None and not endpoint_skew:
            inferred_response_model, inferred_response = _infer_response_from_return(handler)
            inferred_summary, inferred_description = _infer_doc_metadata(handler)

        for method in methods:
            endpoint_key = f"{method}::{path}"
            entry_skew: set[WarningCode] = {WarningCode.VERSION_SKEW} if endpoint_skew else set()

            # Build the enrichment payload for this concrete operation. Plain
            # @openapi handlers (and endpoint-skew handlers) have no metadata to
            # merge, so ``discovered`` is None and the binding alone materializes
            # the operation.
            discovered: dict[str, Any] | None = None
            if endpoint_hints is not None:
                discovered = _discovered_operation_from_endpoint(
                    function_name, endpoint_hints, path, method
                )

            # When methods= was unspecified and we auto-expanded to every HTTP
            # method, drop the request body from GET/HEAD/DELETE operations:
            # OpenAPI leaves a body there semantically undefined and many tools
            # reject it. Explicitly requested methods are left untouched.
            if discovered is not None and methods_expanded and method in BODYLESS_HTTP_METHODS:
                discovered["request_body"] = None

            with reg.lock:
                if explode_canonical:
                    # Seed one per-method entry from the method=None @openapi
                    # entry, then merge any enrichment into it. Collapsing every
                    # bound method into the single method=None entry would make
                    # spec.py emit a lone GET (#358).
                    clone = copy.deepcopy(cast("dict[str, Any]", canonical_target))
                    clone["method"] = method
                    # Preserve the binding route on the clone. The decorator could
                    # not see the binding, so @openapi registered route=None;
                    # without this, spec.py falls back to the function name and
                    # emits the wrong path (#360). An explicit @openapi(route=...)
                    # stays truthy and is never overwritten.
                    if clone.get("route") is None and raw_route:
                        clone["route"] = raw_route
                    if discovered is not None:
                        _merge_into_existing(clone, discovered)
                    if methods_expanded and method in BODYLESS_HTTP_METHODS:
                        clone["request_body"] = None
                    _tag_skew(clone, entry_skew)
                    reg.set(endpoint_key, clone)
                    continue

                if discovered is None:
                    # No enrichment payload for this operation.
                    if canonical_target is not None:
                        # Plain @openapi with an explicit method and no
                        # enrichment. When @openapi decorated the handler before
                        # the @app.route binding was visible the entry was
                        # registered with route=None and spec.py would fall back
                        # to the function name. Reconcile the missing route from
                        # the binding without exploding or overriding the explicit
                        # method. An explicit @openapi(route=...) stays truthy and
                        # is never overwritten.
                        if canonical_target.get("route") is None and raw_route:
                            canonical_target["route"] = raw_route
                        _tag_skew(canonical_target, entry_skew)
                        continue
                    if not entry_skew:
                        if inferred_response_model is None and inferred_response is None:
                            # Plain binding with neither @openapi nor enrichment
                            # nor skew nor an inferable return type: nothing to
                            # register.
                            continue
                        # Return-type inference (P1-A): fall through past the
                        # lock to register the inferred response as a standalone
                        # binding-derived operation below.
                    # Endpoint namespace present but rejected (skew) with no
                    # canonical @openapi entry: fall through to register a bare
                    # binding-derived operation below and tag the skew, so the
                    # degraded spec stays observable via --fail-on-warnings.
                else:
                    # Resolve the target entry by, in order of trust:
                    #   1. the exact OpenAPI endpoint key (method::path),
                    #   2. canonical callable identity, method-aware,
                    #   3. the short function name (backward-compatible fallback).
                    #
                    # The endpoint key is tried FIRST because #359 made
                    # ``_function_id`` one-to-many: an exploded multi-method
                    # handler has several entries sharing one ``_function_id``.
                    # Resolving by id alone would let every method iteration merge
                    # into whichever sibling comes first, corrupting per-method
                    # operations on a re-scan. The exact ``method::path`` key pins
                    # each method to its own entry; the id lookup is then
                    # method-aware as a backstop.
                    target = reg.get(endpoint_key)
                    match_kind = "OpenAPI endpoint"

                    if target is None:
                        target = reg.find_by_function_id(canonical_id, method=method)
                        match_kind = "canonical @openapi id"

                    if target is None:
                        # Short-name fallback: refuse to merge when the name is
                        # ambiguous (shared across modules) to avoid silently
                        # attaching metadata to the wrong handler.
                        if reg.count_by_function_name(function_name) > 1:
                            logger.warning(
                                "Refusing to merge endpoint metadata by ambiguous "
                                "short name '%s': multiple @openapi entries share "
                                "this name across modules. Registering a standalone "
                                "endpoint instead.",
                                function_name,
                            )
                            entry_skew.add(WarningCode.AMBIGUOUS_NAMESPACE)
                        else:
                            target = reg.get(function_name)
                            match_kind = "short-name fallback"

                    if target is not None:
                        _merge_into_existing(target, discovered)
                        _tag_skew(target, entry_skew)
                        logger.debug(
                            "Merged endpoint metadata via %s into endpoint '%s'",
                            match_kind,
                            endpoint_key,
                        )
                        continue

            if discovered is not None:
                register_openapi_metadata(
                    path=path,
                    method=method,
                    request_body=discovered.get("request_body"),
                    request_body_required=discovered.get("request_body_required", True),
                    response=discovered.get("response") or None,
                    parameters=discovered.get("parameters") or None,
                    registry=reg,
                )
            elif inferred_response_model is not None or inferred_response is not None:
                # Standalone operation materialized purely from return-type
                # inference (P1-A). Tag it ``_response_inferred`` so a later scan
                # carrying validation/explicit metadata supersedes it.
                register_openapi_metadata(
                    path=path,
                    method=method,
                    summary=inferred_summary,
                    description=inferred_description,
                    response_model=inferred_response_model,
                    response=cast("dict[int, dict[str, Any]] | None", inferred_response or None),
                    registry=reg,
                )
                with reg.lock:
                    inferred_entry = reg.get(endpoint_key)
                    if inferred_entry is not None:
                        inferred_entry["_response_inferred"] = True
            else:
                # Bare binding-derived operation for an endpoint-skew handler: no
                # enrichment was consumed, but the operation is materialized so
                # the structured VERSION_SKEW warning is observable in the spec.
                register_openapi_metadata(
                    path=path,
                    method=method,
                    registry=reg,
                )
            logger.debug("Registered endpoint metadata for endpoint '%s'", endpoint_key)
            # Hold the registry lock across the get+mutate so tagging honours the
            # registry's documented thread-safety contract (the entry must not be
            # mutated after the lock protecting it has been released).
            with reg.lock:
                registered = reg.get(endpoint_key)
                if registered is not None:
                    _tag_skew(registered, entry_skew)

        # Stamp the per-route auth level onto every operation this function
        # produced so spec.py can infer security when ``infer_auth_level`` is on
        # (#482). Stamping is done here, after all terminal branches, because the
        # method loop has several exit points (explode / plain / merge /
        # register); resolving each finalized entry once here keeps the capture
        # in a single place. Re-stamping is idempotent.
        if auth_level is not None:
            with reg.lock:
                if canonical_target is not None:
                    _stamp_auth_level(canonical_target, auth_level)
                for method in methods:
                    entry = reg.get(f"{method}::{path}")
                    if entry is not None:
                        _stamp_auth_level(entry, auth_level)

        # After exploding a method=None @openapi entry into per-method entries,
        # drop the original so spec.py does not additionally emit it as a bare
        # GET duplicate (#358). Match by identity: find_by_function_id returns
        # the live entry but not its registry key.
        if explode_canonical:
            with reg.lock:
                for key, entry in list(reg.entries.items()):
                    if entry is canonical_target:
                        del reg.entries[key]
                        break


def scan_validation_metadata(
    app: Any,
    route_prefix: str = DEFAULT_ROUTE_PREFIX,
    registry: OpenAPIRegistry | None = None,
) -> None:
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
    scan_endpoint_metadata(app, route_prefix, registry=registry)
