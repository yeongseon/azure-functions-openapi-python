# Producer Guide — Write Your Own Endpoint Metadata

`azure-functions-openapi` generates an OpenAPI document from HTTP handlers. Most
users reach that document through the [`@openapi`](../usage.md) decorator, but
the package also reads a **public extension contract**: any handler that carries
an `endpoint` metadata payload is picked up automatically by the spec generator —
no dependency on `azure-functions-openapi` required at write time.

This is how sibling packages such as
[`azure-functions-validation`](https://github.com/yeongseon/azure-functions-validation-python)
and
[`azure-functions-langgraph`](https://github.com/yeongseon/azure-functions-langgraph-python)
contribute request/response schemas without importing this package. **Third
parties can do exactly the same thing.** This guide shows you how.

## Design principles

The `endpoint` contract is deliberately small and boring, so producers and
consumers can evolve independently:

- **Raw JSON Schema only.** Every schema field (`request_body`, `parameters`,
  `responses`) is a plain JSON Schema `dict`. Producers never ship model
  *classes* — the consumer needs no import of the producing package and no
  access to your Pydantic models.
- **`$defs` are allowed and left unresolved.** If your schema uses
  `$ref: "#/$defs/{Model}"`, keep the `$defs` on the owning schema. **Do not
  pre-normalize or hoist them.** The consumer (`azure-functions-openapi`) is the
  sole authority for hoisting `$defs` into `components/schemas` and for
  resolving `$ref` collisions — see
  [`utils.hoist_inline_defs`](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/src/azure_functions_openapi/utils.py).
- **Self-contained payload.** Everything the consumer needs is in the payload.
  There is no callback into your package at generate time.
- **Warn, don't fail, on version skew.** Consumers that see an unknown `version`
  degrade gracefully rather than crashing — see
  [Version policy](#canonical-schema-and-version-policy).

## The convention

Producers attach the payload to the handler under a single, toolkit-wide
convention attribute:

- **Attribute:** `_azure_functions_metadata`
- **Namespace:** `"endpoint"`
- **Payload shape:** `endpoint.schema.json` (`version: 1`)

The attribute is a `dict` keyed by namespace, so multiple producers can
cooperate on the same handler without clobbering one another (for example, the
`validation` namespace and the `endpoint` namespace can coexist).

### Payload fields (`version: 1`)

| Field | Type | Meaning |
|-------|------|---------|
| `version` | `int` (**required**) | Contract version. Currently `1`. |
| `request_body` | JSON Schema `dict` or `None` | Schema of the request body, or `None` when there is no body. `$defs` allowed, kept unresolved. |
| `request_body_required` | `bool` | Whether the body is required. |
| `parameters` | `list[dict]` | OpenAPI-style parameter objects derived from query/path/header inputs. |
| `responses` | `dict[str, dict]` or `None` | Map of HTTP status code (as a string) to a response object carrying a `schema`. `None` when no response model is declared. |

## Canonical schema and version policy

The canonical JSON Schema for this payload lives in the neutral
**Azure Functions Python DX** hub, not in any single producer or consumer:

```
https://yeongseon.github.io/azure-functions-python-dx/endpoint.schema.json
```

Version policy:

- **Additive, backward-compatible changes keep the same `version`.** New optional
  fields may appear; producers and consumers ignore what they do not recognize.
- **Breaking changes bump `version`.** A consumer supports the current version
  `N` and the previous version `N-1`, so a producer and consumer can be one
  release apart without breaking the build.
- **On an unknown `version`, the consumer warns and falls back** — it never
  silently promotes a spec it cannot fully understand. See the
  [`--fail-on-warnings` CLI flag](../cli.md) if you want CI to treat that skew
  as a hard failure.

## A minimal, standalone producer

The example below is a complete, dependency-free producer. It writes an
`endpoint` payload directly onto a handler using nothing but the standard
library and Pydantic (only to derive the JSON Schema — you can hand-write the
schema instead). It does **not** import `azure-functions-openapi`,
`azure-functions-validation`, or `azure-functions-langgraph`.

```python
import azure.functions as func
from pydantic import BaseModel

HANDLER_METADATA_ATTR = "_azure_functions_metadata"


class CreateUserRequest(BaseModel):
    name: str
    email: str


class UserResponse(BaseModel):
    id: int
    name: str


def with_endpoint_metadata(handler):
    """Attach a version-1 ``endpoint`` payload to *handler*."""
    payload = {
        "version": 1,
        # Raw JSON Schema; $defs (if any) are left unresolved on purpose.
        "request_body": CreateUserRequest.model_json_schema(
            ref_template="#/$defs/{model}"
        ),
        "request_body_required": True,
        "parameters": [],
        "responses": {
            "201": {"schema": UserResponse.model_json_schema(
                ref_template="#/$defs/{model}"
            )},
        },
    }
    # Merge under the "endpoint" namespace without clobbering other producers.
    existing = dict(getattr(handler, HANDLER_METADATA_ATTR, {}))
    existing["endpoint"] = payload
    setattr(handler, HANDLER_METADATA_ATTR, existing)
    return handler


app = func.FunctionApp()


@app.route(route="users", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@with_endpoint_metadata
def create_user(req: func.HttpRequest) -> func.HttpResponse:
    ...
```

Once the handler carries this payload, `azure-functions-openapi` incorporates
the request and response schemas into the generated document automatically —
via [`scan_endpoint_metadata`](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/src/azure_functions_openapi/bridge.py),
the consumer entry point — with no further wiring on your side.

## Validate your payload against the canonical schema

Before shipping a producer, validate a sample payload against the canonical
schema so you catch shape errors early:

```python
import json
import urllib.request

import jsonschema  # pip install jsonschema

SCHEMA_URL = "https://yeongseon.github.io/azure-functions-python-dx/endpoint.schema.json"

with urllib.request.urlopen(SCHEMA_URL) as resp:
    schema = json.load(resp)

payload = getattr(create_user, "_azure_functions_metadata")["endpoint"]
jsonschema.validate(instance=payload, schema=schema)  # raises on mismatch
print("endpoint payload is valid")
```

In CI you will usually vendor a pinned copy of the schema (matched by SHA-256
digest) rather than fetching it over the network, but the validation call is the
same.

## Checklist

- [ ] Payload written under `_azure_functions_metadata["endpoint"]`.
- [ ] `version` set (currently `1`).
- [ ] All schema fields are raw JSON Schema `dict`s; `$defs` left unresolved.
- [ ] No pre-hoisting / pre-normalization of `$ref`s.
- [ ] Existing namespaces preserved when merging the payload.
- [ ] Sample payload validates against the canonical schema.

## Related

- [Architecture](../architecture.md) — how the registry and generator fit together.
- [CLI Guide](../cli.md) — `--fail-on-warnings` for gating on version skew.
- [Usage Guide](../usage.md) — the `@openapi` decorator path for direct authors.
