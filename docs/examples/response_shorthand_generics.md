# Response Shorthand Generics Example

Shows the boundary of the bare `responses=` shorthand: `list[Model]` is accepted and
a `Callable` generic is rejected. It is offline and needs no Azure resources.

Source: `examples/response_shorthand_generics/function_app.py`

## Supported: `list[Model]`

```python
@openapi(
    route="/api/items",
    method="get",
    responses={200: list[Item]},
)
```

The generated `200` response is a JSON array of the shared `Item` component:

```json
{"type": "array", "items": {"$ref": "#/components/schemas/Item"}}
```

Container generics (`list`, `tuple`, `set`, `frozenset`, `dict` and their
`collections.abc` equivalents) and unions/`Optional` are accepted as a bare body shorthand.

## Rejected: `Callable`

A callable has no JSON body, so it cannot be a response schema. Declaring one raises
`ValueError` **when the decorator is applied**, not later during spec generation, and
registers nothing:

```python
@openapi(route="/api/callbacks", method="get", responses={200: Callable[[int], str]})
def callbacks(req): ...
```

The message names the offending origin and the way out (the model text is abridged):

```text
Invalid 'responses' entry for status 200 in function 'callbacks': ... uses the
unsupported generic origin 'Callable'. Only container generics (list, tuple, set,
frozenset, dict and their collections.abc equivalents) and unions/Optional are accepted
as a response-body shorthand. To describe this response, pass an explicit OpenAPI
Response Object mapping as the value instead.
```

The example wraps the rejected declaration in `declare_rejected_shorthand()` so the module
still imports.

## Alternative: an explicit Response Object mapping

Describe the body that clients really receive with a JSON schema:

```python
responses={
    200: {
        "description": "Registered callback",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                }
            }
        },
    }
}
```

This does not make a callable serializable; it documents a JSON value your handler returns.

## Run locally

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_response_shorthand_generics_example.py --no-cov -q
```

The test checks the generated array schema (OpenAPI 3.0 and 3.1, validated), the runtime
body shape, the rejection message, and that only the explicit mapping is registered for
`/api/callbacks`. The decorator-level accept/reject matrix is pinned in
`tests/test_responses_shorthand_generics.py`.
