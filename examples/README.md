# Examples

`azure-functions-openapi` ships four smoke-tested examples:

| Role | Path | Description |
| --- | --- | --- |
| Representative | `examples/webhook_receiver` | Webhook intake with HMAC-SHA256 signature verification. Shows `@openapi()` basics: `summary`, `description`, `tags`, `request_model`, `response_model`, `response`. |
| Complex | `examples/report_jobs` | Async report generation with Bearer auth. Shows `security`, `security_scheme`, `OPENAPI_VERSION_3_1`, `generate_openapi_spec()`, `render_swagger_ui(custom_csp=..., enable_client_logging=True)`. |
| Integration | `examples/notification_request` | Email notification with `@openapi` + `@validate_http` stacked. Shows `requests=`, `responses=` unified params and shared Pydantic models. |
| Bridge | `examples/partner_import_bridge` | Partner data import with `scan_endpoint_metadata(app)`, `register_openapi_metadata()`, `OpenAPIOperationMetadata`, and `request_body_required`. |
