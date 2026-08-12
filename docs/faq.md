# FAQ

## OpenAPI 3.0 vs 3.1: which one should I use?

Use 3.0.0 if downstream tooling in your stack still expects OpenAPI 3.0.

Use 3.1.0 if your tooling supports it and you want newer JSON Schema alignment.

```python
from azure_functions_openapi import OPENAPI_VERSION_3_1, get_openapi_json

spec = get_openapi_json(openapi_version=OPENAPI_VERSION_3_1)
```

## How do I add authentication to my docs?

Use `security` + `security_scheme` in `@openapi`, or pass `security_schemes` to spec generation.

```python
@openapi(
    summary="Protected route",
    security=[{"BearerAuth": []}],
    security_scheme={
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    },
)
```

## Can I use this package without Pydantic?

Yes. Use raw schema dictionaries with the unified `requests` and `responses` parameters.

```python
@openapi(
    requests={"type": "object", "properties": {"name": {"type": "string"}}},
    responses={200: {"description": "OK"}},
)
```

## How do I customize Swagger UI?

Use `render_swagger_ui(title=..., openapi_url=..., custom_csp=..., enable_client_logging=...)`.

```python
return render_swagger_ui(
    title="Service Docs",
    openapi_url="/api/openapi.json",
    enable_client_logging=True,
)
```

## How can I export the spec to a file?

Use the CLI:

```bash
azure-functions-openapi generate --output openapi.json --format json
azure-functions-openapi generate --output openapi.yaml --format yaml
```

Or write strings in Python:

```python
Path("openapi.json").write_text(get_openapi_json(), encoding="utf-8")
```

## How do I validate the generated spec?

Use an external validator such as `openapi-spec-validator`.

```bash
pip install openapi-spec-validator
openapi-spec-validator openapi.json
```

## Does this integrate with `azure-functions-validation`?

Yes. A common pattern is using the same Pydantic model for:

- runtime validation (`@validate_http`)
- OpenAPI schema generation (`@openapi`)

See [Notification Request Example](examples/notification_request.md).

## Can I assign multiple tags?

Yes. Pass a list of strings.

```python
@openapi(tags=["Orders", "Internal", "Admin"])
```

## Can I define custom operation IDs?

Yes. Set `operation_id`.

```python
@openapi(operation_id="createInvoice")
```

The library sanitizes invalid characters automatically and may prefix with `op_` if needed.

## Why is my endpoint missing in the generated spec?

Common causes:

- missing `@openapi` on that handler
- module containing the function was not imported at startup
- route metadata mismatch in the decorator

See [Troubleshooting](troubleshooting.md) for a full checklist.
