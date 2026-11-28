# Querystring Encoding Example (OpenAPI 3.2)

Documents one whole-query-string parameter with `querystring=`, shows what a client
should send, and pins the generated fields. It is offline and needs no Azure resources.

Source: `examples/querystring_encoding/function_app.py`

## Declaration

```python
class SearchQuery(BaseModel):
    q: str
    limit: int = 10
    tags: list[str] = []


@openapi(route="/api/search", method="get", querystring=SearchQuery)
```

## Expected OpenAPI 3.2 fields

`generate_openapi_spec(openapi_version="3.2.0")` emits a single `in: querystring`
parameter whose `content` has exactly one media type (the default
`application/x-www-form-urlencoded`):

```json
{
  "name": "querystring",
  "in": "querystring",
  "content": {
    "application/x-www-form-urlencoded": {
      "schema": {"$ref": "#/components/schemas/SearchQuery"}
    }
  }
}
```

OpenAPI 3.2 requires `content` (not `schema`/`style`) for `querystring`, allows only one
such parameter, and forbids mixing it with `in: query` parameters in the same operation.
The library enforces those rules at generation time.

## What the client should send

Per the media type, the **whole** query string is a form-urlencoded value: a space is
`+`, a literal plus is `%2B`, and array values repeat the key (the default `explode`
for form encoding). For `q="a + b"`, `limit=5`, `tags=["x", "y"]`:

```text
GET /api/search?q=a+%2B+b&limit=5&tags=x&tags=y
```

The library documents this contract but does **not** parse requests: the example
handler decodes the query itself with `urllib.parse.parse_qs` and validates it with
`SearchQuery`. A missing `q` or a non-integer `limit` returns `400` from the handler.

## OpenAPI version boundary

`querystring` exists only in OpenAPI 3.2. Generating 3.0 or 3.1 with it raises
`OpenAPISpecConfigError`; nothing is silently downgraded to `in: query`
parameters. Use `parameters=[{"in": "query", ...}]` for 3.0/3.1 documents.

## Custom `encoding`

For full control, pass a raw `{"in": "querystring", "content": {...}}` parameter. An
`encoding` object inside the media type is copied through unchanged; its meaning is
defined by the OpenAPI 3.2 section "Encoding the x-www-form-urlencoded Media Type", not
by this library.

## Run locally

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_querystring_encoding_example.py --no-cov -q
```

The test asserts the exact parameter object above, rejection under 3.0/3.1, that the
decoded example query validates against the generated schema and the handler, and the
`encoding` passthrough. See also [Querystring parameters](../configuration.md#querystring-parameters-32-only).
