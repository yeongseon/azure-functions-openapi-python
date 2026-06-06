# Azure Functions OpenAPI

`azure-functions-openapi` adds OpenAPI documentation and Swagger UI to Azure Functions Python v2 apps without maintaining a separate spec file.

!!! tip "5-second rule"
    If your team can read one function and immediately see the API contract, you are using this library correctly.

## Why teams use it

- Keep API docs close to function code with `@openapi`
- Generate OpenAPI 3.0.0 or 3.1.0 from runtime metadata
- Serve JSON, YAML, and Swagger UI from the same Function App
- Reuse Pydantic models for both request/response contracts and docs
- Merge operation-level and global security schemes into one spec

## 5-second working example

```python
import json

import azure.functions as func
from pydantic import BaseModel

from azure_functions_openapi import get_openapi_json, get_openapi_yaml, openapi, render_swagger_ui

app = func.FunctionApp()


class HelloResponse(BaseModel):
    message: str


@app.function_name(name="http_trigger")
@openapi(
    summary="Greet user",
    description="Returns a greeting using the `name` query parameter.",
    route="/api/http_trigger",
    method="get",
    tags=["Example"],
    parameters=[
        {
            "name": "name",
            "in": "query",
            "required": True,
            "schema": {"type": "string"},
        }
    ],
    response_model=HelloResponse,
    )
@app.route(route="http_trigger", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    name = req.params.get("name", "world")
    return func.HttpResponse(
        json.dumps({"message": f"Hello, {name}!"}),
        mimetype="application/json",
        status_code=200,
    )


@app.function_name(name="openapi_json")
@app.route(route="openapi.json", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def openapi_json(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="Hello API", version="1.0.0"),
        mimetype="application/json",
    )


@app.function_name(name="openapi_yaml")
@app.route(route="openapi.yaml", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def openapi_yaml(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_yaml(title="Hello API", version="1.0.0"),
        mimetype="application/x-yaml",
    )


@app.function_name(name="swagger_ui")
@app.route(route="docs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(title="Hello API Docs", openapi_url="/api/openapi.json")
```

Run locally:

```bash
func start
```

Open:

- `http://localhost:7071/api/docs`
- `http://localhost:7071/api/openapi.json`
- `http://localhost:7071/api/openapi.yaml`

## Core capabilities

### Decorator-first documentation

`@openapi` attaches metadata per operation:

- `summary`, `description`, `tags`, `operation_id`
- `parameters` (query/path/header/cookie)
- `request_model` or `request_body`
- `response_model` or `response`
- `security` and `security_scheme`

### OpenAPI generation

Generate programmatically with:

- `generate_openapi_spec(...)` for in-memory dictionary output
- `get_openapi_json(...)` for JSON string output
- `get_openapi_yaml(...)` for YAML string output

!!! note
    `get_openapi_json()` and `get_openapi_yaml()` return strings. Wrap them in `func.HttpResponse` in your endpoints.

### Swagger UI rendering

`render_swagger_ui(...)` returns an `HttpResponse` with:

- Swagger UI HTML content
- secure defaults for CSP and browser security headers
- optional custom CSP and client-side request logging

## Compatibility

| Component | Supported |
| --- | --- |
| Python | 3.10 to 3.14 |
| Azure Functions model | Python v2 (`func.FunctionApp`) |
| OpenAPI versions | 3.0.0 and 3.1.0 |
| Pydantic | v2 (≥2.0) |

!!! warning
    This package is for the Azure Functions Python v2 decorator model. It does not support the legacy `function.json`-based model.

## Continue reading

- [Installation](installation.md)
- [Getting Started](getting-started.md)
- [Configuration](configuration.md)
- [Usage](usage.md)
- [CLI](cli.md)
- [Examples](examples/webhook_receiver.md)
- [API Reference](api.md)
- [Troubleshooting](troubleshooting.md)
- [FAQ](faq.md)
