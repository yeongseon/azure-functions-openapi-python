# Security Guide

The canonical security policy is maintained in the root [SECURITY.md](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/SECURITY.md).

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

Caching should be handled at the application or platform level.

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

custom_csp = "default-src 'self'; script-src 'self'"
response = render_swagger_ui(custom_csp=custom_csp)
```

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
