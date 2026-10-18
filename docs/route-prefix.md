# Route Prefix Policy

Azure Functions exposes HTTP-triggered functions under a configurable URL prefix
controlled by `host.json` (`extensions.http.routePrefix`). This page documents
how `azure-functions-openapi` reflects that prefix in generated OpenAPI specs
so the documented URLs match what your Function App actually serves.

## The default `/api` prefix

By default, Azure Functions serves HTTP triggers under `/api/<route>`. The
prefix is set in `host.json`:

```json
{
  "version": "2.0",
  "extensions": {
    "http": {
      "routePrefix": "api"
    }
  }
}
```

To match this default, `azure-functions-openapi` uses `"/api"` as the default
`route_prefix` in:

- `generate_openapi_spec(..., route_prefix="/api")`
- `scan_endpoint_metadata(app, route_prefix="/api")`
- The CLI flag `azure-functions-openapi generate --route-prefix /api`

## Authoring routes with `@openapi`

You can author routes in `@openapi(route=...)` either with or without the
prefix; the spec generator is **idempotent** with respect to the configured
`route_prefix`:

```python
@openapi(route="/users", method="get")        # → /api/users
@openapi(route="/api/users", method="get")    # → /api/users (no double prefix)
```

The recommended form is **without** the prefix (`route="/users"`) so the same
decorated handler works against any `host.json` deployment by passing a
different `--route-prefix` at spec generation time.

Route parameters support only `{name}`, `{name:int}`, and `{name:alpha}`.
Optional parameters, catch-all parameters, and all other inline constraints are
rejected because converting them to required plain strings would describe a
different route contract. See [Route inline constraints](configuration.md#route-inline-constraints)
for the complete supported subset and strict/non-strict behavior.

## Discovered SDK binding routes are never deduplicated

The idempotent dedup in the previous section applies only to an **explicit**
`@openapi(route=...)` override, where the author is naming the already-prefixed
URL as a convenience. It does not apply to a route **discovered** from the
underlying `@app.route(...)` binding (whether through app-scan auto-discovery,
a validation-bridge producer, or `@openapi` inferring the route directly from
the binding below it) — those routes are host-relative, and Azure Functions
composes the served URL as `routePrefix + '/' + routeTemplate`
**unconditionally**, even when the route's own first segment happens to equal
the prefix:

```python
@openapi(summary="List users")
@app.route(route="api/users", methods=["GET"])   # → /api/api/users, not /api/users
def list_users(req): ...
```

This matches what the Azure Functions host actually serves: a function bound
to route `api/users` under `routePrefix: "api"` is reachable at
`/api/api/users`, not `/api/users`. If this collision is unintended, rename the
binding's `route=` so it does not repeat the configured prefix, or write an
explicit `@openapi(route="/api/users")` override instead, which keeps the
dedup behavior described above.

## Customising the prefix

### No prefix

If `host.json` sets `routePrefix` to an empty string, pass `""` so the
generated spec drops the prefix:

```bash
azure-functions-openapi generate --app function_app --route-prefix ""
```

```python
spec = generate_openapi_spec(route_prefix="")
scan_endpoint_metadata(app, route_prefix="")
```

### Custom prefix

For a non-default prefix such as `v1`:

```bash
azure-functions-openapi generate --app function_app --route-prefix /v1
```

```python
spec = generate_openapi_spec(route_prefix="/v1")
scan_endpoint_metadata(app, route_prefix="/v1")
```

The prefix is normalized: leading slash is added if missing, trailing slashes
are stripped (`v1/` and `/v1` both produce `/v1`).

## Consistency across registration paths

The same `route_prefix` applies to all three registration paths so a
FunctionApp that mixes them produces a single, consistent `paths` map:

| Registration path                    | Where prefix is applied              |
| ------------------------------------ | ------------------------------------ |
| `@openapi(route=...)` decorator      | `generate_openapi_spec(route_prefix=)` at spec-build time |
| `register_openapi_metadata(path=...)`| `generate_openapi_spec(route_prefix=)` at spec-build time |
| Validation bridge auto-discovery     | `scan_endpoint_metadata(route_prefix=)` at scan time and `generate_openapi_spec(route_prefix=)` at spec-build time |

To keep the bridge-discovered registry entries and the final spec aligned,
pass the **same** `route_prefix` to both `scan_endpoint_metadata()` and
`generate_openapi_spec()` (or the CLI `--route-prefix`).
