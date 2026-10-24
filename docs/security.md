# Security Guide

The canonical security policy is maintained in the root [SECURITY.md](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/SECURITY.md).

## Protecting documentation routes

OpenAPI JSON/YAML and Swagger UI are ordinary HTTP-triggered functions. A route
registered with `auth_level=func.AuthLevel.ANONYMOUS` is public after deployment
unless another platform layer restricts it. The specification reveals endpoint
shapes, request and response schemas, and security scheme names, so anonymous
documentation is a convenient local-development choice but should be deliberate
in production.

OpenAPI `security` declarations and `security_schemes` describe how clients
authenticate to documented API operations. They **do not** protect the
`openapi.json`, `openapi.yaml`, or `docs` routes that serve the specification and
UI. Protect those HTTP routes separately with one of these patterns.

### 1. Omit documentation routes in production

Azure Functions registers decorators when `function_app.py` is imported. Put
the route definitions behind an app setting so no documentation functions are
registered unless the setting is explicitly enabled:

```python
import os

import azure.functions as func

from azure_functions_openapi import get_openapi_json, get_openapi_yaml, render_swagger_ui

app = func.FunctionApp()

if os.getenv("ENABLE_API_DOCS") == "true":

    @app.route(route="openapi.json", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def openapi_json(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse(
            get_openapi_json(title="My API", app=app),
            mimetype="application/json",
        )

    @app.route(route="openapi.yaml", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def openapi_yaml(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse(
            get_openapi_yaml(title="My API", app=app),
            mimetype="application/x-yaml",
        )

    @app.route(route="docs", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
        return render_swagger_ui(openapi_url="/api/openapi.json")
```

Set `ENABLE_API_DOCS=true` only in environments where these routes should
exist. Any other value, including an unset setting, omits them at import time.

### 2. Protect documentation with an Azure Functions key

When key-protected documentation is required, explicitly select header forwarding:

```python
from azure_functions_openapi import register_openapi_routes

register_openapi_routes(
    app,
    title="My API",
    version="1.0.0",
    auth_level=func.AuthLevel.FUNCTION,
    docs_key_forwarding="header",
)
```

Navigate to `/api/docs?code=<key-authorized-for-both-functions>`. The server
does **not** echo that query value into the served HTML/JavaScript or the
configured specification URL. The browser reads the key from its own page URL,
immediately removes all `code` values with `history.replaceState` (preserving
other parameters and the fragment), and sends it as `x-functions-key` **only**
on Swagger UI's same-origin specification download. The specification request
URL contains no forwarded key. Try-it-out operations, cross-origin URLs,
protocol-relative URLs, and absolute HTTPS specification URLs never receive
this page key. Without a page key, no header is added.
When the key header is attached, the specification fetch uses `redirect: 'error'`:
any redirect fails closed with Swagger UI's normal specification-load error,
without requesting the redirect destination, even on the same origin.

**Limits:** the initial documentation navigation still contains `?code=` until
the script runs. Server/proxy/access logs and browser history before replacement
may record it; `replaceState` cannot erase earlier copies. The key also remains
in browser memory for the page lifetime. In particular,
`performance.getEntriesByType("navigation")[0].name` retains the original
`?code=` navigation URL after `history.replaceState`; cleaning the address bar
does not clear this page-lifetime navigation-timing entry. A function-scoped key authorizes only
its own function: use a host key or a key valid for both the docs and JSON
functions, not merely the docs function's key. Do not use a master key for
routine documentation access. Prefer edge authentication (pattern 3) in production.
Core Tools does not enforce function-key authentication locally, so a local
successful request proves neither key validity nor enforcement on Azure.

For direct JSON/YAML downloads, send an `x-functions-key` header. The low-level
renderer can opt in with `render_swagger_ui(forward_page_key_header=True)`;
it cannot read or forward a header from the initial page request.

**Migration:** `docs_key_forwarding=None` currently retains legacy query forwarding
and emits a `DeprecationWarning` once per protected registration. Silence it by
choosing `"header"` explicitly (recommended), or `"none"` for edge-authenticated
or intentionally anonymous specifications. Explicit `"query"` retains the old
key-in-HTML/spec-URL exposure and is only a compatibility escape hatch. The
default will change to `"header"` in a future minor release before 1.0.
Anonymous registrations never forward a page key, in any mode.

### 3. Enforce access at the platform edge

For identity-aware or policy-based access, keep the documentation endpoints
behind Azure API Management, Microsoft Entra ID through App Service
Authentication (Easy Auth), or equivalent ingress controls. Configure the edge
to require the intended identity or policy for `/api/docs`,
`/api/openapi.json`, and `/api/openapi.yaml`, and prevent a direct Function App
URL from bypassing that control (for example, with access restrictions or
private networking).

### Swagger UI Try-it-out behavior

**Local demonstration versus production:** the default anonymous documentation
registration and enabled Try-it-out are development conveniences, not production
access controls. Make production exposure deliberate using patterns 1–3 above,
and authenticate API operations independently of documentation access.

`render_swagger_ui()` enables Try-it-out and allows all supported submit methods:
`GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD`, and `OPTIONS`. Anyone who can
open the UI can therefore initiate browser-originated calls to documented API
operations. API authentication always applies. CORS applies only to
cross-origin requests and is not access control: when Swagger UI and the API
share the Function App origin, Try-it-out is same-origin and no CORS check is
performed. Exposing Swagger UI does not bypass API authentication, but a CORS
policy must not be relied on to restrict who can call the API.

#### Operation ID Sanitization

Operation IDs are sanitized to:
- Remove dangerous characters
- Keep only alphanumeric characters and underscores
- Ensure they start with a letter (prefixed with `op_` if needed)

#### Parameter Validation

Parameters are validated to ensure:
- Required fields (`name`, `in`) are present
- Each parameter is a valid dictionary
- Parameter structure follows OpenAPI specification

#### Tag Validation

Tags are validated to:
- Ensure they are strings
- Remove whitespace
- Prevent empty tags

### Caching

Caching should be handled at the application or platform level. Per-request generation is acceptable for a small registry or an infrequently requested documentation endpoint. For a larger registry or a frequently requested endpoint, generate the serialized spec after imports complete (or on the first request), store it in a module global, and return that immutable string on later requests. Invalidate it only if the application deliberately registers operations after import. The library does not cache because it cannot know when an application's registry is complete.

```python
_OPENAPI_JSON = get_openapi_json(title="Sample API", app=app)


def openapi_json(req):
    return func.HttpResponse(_OPENAPI_JSON, mimetype="application/json")
```

Use platform response caching only when its access controls and invalidation policy match the sensitivity of the generated document. See [Architecture](architecture.md#spec-generation-performance-budgets) for measured costs and regression budgets.

## Security Best Practices

### For Developers

1. **Always validate input**: Use the built-in validation functions
2. **Sanitize user data**: Let the library handle sanitization
3. **Use HTTPS**: Ensure your Azure Functions use HTTPS
4. **Monitor logs**: Check error logs for security issues
5. **Keep dependencies updated**: Regularly update the library

### For Deployment

1. **Environment Variables**: Use secure environment variables for configuration
2. **Network Security**: Configure proper network security groups
3. **Access Control**: Implement proper authentication and authorization
4. **Regular Updates**: Keep the runtime and dependencies updated

### For API Design

1. **Minimal Information**: Don't expose sensitive information in OpenAPI specs
2. **Proper Authentication**: Document authentication requirements
3. **Rate Limiting**: Implement rate limiting for your APIs
4. **Input Validation**: Validate all inputs at the application level
5. **Error Messages**: Don't expose internal details in error messages

## Security Configuration

### Custom CSP Policy

You can provide a custom CSP policy:

```python
from azure_functions_openapi.swagger_ui import render_swagger_ui

custom_csp = (
    "default-src 'self'; script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; connect-src 'self'"
)
response = render_swagger_ui(custom_csp=custom_csp)
```

Keep `{nonce}` in `script-src` so the renderer's inline scripts can run. The
placeholder is replaced consistently in the response header and HTML-escaped
meta tag. The default policy permits only same-origin spec/API connections.

### Security Headers

Security headers are automatically added to all responses. You can customize them by modifying the `render_swagger_ui` function.


### Logging

Security events are logged with appropriate levels:
- `INFO`: Normal operations
- `WARNING`: Security warnings (e.g., invalid input)
- `ERROR`: Security errors (e.g., validation failures)

## Security Automation

### CI/CD Scanning

The repository uses automated security scanning:

- Bandit for Python static analysis
- Semgrep for broader rule coverage

Security scans run in GitHub Actions via `.github/workflows/security.yml`.
For local parity, run `make security`.
- Dependabot for dependency updates

### SBOM Generation

Software Bill of Materials (SBOM) generation is supported via CI workflows to
track dependency inventory and reduce supply chain risk.

## Security Headers Validation

Validate that security headers are present on Swagger UI responses:

- `X-Content-Type-Options`
- `X-Frame-Options`
- `Referrer-Policy`
- `Content-Security-Policy`

Automated checks should be included in tests or smoke checks for deployments.

## Data Privacy and Compliance

When processing user data:

- Avoid storing sensitive data in logs
- Minimize data collection and retention
- Use encryption in transit and at rest
- Follow applicable privacy regulations for your region

## Incident Response

Follow your organization's standard security runbooks for incidents and disclosures.

## Reporting Security Issues

If you discover a security vulnerability, please:

1. **Do not** create a public issue
2. Email security concerns to: yeongseon.choe@gmail.com
3. Include detailed information about the vulnerability
4. Allow time for the issue to be addressed before disclosure

## Security Updates

Security updates are released as:
- **Patch versions** (e.g., 1.0.1) for critical security fixes
- **Minor versions** (e.g., 1.1.0) for security improvements
- **Major versions** (e.g., 2.0.0) for breaking security changes

Always update to the latest version to ensure you have the latest security fixes.
