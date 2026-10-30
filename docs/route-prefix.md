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

## Resolving the prefix from host.json (opt-in)

Existing Python entry points and the CLI still default to `/api`; detection is
never enabled implicitly. Call `resolve_route_prefix()` and pass its result to
any existing `route_prefix=` parameter to avoid duplicating configuration.
Resolution uses the first available value:

1. The app-setting override environment variable
   `AzureFunctionsJobHost__extensions__http__routePrefix`, when present.
2. `extensions.http.routePrefix` in the supplied `host.json` path (or
   `./host.json` in the current working directory when no path is supplied).
3. The default `/api`.

An empty string at either configured level means no prefix: an empty
`routePrefix` in `host.json` removes the host's prefix, and the helper applies
the same rule to a present but empty app setting. Whether a given hosting
environment delivers an empty app setting to the host is outside the helper's
control, so confirm that before relying on it. Values are normalized: `api`
becomes `/api`, `/v1/` becomes `/v1`, and `""` stays empty. Missing files and
missing keys silently fall back. Unreadable files, invalid JSON, and non-string
`routePrefix` values emit a `RuntimeWarning` naming the file and reason, then
fall back to `/api`.
The file is parsed as strict JSON with an optional UTF-8 byte order mark, so a
`host.json` that contains comments or trailing commas is reported as unreadable.
The helper only reads configuration; it never imports or executes application code.

In `function_app.py`, explicitly locate the file beside your module:

```python
from pathlib import Path

from azure_functions_openapi import register_openapi_routes, resolve_route_prefix

route_prefix = resolve_route_prefix(Path(__file__).with_name("host.json"))
register_openapi_routes(app, title="My API", version="1.0.0", route_prefix=route_prefix)
```

This keeps generated paths and Swagger UI's specification URL aligned. Reuse
the resolved value for standalone generation or scanning calls as needed.
Python API calls do not emit mismatch warnings.

For CLI generation, opt in with `auto`:

```bash
azure-functions-openapi generate --app function_app:app --route-prefix auto
```

The CLI reads `host.json` beside the imported `--app` module, falling back to
the current working directory if there is no app or the module has no `__file__`.
The app-setting override above still wins in `auto` mode. If the file is
unreadable or malformed, `auto` falls back to `/api` and prints the same
`RuntimeWarning` on stderr; that warning does not gate `--fail-on-warnings`. A
**literal** prefix named `auto` must be written `--route-prefix /auto`.

Without `auto`, a configured file prefix that differs from the effective
prefix produces a structured `route-prefix-mismatch` warning as a JSON line on
stderr. This applies both to the unchanged `/api` default and an explicit
prefix. The message names both values and suggests `--route-prefix <value>`
or `--route-prefix auto`. It **gates `--fail-on-warnings` (exit 2)** before
writing output, unlike the advisory `unresolved-route` warning. This comparison
checks the file only, not the environment; missing, malformed, or unreadable
configuration does not produce a mismatch warning. Equal prefixes and `auto`
never produce it. An explicit value that differs from the file is still honored
for the generated paths, but it also produces the warning, so a job that
intentionally documents a gateway-facing prefix should not use
`--fail-on-warnings`.

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
@app.route(route="api/users", methods=["GET"])  # → /api/api/users, not /api/users
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
