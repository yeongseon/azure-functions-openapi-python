from __future__ import annotations

import html
import logging
import re
from unittest.mock import patch

import pytest

from azure_functions_openapi.swagger_ui import (
    _redact_query_for_logging,
    _sanitize_url,
    render_swagger_ui,
)


@pytest.mark.parametrize("custom_csp", [None, "default-src 'self'; script-src 'nonce-{nonce}'"])
def test_header_script_uses_nonce_and_spec_only_guard(custom_csp: str | None) -> None:
    # Given / When
    response = render_swagger_ui(custom_csp=custom_csp, forward_page_key_header=True)
    body = response.get_body().decode()
    # Then
    nonces = re.findall(r'<script nonce="([^"]+)">', body)
    assert nonces and len(set(nonces)) == 1
    policy = response.headers["Content-Security-Policy"]
    assert f"'nonce-{nonces[0]}'" in policy
    assert html.escape(policy, quote=True) in body
    assert "{nonce}" not in body
    assert "history.replaceState" in body
    assert body.index("history.replaceState") < body.index("swagger-ui-bundle.js")
    assert "request.loadSpec === true" in body
    assert "requestUrl.origin === window.location.origin" in body
    assert "requestUrl.href === specUrl.href" in body
    assert "request.headers['x-functions-key'] = pageKey" in body
    assert "request.redirect = 'error'" in body
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "console.log"):
        assert forbidden not in body


def test_header_opt_out_preserves_legacy_html_byte_for_byte() -> None:
    # Given: fixed per-response nonce makes byte comparison meaningful.
    with patch("azure_functions_openapi.swagger_ui.secrets.token_urlsafe", return_value="nonce"):
        original = render_swagger_ui().get_body()
        # When
        explicit = render_swagger_ui(forward_page_key_header=False).get_body()
    # Then
    assert explicit == original
    assert b"history.replaceState" not in explicit
    assert b"x-functions-key" not in explicit


@pytest.mark.parametrize("url", ["//evil.example/x", "///evil.example/x?code=CANARY_KEY_9f3a"])
def test_protocol_relative_url_is_rejected_without_query_logging(
    url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given
    caplog.set_level(logging.DEBUG, logger="azure_functions_openapi")
    # When
    result = _sanitize_url(url)
    # Then
    assert result == "/api/openapi.json"
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert "CANARY_KEY_9f3a" not in caplog.text


def test_absolute_https_spec_is_allowed_but_not_key_forwardable() -> None:
    # Given / When
    body = (
        render_swagger_ui(
            openapi_url="https://other.example/openapi.json",
            forward_page_key_header=True,
        )
        .get_body()
        .decode()
    )
    # Then
    assert 'url: "https://other.example/openapi.json"' in body
    assert "const specKeyForwardingAllowed = false" in body


@pytest.mark.parametrize(
    "url", ['/api/spec"?code=CANARY', "/api/spec\\?code=CANARY", "/api/<x>?code=CANARY"]
)
def test_rejected_url_payload_is_not_in_script(url: str) -> None:
    # Given / When
    body = render_swagger_ui(openapi_url=url, forward_page_key_header=True).get_body().decode()
    # Then
    assert 'url: "/api/openapi.json"' in body
    assert "CANARY" not in body


@pytest.mark.parametrize(
    "url", ["https://[broken", "/api/" + "a" * 100000 + "?code=CANARY"], ids=["malformed", "huge"]
)
def test_malformed_and_huge_urls_remain_json_encoded_and_query_redacted(
    url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given
    caplog.set_level(logging.DEBUG, logger="azure_functions_openapi")
    # When
    body = (
        render_swagger_ui(
            openapi_url=url, title="</title><script>\"'&", forward_page_key_header=True
        )
        .get_body()
        .decode()
    )
    # Then: no new URL-length policy; preserve existing valid-character behavior.
    assert f'url: "{url}"' in body
    assert "&lt;/title&gt;&lt;script&gt;&quot;&#x27;&amp;" in body
    assert "CANARY" not in caplog.text
    assert _redact_query_for_logging(url) == url.split("?")[0]


def test_render_log_contains_only_query_redacted_path(caplog: pytest.LogCaptureFixture) -> None:
    # Given
    caplog.set_level(logging.DEBUG, logger="azure_functions_openapi")
    # When
    render_swagger_ui(openapi_url="/api/openapi.json?code=CANARY&code=SECOND#fragment")
    # Then
    assert len(caplog.records) == 1
    assert caplog.records[0].getMessage().endswith("/api/openapi.json")
    assert _redact_query_for_logging("/api/spec?code=CANARY&code=SECOND#fragment") == "/api/spec"
