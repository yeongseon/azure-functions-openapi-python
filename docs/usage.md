# Usage Guide

This guide shows how to document Azure Functions Python v2 HTTP handlers with `azure-functions-openapi` using production-ready patterns.

## Before you start

- Install package: `pip install azure-functions-openapi`
- Use Azure Functions Python v2 programming model (`func.FunctionApp`)
- Ensure your app has explicit routes for OpenAPI JSON/YAML and Swagger UI

See [Installation](installation.md) and [Getting Started](getting-started.md) first.

For configurable URL prefixes (custom or empty `host.json` `routePrefix`),
see [Route Prefix](route-prefix.md).

## End-to-end baseline

```python
import json

import azure.functions as func
from pydantic import BaseModel

from azure_functions_openapi import get_openapi_json, get_openapi_yaml, openapi, render_swagger_ui

app = func.FunctionApp()


class EchoRequest(BaseModel):
    message: str


class EchoResponse(BaseModel):
    echoed: str


@app.function_name(name="echo")
@openapi(
    summary="Echo message",
    description="Returns the same message received in the request body.",
    tags=["Echo"],
    operation_id="echoMessage",
    route="/api/echo",
    method="post",
    request_model=EchoRequest,
    response_model=EchoResponse,
    response={200: {"description": "Echoed message"}, 400: {"description": "Invalid body"}},
    )
@app.route(route="echo", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def echo(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = EchoRequest.model_validate_json(req.get_body())
    except Exception:
        return func.HttpResponse("Invalid body", status_code=400)

    return func.HttpResponse(
        json.dumps({"echoed": data.message}),
        mimetype="application/json",
        status_code=200,
    )


@app.function_name(name="openapi_json")
@app.route(route="openapi.json", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def openapi_json(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="Echo API", version="1.0.0"),
        mimetype="application/json",
    )


@app.function_name(name="openapi_yaml")
@app.route(route="openapi.yaml", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def openapi_yaml(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_yaml(title="Echo API", version="1.0.0"),
        mimetype="application/x-yaml",
    )


@app.function_name(name="swagger_ui")
@app.route(route="docs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(title="Echo API Docs", openapi_url="/api/openapi.json")
```

## Understanding `@openapi`

`@openapi` captures metadata and stores it in a registry consumed by spec generators.

### Minimal metadata

```python
@openapi(summary="Health check")
```

### Typical metadata

```python
@openapi(
    summary="Get order",
    description="Fetch one order by ID.",
    tags=["Orders"],
    operation_id="getOrder",
    route="/api/orders/{order_id}",
    method="get",
)
```

!!! note
    If `tags` is omitted, the library defaults to `['default']`.

## Request and response schema styles

Use one of two schema styles depending on your app architecture.

### Style A: Pydantic models

Best when you already validate payloads with Pydantic.

```python
class CreateOrderRequest(BaseModel):
    sku: str
    quantity: int


class OrderResponse(BaseModel):
    id: int
    sku: str
    quantity: int


@openapi(
    summary="Create order",
    method="post",
    request_model=CreateOrderRequest,
    response_model=OrderResponse,
    response={201: {"description": "Created"}},
)
```

### Style B: Raw schema dictionaries

Best when you do not use Pydantic.

```python
@openapi(
    summary="Create order",
    method="post",
    request_body={
        "type": "object",
        "properties": {
            "sku": {"type": "string"},
            "quantity": {"type": "integer", "minimum": 1},
        },
        "required": ["sku", "quantity"],
    },
    response={
        201: {
            "description": "Created",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                    }
                }
            },
        }
    },
)
```

!!! warning
    Do not pass dict schemas to `request_model` or `response_model`. Those parameters require Pydantic `BaseModel` classes.

## Parameters (query/path/header/cookie)

Use OpenAPI Parameter Objects in `parameters`.

```python
@openapi(
    summary="Get order",
    method="get",
    route="/api/orders/{order_id}",
    parameters=[
        {
            "name": "order_id",
            "in": "path",
            "required": True,
            "schema": {"type": "integer"},
            "description": "Order identifier",
        },
        {
            "name": "include_items",
            "in": "query",
            "required": False,
            "schema": {"type": "boolean", "default": False},
        },
        {
            "name": "X-Correlation-ID",
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
        },
    ],
)
```

## Security documentation

You can define security at operation-level and component-level.

### API key example

```python
@openapi(
    summary="List invoices",
    method="get",
    security=[{"ApiKeyAuth": []}],
    security_scheme={
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
    },
)
```

### Bearer token example

```python
@openapi(
    summary="List invoices",
    method="get",
    security=[{"BearerAuth": []}],
    security_scheme={
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    },
)
```

## Multiple endpoints and tags

You can annotate each endpoint independently and group by tags.

```python
@openapi(summary="Create customer", tags=["Customers"], method="post")
def create_customer(req: func.HttpRequest) -> func.HttpResponse:
    ...


@openapi(summary="List customers", tags=["Customers"], method="get")
def list_customers(req: func.HttpRequest) -> func.HttpResponse:
    ...


@openapi(summary="Health", tags=["Operations"], method="get")
def health(req: func.HttpRequest) -> func.HttpResponse:
    ...
```

## Spec generation options

Use these APIs when you need programmatic control.

### Generate dictionary spec

```python
from azure_functions_openapi import OPENAPI_VERSION_3_1, generate_openapi_spec

spec = generate_openapi_spec(
    title="Orders API",
    version="2026.03",
    description="Order management service",
    openapi_version=OPENAPI_VERSION_3_1,
    security_schemes={
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    },
)
```

### Generate JSON/YAML strings

```python
json_spec = get_openapi_json(title="Orders API", version="2026.03")
yaml_spec = get_openapi_yaml(title="Orders API", version="2026.03")
```

## Swagger UI route

```python
@app.route(route="docs", methods=["GET"])
def docs(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(
        title="Orders API Docs",
        openapi_url="/api/openapi.json",
        enable_client_logging=False,
    )
```

If your deployment needs stricter or custom CSP:

```python
custom_csp = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
return render_swagger_ui(custom_csp=custom_csp)
```

## Common pitfalls

- Missing docs endpoints (`openapi.json`, `openapi.yaml`, `docs`)
- Passing non-list to `parameters` or `security`
- Invalid route path with whitespace or dangerous patterns
- Using unsupported OpenAPI version string

See [Troubleshooting](troubleshooting.md) for fixes.

## Validation package integration

`azure-functions-openapi` works well with `azure-functions-validation` when you want runtime payload validation plus generated API docs from the same models.

See [Notification Request Example](examples/notification_request.md) for a complete setup.

### Automatic bridge (zero-duplication)

If you want OpenAPI specs generated automatically from `@validate_http` decorators
without repeating models in `@openapi`, use `scan_validation_metadata()`:

```python
from azure_functions_openapi import scan_validation_metadata

# After all routes are registered:
scan_validation_metadata(app)
```

This scans the app's registered HTTP functions for `@validate_http` metadata
and auto-registers them in the OpenAPI registry. Explicit `@openapi` decorators
always take precedence.

!!! info "No extra dependencies required"
    `scan_validation_metadata()` reads the convention-based metadata attribute
    written by `@validate_http` — no extra install step needed beyond having both
    packages in your project.

See [Partner Import Bridge Example](examples/partner_import_bridge.md) for a complete walkthrough.


## Import path migration

The internal module previously named `azure_functions_openapi.openapi` was
renamed to `azure_functions_openapi.spec` to remove a naming conflict with the
public `@openapi` decorator. The old module path remains as a deprecation shim
that emits `DeprecationWarning` and will be removed in a future release.

Update any imports as follows:

**Deprecated** (still works, emits `DeprecationWarning`):

```python
from azure_functions_openapi.openapi import get_openapi_json, get_openapi_yaml
```

**Canonical internal path**:

```python
from azure_functions_openapi.spec import get_openapi_json, get_openapi_yaml
```

**Recommended public API** (preferred for application code):

```python
from azure_functions_openapi import get_openapi_json, get_openapi_yaml
```

The root package re-exports `get_openapi_json`, `get_openapi_yaml`,
`generate_openapi_spec`, `OPENAPI_VERSION_3_0`, `OPENAPI_VERSION_3_1`,
`openapi`, and `render_swagger_ui`, so most user code can import everything
directly from `azure_functions_openapi` without referencing internal
submodules.

## Next steps

- Deep-dive decorator options: [Configuration](configuration.md)
- Auto-generated signatures and docstrings: [API Reference](api.md)
- Generate specs in CI/CD: [CLI](cli.md)
