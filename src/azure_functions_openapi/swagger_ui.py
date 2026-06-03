from __future__ import annotations

import html
import json
import logging
import re
import secrets

from azure.functions import HttpResponse

logger = logging.getLogger(__name__)

# Pinned to avoid supply-chain drift from the unpinned `latest` tag on jsDelivr.
# Bump intentionally; verify releases at https://github.com/swagger-api/swagger-ui/releases.
_SWAGGER_UI_DIST_VERSION = "5.32.4"
_SWAGGER_UI_CDN_BASE = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{_SWAGGER_UI_DIST_VERSION}"


def render_swagger_ui(
    title: str = "API Documentation",
    openapi_url: str = "/api/openapi.json",
    custom_csp: str | None = None,
    enable_client_logging: bool = False,
) -> HttpResponse:
    """
    Render Swagger UI with enhanced security headers and CSP protection.

    Parameters:
        title: Page title for the Swagger UI
        openapi_url: URL to the OpenAPI specification
        custom_csp: Custom Content Security Policy (optional)
        enable_client_logging: Whether to enable browser-side response logging

    Returns:
        HttpResponse with Swagger UI HTML and security headers
    """
    nonce = secrets.token_urlsafe(16)

    # Enhanced CSP policy for better security
    default_csp = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https:; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    csp_policy = custom_csp or default_csp

    # Validate and sanitize inputs
    sanitized_title = _sanitize_html_content(title)
    sanitized_url = _sanitize_url(openapi_url)

    # Escape for safe embedding in HTML attributes and JS string literals
    safe_title = html.escape(sanitized_title, quote=True)
    safe_csp = html.escape(csp_policy, quote=True)
    safe_url_js = json.dumps(sanitized_url)  # produces "..." with proper escaping

    response_interceptor = """
            responseInterceptor: function(response) {
              return response;
            }
    """
    if enable_client_logging:
        response_interceptor = """
            responseInterceptor: function(response) {
              console.log('API Response:', response.status, response.url);
              return response;
            }
    """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta http-equiv="Content-Security-Policy" content="{safe_csp}">
        <meta http-equiv="X-Content-Type-Options" content="nosniff">
        <meta http-equiv="X-Frame-Options" content="DENY">
        <meta http-equiv="X-XSS-Protection" content="1; mode=block">
        <meta http-equiv="Referrer-Policy" content="strict-origin-when-cross-origin">
        <title>{safe_title}</title>
        <link rel="stylesheet"
              type="text/css"
              href="{_SWAGGER_UI_CDN_BASE}/swagger-ui.css" />
      </head>
      <body>
        <div id="swagger-ui"></div>
        <script src="{_SWAGGER_UI_CDN_BASE}/swagger-ui-bundle.js"></script>
        <script nonce="{nonce}">
          // Enhanced security configuration
          const ui = SwaggerUIBundle({{
            url: {safe_url_js},
            dom_id: '#swagger-ui',
            presets: [SwaggerUIBundle.presets.apis],
            layout: 'BaseLayout',
            validatorUrl: null,  // Disable external validator for security
            tryItOutEnabled: true,
            supportedSubmitMethods: ['get', 'post', 'put', 'delete', 'patch'],
            requestInterceptor: function(request) {{
              // Add security headers to requests
              request.headers['X-Requested-With'] = 'XMLHttpRequest';
              return request;
            }},
            {response_interceptor}
          }});
        </script>
      </body>
    </html>
    """

    # Create response with security headers
    response = HttpResponse(html_content, mimetype="text/html")

    # Add additional security headers
    headers = {
        "Content-Security-Policy": csp_policy,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    for header, value in headers.items():
        response.headers[header] = value

    logger.info(f"Swagger UI rendered with enhanced security headers for URL: {sanitized_url}")
    return response


def _sanitize_html_content(content: str) -> str:
    """Sanitize HTML content to prevent XSS attacks.

    Uses :func:`html.escape` for proper entity encoding (``&`` → ``&amp;``,
    ``<`` → ``&lt;``, etc.) instead of stripping characters, which avoids
    data loss for titles like "AT&T API".  Control characters are still
    stripped since they have no valid use in a page title.
    """
    if not content or not isinstance(content, str):
        return "API Documentation"

    # Strip control characters that have no place in a title
    sanitized = content.replace("\n", "").replace("\r", "").replace("\t", "")

    # Limit length before escaping so the cap applies to logical characters
    sanitized = sanitized[:100]

    # Proper HTML entity encoding
    return html.escape(sanitized, quote=True)


def _sanitize_url(url: str) -> str:
    """Sanitize URL to prevent injection attacks.

    Returns a safe root-relative path.  Any URL that does not match the
    allowed character set is replaced with the default ``/api/openapi.json``.
    """
    if not url or not isinstance(url, str):
        return "/api/openapi.json"

    # Block dangerous URI schemes and HTML event handlers
    dangerous_patterns = ["javascript:", "data:", "vbscript:", "<script", "onload="]
    for pattern in dangerous_patterns:
        if pattern.lower() in url.lower():
            logger.warning("Potentially dangerous URL pattern detected: %s", pattern)
            return "/api/openapi.json"

    # Ensure URL starts with /
    sanitized = url if url.startswith("/") else "/" + url

    # Whitelist: only allow characters safe in a URL path + query string.
    # This blocks quotes, backslashes, angle brackets, and other characters
    # that could break out of JS string literals or HTML attributes.
    if not re.match(r"^[a-zA-Z0-9/_\-.~:?#\[\]@!$&()*+,;=%]+$", sanitized):
        logger.warning("URL contains disallowed characters, falling back to default: %s", url)
        return "/api/openapi.json"

    return sanitized
