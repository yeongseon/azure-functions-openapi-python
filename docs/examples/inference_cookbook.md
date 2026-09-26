# Inference Cookbook

This minimal API demonstrates how OpenAPI metadata can be inferred from a
handler's type annotation and docstring. The inference is intentionally
explicit: return-type inference is enabled by default, while docstring
inference requires `infer_docstring=True`.

Source: `examples/inference_cookbook/function_app.py`

## What this example includes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/greetings/{name}` | Return a typed greeting response |
| `GET` | `/api/openapi.json` | OpenAPI JSON |
| `GET` | `/api/openapi.yaml` | OpenAPI YAML |
| `GET` | `/api/docs` | Swagger UI |

## Features demonstrated

- `GreetingResponse` in the return annotation becomes the `200` response schema.
- `infer_docstring=True` opts into summary and description inference.
- The first docstring line becomes the operation summary.
- Remaining docstring text becomes the operation description.
- The handler still returns an Azure Functions `HttpResponse` at runtime.

The relevant declaration is intentionally small:

```python
@openapi(
    route="/api/greetings/{name}",
    method="get",
    tags=["inference"],
    infer_docstring=True,
)
@app.route(route="greetings/{name}", methods=["GET"])
def get_greeting(req: func.HttpRequest) -> GreetingResponse:
    """Greet a caller by name.

    The response schema comes from the return annotation, while this summary
    and description are published only because ``infer_docstring=True`` opts in.
    """
```

## Run locally

The `examples/` directories contain source modules, not standalone Function App
projects. To run locally, copy the example into a project directory and add the
required `host.json`:

```bash
mkdir -p my-inference-app
cp examples/inference_cookbook/function_app.py my-inference-app/
cat > my-inference-app/host.json << 'EOF'
{
  "version": "2.0",
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
EOF

cd my-inference-app
python -m venv .venv
source .venv/bin/activate
pip install azure-functions azure-functions-openapi pydantic
func start
```

## Try the endpoint

```bash
curl "http://localhost:7071/api/greetings/Ada"
```

Expected response:

```json
{"message":"Hello, Ada!","name":"Ada"}
```

Inspect the generated metadata:

```bash
curl "http://localhost:7071/api/openapi.json"
```

The `GET /api/greetings/{name}` operation should contain:

- summary: `Greet a caller by name.`
- a description from the remaining docstring text
- a `200` JSON response whose schema is `GreetingResponse`

## Precedence reminder

Inference fills gaps only. Explicit `@openapi` values win over inferred values,
and validation or enrichment metadata wins over return-type inference. See
[Inferred metadata](../usage.md#inferred-metadata-return-type-docstring) for the
full precedence rules.
