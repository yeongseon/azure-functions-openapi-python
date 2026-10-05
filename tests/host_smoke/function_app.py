from __future__ import annotations

import json

import azure.functions as func

from azure_functions_openapi import get_openapi_json
from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.swagger_ui import render_swagger_ui

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.function_name(name="custom_name")
@openapi(summary="Host smoke", responses={200: {"description": "OK"}})
@app.route()
def python_handler_name(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"function_name": "custom_name"}),
        mimetype="application/json",
    )


@app.route(route="openapi.json")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(get_openapi_json(), mimetype="application/json")


@app.route(route="docs")
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui()
