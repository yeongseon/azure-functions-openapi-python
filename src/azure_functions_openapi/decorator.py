# src/azure_functions_openapi/decorator.py
from __future__ import annotations

import collections.abc as _cabc
from collections.abc import Mapping
from http import HTTPStatus
import inspect
import logging
import re
import types
from typing import (
    Any,
    Callable,
    Literal,
    TypeGuard,
    TypeVar,
    Union,
    cast,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel

from azure_functions_openapi import adapters
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import (
    OpenAPIRegistry,
    ensure_canonical_identity,
    registry,
)
from azure_functions_openapi.utils import sanitize_operation_id, validate_route_path

# Define a generic type variable for functions
F = TypeVar("F", bound=Callable[..., Any])

# The registry now lives in :mod:`azure_functions_openapi.registry`. These
# module-level names are retained as backward-compatible aliases: ``_registry``
# is the owning :class:`OpenAPIRegistry`, while ``_openapi_registry`` and
# ``_registry_lock`` expose its live entry dict and lock (the same objects the
# registry uses internally) so existing call-sites keep working unchanged.
_registry: OpenAPIRegistry = registry
_openapi_registry: dict[str, dict[str, Any]] = registry.entries
_registry_lock = registry.lock

logger = logging.getLogger(__name__)


def _resolve_metadata_target(func: Any) -> tuple[Any, Callable[..., Any]]:
    """Return the original decorated object and the underlying callable used for metadata."""
    if adapters.is_function_builder(func):
        # The user handler and bindings live on the SDK's FunctionBuilder, which
        # only exposes them via private attributes. Route the access through the
        # adapter so all SDK coupling (and the SDKIncompatibleError contract for
        # renamed/restructured internals) stays in one place.
        try:
            function = adapters.build_function(func)
        except ValueError:
            # ``@openapi`` applied below ``@app.route``: the trigger is not
            # registered yet, so build() reports "no trigger". This is a valid
            # decorator ordering (accepted by 0.20.0), not an error. Recover the
            # user handler off the unbuilt builder so metadata still registers;
            # route/method stay unresolved until later discovery/spec generation.
            handler = adapters.get_unbuilt_user_handler(func)
            if handler is None:
                raise
            return func, handler
        return func, adapters.get_user_handler(function)

    if not callable(func):
        raise TypeError(f"Unsupported decorated object: {type(func).__name__}")

    return func, cast(Callable[..., Any], func)


def _extract_binding_hints(func: Any) -> tuple[str | None, str | None, bool, bool]:
    """Extract route and method from a FunctionBuilder's HTTP trigger binding.

    Returns ``(route, method, multiple_methods, methods_unspecified)`` where:
    - ``route`` and ``method`` may each be ``None`` if not available.
    - ``multiple_methods`` is ``True`` when the binding declares more than one
      HTTP method; in that case ``method`` is ``None`` and the caller must
      require an explicit ``method=`` argument from the user.
    - ``methods_unspecified`` is ``True`` only when an ``httptrigger`` binding
      is present but omits ``methods=`` entirely. This is the sole evidence
      that the Azure runtime will answer *every* HTTP method, so it gates the
      all-method expansion in the spec generator (a bare ``@openapi`` with no
      binding must NOT expand).
    """
    if not adapters.is_function_builder(func):
        return None, None, False, False

    try:
        function = adapters.build_function(func)
    except ValueError:
        # No trigger yet (``@openapi`` below ``@app.route``): route/method cannot
        # be auto-detected at decoration time. Leave them unresolved; the caller
        # already tolerates None and later discovery resolves the final binding.
        return None, None, False, False
    bindings = adapters.get_bindings(function)

    for binding in bindings:
        if str(getattr(binding, "type", "")).lower() != "httptrigger":
            continue

        binding_route = getattr(binding, "route", None)
        methods_attr = getattr(binding, "methods", None)

        binding_method: str | None = None
        if isinstance(methods_attr, str):
            binding_method = methods_attr.lower()
        elif isinstance(methods_attr, (list, tuple)):
            if len(methods_attr) > 1:
                # ambiguous — caller must require an explicit method=
                return binding_route, None, True, False
            if methods_attr:
                val = methods_attr[0]
                binding_method = str(getattr(val, "value", val)).lower()

        return binding_route, binding_method, False, binding_method is None

    return None, None, False, False


def _is_pydantic_model(value: Any) -> TypeGuard[type[BaseModel]]:
    """Return True when *value* is a Pydantic ``BaseModel`` subclass (a class)."""
    return isinstance(value, type) and issubclass(value, BaseModel)


def _default_response_description(status: int | Literal["default"]) -> str:
    """Default OpenAPI response description for a bare per-status model shorthand."""
    if status == "default":
        return "Response"
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Successful Response" if 200 <= status < 300 else "Response"


def _coerce_status_key(status: Any, func_name: str) -> int | Literal["default"]:
    """Coerce a ``responses`` status key to an int or the literal ``"default"``."""
    if status == "default":
        return "default"
    if isinstance(status, bool):
        raise ValueError(
            f"Invalid 'responses' status key {status!r} in function '{func_name}': "
            f"status keys must be integers (e.g. 200), numeric strings (e.g. '200'), "
            f"or the literal 'default'."
        )
    if isinstance(status, int):
        return status
    if isinstance(status, str) and status.isdigit():
        return int(status)
    raise ValueError(
        f"Invalid 'responses' status key {status!r} in function '{func_name}': "
        f"status keys must be integers (e.g. 200), numeric strings (e.g. '200'), "
        f"or the literal 'default'. To describe a full Response Object, use the "
        f"dict form as the value."
    )


# Container generics accepted as a response-body shorthand (issue #493). Only
# these origins have a well-defined JSON Schema projection via
# ``TypeAdapter``; other generics (``Callable``, ``Iterator``, coroutines, ...)
# either fail late during spec generation or produce nonsensical schemas, so
# they are rejected at decoration time with an actionable error.
_SHORTHAND_CONTAINER_ORIGINS: frozenset[Any] = frozenset(
    {
        list,
        tuple,
        set,
        frozenset,
        dict,
        _cabc.Sequence,
        _cabc.Mapping,
        _cabc.Set,
        _cabc.MutableSequence,
        _cabc.MutableMapping,
        _cabc.MutableSet,
    }
)


def _is_supported_shorthand_generic(value: Any) -> bool:
    """Return ``True`` if *value* is a generic alias usable as a body shorthand.

    Accepts container generics (``list[...]``, ``dict[...]``, their
    ``collections.abc`` equivalents, etc.) and unions/``Optional`` (both
    ``typing.Union`` and PEP 604 ``X | Y``). Everything else — most notably
    ``Callable`` — is rejected so misuse fails fast at decoration time.
    """
    origin = get_origin(value)
    if origin is None:
        return False
    if origin in _SHORTHAND_CONTAINER_ORIGINS:
        return True
    return origin is Union or origin is types.UnionType


def _normalize_unified_responses(
    responses: Mapping[Any, Any], func_name: str
) -> dict[int | str, dict[str, Any]]:
    """Normalize a unified ``responses=`` mapping into OpenAPI Response Objects.

    Each value may be either:

    * a Pydantic ``BaseModel`` subclass — shorthand for a JSON body of that
      schema, expanded to ``{"description": ..., "content":
      {"application/json": {"schema": Model}}}`` (the model class is resolved to
      a schema at spec-generation time, where the ``components`` registry lives), or
    * a generic collection alias such as ``list[Model]`` — the same bare-shorthand
      treatment, resolved to an array schema at spec-generation time. Only
      container generics (``list``/``tuple``/``set``/``frozenset``/``dict`` and
      their ``collections.abc`` equivalents) and unions/``Optional`` are accepted;
      any other generic (e.g. ``Callable``) raises ``ValueError`` at decoration
      time (#493), or
    * an OpenAPI Response Object mapping (unchanged; a Pydantic model may also appear
      in its ``content.<media>.schema`` position and is resolved the same way), or
    * ``None`` — shorthand for a body-less response (e.g. ``204 No Content``),
      expanded to ``{"description": ...}`` with no ``content`` key.

    Status keys may be ints (``200``), numeric strings (``"200"``), or the literal
    OpenAPI ``"default"`` key (the fallback response for any undocumented status);
    any other key raises ``ValueError``. Values of any other type also raise
    ``ValueError`` so misuse fails fast at decoration time rather than silently
    producing an invalid spec.
    """
    normalized: dict[int | str, dict[str, Any]] = {}
    for raw_status, value in responses.items():
        status = _coerce_status_key(raw_status, func_name)
        if value is None:
            normalized[status] = {"description": _default_response_description(status)}
        elif _is_pydantic_model(value):
            normalized[status] = {
                "description": _default_response_description(status),
                "content": {"application/json": {"schema": value}},
            }
        elif get_origin(value) is not None:
            # A generic alias shorthand (e.g. ``list[Model]``). Only container
            # generics and unions project cleanly to a JSON body schema (#493);
            # reject anything else (``Callable``, iterators, coroutines, ...)
            # here so the failure is at decoration time with a clear message,
            # not a late/garbled schema during spec generation.
            if not _is_supported_shorthand_generic(value):
                origin = get_origin(value)
                origin_name = getattr(origin, "__name__", str(origin))
                raise ValueError(
                    f"Invalid 'responses' entry for status {status} in function "
                    f"'{func_name}': {value!r} uses the unsupported generic "
                    f"origin '{origin_name}'. Only container generics "
                    f"(list, tuple, set, frozenset, dict and their "
                    f"collections.abc equivalents) and unions/Optional are "
                    f"accepted as a response-body shorthand. To describe this "
                    f"response, pass an explicit OpenAPI Response Object mapping "
                    f"as the value instead."
                )
            normalized[status] = {
                "description": _default_response_description(status),
                "content": {"application/json": {"schema": value}},
            }
        elif isinstance(value, Mapping):
            normalized[status] = dict(value)
        else:
            raise ValueError(
                f"Invalid 'responses' entry for status {status} in function "
                f"'{func_name}': each value must be a Pydantic BaseModel subclass, "
                f"a generic collection alias (e.g. list[Model]), an OpenAPI "
                f"Response Object mapping, or None (body-less response), "
                f"got {type(value).__name__}."
            )
    return normalized


def _infer_response_from_return(
    func: Callable[..., Any],
) -> tuple[type[BaseModel] | None, dict[int | str, dict[str, Any]] | None]:
    """Infer a 200 response from a handler's return annotation (P1-A, #TBD).

    Gap-filling only. Returns ``(model, None)`` when the return annotation is a
    Pydantic ``BaseModel`` subclass, or ``(None, {200: <Response Object>})`` when
    it is a supported container/union shorthand (e.g. ``list[User]``,
    ``Optional[User]``) — the raw type is stored and resolved to a schema at
    spec-generation time, exactly like an explicit ``responses=`` shorthand.

    Returns ``(None, None)`` when the return annotation is absent, unresolved, or
    not a documentable schema type (``None``/``NoneType``, ``Any``,
    ``func.HttpResponse``, bare ``str``/``int``, ...). Inference is the
    lowest-precedence source: callers apply it only when the user supplied no
    explicit ``responses=``, and validation/explicit metadata supersedes it
    during scan-time reconciliation.

    All annotation introspection is wrapped so a handler with unresolved forward
    references (e.g. under ``from __future__ import annotations``) never breaks
    decoration or spec generation — on any failure inference simply yields
    nothing.
    """
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        # Unresolved forward refs / stringized annotations / exotic objects:
        # never let inference raise. Emit nothing instead.
        return None, None

    hint = hints.get("return")
    if hint is None:
        # No return annotation, or annotated as ``None`` (``get_type_hints``
        # maps a bare ``None`` return to ``type(None)``, handled by the
        # not-documentable fall-through below).
        return None, None

    if _is_pydantic_model(hint):
        return hint, None

    if _is_supported_shorthand_generic(hint):
        return None, {
            200: {
                "description": _default_response_description(200),
                "content": {"application/json": {"schema": hint}},
            }
        }

    # Not a documentable schema type (NoneType, Any, func.HttpResponse, bare
    # scalars, unsupported generics): leave the response undocumented.
    return None, None

def _infer_doc_metadata(func: Callable[..., Any]) -> tuple[str, str]:
    """Infer ``(summary, description)`` from a handler's docstring (P1-A Phase 2).

    Gap-filling only and lowest precedence: the first non-empty line of the
    (dedented) docstring becomes the ``summary`` and the remainder becomes the
    ``description``. Callers apply each field only when the user supplied no
    explicit value. A missing or blank docstring yields ``("", "")``.
    """
    doc = inspect.getdoc(func)
    if not doc or not doc.strip():
        return "", ""
    lines = doc.strip().split("\n")
    summary = lines[0].strip()
    description = "\n".join(lines[1:]).strip()
    return summary, description


def openapi(
    # ── basic metadata ───────────────────────────────────────────
    summary: str = "",
    description: str = "",
    tags: list[str] | None = None,
    operation_id: str | None = None,
    # ── routing information ─────────────────────────────────────
    route: str | None = None,
    method: str | None = None,
    parameters: list[dict[str, Any]] | None = None,
    # ── typed parameters (documentation sugar) ──────────────────
    path: type[BaseModel] | None = None,
    headers: type[BaseModel] | None = None,
    security: list[dict[str, list[str]]] | None = None,
    security_scheme: dict[str, dict[str, Any]] | None = None,
    # ── request / response schema ───────────────────────────────
    requests: type[BaseModel] | dict[str, Any] | None = None,
    request_body_required: bool = True,
    responses: type[BaseModel] | Mapping[int | Literal["default"], Any] | None = None,
    # ── querystring (OpenAPI 3.2 only) ───────────────────────
    querystring: type[BaseModel] | dict[str, Any] | None = None,
    querystring_media_type: str = "application/x-www-form-urlencoded",
) -> Callable[[F], F]:
    """
    Decorator that attaches OpenAPI metadata to an Azure Functions handler.

    Examples
    --------
    ### 1 · Minimal “Hello World”

    ```python
    @openapi(summary="Hello", description="Returns plain text.", method="get")
    @app.route(route="hello")
    def hello(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("Hello, world!", status_code=200)
    ```

    ### 2 · Pydantic-powered JSON API

    ```python
    from pydantic import BaseModel

    class TodoRequest(BaseModel):
        title: str
        done: bool = False

    class TodoResponse(BaseModel):
        id: int
        title: str
        done: bool

    @openapi(
        summary="Update a todo item",
        description="Update a todo and return the updated document.",
        tags=["Todo"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
        requests=TodoRequest,
        responses=TodoResponse,
        operation_id="updateTodo",
    )
    @app.route(route="todos/{id}", methods=["PUT"])
    def update_todo(req: func.HttpRequest) -> func.HttpResponse:
        # ... business logic ...
        body = TodoRequest.model_validate_json(req.get_body())
        todo = TodoResponse(id=1, **body.model_dump())
        return func.HttpResponse(
            todo.model_dump_json(),
            status_code=200,
            mimetype="application/json",
        )
    ```

    After starting the Function App you get:

    * **Swagger UI** → `http://localhost:7071/api/docs`
    * **Raw JSON spec** → `http://localhost:7071/api/openapi.json`

    Parameters
    ----------
    summary:
        Short description shown in Swagger UI.
    description:
        Longer Markdown-enabled description.
    tags:
        List of group tags.
    operation_id:
        Custom operationId (defaults to function name).
    route:
        Override for the HTTP route path (e.g. "/items/{id}").
    method:
        Explicit HTTP method for this operation. When omitted, the method is
        inferred from the ``@app.route`` binding: a single ``methods=`` value is
        used directly, and a binding that omits ``methods=`` expands to every
        HTTP method (matching the Azure runtime). A bare ``@openapi`` with no
        route binding and no ``method=`` emits a single ``get`` operation.
    parameters:
        List of raw OpenAPI param objects (query/path/header/cookie).
    path:
        Pydantic model whose fields document ``in: path`` parameters. Every
        field becomes ``required: true``. Nested-object fields are rejected.
        Documentation only — no runtime validation.
    headers:
        Pydantic model whose fields document ``in: header`` parameters.
        Requiredness follows the model's optional/required fields. Nested-object
        fields are rejected. Documentation only — no runtime validation.
    security:
        List of OpenAPI Security Requirement Objects.
        Example: [{"BearerAuth": []}]
    security_scheme:
        Security scheme definitions to include in components.securitySchemes.
        Example: {"BearerAuth": {"type": "http", "scheme": "bearer"}}
    requests:
        Request parameter that accepts either a Pydantic model class (used to
        derive the requestBody schema) or a raw requestBody schema dict.
    request_body_required:
        Whether the request body is required. Defaults to True.
    responses:
        Response parameter. Accepts either:

        * a Pydantic model class (its schema is injected into the first 2xx
          response), or
        * a dict keyed by status code whose values are OpenAPI Response Objects.
          Each value may additionally be a bare Pydantic model class as shorthand
          for a JSON body of that schema, and a model class may also appear in the
          `content.<media>.schema` position of a Response Object. This lets a
          single operation express a typed success body together with several
          documented status codes — e.g.
          ``responses={202: AcceptedModel, 422: {"description": "Validation error"}}``.
    querystring:
        OpenAPI 3.2 querystring parameter schema. Accepts either a Pydantic
        model class or a raw JSON Schema dict, emitted as an ``in: querystring``
        parameter. Only valid for ``openapi_version="3.2.0"``; raises under
        3.0/3.1.
    querystring_media_type:
        Media type used to encode the querystring content. Defaults to
        ``application/x-www-form-urlencoded``.

    Returns
    -------
    Callable
        The original function, with its name stored in `_openapi_registry`.
    """

    def decorator(func: F) -> F:
        target_name = getattr(func, "__qualname__", getattr(func, "__name__", "<unknown>"))
        try:
            original_func, metadata_func = _resolve_metadata_target(func)
            target_name = f"{metadata_func.__module__}.{metadata_func.__qualname__}"

            # Auto-detect route/method from FunctionBuilder bindings when
            # not explicitly provided by the caller.
            effective_route = route
            effective_method = method
            binding_route, binding_method, binding_multi, binding_methods_unspecified = (
                _extract_binding_hints(func)
            )
            if effective_route is None and binding_route is not None:
                effective_route = binding_route
            if effective_method is None:
                if binding_method is not None:
                    effective_method = binding_method
                elif binding_multi:
                    raise OpenAPISpecConfigError(
                        f"Cannot infer a single HTTP method for '{metadata_func.__name__}': "
                        "@app.route declares multiple methods. "
                        "Pass method=... explicitly to @openapi, "
                        "or create a separate @openapi-decorated function per method."
                    )

            # All-method expansion (see spec generator) is only justified when a
            # real httptrigger binding is present but omits ``methods=``; a bare
            # @openapi with no binding leaves the method unresolved and must emit
            # a single operation instead of fanning out to every HTTP verb (#347).
            expand_all_methods = effective_method is None and binding_methods_unspecified

            # Enhanced input validation and sanitization
            validated_route = _validate_and_sanitize_route(effective_route, metadata_func.__name__)
            validated_method = _validate_method(effective_method, metadata_func.__name__)
            sanitized_operation_id = _validate_and_sanitize_operation_id(
                operation_id, metadata_func.__name__
            )
            validated_parameters = _validate_parameters(parameters, metadata_func.__name__)
            validated_parameters = _merge_typed_parameters(
                validated_parameters, path, headers, metadata_func.__name__
            )
            validated_security = _validate_security(security, metadata_func.__name__)
            validated_security_scheme = _validate_security_scheme(
                security_scheme, metadata_func.__name__
            )
            validated_tags = _validate_tags(tags, metadata_func.__name__)

            resolved_request_model: type[BaseModel] | None = None
            resolved_request_body: dict[str, Any] | None = None
            resolved_response_model: type[BaseModel] | None = None
            resolved_response: dict[int | str, dict[str, Any]] | None = None

            if requests is not None:
                if isinstance(requests, dict):
                    resolved_request_body = requests
                elif isinstance(requests, type) and issubclass(requests, BaseModel):
                    resolved_request_model = requests
                else:
                    raise ValueError(
                        "'requests' must be either a Pydantic BaseModel subclass or a dictionary."
                    )

            if responses is not None:
                if isinstance(responses, Mapping):
                    resolved_response = _normalize_unified_responses(
                        responses, metadata_func.__name__
                    )
                elif _is_pydantic_model(responses):
                    resolved_response_model = responses
                else:
                    raise ValueError(
                        "'responses' must be either a Pydantic BaseModel subclass or a dictionary."
                    )

            # ── return-type inference (P1-A) ─────────────────────────────
            # Lowest-precedence gap-fill: only when the user supplied no
            # explicit ``responses=``. An inferred response is marked so that
            # scan-time validation/explicit metadata can supersede it (Oracle
            # precedence: explicit > validation > inference).
            response_inferred = False
            if responses is None:
                inferred_model, inferred_response = _infer_response_from_return(metadata_func)
                if inferred_model is not None:
                    resolved_response_model = inferred_model
                    response_inferred = True
                elif inferred_response is not None:
                    resolved_response = inferred_response
                    response_inferred = True

            # ── docstring inference (P1-A Phase 2) ───────────────────────
            # Lowest-precedence gap-fill, per field: only when the user gave
            # no explicit ``summary=`` / ``description=``. The handler docstring's
            # first line becomes the summary and the remainder the description.
            effective_summary = summary
            effective_description = description
            if not summary or not description:
                inferred_summary, inferred_description = _infer_doc_metadata(metadata_func)
                effective_summary = summary or inferred_summary
                effective_description = description or inferred_description

            resolved_querystring_model: type[BaseModel] | None = None
            resolved_querystring_schema: dict[str, Any] | None = None
            if querystring is not None:
                if isinstance(querystring, dict):
                    resolved_querystring_schema = querystring
                elif isinstance(querystring, type) and issubclass(querystring, BaseModel):
                    resolved_querystring_model = querystring
                else:
                    raise ValueError(
                        "'querystring' must be either a Pydantic BaseModel subclass "
                        "or a dictionary."
                    )

            # Validate request/response models
            _validate_models(
                resolved_request_model,
                resolved_response_model,
                metadata_func.__name__,
            )

            function_id = ensure_canonical_identity(metadata_func)

            with _registry_lock:
                registry_key = metadata_func.__name__
                existing = registry.get(registry_key)
                if existing and existing.get("_function_id") != function_id:
                    existing_id = existing.get("_function_id")
                    if isinstance(existing_id, str):
                        # Preserve displaced entry under its fully-qualified id
                        registry.setdefault(existing_id, existing)

                registry.set(
                    registry_key,
                    {
                        # ── basic metadata ────────────────────────────────────────
                        "summary": effective_summary,
                        "description": effective_description,
                        "tags": validated_tags,
                        "operation_id": sanitized_operation_id,
                        # ── routing info ─────────────────────────────────────────
                        "route": validated_route,
                        "method": validated_method,
                        # Evidence that the runtime answers every HTTP method
                        # (binding present, ``methods=`` omitted). Gates all-method
                        # expansion in the spec generator; a bare @openapi stays
                        # single-operation (#347).
                        "_expand_all_methods": expand_all_methods,
                        "parameters": validated_parameters,
                        "security": validated_security,
                        "security_scheme": validated_security_scheme,
                        # ── request / response schema ────────────────────────
                        "request_model": resolved_request_model,
                        "request_body": resolved_request_body,
                        "request_body_required": request_body_required,
                        "response_model": resolved_response_model,
                        "response": resolved_response or {},
                        # Marks ``response``/``response_model`` as return-type
                        # inferred (P1-A) so scan-time reconciliation lets
                        # validation/explicit metadata supersede it.
                        "_response_inferred": response_inferred,
                        # ── querystring (OpenAPI 3.2) ────────────────────────
                        "querystring_model": resolved_querystring_model,
                        "querystring_schema": resolved_querystring_schema,
                        "querystring_media_type": querystring_media_type,
                        "function_name": metadata_func.__name__,
                        "_function_id": function_id,
                    },
                )

            logger.debug(f"Registered OpenAPI metadata for function '{metadata_func.__name__}'")
            return cast(F, original_func)

        except OpenAPISpecConfigError as e:
            logger.error(f"Failed to register OpenAPI metadata for '{target_name}': {str(e)}")
            raise
        except (ValueError, RuntimeError, TypeError) as e:
            # ValueError/TypeError: validation failures (input contract).
            # SDK-internal access failures raise SDKIncompatibleError, which is a
            # subclass of OpenAPISpecConfigError and is handled by the branch above;
            # any RuntimeError reaching here is unexpected and re-raised unchanged
            # to avoid double-wrapping.
            logger.error(f"Failed to register OpenAPI metadata for '{target_name}': {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to register OpenAPI metadata for '{target_name}': {str(e)}")
            raise RuntimeError(
                f"Failed to register OpenAPI metadata for '{target_name}': {e}"
            ) from e

    return decorator


def get_openapi_registry() -> dict[str, dict[str, Any]]:
    """
    Retrieve OpenAPI metadata for all registered functions.

    Returns:
        A dictionary where each key is a function name and value is its OpenAPI metadata.
    """
    return registry.snapshot()


def clear_openapi_registry() -> None:
    """Remove all entries from the OpenAPI registry.

    Primarily useful for testing or when rebuilding the registry from scratch.
    """
    registry.clear()


def register_openapi_metadata(
    path: str,
    method: str,
    *,
    operation_id: str | None = None,
    summary: str = "",
    description: str = "",
    tags: list[str] | None = None,
    request_model: type[BaseModel] | None = None,
    request_body: dict[str, Any] | None = None,
    request_body_required: bool = True,
    response_model: type[BaseModel] | None = None,
    response: dict[int, dict[str, Any]] | None = None,
    querystring: type[BaseModel] | dict[str, Any] | None = None,
    querystring_media_type: str = "application/x-www-form-urlencoded",
    parameters: list[dict[str, Any]] | None = None,
    security: list[dict[str, list[str]]] | None = None,
    security_scheme: dict[str, dict[str, Any]] | None = None,
    registry: OpenAPIRegistry | None = None,
) -> None:
    """Register OpenAPI metadata for an endpoint programmatically.

    Use this instead of the ``@openapi()`` decorator when the HTTP handler
    is generated dynamically (e.g. by ``azure-functions-langgraph``).

    Parameters
    ----------
    path:
        URL path for the endpoint (e.g. ``/api/chat/invoke``).
    method:
        HTTP method (e.g. ``POST``).
    operation_id:
        Custom operationId. Auto-generated from method + path if omitted.
    summary:
        Short description shown in Swagger UI.
    description:
        Longer Markdown-enabled description.
    tags:
        List of group tags. Defaults to ``["default"]``.
    request_model:
        Pydantic model for the request body schema. Mutually exclusive
        with ``request_body``.
    request_body:
        Raw requestBody schema dict.
    request_body_required:
        Whether the request body is required. Defaults to True.
    response_model:
        Pydantic model for the 200-response schema.
    response:
        Manual responses dict keyed by status code.
    querystring:
        OpenAPI 3.2 querystring parameter schema. Accepts either a Pydantic
        model class or a raw JSON Schema dict. Emitted only for
        ``openapi_version="3.2.0"``; raises under 3.0/3.1.
    querystring_media_type:
        Media type used to encode the querystring content. Defaults to
        ``application/x-www-form-urlencoded``.
    parameters:
        List of OpenAPI parameter objects (query/path/header/cookie).
    security:
        List of OpenAPI Security Requirement Objects.
    security_scheme:
        Security scheme definitions for components.securitySchemes.
    registry:
        Target :class:`OpenAPIRegistry` to record the operation in. Defaults to
        the process-wide global registry (``None``); pass an isolated registry
        to scope the metadata to a single application (see #381).

    Notes
    -----
    A ``method`` + ``path`` pair is a single OpenAPI operation by definition, so
    calling this again for the same pair replaces the prior entry
    (last-writer-wins) rather than raising. This intentionally powers the
    scan-then-enrich pattern: :func:`scan_endpoint_metadata` seeds a minimal
    entry from bridge/validation metadata, and a subsequent call here overrides
    it with richer, human-authored metadata.

    Raises
    ------
    ValueError
        If ``path`` or ``method`` is empty/invalid.
    """
    if not path or not isinstance(path, str):
        raise ValueError("path must be a non-empty string")
    if not method or not isinstance(method, str):
        raise ValueError("method must be a non-empty string")

    # Reuse shared method validation (normalizes to lowercase).
    # method is guaranteed non-empty at this point by the check above.
    validated_method = _validate_method(method, f"register_openapi_metadata({path})")
    if validated_method is None:  # pragma: no cover — unreachable; guard above ensures non-empty
        raise ValueError("method must be a non-empty string")

    if request_model is not None and request_body is not None:
        raise ValueError(
            f"Cannot provide both 'request_model' and 'request_body' "
            f"for {validated_method.upper()} {path}."
        )

    _validate_and_sanitize_route(path, f"{validated_method.upper()} {path}")

    registry_key = f"{validated_method}::{path}"

    if operation_id:
        sanitized_op_id = _validate_and_sanitize_operation_id(operation_id, registry_key)
    else:
        clean_path = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
        fallback_op_id = f"{validated_method}_{clean_path}" if clean_path else validated_method
        sanitized_op_id = sanitize_operation_id(fallback_op_id)

    validated_parameters = _validate_parameters(parameters, registry_key) if parameters else []
    validated_security = _validate_security(security, registry_key) if security else []
    validated_security_scheme = (
        _validate_security_scheme(security_scheme, registry_key) if security_scheme else {}
    )
    validated_tags = _validate_tags(tags, registry_key) if tags else ["default"]

    if request_model is not None or response_model is not None:
        _validate_models(request_model, response_model, registry_key)

    resolved_querystring_model: type[BaseModel] | None = None
    resolved_querystring_schema: dict[str, Any] | None = None
    if querystring is not None:
        if isinstance(querystring, dict):
            resolved_querystring_schema = querystring
        elif isinstance(querystring, type) and issubclass(querystring, BaseModel):
            resolved_querystring_model = querystring
        else:
            raise ValueError(
                "'querystring' must be either a Pydantic BaseModel subclass or a dictionary."
            )

    reg = registry if registry is not None else _registry
    with reg.lock:
        # Same method+path is a single OpenAPI operation by definition, so
        # registering it again is an intentional last-writer-wins replace, not a
        # collision between two logical operations. This is what powers the
        # scan-then-enrich pattern: the bridge seeds a minimal entry via
        # ``scan_endpoint_metadata`` and the caller then overrides it here with
        # richer, human-authored metadata. Log the replace at debug level so it
        # stays traceable without being noisy.
        if reg.get(registry_key) is not None:
            logger.debug(
                "Replacing existing OpenAPI metadata for '%s %s' (last-writer-wins)",
                validated_method.upper(),
                path,
            )
        reg.set(
            registry_key,
            {
                "summary": summary,
                "description": description,
                "tags": validated_tags,
                "operation_id": sanitized_op_id,
                "route": path,
                "method": validated_method,
                "parameters": validated_parameters,
                "security": validated_security,
                "security_scheme": validated_security_scheme,
                "request_model": request_model,
                "request_body": request_body,
                "request_body_required": request_body_required,
                "response_model": response_model,
                "response": response or {},
                "querystring_model": resolved_querystring_model,
                "querystring_schema": resolved_querystring_schema,
                "querystring_media_type": querystring_media_type,
                "function_name": registry_key,
                "_function_id": f"programmatic.{registry_key}",
            },
        )

    logger.debug("Registered programmatic OpenAPI metadata for '%s %s'", validated_method, path)


# RFC 7230 §3.2.6 token: the grammar an HTTP method name must satisfy. Used to
# accept non-standard methods (e.g. ``PURGE``, ``QUERY``) for documentation-only
# emission (#471) while still rejecting garbage like whitespace or ``"GET POST"``.
_HTTP_TOKEN_RE = re.compile(r"^[-!#$%&'*+.^_`|~0-9A-Za-z]+$")


def _validate_method(method: str | None, func_name: str) -> str | None:
    """Validate and normalize HTTP method.

    Returns the lowercased method string, or ``None`` when *method* is not
    provided. A ``None`` result records that the method is unresolved at
    registration time; how it is later rendered depends on binding evidence
    (#347/#350). Only when a real ``httptrigger`` binding is present but omits
    ``methods=`` does the spec generator expand the operation to every HTTP
    method (matching the Azure runtime). A bare ``@openapi`` with no route
    binding and no ``method=`` stays a single ``get`` operation instead of
    fanning out to every verb.
    """
    if method is None:
        return None

    if not isinstance(method, str) or not method.strip():
        raise ValueError(f"method must be a non-empty string for function '{func_name}'")

    normalized = method.strip().upper()
    if not _HTTP_TOKEN_RE.match(normalized):
        raise ValueError(
            f"Invalid HTTP method: {method!r} for function '{func_name}'. "
            "Method names must be a valid HTTP token (RFC 7230): letters, digits, "
            "or the characters !#$%&'*+-.^_`|~ with no whitespace."
        )

    return normalized.lower()


def _validate_and_sanitize_route(route: str | None, func_name: str) -> str | None:
    """Validate and sanitize route path."""
    if not route:
        return None

    if not validate_route_path(route):
        logger.warning(
            "Invalid route path '%s' for function '%s'. Validation failed; no fallback applied.",
            route,
            func_name,
        )
        raise ValueError(f"Invalid route path: {route}")

    return route


def _validate_and_sanitize_operation_id(operation_id: str | None, func_name: str) -> str | None:
    """Validate and sanitize operation ID."""
    if not operation_id:
        return None

    sanitized = sanitize_operation_id(operation_id)
    if not sanitized:
        logger.warning(
            "Invalid operation ID '%s' for function '%s'. Validation failed; no fallback applied.",
            operation_id,
            func_name,
        )
        raise ValueError(f"Invalid operation ID: {operation_id}")

    return sanitized


def _inline_param_defs(node: Any, defs: dict[str, Any], seen: frozenset[str]) -> Any:
    """Recursively inline ``$ref`` targets from ``$defs`` into ``node``.

    Pydantic represents enums and nested models as ``$ref`` entries pointing at
    ``$defs``. Inlining lets the parameter-schema validator inspect the real
    shape (enum vs object) instead of an opaque reference. A ``seen`` guard
    prevents infinite recursion on self-referential models.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            if name in seen:
                return {}
            target = defs.get(name, {})
            return _inline_param_defs(target, defs, seen | {name})
        return {k: _inline_param_defs(v, defs, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_param_defs(item, defs, seen) for item in node]
    return node


def _schema_is_object(schema: dict[str, Any]) -> bool:
    """Return True when a schema describes an object (invalid for path/header).

    Covers the plain ``type: object`` case plus array-form ``type: ["object",
    ...]`` and the marker keys pydantic emits for dicts/models/tuples
    (``properties``, ``additionalProperties``, ``prefixItems``) even when an
    explicit ``type`` is absent.
    """
    schema_type = schema.get("type")
    if schema_type == "object":
        return True
    if isinstance(schema_type, list) and "object" in schema_type:
        return True
    return any(key in schema for key in ("properties", "additionalProperties", "prefixItems"))


def _assert_param_schema_scalar(
    schema: dict[str, Any], location: str, field: str, func_name: str
) -> None:
    """Reject object-shaped schemas for ``path``/``header`` parameters.

    OpenAPI ``path`` and ``header`` parameters must be primitives, enums, or
    arrays of primitives. Nested models (objects) are invalid, so an explicit,
    early error is raised instead of emitting a malformed spec.
    """
    if _schema_is_object(schema):
        raise OpenAPISpecConfigError(
            f"Field '{field}' of the '{location}' model for '{func_name}' maps to "
            f"an object schema, which is invalid for '{location}' parameters. "
            f"Use scalar, enum, or array-of-scalar fields only."
        )
    if schema.get("type") == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            _assert_param_schema_scalar(items, location, field, func_name)
    for combinator in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(combinator, []):
            if isinstance(sub, dict) and sub.get("type") != "null":
                _assert_param_schema_scalar(sub, location, field, func_name)


# Keys whose values are user data (examples/defaults), not nested schemas: do
# not recurse into them when stripping ``title`` so caller-supplied payloads that
# happen to contain a ``title`` field are preserved verbatim.
_SCHEMA_OPAQUE_KEYS = frozenset({"example", "examples", "default"})


def _strip_titles(node: Any) -> Any:
    """Recursively drop pydantic-injected ``title`` keys from a schema.

    Pydantic adds ``title`` to every field and to nested ``items`` / combinator
    branches. They are noise in a generated parameter schema, so remove them at
    every level rather than only at the top.
    """
    if isinstance(node, dict):
        return {
            k: (v if k in _SCHEMA_OPAQUE_KEYS else _strip_titles(v))
            for k, v in node.items()
            if k != "title"
        }
    if isinstance(node, list):
        return [_strip_titles(item) for item in node]
    return node


def _strip_null_branches(schema: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Remove JSON-Schema ``null`` branches from ``anyOf``/``oneOf``.

    ``Optional[T]`` renders as ``anyOf: [T, {type: null}]``. Absence is already
    modelled by ``required: false`` on the parameter, and a literal ``type:
    null`` branch is invalid under OpenAPI 3.0, so the null branch is dropped.
    When a single non-null branch remains it is flattened up into the schema.
    Returns the cleaned schema and whether a null branch was present.
    """
    result = dict(schema)
    was_nullable = False
    for combinator in ("anyOf", "oneOf"):
        branches = result.get(combinator)
        if not isinstance(branches, list):
            continue
        non_null = [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]
        if len(non_null) < len(branches):
            was_nullable = True
        if len(non_null) == 1:
            del result[combinator]
            sole = non_null[0]
            if isinstance(sole, dict):
                for key, value in sole.items():
                    result.setdefault(key, value)
        elif non_null:
            result[combinator] = non_null
        else:
            del result[combinator]
    # Nested schemas carry their own Optional encodings — e.g. ``list[Optional[T]]``
    # renders the null branch under ``items`` — which are equally invalid under
    # OpenAPI 3.0, so clean surviving children recursively. Their nullability does
    # not affect the parameter's own presence, so ``was_nullable`` stays top-level.
    if isinstance(result.get("items"), dict):
        result["items"], _ = _strip_null_branches(result["items"])
    for combinator in ("anyOf", "oneOf", "allOf"):
        subs = result.get(combinator)
        if isinstance(subs, list):
            result[combinator] = [
                _strip_null_branches(s)[0] if isinstance(s, dict) else s for s in subs
            ]
    # A leftover ``default: null`` only encoded the now-removed null branch.
    if "default" in result and result["default"] is None:
        del result["default"]
    return result, was_nullable


def _expand_model_parameters(
    model: type[BaseModel] | None, location: str, func_name: str
) -> list[dict[str, Any]]:
    """Expand a Pydantic model into OpenAPI ``parameters`` entries.

    Each model field becomes one parameter with ``in=location``. Field aliases
    (when present) are used as the wire name. ``path`` parameters are always
    ``required: true`` per the OpenAPI spec; ``header`` requiredness follows the
    model's own required/optional field semantics. Nested-object fields are
    rejected. This is documentation sugar only — it performs no runtime
    validation.
    """
    if model is None:
        return []
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise ValueError(f"'{location}' must be a Pydantic BaseModel subclass.")

    # ``model_json_schema()`` keys properties by wire name, so two fields sharing
    # an alias collapse into one property and one parameter would be silently
    # dropped. Inspect the declared fields first and fail fast on the collision.
    seen_wire: dict[str, str] = {}
    for field_name, field_info in model.model_fields.items():
        wire = field_info.alias or field_name
        if wire in seen_wire:
            raise OpenAPISpecConfigError(
                f"Fields '{seen_wire[wire]}' and '{field_name}' of the '{location}' "
                f"model for '{func_name}' both map to parameter name '{wire}'. "
                f"Use distinct field names or aliases."
            )
        seen_wire[wire] = field_name

    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    properties: dict[str, Any] = schema.get("properties", {})
    required_names = set(schema.get("required", []))

    params: list[dict[str, Any]] = []
    for name, raw_field_schema in properties.items():
        field_schema = _inline_param_defs(raw_field_schema, defs, frozenset())
        field_schema = _strip_titles(field_schema)
        field_schema, was_nullable = _strip_null_branches(field_schema)
        _assert_param_schema_scalar(field_schema, location, name, func_name)

        if location == "path" and was_nullable:
            raise OpenAPISpecConfigError(
                f"Path field '{name}' of the 'path' model for '{func_name}' is "
                f"Optional/nullable, but path parameters must always be present. "
                f"Make the field required (non-Optional)."
            )

        description = field_schema.pop("description", None)

        param: dict[str, Any] = {"name": name, "in": location}
        param["required"] = True if location == "path" else name in required_names
        if description is not None:
            param["description"] = description
        param["schema"] = field_schema
        params.append(param)
    return params


def _merge_typed_parameters(
    base: list[dict[str, Any]],
    path: type[BaseModel] | None,
    headers: type[BaseModel] | None,
    func_name: str,
) -> list[dict[str, Any]]:
    """Merge typed ``path``/``headers`` params into the raw ``parameters`` list.

    On a duplicate ``(name, in)`` pair — across raw and typed params, or between
    the two typed models — fail fast rather than silently overriding.
    """
    typed = _expand_model_parameters(path, "path", func_name) + _expand_model_parameters(
        headers, "header", func_name
    )
    if not typed:
        return base

    merged = list(base)
    seen = {(p.get("name"), p.get("in")) for p in merged if isinstance(p, dict) and "name" in p}
    for param in typed:
        key = (param["name"], param["in"])
        if key in seen:
            raise OpenAPISpecConfigError(
                f"Duplicate parameter '{param['name']}' (in: {param['in']}) for "
                f"'{func_name}': typed path=/headers= collides with an existing "
                f"parameter. Remove the duplicate from parameters= or the model."
            )
        seen.add(key)
        merged.append(param)
    return merged


def _validate_parameters(
    parameters: list[dict[str, Any]] | None, func_name: str
) -> list[dict[str, Any]]:
    """Validate parameters list."""
    if not parameters:
        return []

    if not isinstance(parameters, list):
        raise ValueError("Parameters must be a list")

    validated_params = []
    for i, param in enumerate(parameters):
        if not isinstance(param, dict):
            raise ValueError(f"Parameter at index {i} must be a dictionary")

        # Validate required fields. OpenAPI 3.2 'querystring' parameters are
        # special: 'name' is unused and the payload is carried in 'content'
        # rather than 'schema'.
        if param.get("in") == "querystring":
            if "content" not in param:
                raise ValueError(
                    f"querystring parameter at index {i} missing required field: content"
                )
        else:
            required_fields = ["name", "in"]
            for field in required_fields:
                if field not in param:
                    raise ValueError(f"Parameter at index {i} missing required field: {field}")

        validated_params.append(param)

    return validated_params


def _validate_security(
    security: list[dict[str, list[str]]] | None, func_name: str
) -> list[dict[str, list[str]]]:
    """Validate OpenAPI security requirements list."""
    if not security:
        return []

    if not isinstance(security, list):
        raise ValueError("Security must be a list")

    validated_security: list[dict[str, list[str]]] = []
    for i, requirement in enumerate(security):
        if not isinstance(requirement, dict):
            raise ValueError(f"Security requirement at index {i} must be a dictionary")

        validated_requirement: dict[str, list[str]] = {}
        for scheme_name, scopes in requirement.items():
            if not isinstance(scheme_name, str) or not scheme_name.strip():
                raise ValueError(f"Security scheme name at index {i} must be a non-empty string")

            if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
                raise ValueError(
                    f"Security scopes for '{scheme_name}' at index {i} must be a list of strings"
                )

            validated_requirement[scheme_name] = scopes

        validated_security.append(validated_requirement)

    return validated_security


def _validate_security_scheme(
    security_scheme: dict[str, dict[str, Any]] | None, func_name: str
) -> dict[str, dict[str, Any]]:
    """Validate OpenAPI security scheme definitions.

    Each key is a scheme name and each value must be a dict with at least a 'type' field.
    Valid types: 'apiKey', 'http', 'oauth2', 'openIdConnect'.

    Also validates required sub-fields per type as defined by the OpenAPI spec:
    - apiKey: requires 'name' and 'in' (query/header/cookie)
    - http: requires 'scheme'
    - oauth2: requires 'flows' (dict)
    - openIdConnect: requires 'openIdConnectUrl' (non-empty string)
    """
    if not security_scheme:
        return {}

    if not isinstance(security_scheme, dict):
        raise ValueError("security_scheme must be a dictionary")

    valid_types = {"apiKey", "http", "oauth2", "openIdConnect"}
    validated: dict[str, dict[str, Any]] = {}

    for scheme_name, scheme_def in security_scheme.items():
        if not isinstance(scheme_name, str) or not scheme_name.strip():
            raise ValueError("Security scheme name must be a non-empty string")

        if not isinstance(scheme_def, dict):
            raise ValueError(f"Security scheme '{scheme_name}' definition must be a dictionary")

        scheme_type = scheme_def.get("type")
        if not scheme_type or scheme_type not in valid_types:
            raise ValueError(
                f"Security scheme '{scheme_name}' must have a valid 'type' field. "
                f"Valid types: {', '.join(sorted(valid_types))}"
            )

        # Validate required sub-fields per scheme type
        if scheme_type == "apiKey":
            if not isinstance(scheme_def.get("name"), str) or not scheme_def["name"].strip():
                raise ValueError(
                    f"apiKey security scheme '{scheme_name}' must define a non-empty 'name'"
                )
            if scheme_def.get("in") not in {"query", "header", "cookie"}:
                raise ValueError(
                    f"apiKey security scheme '{scheme_name}' must define "
                    f"'in' as one of: query, header, cookie"
                )
        elif scheme_type == "http":
            if not isinstance(scheme_def.get("scheme"), str) or not scheme_def["scheme"].strip():
                raise ValueError(
                    f"http security scheme '{scheme_name}' must define a non-empty 'scheme'"
                )
        elif scheme_type == "oauth2":
            if not isinstance(scheme_def.get("flows"), dict):
                raise ValueError(
                    f"oauth2 security scheme '{scheme_name}' must define 'flows' as a dict"
                )
        elif scheme_type == "openIdConnect":
            url = scheme_def.get("openIdConnectUrl")
            if not isinstance(url, str) or not url.strip():
                raise ValueError(
                    f"openIdConnect security scheme '{scheme_name}' "
                    f"must define a non-empty 'openIdConnectUrl'"
                )

        validated[scheme_name] = scheme_def

    return validated


def _validate_tags(tags: list[str] | None, func_name: str) -> list[str]:
    """Validate tags list."""
    if not tags:
        return ["default"]

    if not isinstance(tags, list):
        raise ValueError("Tags must be a list")

    validated_tags = []
    for i, tag in enumerate(tags):
        if not isinstance(tag, str):
            raise ValueError(f"Tag at index {i} must be a string")

        # Sanitize tag
        sanitized_tag = tag.strip()
        if not sanitized_tag:
            raise ValueError(f"Tag at index {i} cannot be empty")

        validated_tags.append(sanitized_tag)

    return validated_tags


def _validate_models(
    request_model: type[BaseModel] | None,
    response_model: type[BaseModel] | None,
    func_name: str,
) -> None:
    """Validate Pydantic models.

    Raises:
        ValueError: If request_model or response_model is not a Pydantic BaseModel subclass.
            Provides helpful error messages when dict is passed instead of a model.
    """
    if request_model is not None:
        if isinstance(request_model, dict):
            raise ValueError(
                "request_model must be a Pydantic BaseModel class, not a dict. "
                "To use a dict schema, use 'request_body' parameter instead."
            )
        if not isinstance(request_model, type) or not issubclass(request_model, BaseModel):
            raise ValueError(
                "request_model must be a Pydantic BaseModel subclass, "
                f"got {type(request_model).__name__}"
            )

    if response_model is not None:
        if isinstance(response_model, dict):
            raise ValueError(
                "response_model must be a Pydantic BaseModel class, not a dict. "
                "To use a dict schema, use 'response' parameter instead."
            )
        if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
            raise ValueError(
                "response_model must be a Pydantic BaseModel subclass, "
                f"got {type(response_model).__name__}"
            )
