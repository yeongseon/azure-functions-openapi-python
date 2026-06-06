# Notification Request Example

This is the integration example showing how to stack `@openapi` and `@validate_http`
on the same handler. Pydantic models are shared between both decorators so the
OpenAPI spec and runtime validation stay synchronized.

Source: `examples/notification_request/function_app.py`

## What this example includes

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/notifications/email` | Send email notification |
| `GET` | `/api/notifications/status` | Get notification delivery status |
| `GET` | `/api/openapi.json` | OpenAPI JSON |
| `GET` | `/api/openapi.yaml` | OpenAPI YAML |
| `GET` | `/api/docs` | Swagger UI |

## Features demonstrated

- `@openapi` and `@validate_http` stacked on the same handler
- `requests=` parameter for request model (unified param)
- `response_model=` for response schema
- `response` dict for multi-status documentation (202, 404, 422)
- Shared Pydantic models between OpenAPI and validation decorators

## Data models

```python
class EmailNotificationRequest(BaseModel):
    to: list[str] = Field(..., min_length=1, description="Recipient email addresses.")
    subject: str = Field(..., min_length=1, max_length=200, description="Email subject line.")
    body_text: str = Field(..., description="Plain-text email body.")
    body_html: str | None = Field(default=None, description="Optional HTML email body.")
    priority: str = Field(default="normal", description="Priority: low, normal, high.")


class NotificationAcceptedResponse(BaseModel):
    notification_id: str = Field(..., description="Unique notification identifier.")
    status: str = Field(default="queued", description="Processing status.")
    queued_at: str = Field(..., description="ISO-8601 timestamp.")


class NotificationStatusQuery(BaseModel):
    notification_id: str = Field(..., description="Notification ID to look up.")


class NotificationStatusResponse(BaseModel):
    notification_id: str
    status: str = Field(..., description="One of: queued, sending, delivered, failed.")
    delivered_at: str | None = Field(default=None, description="Delivery timestamp.")
```

## How the docs are configured

Both decorators share the same Pydantic model:

```python
@openapi(
    route="/api/notifications/email",
    method="post",
    summary="Send email notification",
    description="Validate and queue an email notification for delivery.",
    tags=["notifications"],
    requests=EmailNotificationRequest,
    response_model=NotificationAcceptedResponse,
    response={
        202: {"description": "Notification queued for delivery"},
        422: {"description": "Validation error"},
    },
    )
@app.route(route="notifications/email", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@validate_http(body=EmailNotificationRequest, response_model=NotificationAcceptedResponse)
def send_notification(
    req: func.HttpRequest, body: EmailNotificationRequest
) -> func.HttpResponse:
    ...
```

The status endpoint uses query parameter validation:

```python
@openapi(
    route="/api/notifications/status",
    method="get",
    summary="Get notification status",
    description="Look up the delivery status of a previously queued notification.",
    tags=["notifications"],
    parameters=[
        {
            "name": "notification_id",
            "in": "query",
            "required": True,
            "description": "Notification ID returned from the send endpoint.",
            "schema": {"type": "string"},
        }
    ],
    response_model=NotificationStatusResponse,
    response={
        200: {"description": "Notification status"},
        404: {"description": "Notification not found"},
    },
)
@validate_http(query=NotificationStatusQuery, response_model=NotificationStatusResponse)
def get_notification_status(
    req: func.HttpRequest, query: NotificationStatusQuery
) -> NotificationStatusResponse | func.HttpResponse:
    ...
```

## Run locally

The `examples/` directories contain source modules, not standalone Function App projects.
To run locally, copy the example into a project directory with the required `host.json`:

```bash
mkdir -p my-notification-app
cp examples/notification_request/function_app.py my-notification-app/
cat > my-notification-app/host.json << 'EOF'
{
  "version": "2.0",
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
EOF

cd my-notification-app
python -m venv .venv
source .venv/bin/activate
pip install azure-functions azure-functions-openapi azure-functions-validation pydantic
func start
```

## Test with `curl`

### 1) Send notification (valid)

```bash
curl -X POST "http://localhost:7071/api/notifications/email" \
  -H "Content-Type: application/json" \
  -d '{"to":["user@example.com"],"subject":"Test","body_text":"Hello from the API"}'
```

Expected output (status 202):

```json
{"notification_id":"ntf_abc123def456","status":"queued","queued_at":"2026-04-12T00:00:00+00:00"}
```

### 2) Send notification (invalid body)

```bash
curl -X POST "http://localhost:7071/api/notifications/email" \
  -H "Content-Type: application/json" \
  -d '{"to":[],"subject":""}'
```

Expected behavior:

- request fails validation
- response status `422` with validation error details

### 3) Get notification status

```bash
curl "http://localhost:7071/api/notifications/status?notification_id=ntf_abc123def456"
```

Expected output:

```json
{"notification_id":"ntf_abc123def456","status":"queued","delivered_at":null}
```

### 4) Get unknown notification

```bash
curl -i "http://localhost:7071/api/notifications/status?notification_id=ntf_unknown"
```

Expected status:

```text
HTTP/1.1 404 Not Found
```

## Inspect generated spec

```bash
curl "http://localhost:7071/api/openapi.json"
```

You should see:

- two operations under `notifications` tag
- `EmailNotificationRequest` and `NotificationAcceptedResponse` schemas
- query parameter `notification_id` on the status endpoint

## Open Swagger UI

Open `http://localhost:7071/api/docs` in your browser.

Expected behavior:

- `notifications` tag groups both operations
- request body editor for `POST /api/notifications/email`
- query parameter input for `notification_id`

## Production takeaways

- Stack `@openapi` and `@validate_http` on the same handler for synchronized docs and validation
- Use shared Pydantic models to prevent schema drift between spec and runtime
- Return explicit `func.HttpResponse` with `status_code=202` for async operations (bypasses `@validate_http` default 200)
- Add `422` response documentation for validation error paths

## Next example

See [Partner Import Bridge Example](partner_import_bridge.md) for auto-generating OpenAPI docs from `@validate_http` without `@openapi`.

## Related docs

- [Usage](../usage.md)
- [Configuration](../configuration.md)
- [FAQ](../faq.md)
- [Troubleshooting](../troubleshooting.md)
