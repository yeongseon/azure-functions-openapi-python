from __future__ import annotations

import json

import azure.functions as func

from azure_functions_openapi import get_openapi_json, register_openapi_routes
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
    return func.HttpResponse(get_openapi_json(app=app), mimetype="application/json")


@app.route(route="docs")
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui()


# Registered through the public helper so the real-host smoke job fails to index
# the whole app (no job functions found) if a helper handler ever stops declaring a
# parameter for its HTTP trigger binding (#814).
registered_docs = register_openapi_routes(
    app,
    title="Registered host smoke",
    version="1",
    json_route="registered/openapi.json",
    yaml_route="registered/openapi.yaml",
    docs_route="registered/docs",
    name_prefix="registered",
)


protected_docs = register_openapi_routes(
    app,
    title="Protected host smoke",
    version="1",
    json_route="protected/openapi.json",
    yaml_route="protected/openapi.yaml",
    docs_route="protected/docs",
    name_prefix="protected",
    auth_level=func.AuthLevel.FUNCTION,
    docs_key_forwarding="header",
)
