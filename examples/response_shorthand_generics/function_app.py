"""Response shorthand generics example — what ``responses=`` accepts and rejects.

Demonstrates:
- ``list[Model]`` as a bare response-body shorthand (an array of the model schema)
- a deliberately rejected ``Callable`` generic, which fails at decoration time
- the supported alternative: an explicit OpenAPI Response Object mapping
"""

from __future__ import annotations

from collections.abc import Callable

import azure.functions as func
from pydantic import BaseModel

from azure_functions_openapi import get_openapi_json
from azure_functions_openapi.decorator import openapi

app = func.FunctionApp()


class Item(BaseModel):
    id: int
    name: str


@openapi(
    route="/api/items",
    method="get",
    summary="List items",
    tags=["items"],
    responses={200: list[Item]},  # supported shorthand: an array of Item
)
@app.route(route="items", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_items(req: func.HttpRequest) -> func.HttpResponse:
    items = [Item(id=1, name="widget"), Item(id=2, name="gadget")]
    return func.HttpResponse(
        "[" + ",".join(item.model_dump_json() for item in items) + "]",
        mimetype="application/json",
    )


def declare_rejected_shorthand() -> str:
    """Declare ``Callable`` as a response shorthand and return the rejection message.

    A callable has no JSON body schema, so the decorator raises ``ValueError``
    when it is applied (not later, during spec generation) and registers nothing.
    """
    try:

        @openapi(
            route="/api/callbacks",
            method="get",
            responses={200: Callable[[int], str]},  # rejected: not a container generic
        )
        def callbacks(req: func.HttpRequest) -> func.HttpResponse:
            return func.HttpResponse("unreachable")

    except ValueError as exc:
        return str(exc)
    raise RuntimeError("Callable shorthand was unexpectedly accepted")


# The supported alternative: describe the body with an explicit Response Object
# mapping and a JSON schema that clients can actually receive.
@openapi(
    route="/api/callbacks",
    method="get",
    summary="Describe a callback registration",
    tags=["items"],
    responses={
        200: {
            "description": "Registered callback",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"],
                    }
                }
            },
        }
    },
)
@app.route(route="callbacks", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_callback(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"url": "https://example.invalid/hook"}', mimetype="application/json")


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_spec")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(title="Response Shorthand Generics API"), mimetype="application/json"
    )
