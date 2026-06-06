"""E2E test function app for azure-functions-openapi.

Exposes minimal routes that the e2e test suite can call
against a real Azure Functions Consumption host.
"""

from __future__ import annotations

import json
import logging

import azure.functions as func
from pydantic import BaseModel

from azure_functions_openapi import get_openapi_json, get_openapi_yaml
from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.swagger_ui import render_swagger_ui

app = func.FunctionApp()


class ItemResponse(BaseModel):
    id: int
    name: str


@app.route(route="health", auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness probe used by e2e warmup loop."""
    return func.HttpResponse(json.dumps({"status": "ok"}), mimetype="application/json")


@openapi(
    route="/api/items",
    summary="List items",
    tags=["items"],
    response={200: {"description": "OK", "content": {"application/json": {}}}},
)
@app.route(route="items", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_items(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("list_items called")
    items = [{"id": 1, "name": "widget"}, {"id": 2, "name": "gadget"}]
    return func.HttpResponse(json.dumps(items), mimetype="application/json")


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(get_openapi_json(), mimetype="application/json")


@app.route(route="openapi.yaml", auth_level=func.AuthLevel.ANONYMOUS)
def openapi_yaml_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(get_openapi_yaml(), mimetype="application/x-yaml")


@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="swagger_ui")
def swagger_ui_handler(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui()
