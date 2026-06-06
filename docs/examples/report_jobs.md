# Report Jobs Example

This is the complex example demonstrating a multi-endpoint API with Bearer token
authentication and an async job pattern: submit a report, poll its status, and
download the result.

Source: `examples/report_jobs/function_app.py`

## What this example includes

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/reports` | Submit a report job |
| `GET` | `/api/reports/{job_id}/status` | Poll job status |
| `GET` | `/api/reports/{job_id}/download` | Download completed report |
| `GET` | `/api/openapi.json` | OpenAPI JSON |
| `GET` | `/api/openapi.yaml` | OpenAPI YAML (3.1) |
| `GET` | `/api/docs` | Swagger UI |

## Features demonstrated

- `@openapi()` with `security` and `security_scheme` (Bearer token)
- Path parameters (`{job_id}`)
- `generate_openapi_spec()` with `OPENAPI_VERSION_3_1`
- `render_swagger_ui()` with `custom_csp` and `enable_client_logging=True`
- `request_model` and `response_model`
- Multiple response codes per endpoint (200, 202, 400, 401, 404)

## Data models

```python
class ReportFormat(str, Enum):
    csv = "csv"
    pdf = "pdf"
    xlsx = "xlsx"


class ReportRequest(BaseModel):
    report_type: str = Field(..., description="Report type, e.g. 'monthly_sales'.")
    date_from: str = Field(..., description="Start date (ISO-8601).")
    date_to: str = Field(..., description="End date (ISO-8601).")
    format: ReportFormat = Field(default=ReportFormat.csv, description="Output format.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional filters.")


class ReportJobResponse(BaseModel):
    job_id: str = Field(..., description="Unique job identifier.")
    status: str = Field(default="queued", description="Job status.")
    created_at: str = Field(..., description="ISO-8601 timestamp.")


class ReportStatusResponse(BaseModel):
    job_id: str
    status: str = Field(..., description="One of: queued, processing, completed, failed.")
    progress_pct: int = Field(default=0, description="Progress percentage (0-100).")
    download_url: str | None = Field(default=None, description="Available when status=completed.")
    error: str | None = Field(default=None, description="Error message when status=failed.")
```

## How the docs are configured

Security is declared once and reused across all endpoints:

```python
_BEARER_SCHEME = {
    "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "API key or JWT token",
    }
}
_BEARER_SECURITY = [{"BearerAuth": []}]


@openapi(
    route="/api/reports",
    method="post",
    summary="Submit a report job",
    description="Queue a new report generation job. Returns a job ID for status polling.",
    tags=["reports"],
    request_model=ReportRequest,
    response_model=ReportJobResponse,
    response={
        202: {"description": "Report job queued"},
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
    },
    security=_BEARER_SECURITY,
    security_scheme=_BEARER_SCHEME,
    )
@app.route(route="reports", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def submit_report(req: func.HttpRequest) -> func.HttpResponse:
    ...
```

The OpenAPI YAML route uses `generate_openapi_spec()` with `OPENAPI_VERSION_3_1`:

```python
from azure_functions_openapi import OPENAPI_VERSION_3_1, generate_openapi_spec

spec = generate_openapi_spec(
    title="Report Jobs API",
    version="1.0.0",
    openapi_version=OPENAPI_VERSION_3_1,
)
```

The Swagger UI route uses `custom_csp` and `enable_client_logging`:

```python
render_swagger_ui(
    title="Report Jobs API",
    custom_csp=(
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https:; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self'"
    ),
    enable_client_logging=True,
)
```

## Run locally

The `examples/` directories contain source modules, not standalone Function App projects.
To run locally, copy the example into a project directory with the required `host.json`:

```bash
mkdir -p my-report-app
cp examples/report_jobs/function_app.py my-report-app/
cat > my-report-app/host.json << 'EOF'
{
  "version": "2.0",
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
EOF

cd my-report-app
python -m venv .venv
source .venv/bin/activate
pip install azure-functions azure-functions-openapi pydantic pyyaml
func start
```

## Test with `curl`

### 1) Submit a report job

```bash
curl -X POST "http://localhost:7071/api/reports" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-token-123" \
  -d '{"report_type":"monthly_sales","date_from":"2026-01-01","date_to":"2026-01-31","format":"csv"}'
```

Expected output (status 202):

```json
{"job_id":"rpt_abc123def456","status":"queued","created_at":"2026-04-12T00:00:00+00:00"}
```

### 2) Poll status

```bash
curl "http://localhost:7071/api/reports/rpt_abc123def456/status" \
  -H "Authorization: Bearer test-token-123"
```

Expected output:

```json
{"job_id":"rpt_abc123def456","status":"queued","progress_pct":0,"download_url":null,"error":null}
```

### 3) Download (when completed)

```bash
curl "http://localhost:7071/api/reports/rpt_abc123def456/download" \
  -H "Authorization: Bearer test-token-123"
```

### 4) Unauthorized request

```bash
curl -X POST "http://localhost:7071/api/reports" \
  -H "Content-Type: application/json" \
  -d '{"report_type":"monthly_sales","date_from":"2026-01-01","date_to":"2026-01-31"}'
```

Expected output (status 401):

```json
{"error": "Missing or invalid Authorization header"}
```

## Inspect generated spec

```bash
curl "http://localhost:7071/api/openapi.json"
```

You should see:

- three paths under `reports` tag
- `securitySchemes.BearerAuth` in `components`
- `security` requirement on all three operations
- `ReportRequest`, `ReportJobResponse`, `ReportStatusResponse` schemas

## Open Swagger UI

Open `http://localhost:7071/api/docs` in your browser.

Expected behavior:

- all `reports` operations grouped under one tag
- `Authorize` button for Bearer token input
- request body editor for `POST /api/reports`
- path parameter field for `{job_id}`

## Production takeaways

- Use `security_scheme` to declare auth requirements in the generated spec
- Validate tokens in handler code (the spec only documents the requirement)
- Return `202` for async jobs and provide a status polling endpoint
- Use `generate_openapi_spec()` when you need fine-grained control over spec output

## Next example

See [Notification Request Example](notification_request.md) for combining `@openapi` with `@validate_http` on the same handler.

## Related docs

- [Usage](../usage.md)
- [Configuration](../configuration.md)
- [FAQ](../faq.md)
- [Troubleshooting](../troubleshooting.md)
