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

# Subresource Integrity (SRI) hashes for the pinned CDN assets. The browser
# refuses to execute/apply a resource whose content does not match, so a CDN
# compromise or a repointed version tag cannot serve altered assets.
#
# Regenerate on every ``_SWAGGER_UI_DIST_VERSION`` bump, e.g.:
#   curl -sSL "$BASE/swagger-ui.css" | openssl dgst -sha384 -binary | openssl base64 -A
#   curl -sSL "$BASE/swagger-ui-bundle.js" | openssl dgst -sha384 -binary | openssl base64 -A
_SWAGGER_UI_CSS_SRI = "sha384-AHNbXeU7DPcgcihnwKYc3FOT0hTfhEwVFc2JRxxF5S/mplUdt/7G1g6nIblzENrX"
_SWAGGER_UI_BUNDLE_SRI = "sha384-FgJpbEfGqpFeiFJh0+HNvyohx84XMd+IwgPyxJxjuDFMHVYmoFqrDEJNrVFexwA0"


def render_swagger_ui(
    title: str = "API Documentation",
    openapi_url: str = "/api/openapi.json",
    custom_csp: str | None = None,
    enable_client_logging: bool = False,
    *,
    forward_page_key_header: bool = False,
) -> HttpResponse:
    """
    Render Swagger UI with enhanced security headers and CSP protection.

    Parameters:
        title: Page title for the Swagger UI
        openapi_url: URL to the OpenAPI specification
        custom_csp: Custom Content Security Policy (optional)
        enable_client_logging: Whether to enable browser-side response logging
        forward_page_key_header: Read and remove the page's code query in the browser,
            forwarding it only as a header on the same-origin spec download. Absolute
            HTTPS spec URLs are supported but never receive the page key.

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

    csp_policy = custom_csp.replace("{nonce}", nonce) if custom_csp else default_csp

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
              console.log('API Response:', response.status, response.url.split('?')[0]);
              return response;
            }
    """

    page_key_script = ""
    key_interceptor = ""
    if forward_page_key_header:
        allowed_js = json.dumps(sanitized_url.startswith("/") and not openapi_url.startswith("//"))
        page_key_script = f"""<script nonce="{nonce}">
          const pageQuery = new URLSearchParams(window.location.search);
          const pageKey = pageQuery.get('code');
          if (pageQuery.has('code')) {{
            const pageUrl = new URL(window.location.href);
            pageUrl.searchParams.delete('code');
            history.replaceState(history.state, '',
              pageUrl.pathname + pageUrl.search + pageUrl.hash);
          }}
          const specKeyForwardingAllowed = {allowed_js};
        </script>
        """
        key_interceptor = f"""
              if (pageKey && specKeyForwardingAllowed && request.loadSpec === true &&
                  !request.url.startsWith('//')) {{
                try {{
                  const specUrl = new URL({safe_url_js}, window.location.href);
                  const requestUrl = new URL(request.url, window.location.href);
                  if (requestUrl.origin === window.location.origin &&
                      requestUrl.href === specUrl.href) {{
                    request.headers['x-functions-key'] = pageKey;
                    request.redirect = 'error';
                  }}
                }} catch (error) {{
                  if (!(error instanceof TypeError)) throw error;
                }}
              }}"""

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta http-equiv="Content-Security-Policy" content="{safe_csp}">
        <meta http-equiv="X-Content-Type-Options" content="nosniff">
        <meta http-equiv="X-Frame-Options" content="DENY">
        <meta http-equiv="Referrer-Policy" content="strict-origin-when-cross-origin">
        <title>{safe_title}</title>
        <link rel="stylesheet"
              type="text/css"
              integrity="{_SWAGGER_UI_CSS_SRI}"
              crossorigin="anonymous"
              href="{_SWAGGER_UI_CDN_BASE}/swagger-ui.css" />
      </head>
      <body>
        <div id="swagger-ui"></div>
        {page_key_script}<script src="{_SWAGGER_UI_CDN_BASE}/swagger-ui-bundle.js"
                integrity="{_SWAGGER_UI_BUNDLE_SRI}"
                crossorigin="anonymous"></script>
        <script nonce="{nonce}">
          // Enhanced security configuration
          const ui = SwaggerUIBundle({{
            url: {safe_url_js},
            dom_id: '#swagger-ui',
            presets: [SwaggerUIBundle.presets.apis],
            layout: 'BaseLayout',
            validatorUrl: null,  // Disable external validator for security
            tryItOutEnabled: true,
            supportedSubmitMethods: ['get', 'post', 'put', 'delete', 'patch', 'head', 'options'],
            requestInterceptor: function(request) {{
              // Add security headers to requests
              request.headers['X-Requested-With'] = 'XMLHttpRequest';{key_interceptor}
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
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    for header, value in headers.items():
        response.headers[header] = value

    redacted_url = _redact_query_for_logging(sanitized_url)
    logger.info(f"Swagger UI rendered with enhanced security headers for URL: {redacted_url}")
    return response


def _redact_query_for_logging(url: str) -> str:
    """Strip the query string from ``url`` before it is written to a log.

    Protected documentation routes may forward an Azure Functions key as a
    ``?code=...`` query value so the browser can fetch the protected
    specification (see :mod:`azure_functions_openapi.docs_routes`). That key
    must reach the rendered page, but it must never be copied into
    application logs. Only the path portion is useful for diagnostics, so
    everything from the first ``?`` onward is dropped here. The *served* URL
    (used in the HTML/JS response) is unaffected — only the logged
    representation is redacted.
    """
    if not url or not isinstance(url, str):
        return url
    path, _sep, _query = url.partition("?")
    return path


def _sanitize_html_content(content: str) -> str:
    """Sanitize content for use in HTML contexts.

    Strips control characters and limits length.  Does **not** perform
    HTML entity encoding — callers are responsible for applying
    :func:`html.escape` in the appropriate context so there is no
    double-escaping.
    """
    if not content or not isinstance(content, str):
        return "API Documentation"

    # Strip control characters that have no place in a title
    sanitized = content.replace("\n", "").replace("\r", "").replace("\t", "")

    # Limit length
    return sanitized[:100]


def _sanitize_url(url: str) -> str:
    """Sanitize URL to prevent injection attacks.

    Returns a safe root-relative path or absolute HTTPS URL. Any URL that does
    not match the allowed character set is replaced with the default.
    """
    if not url or not isinstance(url, str):
        return "/api/openapi.json"

    if url.startswith("//"):
        logger.warning(
            "Protocol-relative specification URL rejected: %s", _redact_query_for_logging(url)
        )
        return "/api/openapi.json"

    # Block dangerous URI schemes and HTML event handlers
    dangerous_patterns = ["javascript:", "data:", "vbscript:", "<script", "onload="]
    for pattern in dangerous_patterns:
        if pattern.lower() in url.lower():
            logger.warning("Potentially dangerous URL pattern detected: %s", pattern)
            return "/api/openapi.json"

    sanitized = url if url.startswith(("/", "https://")) else "/" + url

    # Whitelist: only allow characters safe in a URL path + query string.
    # This blocks quotes, backslashes, angle brackets, and other characters
    # that could break out of JS string literals or HTML attributes.
    if not re.match(r"^[a-zA-Z0-9/_\-.~:?#\[\]@!$&()*+,;=%]+$", sanitized):
        logger.warning(
            "URL contains disallowed characters, falling back to default: %s",
            _redact_query_for_logging(url),
        )
        return "/api/openapi.json"

    return sanitized
