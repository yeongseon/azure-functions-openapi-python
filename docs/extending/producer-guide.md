# Producer Guide: the `endpoint` metadata convention

This page documents the **internal toolkit convention** that lets a package in
the Azure Functions Python DX Toolkit contribute OpenAPI operation metadata for
its handlers, which `azure-functions-openapi` then compiles into a spec.

!!! warning "Internal convention, not a public extension API"
    This is a **convention shared inside the DX Toolkit**, not a supported
    third-party extension API. The dict shape is versioned and may change with
    the `version` field; it carries **no external compatibility guarantee** and
    there is **no** canonical/hosted schema to download. If you are building a
    toolkit package (e.g. `azure-functions-validation`,
    `azure-functions-langgraph`), follow this convention so the ecosystem stays
    consistent. If you are outside the toolkit, prefer the `@openapi` decorator.

## The convention

A producer attaches a **plain dict** to its HTTP handler under the
`_azure_functions_metadata` attribute, in the `"endpoint"` namespace:

```python
import azure.functions as func


def make_handler():
    def handler(req: func.HttpRequest) -> func.HttpResponse:
        # ... your real handler logic ...
        return func.HttpResponse("ok")

    # The producer convention: a plain dict, no runtime dependency on
    # azure-functions-openapi / -validation / -langgraph.
    handler._azure_functions_metadata = {
        "endpoint": {
            "version": 1,
            "request_body": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            "request_body_required": True,
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "integer"},
                }
            ],
            "responses": {
                "200": {"schema": {"type": "object", "properties": {"id": {"type": "integer"}}}},
                "422": {"schema": {"type": "object", "properties": {"detail": {"type": "string"}}}},
            },
        }
    }
    return handler
```

That is the whole contract. The producer writes a dict and depends on **nothing**
at runtime — not `azure-functions-openapi`, not `azure-functions-validation`,
not `azure-functions-langgraph`.

### Payload keys

| Key | Meaning |
| --- | --- |
| `version` | Contract version. Currently `1`. |
| `request_body` | Raw JSON Schema for the request body. |
| `request_body_required` | Whether the request body is required. |
| `parameters` | List of OpenAPI parameter objects (query / path / header / cookie). |
| `responses` | Map of status code (string) → `{"description"?, "schema"}`. Include non-success statuses (e.g. `"422"`) here too. |

## Design principle: embed raw JSON Schema, do not pre-normalize

The embedded schemas are **raw JSON Schema**. Producers may use local `$defs`
and leave them **unresolved** — the consumer hoists them into
`components.schemas` for you:

```python
"request_body": {
    "type": "object",
    "properties": {"parent": {"$ref": "#/$defs/Parent"}},
    "$defs": {"Parent": {"type": "object", "properties": {"id": {"type": "integer"}}}},
}
```

Producers should **never** pre-hoist, pre-resolve, or otherwise normalize the
schema. Emit exactly what your model serializer produces; the consumer owns
normalization (see `utils.hoist_inline_defs`).

## Version policy (as it behaves today)

- Every payload carries `version: 1`.
- The consumer accepts the versions in `SUPPORTED_ENDPOINT_VERSIONS`
  (currently `frozenset({1})`).
- On an **unknown or malformed** version the consumer **warns and skips** that
  handler's endpoint metadata (it does not raise) and continues.
- **Additive** changes (e.g. adding a new non-success response like `"422"`)
  keep `version` at `1`. A **breaking** change bumps the version.

There is intentionally **no** promised "consumer supports version `N` and
`N-1`" policy — the consumer accepts exactly the versions in
`SUPPORTED_ENDPOINT_VERSIONS` and warns on anything else. Do not rely on more
than that.

## How the payload reaches the spec

Producer metadata is **not** picked up automatically by the in-process spec
functions. You must run discovery first, which reads each handler's `endpoint`
namespace and registers the operations:

```python
from azure_functions_openapi.bridge import scan_endpoint_metadata
from azure_functions_openapi.spec import generate_openapi_spec

# 1. Discover endpoint metadata on the live FunctionApp...
scan_endpoint_metadata(app)
# 2. ...then compile the spec.
spec = generate_openapi_spec(title="My API", version="1.0.0")
```

### From the CLI

The CLI can run that discovery for you. Pass an explicit `module:variable` so it
can resolve the `FunctionApp` and scan it:

```bash
azure-functions-openapi generate --app function_app:app --output openapi.json
```

With `--app module` (no `:variable`) the CLI imports the module so `@openapi`
decorators register, but it does **not** scan endpoint metadata and prints a
note reminding you to pass `module:variable`. See the
[CLI Guide](../cli.md) for details.

## Related

- [CLI Guide](../cli.md)
- [Usage](../usage.md)
- [API Reference](../api.md)
