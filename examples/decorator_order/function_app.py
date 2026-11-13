"""Decorator order example — ``@openapi`` above or below ``@app.route``.

Demonstrates:
- the two supported orders, each on its own small ``FunctionApp``
- that ``generate_openapi_spec(app=app)`` produces the same operation for both
  (route, method, path parameter and response metadata come from the binding)
- the one order-dependent limit: with ``@openapi`` *below* ``@app.route``, a spec
  generated without ``app=`` cannot see the binding and falls back to the function name
"""

from __future__ import annotations

import azure.functions as func
from pydantic import BaseModel

from azure_functions_openapi import openapi


class Thing(BaseModel):
    id: str
    name: str


# Identical OpenAPI metadata for both orders; only the decorator order differs.
document_thing = openapi(
    summary="Get a thing",
    operation_id="getThing",
    tags=["things"],
    responses={200: Thing, 404: {"description": "Thing not found"}},
)


def _respond(req: func.HttpRequest) -> func.HttpResponse:
    thing = Thing(id=req.route_params.get("id", ""), name="widget")
    return func.HttpResponse(thing.model_dump_json(), mimetype="application/json")


# Order A: @openapi is the outermost decorator. It receives the builder that
# @app.route returned, so it can read the binding immediately.
outer_app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@document_thing
@outer_app.route(route="things/{id}", methods=["GET"])
def get_thing_outer(req: func.HttpRequest) -> func.HttpResponse:
    return _respond(req)


# Order B: @openapi sits below @app.route. It runs first, before the binding exists;
# discovery reconciles it once an app is available.
inner_app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@inner_app.route(route="things/{id}", methods=["GET"])
@document_thing
def get_thing_inner(req: func.HttpRequest) -> func.HttpResponse:
    return _respond(req)
