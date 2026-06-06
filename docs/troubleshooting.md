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

- passing a dict to `request_model` or `response_model`
- mixing incompatible Pydantic usage patterns in your own function code

### Fixes

- pass Pydantic classes to `request_model` and `response_model`
- if you need raw schema dicts, use `request_body` and `response`
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
