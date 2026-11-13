# HTTP Error Responses Example

A minimal endpoint that documents a success response **and** typed error responses.
Existing examples document error status codes with a description only; this one
shows how to publish a body schema and media type for `404` and `500`, and how to
reuse one error model for several status codes.

Source: `examples/http_error_responses/function_app.py`

## What this example includes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/orders/{order_id}` | Return an order, or a problem document |
| `GET` | `/api/openapi.json` | OpenAPI JSON |
| `GET` | `/api/openapi.yaml` | OpenAPI YAML |
| `GET` | `/api/docs` | Swagger UI |

## The declaration

```python
@openapi(
    route="/api/orders/{order_id}",
    method="get",
    responses={
        200: {
            "description": "The order",
            "content": {"application/json": {"schema": Order}},
        },
        404: {
            "description": "No order with this identifier",
            "content": {"application/problem+json": {"schema": ProblemDetails}},
        },
        500: {
            "description": "Unexpected failure while reading the order",
            "content": {"application/problem+json": {"schema": ProblemDetails}},
        },
    },
)
```

`ProblemDetails` is a Pydantic model, so `404` and `500` both point at one
`#/components/schemas/ProblemDetails` component. The handler returns the same shape
with `Content-Type: application/problem+json`, so the documented media type matches
what clients receive. The library only documents responses; it does not turn
exceptions into error bodies.

## Run locally

The `examples/` directories contain source modules, not standalone Function App
projects. To try the spec generation without the Functions host (offline, no credentials):

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_http_error_responses_example.py --no-cov -q
```

To serve it with Core Tools, copy the module into a project with a `host.json` as
described in the [Inference Cookbook](inference_cookbook.md#run-locally), then:

```bash
curl -i http://localhost:7071/api/orders/ord_1     # 200 application/json
curl -i http://localhost:7071/api/orders/missing   # 404 application/problem+json
curl -i http://localhost:7071/api/orders/boom      # 500 application/problem+json
```

Expected `404` body (key order may differ):

```json
{"type":"about:blank","title":"Order not found","status":404,"detail":"No order with id \"missing\"."}
```

The smoke test checks the generated operation for status codes, media types and
`$ref` schemas under OpenAPI 3.0 and 3.1, validates the document, and calls the
handler to assert each runtime status and media type is one the spec documents.

See the [Usage Guide](../usage.md#style-b-raw-schema-dictionaries) for the `responses`
parameter forms.
