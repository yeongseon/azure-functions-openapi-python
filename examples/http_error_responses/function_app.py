"""HTTP error responses example — documenting 4xx/5xx bodies next to a success body.

Demonstrates:
- a typed ``200`` response plus ``404`` and ``500`` error responses in ``responses``
- documenting an RFC 9457 style error body as ``application/problem+json``
- reusing one Pydantic error model across several status codes (one shared component)
- keeping the documented error shape identical to what the handler actually returns
"""

from __future__ import annotations

import json

import azure.functions as func
from pydantic import BaseModel, Field

from azure_functions_openapi import get_openapi_json, get_openapi_yaml
from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.swagger_ui import render_swagger_ui

app = func.FunctionApp()

PROBLEM_JSON = "application/problem+json"


class Order(BaseModel):
    order_id: str = Field(..., description="Order identifier.")
    status: str = Field(..., description="Fulfilment status.")


class ProblemDetails(BaseModel):
    """Error body shared by every documented 4xx/5xx response."""

    type: str = Field(default="about:blank", description="URI reference identifying the problem.")
    title: str = Field(..., description="Short, human-readable summary.")
    status: int = Field(..., description="HTTP status code of this response.")
    detail: str = Field(..., description="Explanation specific to this occurrence.")


_ORDERS = {"ord_1": Order(order_id="ord_1", status="shipped")}


def _problem(status: int, title: str, detail: str) -> func.HttpResponse:
    body = ProblemDetails(title=title, status=status, detail=detail)
    return func.HttpResponse(body.model_dump_json(), mimetype=PROBLEM_JSON, status_code=status)


@openapi(
    route="/api/orders/{order_id}",
    method="get",
    summary="Get an order",
    description="Returns the order, or a problem document when it does not exist or lookup fails.",
    tags=["orders"],
    parameters=[{"name": "order_id", "in": "path", "required": True, "schema": {"type": "string"}}],
    responses={
        200: {
            "description": "The order",
            "content": {"application/json": {"schema": Order}},
        },
        404: {
            "description": "No order with this identifier",
            "content": {PROBLEM_JSON: {"schema": ProblemDetails}},
        },
        500: {
            "description": "Unexpected failure while reading the order",
            "content": {PROBLEM_JSON: {"schema": ProblemDetails}},
        },
    },
)
@app.route(route="orders/{order_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_order(req: func.HttpRequest) -> func.HttpResponse:
    order_id = req.route_params.get("order_id", "")
    if order_id == "boom":  # deterministic stand-in for an unexpected failure
        return _problem(500, "Internal Server Error", "Order storage is unavailable.")
    order = _ORDERS.get(order_id)
    if order is None:
        return _problem(404, "Order not found", f"No order with id {json.dumps(order_id)}.")
    return func.HttpResponse(order.model_dump_json(), mimetype="application/json", status_code=200)


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_spec")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="HTTP Error Responses API"), mimetype="application/json"
    )


@app.route(route="openapi.yaml", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_yaml_spec")
def openapi_yaml_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_yaml(title="HTTP Error Responses API"), mimetype="application/x-yaml"
    )


@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="swagger_ui")
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(title="HTTP Error Responses API")
