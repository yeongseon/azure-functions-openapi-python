# Versioned Response Metadata Example

Documents a **versioned response media type** (`application/vnd.example.v2+json`)
and **response headers** (`Location`, `ETag`) through the `version: 2` endpoint
metadata payload, compiled by `scan_endpoint_metadata(app)`. It is offline and
needs no Azure resources.

Source: `examples/versioned_response_metadata/function_app.py`

## The metadata payload

The handler carries a plain dict under `_azure_functions_metadata["endpoint"]`.
Apply the attachment **below** `@app.route`, so the attribute is set on the real
handler before the route decorator wraps it:

```python
ENDPOINT_METADATA = {
    "version": 2,
    "responses": {
        "201": {
            "description": "Invoice created",
            "content": {"application/vnd.example.v2+json": {"schema": Invoice.model_json_schema()}},
            "headers": {
                "Location": {"description": "URL of the created invoice.", "schema": {"type": "string"}},
                "ETag": {"description": "Entity tag of the invoice.", "schema": {"type": "string"}},
            },
        },
        "400": {
            "description": "Invalid request",
            "content": {"application/problem+json": {"schema": {"type": "object"}}},
        },
    },
}
```

Every v2 response needs a `content` mapping (an empty mapping means no body). The
full payload rules are in the [Producer Guide](../extending/producer-guide.md#v2-response-representations).

## Expected generated fragment

`generate_openapi_spec(...)` produces this for `POST /api/invoices` (identical under
OpenAPI 3.0 and 3.1; the `Invoice` schema is abbreviated here):

```json
"responses": {
  "201": {
    "description": "Invoice created",
    "content": {
      "application/vnd.example.v2+json": {
        "schema": {"title": "Invoice", "type": "object", "required": ["invoice_id", "total_cents"], "properties": {"...": "..."}}
      }
    },
    "headers": {
      "Location": {"schema": {"type": "string"}, "description": "URL of the created invoice."},
      "ETag": {"schema": {"type": "string"}, "description": "Entity tag of the invoice."}
    }
  },
  "400": {
    "description": "Invalid request",
    "content": {"application/problem+json": {"schema": {"type": "object"}}}
  }
}
```

## Documented headers vs. runtime headers

The `headers` entries are **documentation only**. This library neither adds them to
real responses nor checks that your handler sends them. The example handler sets
`Location` and `ETag` itself:

```python
return func.HttpResponse(
    invoice.model_dump_json(),
    mimetype=INVOICE_MEDIA_TYPE,
    status_code=201,
    headers={"Location": "/api/invoices/inv_1", "ETag": '"v1"'},
)
```

If you remove those `headers=` from the handler, the generated spec does not change, and
clients would stop receiving headers the spec still promises. Likewise the
documented media type is not negotiated: the handler must set the matching
`Content-Type`. The test suite covers both sides.

## Run locally

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_versioned_response_metadata_example.py --no-cov -q
```

The test builds the spec for OpenAPI 3.0 and 3.1, validates it, compares the exact
`201`/`400` response fragments, and calls the handler directly to assert the runtime
status, media type and headers.
