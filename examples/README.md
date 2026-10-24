# Examples

## Local-only security defaults

These runnable examples use anonymous routes for local demonstration. Their OpenAPI
security declarations are documentation, not an authentication gateway. Do not deploy
unchanged to production: configure real authentication, network restrictions and secrets
through your deployment environment. In particular, webhook signature checking is optional
when `WEBHOOK_SECRET` is unset, example bearer checks are not a production identity provider,
and the partner purge example checks only that `X-API-Key` is present, not its identity.

`e2e_app/` is the exception to local-only hosting: CI deploys it temporarily to Azure
for certification with synthetic data, anonymous warmup/test/docs routes, and resource-group
cleanup. Keep its public reachability for certification, not as a production default.

`azure-functions-openapi` ships five smoke-tested examples:

| Role | Path | Description |
| --- | --- | --- |
| Representative | `examples/webhook_receiver` | Webhook intake with HMAC-SHA256 signature verification. Shows `@openapi()` basics: `summary`, `description`, `tags`, `requests`, and `responses`. |
| Complex | `examples/report_jobs` | Async report generation with Bearer auth. Shows `security`, `security_scheme`, `OPENAPI_VERSION_3_1`, `generate_openapi_spec()`, `render_swagger_ui(custom_csp=..., enable_client_logging=True)`. |
| Integration | `examples/notification_request` | Email notification with `@openapi` + `@validate_http` stacked. Shows `requests=`, `responses=` unified params and shared Pydantic models. |
| Inference | `examples/inference_cookbook` | Minimal API documented from a Pydantic return annotation and an opt-in handler docstring. |
| Bridge | `examples/partner_import_bridge` | Partner data import with `scan_endpoint_metadata(app)`, `register_openapi_metadata()`, `OpenAPIOperationMetadata`, and `request_body_required`. |
