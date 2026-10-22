from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser

import pytest

from azure_functions_openapi import swagger_ui
from tools.browser_integrity import compare_asset
from tools.security_report import Status


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"link", "script"} and "integrity" in values:
            self.assets.append(values)


def test_pinned_browser_assets_have_valid_integrity_and_crossorigin() -> None:
    # Given imported production constants; When HTML is rendered; Then both assets enforce SRI.
    parser = AssetParser()
    parser.feed(swagger_ui.render_swagger_ui().get_body().decode())
    assert swagger_ui._SWAGGER_UI_CDN_BASE == (
        "https://cdn.jsdelivr.net/npm/swagger-ui-dist@" + swagger_ui._SWAGGER_UI_DIST_VERSION
    )
    assert len(parser.assets) == 2
    for asset, digest in zip(
        parser.assets,
        [swagger_ui._SWAGGER_UI_CSS_SRI, swagger_ui._SWAGGER_UI_BUNDLE_SRI],
        strict=True,
    ):
        assert digest.startswith("sha384-")
        assert len(base64.b64decode(digest.removeprefix("sha384-"), validate=True)) == 48
        assert asset["integrity"] == digest
        assert asset["crossorigin"] == "anonymous"
        assert (asset.get("src") or asset.get("href") or "").startswith(
            swagger_ui._SWAGGER_UI_CDN_BASE + "/"
        )


@pytest.mark.parametrize(
    "body,expected",
    [(b"asset", Status.PASS), (b"modified", Status.FAIL), (None, Status.TOOL_ERROR)],
)
def test_asset_comparison_distinguishes_mismatch_from_outage(
    body: bytes | None, expected: Status
) -> None:
    # Given a pinned digest; When bytes or a network failure arrive; Then classify distinctly.
    digest = "sha384-" + base64.b64encode(hashlib.sha384(b"asset").digest()).decode()
    assert compare_asset(body, digest) == expected
