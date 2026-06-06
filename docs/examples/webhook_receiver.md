# Webhook Receiver Example

This is the representative example showing the core `@openapi` workflow.
It accepts inbound webhook events with HMAC-SHA256 signature verification
and returns `202 Accepted`.

Source: `examples/webhook_receiver/function_app.py`

## What this example includes

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/webhooks/orders` | Receive order webhook |
| `GET` | `/api/openapi.json` | OpenAPI JSON |
| `GET` | `/api/openapi.yaml` | OpenAPI YAML |
| `GET` | `/api/docs` | Swagger UI |

## Features demonstrated

- `@openapi()` with `summary`, `description`, `tags`
- `request_model` and `response_model` for Pydantic schema generation
- `response` dict for documenting multiple status codes (202, 400, 401, 409)
- `get_openapi_json()`, `get_openapi_yaml()`
- `render_swagger_ui()`

## Data models

```python
class WebhookEvent(BaseModel):
    event_type: str = Field(..., description="Event type, e.g. 'order.completed'.")
    source: str = Field(..., description="Origin system, e.g. 'shopify'.")
    occurred_at: str = Field(..., description="ISO-8601 timestamp of event occurrence.")
    data: dict[str, Any] = Field(default_factory=dict, description="Arbitrary event payload.")


class WebhookAcceptedResponse(BaseModel):
    delivery_id: str = Field(..., description="Unique delivery identifier.")
    status: str = Field(default="accepted", description="Processing status.")
    received_at: str = Field(..., description="ISO-8601 timestamp of receipt.")
```

## How the docs are configured

```python
@openapi(
    route="/api/webhooks/orders",
    method="post",
    summary="Receive order webhook",
    description=(
        "Accepts an inbound webhook event for asynchronous processing.\n\n"
        "If `WEBHOOK_SECRET` is set, the `X-Signature` header is verified "
        "using HMAC-SHA256 (bound to `X-Webhook-Timestamp`) before the "
        "payload is accepted. Stale timestamps (>5 min) are rejected.\n\n"
        "Duplicate deliveries are rejected via the `X-Delivery-Id` header."
    ),
    tags=["webhooks"],
    request_model=WebhookEvent,
    response_model=WebhookAcceptedResponse,
    response={
        202: {"description": "Webhook accepted for processing"},
        400: {"description": "Invalid request payload"},
        401: {"description": "Invalid webhook signature or expired timestamp"},
        409: {"description": "Duplicate delivery (replay)"},
    },
    )
@app.route(route="webhooks/orders", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def receive_order_webhook(req: func.HttpRequest) -> func.HttpResponse:
    ...
```

## Run locally

The `examples/` directories contain source modules, not standalone Function App projects.
To run locally, copy the example into a project directory with the required `host.json`:

```bash
mkdir -p my-webhook-app
cp examples/webhook_receiver/function_app.py my-webhook-app/
cat > my-webhook-app/host.json << 'EOF'
{
  "version": "2.0",
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
EOF

cd my-webhook-app
python -m venv .venv
source .venv/bin/activate
pip install azure-functions azure-functions-openapi pydantic
func start
```

## Test with `curl`

### Success case

```bash
curl -X POST "http://localhost:7071/api/webhooks/orders" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"order.completed","source":"shopify","occurred_at":"2026-04-12T00:00:00+00:00","data":{"order_id":"12345"}}'
```

Expected output (status 202):

```json
{"delivery_id":"dlv_abc123def456","status":"accepted","received_at":"2026-04-12T00:00:01+00:00"}
```

### With HMAC signature

Set the `WEBHOOK_SECRET` environment variable, then include the signature headers:

```bash
curl -X POST "http://localhost:7071/api/webhooks/orders" \
  -H "Content-Type: application/json" \
  -H "X-Signature: sha256=<computed_hmac>" \
  -H "X-Webhook-Timestamp: 2026-04-12T00:00:00+00:00" \
  -H "X-Delivery-Id: dlv-unique-001" \
  -d '{"event_type":"order.completed","source":"shopify","occurred_at":"2026-04-12T00:00:00+00:00"}'
```

### Error case — missing required fields

```bash
curl -X POST "http://localhost:7071/api/webhooks/orders" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"order.completed"}'
```

Expected output (status 400):

```json
{"error": "event_type and source are required"}
```

## Inspect generated spec

JSON:

```bash
curl "http://localhost:7071/api/openapi.json"
```

YAML:

```bash
curl "http://localhost:7071/api/openapi.yaml"
```

You should see one path for `/api/webhooks/orders` with:

- tag `webhooks`
- `WebhookEvent` request schema
- `WebhookAcceptedResponse` response schema
- `202`, `400`, `401`, `409` response codes

## Open Swagger UI

Open `http://localhost:7071/api/docs` in your browser.

Expected behavior:

- the `receive_order_webhook` operation appears
- request body editor shows `WebhookEvent` fields
- `Try it out` sends request to your local function app

## Production takeaways

- Always verify webhook signatures when accepting external events
- Use delivery ID deduplication to handle retries safely
- Reject stale timestamps to prevent replay attacks
- Return `202 Accepted` (not `200 OK`) for async processing

## Next example

See [Report Jobs Example](report_jobs.md) for a multi-endpoint API with Bearer auth and async job polling.

## Related docs

- [Usage](../usage.md)
- [Configuration](../configuration.md)
- [FAQ](../faq.md)
- [Troubleshooting](../troubleshooting.md)
