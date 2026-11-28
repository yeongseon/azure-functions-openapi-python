"""OpenAPI 3.2 querystring encoding example — one whole-query-string parameter.

Demonstrates:
- ``querystring=`` documenting the *entire* query string as one ``in: querystring``
  parameter (OpenAPI 3.2 only; ``application/x-www-form-urlencoded`` by default)
- what a client should send, and how the handler decodes it
- that the library documents the contract but never parses the query for you
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import azure.functions as func
from pydantic import BaseModel, Field, ValidationError

from azure_functions_openapi import OPENAPI_VERSION_3_2, get_openapi_json
from azure_functions_openapi.decorator import openapi

app = func.FunctionApp()


class SearchQuery(BaseModel):
    q: str = Field(..., description="Free-text search term.")
    limit: int = Field(default=10, description="Maximum number of results.")
    tags: list[str] = Field(default_factory=list, description="Repeat `tags` to filter.")


def parse_search_query(url: str) -> SearchQuery:
    """Decode a form-urlencoded query string the way a 3.2 client encodes it.

    ``parse_qs`` applies the media type's rules: ``+`` is a space and ``%2B`` is a
    literal plus. Repeated keys become lists; scalar fields take the last value.
    """
    raw = parse_qs(urlsplit(url).query, keep_blank_values=True)
    data: dict[str, object] = {}
    for key, values in raw.items():
        data[key] = values if key == "tags" else values[-1]
    return SearchQuery.model_validate(data)


@openapi(
    route="/api/search",
    method="get",
    summary="Search with a whole-query-string schema",
    tags=["search"],
    querystring=SearchQuery,
)
@app.route(route="search", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def search(req: func.HttpRequest) -> func.HttpResponse:
    try:
        query = parse_search_query(req.url)
    except ValidationError:
        return func.HttpResponse('{"error": "invalid query string"}', status_code=400)
    return func.HttpResponse(query.model_dump_json(), mimetype="application/json")


@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="openapi_spec")
def openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    # querystring parameters exist only in OpenAPI 3.2, so the document is 3.2.
    return func.HttpResponse(
        get_openapi_json(title="Querystring Encoding API", openapi_version=OPENAPI_VERSION_3_2),
        mimetype="application/json",
    )
