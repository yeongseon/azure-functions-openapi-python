# Migrating to unified `requests=` / `responses=`

The `@openapi` decorator historically exposed **four discrete** request/response
parameters:

- `request_model=`
- `request_body=`
- `response_model=`
- `response=`

These are now **deprecated** in favor of **two unified** parameters —
`requests=` and `responses=` — each of which accepts *either* a Pydantic model
class *or* a raw schema dict (and, for `responses=`, a per-status-code map).
Passing any discrete parameter emits a `DeprecationWarning`.

This page is the authoritative, before/after migration reference. For the
day-to-day usage guide see [Usage → Request and response schema
styles](../usage.md#request-and-response-schema-styles).

## Why migrate

- The unified parameters express **every** case the discrete pair could,
  including the typed-success-body **and** extra-status-code combination that
  previously required mixing `response_model=` with `response=` (closed by
  [#410] / [#418]).
- One consistent surface (`requests` / `responses`) is easier to learn,
  document, and evolve than four interacting parameters.
- The discrete parameters will eventually be removed; migrating now avoids a
  future breaking change (see [Alias-retention policy](#alias-retention-policy)).

## Before / after recipes

Each discrete parameter maps directly onto a unified one. `requests=` and
`responses=` infer their meaning from the value's type: a Pydantic `BaseModel`
subclass behaves like the old `*_model` form, and a `dict` behaves like the old
`request_body=` / `response=` form.

### `request_model=Model` → `requests=Model`

```python
# Before
@openapi(summary="Create order", method="post", request_model=CreateOrderRequest)

# After
@openapi(summary="Create order", method="post", requests=CreateOrderRequest)
```

### `request_body={...}` → `requests={...}`

```python
# Before
@openapi(
    summary="Create order",
    method="post",
    request_body={
        "type": "object",
        "properties": {"sku": {"type": "string"}},
        "required": ["sku"],
    },
)

# After
@openapi(
    summary="Create order",
    method="post",
    requests={
        "type": "object",
        "properties": {"sku": {"type": "string"}},
        "required": ["sku"],
    },
)
```

### `response_model=Model` → `responses=Model`

```python
# Before
@openapi(summary="Create order", method="post", response_model=OrderResponse)

# After
@openapi(summary="Create order", method="post", responses=OrderResponse)
```

A bare model on `responses=` derives the `200` response schema from the model,
exactly as `response_model=` did.

### `response={status: {...}}` → `responses={status: {...}}`

```python
# Before
@openapi(
    summary="Create order",
    method="post",
    response={201: {"description": "Created"}},
)

# After
@openapi(
    summary="Create order",
    method="post",
    responses={201: {"description": "Created"}},
)
```

### Typed success body **plus** extra status codes → `responses={202: Model, 422: {...}}`

This is the case that could **not** migrate before [#410] was closed by [#418].
Previously a typed success body (`response_model=`) combined with additional
documented status codes (`response=`) required keeping the discrete pair. Now a
single `responses=` map expresses both — a per-status value may be a Pydantic
model (expanded to a JSON body of that schema) *or* a raw Response Object dict:

```python
# Before (had to keep the discrete pair)
@openapi(
    summary="Enqueue order",
    method="post",
    response_model=AcceptedModel,          # typed 202 body
    response={422: {"description": "Validation error"}},
)

# After (fully unified)
@openapi(
    summary="Enqueue order",
    method="post",
    responses={
        202: AcceptedModel,                # model → typed 202 JSON body
        422: {"description": "Validation error"},
    },
)
```

### Optional request bodies are unchanged

`request_body_required=` is orthogonal to this migration — keep using it
alongside `requests=`:

```python
@openapi(
    summary="Partial update",
    method="patch",
    requests=PatchOrderRequest,
    request_body_required=False,
)
```

## Mixing rules

You cannot pass both a unified parameter and its discrete equivalent:

- `requests=` together with `request_model=` or `request_body=` raises
  `ValueError`.
- `responses=` together with `response_model=` or `response=` raises
  `ValueError`.

Migrate each operation fully to the unified form in one step.

## Alias-retention policy

On a package with this level of adoption, removing public-API parameters is a
generational change and must come with an explicit, published window rather than
an open-ended "a future release".

- The discrete parameters (`request_model=`, `request_body=`, `response_model=`,
  `response=`) remain **accepted** — emitting a `DeprecationWarning` — for **at
  least two minor releases** after the deprecation was introduced.
- The `DeprecationWarning` shipped in **0.20.0** ([#286]).
- Therefore the discrete parameters will **not be removed before 0.23.0**, and
  removal will be announced in the CHANGELOG for the release that performs it.

The [actual removal](https://github.com/yeongseon/azure-functions-openapi-python/issues/285)
is tracked separately; this policy only fixes the earliest removal boundary so
downstream users have a dependable window to migrate.

## Tracking

The unified-parameter migration is tracked in [#285]. If you hit a case the
unified parameters cannot express, please open an issue referencing #285.

[#285]: https://github.com/yeongseon/azure-functions-openapi-python/issues/285
[#286]: https://github.com/yeongseon/azure-functions-openapi-python/issues/286
[#410]: https://github.com/yeongseon/azure-functions-openapi-python/issues/410
[#418]: https://github.com/yeongseon/azure-functions-openapi-python/issues/418
