# Decorator Order Example

`@openapi` works both **above** and **below** `@app.route`. This example puts each
order on its own small `FunctionApp`, shows that they generate the same operation, and
documents the one order-dependent limit. It is offline and needs no Azure resources.

Source: `examples/decorator_order/function_app.py`

## The two orders

```python
document_thing = openapi(
    summary="Get a thing",
    operation_id="getThing",
    tags=["things"],
    responses={200: Thing, 404: {"description": "Thing not found"}},
)

# Order A: @openapi outermost
@document_thing
@outer_app.route(route="things/{id}", methods=["GET"])
def get_thing_outer(req): ...

# Order B: @openapi below @app.route
@inner_app.route(route="things/{id}", methods=["GET"])
@document_thing
def get_thing_inner(req): ...
```

Both are valid. Route, method and path parameters come from the `@app.route` binding;
`@openapi` only adds documentation.

## Same result

`generate_openapi_spec(app=outer_app)` and `generate_openapi_spec(app=inner_app)`
return identical documents: `GET /api/things/{id}` with the `id` path parameter, `200`
returning the `Thing` schema, and `404` with its description.

## Order-dependent limit

Order A reads the binding at decoration time. Order B runs before the binding exists, so
it needs an app to reconcile against. Pass `app=` (or call `scan_endpoint_metadata(app)`
first). Without one, a spec generated from the global registry has no evidence about the
route and falls back to the function name:

| Order | `generate_openapi_spec(app=app)` | `generate_openapi_spec()` (no app) |
| --- | --- | --- |
| `@openapi` above `@app.route` | `/api/things/{id}` | `/api/things/{id}` |
| `@openapi` below `@app.route` | `/api/things/{id}` | `/api/get_thing_inner` plus a "could not be verified" `RuntimeWarning` |

The CLI behaves the same way: use `--app module:variable` so it receives the app. See
[`@openapi` below `@app.route`](../architecture.md#openapi-below-approute) for the
design background.

## Run locally

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_decorator_order_example.py tests/test_decorator_order_routes.py --no-cov -q
```

`tests/test_decorator_order_example.py` asserts the equal documents, the function-name
fallback with its warning, and that scanning the app repairs it. The broader behavior
matrix (CLI, strict mode, multi-method expansion) is pinned in
`tests/test_decorator_order_routes.py`.
