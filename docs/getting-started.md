# Getting Started

This quickstart takes you from zero to a working Azure Functions API with:

- a documented HTTP endpoint (`@openapi`)
- generated OpenAPI JSON and YAML routes
- Swagger UI route

## Prerequisites

Before you begin, make sure you have:

- Python 3.10+
- Azure Functions Core Tools v4
- An Azure Functions Python v2 app (`func.FunctionApp`)

!!! warning
    `azure-functions-openapi` targets the Azure Functions Python v2 decorator model. It does not support the legacy `function.json` model.

## Install dependencies

```bash
pip install azure-functions azure-functions-openapi
```

If you use Pydantic models in your function contracts:

```bash
pip install pydantic
```

## Create your first documented endpoint

Add a file like `function_app.py`:

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
    tags=["Hello"],
    operation_id="greetUser",
    route="/api/http_trigger",
    method="get",
    parameters=[
        {
            "name": "name",
            "in": "query",
            "required": True,
            "schema": {"type": "string"},
            "description": "Name to greet",
        }
    ],
    response_model=HelloResponse,
    response={
        200: {"description": "Successful greeting"},
        400: {"description": "Missing name"},
    },
    )
@app.route(route="http_trigger", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    name = req.params.get("name")
    if not name:
        return func.HttpResponse("Missing name", status_code=400)

    return func.HttpResponse(
        json.dumps({"message": f"Hello, {name}!"}),
        mimetype="application/json",
        status_code=200,
    )
```

## Add spec endpoints

Add JSON and YAML routes to publish the generated spec:

```python
@app.function_name(name="openapi_json")
@app.route(route="openapi.json", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def openapi_json(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(
            title="Hello API",
            version="1.0.0",
            description="OpenAPI spec for Hello API",
        ),
        mimetype="application/json",
    )


@app.function_name(name="openapi_yaml")
@app.route(route="openapi.yaml", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def openapi_yaml(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_yaml(
            title="Hello API",
            version="1.0.0",
            description="OpenAPI spec for Hello API",
        ),
        mimetype="application/x-yaml",
    )
```

!!! note
    `get_openapi_json()` and `get_openapi_yaml()` return strings. Wrap them in `func.HttpResponse` as shown above.

## Add Swagger UI endpoint

```python
@app.function_name(name="swagger_ui")
@app.route(route="docs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(
        title="Hello API Docs",
        openapi_url="/api/openapi.json",
    )
```

## Run locally

```bash
func start
```

When startup succeeds, test all routes.

## Test with `curl`

Call your endpoint:

```bash
curl "http://localhost:7071/api/http_trigger?name=Azure"
```

Expected response:

```json
{"message":"Hello, Azure!"}
```

Fetch JSON spec:

```bash
curl "http://localhost:7071/api/openapi.json"
```

Fetch YAML spec:

```bash
curl "http://localhost:7071/api/openapi.yaml"
```

The generated spec is served as a JSON document — the same format a client generator reads to produce SDKs:

![OpenAPI spec preview for the Hello API generated from the @openapi decorator](assets/hello_openapi_spec_preview.png)

## View Swagger UI

Open:

`http://localhost:7071/api/docs`

You should see:

- one operation (`http_trigger`)
- operation summary and description
- query parameter `name`
- response schema generated from `HelloResponse`

![Swagger UI showing the Hello API with the greetUser GET operation, query parameter, and response schema](assets/hello_openapi_swagger_ui_preview.png)

## Next steps

1. Add request validation and richer models ([Usage](usage.md))
2. Configure security schemes and OpenAPI versions ([Configuration](configuration.md))
3. Explore complete examples ([Webhook Receiver](examples/webhook_receiver.md), [Report Jobs](examples/report_jobs.md), [Notification Request](examples/notification_request.md), [Partner Import Bridge](examples/partner_import_bridge.md))

## Troubleshooting quick checks

If docs are blank:

- confirm endpoint functions are imported during app startup
- confirm target handlers are decorated with `@openapi`
- confirm `openapi_url` in `render_swagger_ui()` points to a valid route

For deeper issues, see [Troubleshooting](troubleshooting.md).
