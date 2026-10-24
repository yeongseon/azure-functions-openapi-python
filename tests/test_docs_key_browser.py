from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from azure_functions_openapi.swagger_ui import render_swagger_ui


@pytest.fixture
def browser_toolchain() -> tuple[str, Path]:
    node = shutil.which("node")
    package = Path(
        os.environ.get("PLAYWRIGHT_PACKAGE", ".cache/browser/node_modules/playwright")
    ).resolve()
    if node is None or not (package / "package.json").is_file():
        pytest.fail("Node and Playwright are required; run make browser-install", pytrace=False)
    return node, package


@pytest.mark.browser
@pytest.mark.parametrize(
    "custom_csp", [None, "default-src 'self'; script-src 'nonce-{nonce}'; connect-src 'self'"]
)
def test_page_key_forwarding_in_chromium(
    custom_csp: str | None, browser_toolchain: tuple[str, Path]
) -> None:
    # Given: explicitly installed toolchain; test execution never downloads dependencies.
    node, package = browser_toolchain
    response = render_swagger_ui(custom_csp=custom_csp, forward_page_key_header=True)
    payload = json.dumps({"html": response.get_body().decode(), "headers": dict(response.headers)})
    environment = dict(os.environ)
    local_browsers = Path(".cache/ms-playwright").resolve()
    if local_browsers.exists():
        environment["PLAYWRIGHT_BROWSERS_PATH"] = str(local_browsers)

    # When
    result = subprocess.run(
        [node, str(Path(__file__).with_name("docs_key_browser.cjs")), str(package)],
        input=payload,
        text=True,
        capture_output=True,
        timeout=60,
        env=environment,
    )

    # Then
    assert result.returncode == 0, result.stderr
    assert (
        "PASS: address redacted; spec header only; operation and cross-origin keys absent"
        in result.stdout
    )


@pytest.mark.browser
@pytest.mark.browser_cdn
@pytest.mark.parametrize(
    ("scenario", "status"),
    [
        ("normal", 200),
        ("same-origin", 302),
        ("cross-origin", 302),
        ("same-origin", 307),
        ("same-origin", 308),
        ("chain", 302),
    ],
)
def test_real_swagger_bundle_rejects_key_bearing_redirects(
    scenario: str, status: int, browser_toolchain: tuple[str, Path]
) -> None:
    # Given: real, SRI-enforced CDN assets and permissive cross-origin policy where needed.
    node, package = browser_toolchain
    environment = dict(os.environ)
    csp = None
    if scenario in {"cross-origin", "chain"}:
        csp = (
            "default-src 'self'; script-src 'nonce-{nonce}' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; connect-src *"
        )
    response = render_swagger_ui(custom_csp=csp, forward_page_key_header=True)
    payload = json.dumps(
        {
            "html": response.get_body().decode(),
            "headers": dict(response.headers),
            "scenario": scenario,
            "status": status,
        }
    )
    # When: Chromium executes the real bundle against actual local HTTP redirect responses.
    result = subprocess.run(
        [node, str(Path(__file__).with_name("docs_key_cdn_browser.cjs")), str(package)],
        input=payload,
        text=True,
        capture_output=True,
        timeout=90,
        env=environment,
    )
    # Then: transport logs and Swagger's UI must show fail-closed behavior (or normal success).
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
