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
- The discrete parameters were removed from `@openapi`; migrating to the unified
  surface is required for decorator-based registration (see
  [Removal policy](#removal-policy)).

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

### Array response bodies → `responses={200: list[Model]}`

A per-status value may also be a generic collection alias such as
`list[Model]`, resolved to an array schema in the generated spec — no wrapper
model required:

```python
@openapi(
    summary="List orders",
    method="get",
    responses={200: list[OrderResponse]},   # → array of OrderResponse
)
```

### Fallback error responses → `responses={..., "default": ErrorModel}`

The OpenAPI `"default"` response key documents the response for any status code
not otherwise listed — ideal for a shared error model. Pass it alongside your
concrete statuses; a bare model is expanded to a Response Object just like a
numeric key:

```python
@openapi(
    summary="Get order",
    method="get",
    responses={
        200: OrderResponse,
        404: ErrorResponse,
        "default": ErrorResponse,   # any other status → ErrorResponse
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

On `register_openapi_metadata()`, you cannot pass both a unified parameter and
its discrete equivalent:

- `requests=` together with `request_model=` or `request_body=` raises
  `ValueError`.
- `responses=` together with `response_model=` or `response=` raises
  `ValueError`.

Migrate each operation fully to the unified form in one step.

## Removal policy

On a package with this level of adoption, removing public-API parameters is a
generational change and came with an explicit, published deprecation window.

- The `DeprecationWarning` shipped in **0.20.0** ([#286]).
- The discrete parameters (`request_model=`, `request_body=`, `response_model=`,
  `response=`) were **removed from `@openapi`** after the two-minor-release
  window elapsed; the removal is announced in the CHANGELOG.
- They remain **available on `register_openapi_metadata()`**, the stable
  programmatic registration API.

The removal is tracked in
[#285](https://github.com/yeongseon/azure-functions-openapi-python/issues/285).

## `responses=` generic shorthand is restricted to containers (#493)

The `responses=` mapping accepts a **generic collection alias** as a bare
response-body shorthand — for example:

```python
@openapi(route="items", method="get", responses={200: list[Item]})
def list_items(req): ...
```

Previously **any** generic alias with a non-`None` `typing.get_origin(...)` was
accepted and only resolved at spec-generation time, so an unsupported generic
such as `Callable[[int], str]` was not rejected up front — it either failed
late or produced a nonsensical schema.

As of **#493**, only container generics are accepted as a shorthand:

- `list[...]`, `tuple[...]`, `set[...]`, `frozenset[...]`, `dict[...]` and their
  `collections.abc` equivalents (`Sequence`, `Mapping`, `Set`, and the
  `Mutable*` variants).
- Unions / `Optional` — both `typing.Union[...]` and PEP 604 `X | Y`.

Any other generic (most notably `Callable`, iterators, coroutines, ...) now
raises a `ValueError` **at decoration time** with an actionable message:

```text
Invalid 'responses' entry for status 200 in function 'handler':
typing.Callable[[int], str] uses the unsupported generic origin 'Callable'.
Only container generics (list, tuple, set, frozenset, dict and their
collections.abc equivalents) and unions/Optional are accepted as a
response-body shorthand. To describe this response, pass an explicit OpenAPI
Response Object mapping as the value instead.
```

**Breaking change:** if you previously relied on a non-container generic being
silently accepted (and producing whatever schema fell out of `TypeAdapter`),
replace it with an explicit OpenAPI Response Object mapping:

```python
# before (now raises ValueError at decoration time)
@openapi(route="cb", method="get", responses={200: Callable[[int], str]})
def handler(req): ...

# after — describe the response explicitly
@openapi(
    route="cb",
    method="get",
    responses={
        200: {
            "description": "Callback descriptor",
            "content": {"application/json": {"schema": {"type": "string"}}},
        }
    },
)
def handler(req): ...
```

## Tracking

The unified-parameter migration is tracked in [#285]. If you hit a case the
unified parameters cannot express, please open an issue referencing #285.

[#285]: https://github.com/yeongseon/azure-functions-openapi-python/issues/285
[#286]: https://github.com/yeongseon/azure-functions-openapi-python/issues/286
[#410]: https://github.com/yeongseon/azure-functions-openapi-python/issues/410
[#418]: https://github.com/yeongseon/azure-functions-openapi-python/issues/418
