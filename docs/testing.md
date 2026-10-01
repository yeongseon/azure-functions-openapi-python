# Testing Guide

This project targets **85%+ total coverage** for core modules.
Latest measured result (CI): **87%** (2026-02-09).

## Test Structure

```text
tests/
  test_decorator.py              # @openapi decorator registration and metadata
  test_decorator_enhanced.py     # Advanced decorator validation (security, models)
  test_openapi.py                # Core spec generation from registry
  test_openapi_3_1.py            # OpenAPI 3.1 specific output (nullable, examples)
  test_openapi_enhanced.py       # Edge cases in spec generation
  test_openapi_spec.py           # Full spec compilation tests
  test_swagger_ui.py             # Swagger UI rendering and security headers
  test_swagger_ui_enhanced.py    # CSP, sanitization, edge cases
  test_cli.py                    # CLI command parsing and generation
  test_utils.py                  # Schema conversion, route validation, sanitization
  test_utils_enhanced.py         # Additional utility edge cases
  test_hello_openapi_function_app.py  # Smoke test for webhook_receiver example
  test_todo_crud_example.py      # Smoke test for report_jobs example
  test_with_validation_example.py # Smoke test for notification_request example
```

## Running Tests

Run the full test suite:

```bash
make test
```

Run tests with coverage reporting:

```bash
make cov
```

Run a specific test file:

```bash
hatch run pytest tests/test_decorator.py -v
```

Run tests matching a keyword:

```bash
hatch run pytest -k "security" -v
```

## Coverage Policy

- CI runs tests on Python **3.10 through 3.14**.
- All matrix versions are **required** -- no allow-fail entries.
- Python 3.14 is treated as stable support, not preview.
- Coverage report is generated as `coverage.xml`.
- Codecov upload runs in CI for the Python 3.10 job.

### Coverage thresholds

| Module | Target |
| --- | --- |
| `decorator.py` | 90%+ |
| `openapi.py` | 85%+ |
| `swagger_ui.py` | 85%+ |
| `cli.py` | 80%+ |
| `utils.py` | 90%+ |

## Test Categories

### Decorator tests

Verify that `@openapi` correctly stores metadata in the global registry:

```python
def test_openapi_decorator_stores_summary():
    @openapi(summary="Test endpoint", route="/api/test")
    def my_func(req):
        pass

    registry = get_openapi_registry()
    assert registry["my_func"]["summary"] == "Test endpoint"
```

### Validation tests

Ensure invalid inputs raise `ValueError` with descriptive messages:

```python
def test_invalid_route_raises():
    with pytest.raises(ValueError, match="Invalid route path"):
        @openapi(summary="Bad", route="../../etc/passwd")
        def bad_route(req):
            pass
```

### Spec generation tests

Confirm that `generate_openapi_spec()` produces valid OpenAPI structures:

```python
def test_spec_contains_paths():
    @openapi(summary="Hello", route="/api/hello", method="get")
    def hello(req):
        pass

    spec = generate_openapi_spec(title="Test API")
    assert "/api/hello" in spec["paths"]
    assert "get" in spec["paths"]["/api/hello"]
```

### Pydantic model tests

Verify schema generation from Pydantic v2 models:

```python
class ItemResponse(BaseModel):
    id: int
    name: str

def test_response_model_schema():
    @openapi(
        summary="Get item",
        route="/api/items",
        method="get",
        responses=ItemResponse,
    )
    def get_item(req):
        pass

    spec = generate_openapi_spec()
    schema = spec["paths"]["/api/items"]["get"]["responses"]["200"]
    assert "content" in schema
    assert "application/json" in schema["content"]
```

### Security scheme tests

Validate that security requirements and scheme definitions appear in the output spec:

```python
def test_security_scheme_in_components():
    @openapi(
        summary="Protected",
        route="/api/protected",
        security=[{"BearerAuth": []}],
        security_scheme={
            "BearerAuth": {"type": "http", "scheme": "bearer"}
        },
    )
    def protected(req):
        pass

    spec = generate_openapi_spec()
    assert "securitySchemes" in spec["components"]
    assert "BearerAuth" in spec["components"]["securitySchemes"]
```

### Swagger UI tests

Confirm the HTML response includes security headers and CSP:

```python
def test_swagger_ui_has_csp():
    response = render_swagger_ui()
    assert response.headers["Content-Security-Policy"] is not None
    assert "X-Frame-Options" in response.headers
```

### CLI tests

Test command parsing and output format:

```python
def test_cli_generate_json(capsys):
    result = main(["generate", "--title", "CLI Test"])
    assert result == 0
    output = capsys.readouterr().out
    assert '"openapi"' in output
```

### Example smoke tests

Smoke tests import each example's `function_app.py` and verify that the app object
exists and the OpenAPI registry is populated:

```python
def test_webhook_receiver_example_registers_metadata():
    import importlib
    mod = importlib.import_module("examples.webhook_receiver.function_app")
    registry = get_openapi_registry()
    assert len(registry) > 0
```

## Adding New Tests

When adding a feature:

1. Write happy-path tests that verify correct output.
2. Write error tests that verify `ValueError` or `TypeError` is raised for invalid inputs.
3. Write regression tests for any bug fix.
4. Keep tests isolated -- each test should set up its own state.
5. Clear the OpenAPI registry between tests if necessary to avoid cross-contamination.

### Naming convention

```text
test_<module>_<scenario>
test_<module>_<scenario>_<expected_result>
```

Examples:

- `test_decorator_stores_tags`
- `test_openapi_invalid_version_raises`
- `test_swagger_ui_custom_csp_applied`

## Performance Considerations

- Tests should complete in under 10 seconds on CI.
- Avoid external network calls in tests -- mock Azure Functions SDK where needed.
- The OpenAPI registry is a global singleton; reset it in test fixtures when testing
  registration behavior.

## CI Integration

The CI workflow runs:

1. `make lint` -- Ruff linting
2. `make typecheck` -- mypy type checking
3. `make test` -- pytest with coverage
4. `make security` -- Bandit security scan

All four steps must pass for a PR to be mergeable. The matrix covers
Python 3.10, 3.11, 3.12, 3.13, and 3.14.

## Real Azure E2E Tests

The project includes a real Azure end-to-end test workflow that deploys an actual Function App to Azure and validates HTTP endpoints.

### Workflow

- **File**: `.github/workflows/e2e-azure.yml`
- **Trigger**: Manual (`workflow_dispatch`) or weekly schedule (Mondays 02:00 UTC)
- **Infrastructure**: Azure Consumption plan, `koreacentral` region
- **Cleanup**: Resource group deleted immediately after tests (`if: always()`)

### Running E2E Tests

```bash
gh workflow run e2e-azure.yml --ref main
```

### Required Secrets & Variables

| Name | Type | Description |
| --- | --- | --- |
| `AZURE_CLIENT_ID` | Secret | App Registration Client ID (OIDC) |
| `AZURE_TENANT_ID` | Secret | Azure Tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Secret | Azure Subscription ID |
| `AZURE_LOCATION` | Variable | Azure region (default: `koreacentral`) |

### Test Report

HTML test report is uploaded as a GitHub Actions artifact (retained 30 days).
