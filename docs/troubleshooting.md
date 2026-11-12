# Troubleshooting

Use this guide to diagnose common `azure-functions-openapi` issues in local development and CI.

## 1) Swagger UI not loading

### Symptoms

- `/api/docs` returns 404
- page loads but no operations appear
- browser console shows CSP or fetch errors

### Checks

1. Confirm docs route exists:

```python
@app.route(route="docs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def docs(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui(openapi_url="/api/openapi.json")
```

2. Confirm OpenAPI route is reachable:

```bash
curl "http://localhost:7071/api/openapi.json"
```

3. Confirm `openapi_url` in `render_swagger_ui(...)` matches your route.

### Fixes

- set explicit `openapi_url="/api/openapi.json"`
- keep docs and spec routes under same host/origin
- if CSP blocks assets in your environment, pass an explicit `custom_csp`

### Protected Swagger UI: the page loads but the spec does not (or the reverse)

With `auth_level=func.AuthLevel.FUNCTION` the docs page (`/api/docs`) and the
specification (`/api/openapi.json`) are **two separate functions**, each checked
by the Functions host on its own. They can therefore give different results:

| Request | Expected result |
| --- | --- |
| `/api/docs` with no key | Host rejects it (`401`); the page is never served |
| `/api/docs?code=<wrong key>` | Host rejects it (`401`) |
| `/api/docs?code=<key valid for docs and JSON>` | Page is served. With `docs_key_forwarding="header"` the HTML and the spec URL do **not** contain the key |
| Spec download without `x-functions-key` | Host rejects it (`401`); the page shows Swagger UI's spec-load error |
| Spec download with a valid `x-functions-key` | `200` with the OpenAPI JSON |

Typical causes of "page loads, spec fails": the key in the URL only authorizes the
docs function (use a host key or a key valid for both functions); the registration
left `docs_key_forwarding` unset or `"none"`, so no key reaches the spec request; or a
redirect occurred (the spec fetch fails closed on redirects). "Spec works, page
fails" usually means the key was sent to `openapi.json` but not to `/api/docs`.

Reproduce the table offline with fake keys only:

```bash
python -m pytest tests/test_protected_docs_recipe.py --no-cov -q
```

The test registers the routes with `docs_key_forwarding="header"` and drives them
through a small **test double** that mimics the host's key check against a made-up
key. Use fake keys such as `FAKE-DOCS-KEY` in your own experiments and never paste a
real key into an issue or log. Azure Functions Core Tools does not enforce function
keys locally, so a local success proves neither key validity nor enforcement on
Azure; the double only shows what this library puts in the HTML and which header it
asks the browser to send.

!!! warning "UI display is not authorization"
    `docs_key_forwarding` only controls how the browser carries a key you already
    hold. Access is enforced by the host (or an edge such as API Management or Easy
    Auth), and API operations need their own authentication; exposing the UI never
    bypasses it. See [Protecting documentation routes](security.md#protecting-documentation-routes)
    for the supported patterns and limits (the initial `?code=` navigation can still
    appear in logs).

## 2) Spec not showing all endpoints

### Symptoms

- `paths` is empty
- only some operations are present

### Root causes

- handler missing `@openapi`
- module containing handlers not imported at startup
- decorator registration failed due to invalid parameter value

### Checks

Inspect registry during runtime:

```python
from azure_functions_openapi.decorator import get_openapi_registry

print(get_openapi_registry().keys())
```

Registry keys are keyed by the decorated function's short name. When two
handlers share the same short name, the earlier (displaced) entry is preserved
under its fully-qualified id (`module.qualname`) in addition to the short-name
key, so no registration is silently lost. If you rely on these keys for
debugging, expect both a short-name key and a fully-qualified key when name
collisions occur.

### Fixes

- add `@openapi` to every operation you want documented
- ensure all function modules are imported before generating specs
- correct invalid decorator values (for example invalid route path)

## 3) Pydantic v1 vs v2 issues

### Symptoms

- schema conversion errors
- model APIs differ (`schema()` vs `model_json_schema()`)

### What the library does

`azure-functions-openapi` requires Pydantic v2. If you are using Pydantic v1, upgrade to v2 before using this library.

### Common mistakes

- passing a dict where a Pydantic model is expected (or vice versa) to `requests` / `responses`
- mixing incompatible Pydantic usage patterns in your own function code

### Fixes

- pass Pydantic model classes to `requests` / `responses` for model-derived schemas
- if you need raw schema dicts, pass a `dict` to `requests` / `responses`
- keep a single Pydantic major version in your environment

## 4) Route mismatch between function and OpenAPI output

### Symptoms

- function route works but docs path is different
- path parameters not matching runtime route

### Why this happens

`@app.route(route=...)` controls runtime routing.
`@openapi(route=...)` controls documented path.

If they diverge, behavior and docs diverge.

### Fix

Keep them aligned by design:

```python
@openapi(route="/api/users/{user_id}", method="get")
@app.route(route="users/{user_id}", methods=["GET"])
```

!!! tip
    Documented routes often include `/api/...` while `app.route` may be relative. Be consistent across your app and docs conventions.

## 5) Invalid route or operation ID validation errors

### Symptoms

- `ValueError: Invalid route path ...`
- `ValueError: Invalid operation ID ...`

### Fixes

- use safe route characters (`a-z`, `A-Z`, digits, `_`, `-`, `/`, `{}`, no spaces)
- avoid dangerous patterns (`..`, `javascript:`, script snippets)
- use readable operation IDs (letters, digits, underscore)

## 6) CLI generates empty or unexpected output

### Symptoms

- generated spec has no routes
- wrong output format/version

### Checks

- use explicit flags: `--format`, `--openapi-version`
- confirm decorated modules are imported in process where CLI runs

### Example

```bash
azure-functions-openapi generate --format json --openapi-version 3.1 --output openapi.json
```

## 7) Swagger UI loads but `Try it out` fails

### Symptoms

- operation visible but execution fails in browser
- CORS/network/auth errors

### Checks

- verify API host and route are reachable from browser
- verify request headers expected by your function
- verify auth requirements if endpoint is not anonymous

## 8) Debug checklist

Use this checklist in order:

1. Confirm `@openapi` decorators exist on expected handlers
2. Confirm `openapi.json` endpoint returns valid JSON
3. Confirm `docs` endpoint calls `render_swagger_ui(openapi_url="/api/openapi.json")`
4. Confirm registry has expected function keys
5. Confirm route/method consistency between Azure route and OpenAPI metadata

## Need more help?

- [Usage Guide](usage.md)
- [Configuration](configuration.md)
- [API Reference](api.md)
- [FAQ](faq.md)
