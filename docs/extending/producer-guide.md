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
| `version` | Contract version. This consumer accepts `1` and `2`. |
| `request_body` | Raw JSON Schema for the request body. |
| `request_body_required` | Whether the request body is required. |
| `parameters` | List of OpenAPI parameter objects (query / path / header / cookie). |
| `responses` | In v1, status string → `{"description"?, "schema"}`. In v2, use the representation below. Include non-success statuses too. |

### V2 response representations

Use `version: 2` for response media types, header schemas or explicit body absence.
Request-body and parameter fields retain their v1 shape:

```python
payload = {
    "version": 2,
    "responses": {
        "201": {
            "description": "Created",
            "content": {"application/json": {"schema": {"type": "object"}}},
            "headers": {"Location": {"schema": {"type": "string"}}},
        },
        "400": {
            "content": {"application/problem+json": {"schema": {"type": "object"}}},
        },
        "204": {"content": {}},
    },
}
```

- Status keys must be three-digit **strings** from `"200"` to `"599"`.
- Every response requires a `content` mapping. Each media object requires a
  dictionary `schema`; response-level legacy `schema` is forbidden in v2.
- Empty `content` means no body: the OpenAPI response omits `content` entirely.
  A media schema `{"type": "null"}` describes a real null body, not body absence.
  Statuses 204, 205 and 304 require empty content.
- `description` defaults to `""`. Optional `headers` maps HTTP token names to
  dictionary `schema` objects and optional string descriptions. Names compare
  case-insensitively; duplicate case variants and `Content-Type` are rejected.
  These schemas are not literal header values or duplicate-wire-line guarantees.
- Media types use a `type/subtype` name without whitespace or parameters.
  `text/event-stream` may carry `{"schema": {"type": "string"}}`; this documents
  the representation, not event-item streaming semantics. V2 does not consume
  `itemSchema`.
- The consumer copies only allowlisted response/media/header fields. Unknown
  fields are ignored with structured `discovery-skipped` diagnostics naming v2,
  the status and the field; `x-*` fields are silently ignored, not forwarded.
  Schema dictionaries themselves are preserved for the existing schema compiler.
- A malformed response is skipped as a unit, with actionable diagnostics. Valid
  sibling responses and request/parameter hints survive. Missing content never
  becomes inferred JSON or inferred body absence.

Response media and header schemas may contain nested `$defs`. The same compiler
hoists both, resolves component-name collisions, and converts schemas for the
selected OpenAPI 3.0, 3.1 or 3.2 target. Endpoint payload versions and OpenAPI
document versions are independent.

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

- Every payload carries an integer `version`, not a boolean or string.
- The consumer accepts the versions in `SUPPORTED_ENDPOINT_VERSIONS`
  (currently `frozenset({1, 2})`).
- On an **unknown or malformed** version the consumer **warns and skips** that
  handler's endpoint metadata (it does not raise) and continues.
- V1 behavior is unchanged: every status gets `application/json`, including a
  missing/null schema and `"204": {}`. Do not use v1 to imply body absence.
- Adding another v1 status keeps version 1. Richer response representations need
  version 2: older consumers would misread a v1 `content` field as JSON with a
  missing schema, so this is not a safely ignorable additive v1 field.
- Unknown versions produce `version-skew` diagnostics and degraded binding-based
  discovery, never legacy `validation` namespace fallback. The wrapper chain may
  still provide a supported inner payload. Rejected response hints are never
  fabricated; the generator's ordinary fallback response is not a producer claim.

There is intentionally **no** promised "consumer supports version `N` and
`N-1`" policy — the consumer accepts exactly the versions in
`SUPPORTED_ENDPOINT_VERSIONS` and warns on anything else. Do not rely on more
than that.

### Independently versioned producer and consumer

A producer release A can continue emitting `{"version": 1, "responses": {"200":
{"schema": {"type": "object"}}}}` to both an older v1-only consumer and this
consumer. A later producer release B may opt into the v2 payload above only for
richer contracts. A v1-only consumer rejects that v2 payload with a version
warning; this consumer consumes it. Upgrading the consumer first also works:
producer A's v1 output is unchanged. Neither package imports the other's contract
model, and neither release waits for or pins the other's release. Ensure the
selected consumer explicitly supports the emitted version, or supply explicit
`@openapi` metadata instead; never relabel v2 content as v1 for compatibility.

This is the written compatibility policy for the internal convention: accepted
versions retain their meanings; a semantic change needs a distinct version and
documented consumer support. It is not a new public third-party extension API.

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
