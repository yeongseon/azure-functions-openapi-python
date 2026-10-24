from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from azure_functions_openapi.swagger_ui import render_swagger_ui


@pytest.mark.browser
@pytest.mark.parametrize(
    "custom_csp", [None, "default-src 'self'; script-src 'nonce-{nonce}'; connect-src 'self'"]
)
def test_page_key_forwarding_in_chromium(custom_csp: str | None) -> None:
    # Given: use the already-cached demo toolchain; never download a test dependency.
    node = shutil.which("node")
    packages = (Path.home() / ".npm/_npx").glob("*/node_modules/playwright/package.json")
    package = next(
        (p.parent for p in packages if json.loads(p.read_text())["version"] == "1.54.1"), None
    )
    if node is None or package is None:
        pytest.skip(
            "Node and cached Playwright 1.54.1 are required for offline browser verification"
        )
    assert node is not None and package is not None
    response = render_swagger_ui(custom_csp=custom_csp, forward_page_key_header=True)
    payload = json.dumps({"html": response.get_body().decode(), "headers": dict(response.headers)})
    environment = dict(os.environ)
    executable = Path.home() / ".cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
    if executable.exists():
        environment.setdefault("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", str(executable))
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
    if result.returncode == 77:
        pytest.skip("Cached Playwright Chromium is unavailable: " + result.stderr.strip())
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
def test_real_swagger_bundle_rejects_key_bearing_redirects(scenario: str, status: int) -> None:
    # Given: real, SRI-enforced CDN assets and permissive cross-origin policy where needed.
    node = shutil.which("node")
    packages = (Path.home() / ".npm/_npx").glob("*/node_modules/playwright/package.json")
    package = next(
        (p.parent for p in packages if json.loads(p.read_text())["version"] == "1.54.1"), None
    )
    if node is None or package is None:
        pytest.skip("Node and cached Playwright 1.54.1 are required")
    executable = Path.home() / ".cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
    environment = dict(os.environ)
    if executable.exists():
        environment.setdefault("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", str(executable))
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
    if result.returncode == 77:
        pytest.skip(result.stderr.strip())
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
