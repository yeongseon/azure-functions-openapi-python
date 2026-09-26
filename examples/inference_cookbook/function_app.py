"""Inference cookbook example — typed responses and opt-in docstring metadata.

Demonstrates:
- inferring a response schema from a Pydantic return annotation
- opting into summary and description inference from a handler docstring
- keeping the runtime response as an Azure Functions ``HttpResponse``
"""

from __future__ import annotations

import azure.functions as func
from pydantic import BaseModel

from azure_functions_openapi import get_openapi_json, get_openapi_yaml
from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.swagger_ui import render_swagger_ui

app = func.FunctionApp()


class GreetingResponse(BaseModel):
    """Response returned by the greeting endpoint."""

    message: str
    name: str


@openapi(
    route="/api/greetings/{name}",
    method="get",
    tags=["inference"],
    parameters=[
        {
            "name": "name",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
    ],
    infer_docstring=True,
)
def build_greeting_response(req: func.HttpRequest) -> GreetingResponse:
    """Greet a caller by name.

    The response schema comes from the return annotation, while this summary
    and description are published only because ``infer_docstring=True`` opts in.
    """
    name = req.route_params.get("name", "world")
    return GreetingResponse(message=f"Hello, {name}!", name=name)


@app.function_name(name="get_greeting")
@app.route(route="greetings/{name}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_greeting(req: func.HttpRequest) -> func.HttpResponse:
    """Serialize the typed greeting for the Azure Functions HTTP runtime."""
    response = build_greeting_response(req)
    return func.HttpResponse(
        response.model_dump_json(), mimetype="application/json", status_code=200
    )


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_spec")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="Inference Cookbook API"), mimetype="application/json"
    )


@app.route(route="openapi.yaml", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_yaml_spec")
def openapi_yaml_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_yaml(title="Inference Cookbook API"), mimetype="application/x-yaml"
    )


@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="swagger_ui")
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(title="Inference Cookbook API")
