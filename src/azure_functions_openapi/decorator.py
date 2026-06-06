# src/azure_functions_openapi/decorator.py
from __future__ import annotations

import copy
import logging
import threading
from typing import Any, Callable, TypeVar, cast

from azure.functions.decorators.function_app import FunctionBuilder
from pydantic import BaseModel

from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.utils import sanitize_operation_id, validate_route_path

# Define a generic type variable for functions
F = TypeVar("F", bound=Callable[..., Any])

# Global registry to hold OpenAPI metadata for each function
_openapi_registry: dict[str, dict[str, Any]] = {}
_registry_lock = threading.RLock()

logger = logging.getLogger(__name__)


def _resolve_metadata_target(func: Any) -> tuple[Any, Callable[..., Any]]:
    """Return the original decorated object and the underlying callable used for metadata."""
    if isinstance(func, FunctionBuilder):
        # ``FunctionBuilder._function._func`` is a private attribute of the
        # ``azure-functions`` SDK. Guard against future renames/restructures so
        # callers get an actionable error instead of an opaque AttributeError.
        try:
            return func, func._function._func
        except AttributeError as exc:  # pragma: no cover - depends on SDK internals
            raise RuntimeError(
                "Unable to access FunctionBuilder._function._func; the installed "
                "azure-functions SDK appears incompatible with @openapi. "
                "Please report this issue at "
                "https://github.com/yeongseon/azure-functions-openapi-python/issues "
                f"with your azure-functions version. (underlying error: {exc})"
            ) from exc

    if not callable(func):
        raise TypeError(f"Unsupported decorated object: {type(func).__name__}")

    return func, cast(Callable[..., Any], func)


def _extract_binding_hints(func: Any) -> tuple[str | None, str | None, bool]:
    """Extract route and method from a FunctionBuilder's HTTP trigger binding.

    Returns ``(route, method, multiple_methods)`` where:
    - ``route`` and ``method`` may each be ``None`` if not available.
    - ``multiple_methods`` is ``True`` when the binding declares more than one
      HTTP method; in that case ``method`` is ``None`` and the caller must
      require an explicit ``method=`` argument from the user.
    """
    if not isinstance(func, FunctionBuilder):
        return None, None, False

    try:
        function_obj = func._function
        bindings = getattr(function_obj, "_bindings", [])
    except AttributeError:
        return None, None, False

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
                return binding_route, None, True  # ambiguous — caller must require explicit method
            if methods_attr:
                val = methods_attr[0]
                binding_method = str(getattr(val, "value", val)).lower()

        return binding_route, binding_method, False

    return None, None, False


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
    security: list[dict[str, list[str]]] | None = None,
    security_scheme: dict[str, dict[str, Any]] | None = None,
    # ── request / response schema ───────────────────────────────
    request_model: type[BaseModel] | None = None,
    request_body: dict[str, Any] | None = None,
    requests: type[BaseModel] | dict[str, Any] | None = None,
    request_body_required: bool = True,
    response_model: type[BaseModel] | None = None,
    response: dict[int, dict[str, Any]] | None = None,
    responses: type[BaseModel] | dict[int, dict[str, Any]] | None = None,
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
        request_model=TodoRequest,
        response_model=TodoResponse,
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
        Explicit HTTP method if not inferrable.
    parameters:
        List of param objects (query/path/header/cookie).
    security:
        List of OpenAPI Security Requirement Objects.
        Example: [{"BearerAuth": []}]
    security_scheme:
        Security scheme definitions to include in components.securitySchemes.
        Example: {"BearerAuth": {"type": "http", "scheme": "bearer"}}
    request_model:
        Pydantic model used to derive requestBody schema.
    request_body:
        Raw requestBody schema (if you don't use Pydantic).
    requests:
        Unified request parameter that accepts either a Pydantic model class
        (equivalent to `request_model`) or a raw requestBody schema dict
        (equivalent to `request_body`).
    request_body_required:
        Whether the request body is required. Defaults to True.
    response_model:
        Pydantic model used to derive 200-response schema.
    response:
        Manual responses dict keyed by status code.
    responses:
        Unified response parameter that accepts either a Pydantic model class
        (equivalent to `response_model`) or a manual responses dict keyed by
        status code (equivalent to `response`).

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
            binding_route, binding_method, binding_multi = _extract_binding_hints(func)
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

            # Enhanced input validation and sanitization
            validated_route = _validate_and_sanitize_route(effective_route, metadata_func.__name__)
            validated_method = _validate_method(effective_method, metadata_func.__name__)
            sanitized_operation_id = _validate_and_sanitize_operation_id(
                operation_id, metadata_func.__name__
            )
            validated_parameters = _validate_parameters(parameters, metadata_func.__name__)
            validated_security = _validate_security(security, metadata_func.__name__)
            validated_security_scheme = _validate_security_scheme(
                security_scheme, metadata_func.__name__
            )
            validated_tags = _validate_tags(tags, metadata_func.__name__)

            resolved_request_model = request_model
            resolved_request_body = request_body
            resolved_response_model = response_model
            resolved_response = response

            if requests is not None:
                if request_model is not None or request_body is not None:
                    raise ValueError(
                        "Cannot provide both 'requests' and 'request_model'/'request_body'."
                    )
                if isinstance(requests, dict):
                    resolved_request_body = requests
                elif isinstance(requests, type) and issubclass(requests, BaseModel):
                    resolved_request_model = requests
                else:
                    raise ValueError(
                        "'requests' must be either a Pydantic BaseModel subclass or a dictionary."
                    )

            if responses is not None:
                if response_model is not None or response is not None:
                    raise ValueError(
                        "Cannot provide both 'responses' and 'response_model'/'response'."
                    )
                if isinstance(responses, dict):
                    resolved_response = responses
                elif isinstance(responses, type) and issubclass(responses, BaseModel):
                    resolved_response_model = responses
                else:
                    raise ValueError(
                        "'responses' must be either a Pydantic BaseModel subclass or a dictionary."
                    )

            # Validate request/response models
            _validate_models(
                resolved_request_model,
                resolved_response_model,
                metadata_func.__name__,
            )

            function_id = f"{metadata_func.__module__}.{metadata_func.__qualname__}"

            with _registry_lock:
                registry_key = metadata_func.__name__
                existing = _openapi_registry.get(registry_key)
                if existing and existing.get("_function_id") != function_id:
                    existing_id = existing.get("_function_id")
                    if isinstance(existing_id, str):
                        # Preserve displaced entry under its fully-qualified id
                        _openapi_registry.setdefault(existing_id, existing)

                _openapi_registry[registry_key] = {
                    # ── basic metadata ────────────────────────────────────────
                    "summary": summary,
                    "description": description,
                    "tags": validated_tags,
                    "operation_id": sanitized_operation_id,
                    # ── routing info ─────────────────────────────────────────
                    "route": validated_route,
                    "method": validated_method,
                    "parameters": validated_parameters,
                    "security": validated_security,
                    "security_scheme": validated_security_scheme,
                    # ── request / response schema ────────────────────────
                    "request_model": resolved_request_model,
                    "request_body": resolved_request_body,
                    "request_body_required": request_body_required,
                    "response_model": resolved_response_model,
                    "response": resolved_response or {},
                    "function_name": metadata_func.__name__,
                    "_function_id": function_id,
                }

            logger.debug(f"Registered OpenAPI metadata for function '{metadata_func.__name__}'")
            return cast(F, original_func)

        except OpenAPISpecConfigError as e:
            logger.error(f"Failed to register OpenAPI metadata for '{target_name}': {str(e)}")
            raise
        except (ValueError, RuntimeError, TypeError) as e:
            # ValueError/TypeError: validation failures (input contract).
            # RuntimeError: SDK-internal access failures from _resolve_metadata_target;
            # already carries an actionable message — re-raise unchanged to avoid
            # double-wrapping.
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
    with _registry_lock:
        return copy.deepcopy(_openapi_registry)


def clear_openapi_registry() -> None:
    """Remove all entries from the OpenAPI registry.

    Primarily useful for testing or when rebuilding the registry from scratch.
    """
    with _registry_lock:
        _openapi_registry.clear()


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
    parameters: list[dict[str, Any]] | None = None,
    security: list[dict[str, list[str]]] | None = None,
    security_scheme: dict[str, dict[str, Any]] | None = None,
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
    parameters:
        List of OpenAPI parameter objects (query/path/header/cookie).
    security:
        List of OpenAPI Security Requirement Objects.
    security_scheme:
        Security scheme definitions for components.securitySchemes.

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
        fallback_op_id = (
            f"{validated_method}_{clean_path}" if clean_path else validated_method
        )
        sanitized_op_id = sanitize_operation_id(fallback_op_id)

    validated_parameters = _validate_parameters(parameters, registry_key) if parameters else []
    validated_security = _validate_security(security, registry_key) if security else []
    validated_security_scheme = (
        _validate_security_scheme(security_scheme, registry_key) if security_scheme else {}
    )
    validated_tags = _validate_tags(tags, registry_key) if tags else ["default"]

    if request_model is not None or response_model is not None:
        _validate_models(request_model, response_model, registry_key)

    with _registry_lock:
        _openapi_registry[registry_key] = {
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
            "function_name": registry_key,
            "_function_id": f"programmatic.{registry_key}",
        }

    logger.debug("Registered programmatic OpenAPI metadata for '%s %s'", validated_method, path)


_VALID_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def _validate_method(method: str | None, func_name: str) -> str | None:
    """Validate and normalize HTTP method.

    Returns the lowercased method string, or ``None`` when *method* is not
    provided (the spec generator will default to ``"get"``).
    """
    if method is None:
        return None

    if not isinstance(method, str) or not method.strip():
        raise ValueError(f"method must be a non-empty string for function '{func_name}'")

    normalized = method.strip().upper()
    if normalized not in _VALID_HTTP_METHODS:
        raise ValueError(
            f"Invalid HTTP method: {method!r} for function '{func_name}'. "
            f"Must be one of {sorted(_VALID_HTTP_METHODS)}"
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

        # Validate required fields
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
            raise ValueError(
                f"Security scheme '{scheme_name}' definition must be a dictionary"
            )

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
