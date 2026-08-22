# Configuration

This guide covers configuration points across:

- `@openapi` decorator parameters
- OpenAPI version selection (`3.0.0` vs `3.1.0`)
- spec generation options
- Swagger UI rendering options
- security scheme setup

## `@openapi` parameters

`@openapi(...)` is the primary configuration surface.

### Metadata fields

| Parameter | Type | Purpose |
| --- | --- | --- |
| `summary` | `str` | Short operation summary in Swagger UI |
| `description` | `str` | Long operation description (Markdown supported) |
| `tags` | `list[str] \| None` | Group operations in docs; defaults to `['default']` |
| `operation_id` | `str \| None` | Custom operation ID; sanitized to safe identifier |

### Routing and protocol fields

| Parameter | Type | Purpose |
| --- | --- | --- |
| `route` | `str \| None` | Override documented path (for example `/api/items/{id}`) |
| `method` | `str \| None` | Force HTTP method used in spec (`get`, `post`, etc.) |
| `parameters` | `list[dict] \| None` | OpenAPI Parameter Objects for path/query/header/cookie |

### Security fields

| Parameter | Type | Purpose |
| --- | --- | --- |
| `security` | `list[dict[str, list[str]]] \| None` | Operation-level security requirements |
| `security_scheme` | `dict[str, dict] \| None` | Security schemes merged into `components.securitySchemes` |

### Body and response fields

Prefer the **unified** `requests` / `responses` parameters. Each accepts either
a Pydantic model class or a raw schema dict.

| Parameter | Type | Purpose |
| --- | --- | --- |
| `requests` | `type[BaseModel] \| dict \| None` | Unified request body — model (like `request_model`) or raw schema dict (like `request_body`) |
| `request_body_required` | `bool` | Whether the request body is required; defaults to `True` |
| `responses` | `type[BaseModel] \| dict[int, dict] \| None` | Unified responses — model (typed `200` schema) or a status-code map (like `response`) |

#### Deprecated (issue #285)

These discrete parameters still work but emit a `DeprecationWarning`. Migrate to
`requests` / `responses`.

| Deprecated parameter | Type | Replacement |
| --- | --- | --- |
| `request_model` | `type[BaseModel] \| None` | `requests=Model` |
| `request_body` | `dict \| None` | `requests={...}` |
| `response_model` | `type[BaseModel] \| None` | `responses=Model` |
| `response` | `dict[int, dict] \| None` | `responses={...}` |

!!! warning
    A model passed to `requests` / `responses` must be a Pydantic `BaseModel`
    class; pass a `dict` for raw schemas. You cannot combine `requests` with
    `request_model`/`request_body`, nor `responses` with
    `response_model`/`response` — doing so raises `ValueError`.

!!! note "One response case cannot migrate yet (issue #410)"
    `responses=` accepts a model **or** a status-code map, but not both. An
    operation that needs a model-derived `200` schema *and* extra status codes
    must keep the discrete `response_model=` + `response=` pair for now (still
    emits a `DeprecationWarning`). Tracked in issue #410.

## Parameter examples

### Metadata and route

```python
@openapi(
    summary="Get product",
    description="Returns one product by id.",
    tags=["Products"],
    operation_id="getProduct",
    route="/api/products/{id}",
    method="get",
)
```

### Parameters

```python
@openapi(
    summary="Get product",
    method="get",
    parameters=[
        {
            "name": "id",
            "in": "path",
            "required": True,
            "schema": {"type": "integer"},
        },
        {
            "name": "locale",
            "in": "query",
            "required": False,
            "schema": {"type": "string", "default": "en-US"},
        },
    ],
)
```

### Request/response models

```python
class ProductCreate(BaseModel):
    name: str


class ProductResponse(BaseModel):
    id: int
    name: str


# Single typed response — fully migratable to the unified parameters:
@openapi(
    summary="Create product",
    method="post",
    requests=ProductCreate,
    responses=ProductResponse,
)


# Model-derived 200 plus extra status codes — keep the discrete response
# parameters until issue #410 lands (still emits a DeprecationWarning):
@openapi(
    summary="Create product",
    method="post",
    requests=ProductCreate,
    response_model=ProductResponse,
    response={201: {"description": "Created"}, 400: {"description": "Bad request"}},
)
```

## OpenAPI version selection

Supported versions:

- `OPENAPI_VERSION_3_0` (`"3.0.0"`)
- `OPENAPI_VERSION_3_1` (`"3.1.0"`)
- `OPENAPI_VERSION_3_2` (`"3.2.0"`)

```python
from azure_functions_openapi import OPENAPI_VERSION_3_1, get_openapi_json

json_spec = get_openapi_json(
    title="Catalog API",
    version="2026.03",
    openapi_version=OPENAPI_VERSION_3_1,
)
```

### What changes in 3.1 / 3.2 mode

- nullable schemas are converted from `nullable: true` to `type: [<type>, "null"]`
- `example` values are normalized to `examples`

3.2.0 is a backward-compatible superset of 3.1.0 and reuses the same JSON
Schema 2020-12 conversions. This library emits a valid 3.2.0 document and
supports 3.2-only constructs (querystring schemas, `additionalOperations`,
the `query` HTTP method, and streaming media types via `itemSchema`). Note
that some viewers — including the bundled Swagger UI — may not yet render
3.2.0 documents.

## Spec generation options

### `generate_openapi_spec(...)`

Use this when you need an in-memory dict:

```python
spec = generate_openapi_spec(
    title="Catalog API",
    version="2026.03",
    description="Catalog service",
    security_schemes={
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    },
)
```

### `get_openapi_json(...)` and `get_openapi_yaml(...)`

Use these for endpoint responses or file output:

```python
json_text = get_openapi_json(title="Catalog API", version="2026.03")
yaml_text = get_openapi_yaml(title="Catalog API", version="2026.03")
```

!!! note
    Both functions return strings. Create `func.HttpResponse` yourself when serving them from Azure Functions routes.

## Swagger UI customization

`render_swagger_ui(...)` parameters:

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `title` | `str` | `API Documentation` | Browser tab title |
| `openapi_url` | `str` | `/api/openapi.json` | URL to the OpenAPI endpoint |
| `custom_csp` | `str \| None` | `None` | Replace default Content Security Policy |
| `enable_client_logging` | `bool` | `False` | Log API responses in browser console |

Example:

```python
return render_swagger_ui(
    title="Catalog API Docs",
    openapi_url="/api/openapi.json",
    enable_client_logging=True,
)
```

Custom CSP example:

```python
custom_csp = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
return render_swagger_ui(custom_csp=custom_csp)
```

## Security scheme configuration

You can define schemes in two places.

### Per-operation in decorator

```python
@openapi(
    summary="Get profile",
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

### Global in spec generator

```python
global_schemes = {
    "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
}

json_spec = get_openapi_json(security_schemes=global_schemes)
```

The generated spec merges global and decorator-defined schemes into `components.securitySchemes`.

## Validation and safety rules

The library validates and sanitizes:

- route paths (`validate_route_path`)
- operation IDs (`sanitize_operation_id`)
- parameter shape (`name` and `in` required)
- security requirement object types

Invalid values raise `ValueError` during decorator registration.

## Cross-links

- [Usage](usage.md)
- [API Reference](api.md)
- [CLI](cli.md)
- [FAQ](faq.md)
- [Troubleshooting](troubleshooting.md)
