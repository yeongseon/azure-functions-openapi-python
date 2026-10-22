"""Verify the wheel's pinned browser assets without retaining downloaded source."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
from pathlib import Path
import subprocess

from azure_functions_openapi.swagger_ui import (
    _SWAGGER_UI_BUNDLE_SRI,
    _SWAGGER_UI_CDN_BASE,
    _SWAGGER_UI_CSS_SRI,
    _SWAGGER_UI_DIST_VERSION,
)
from tools.security_report import Check, Status, write_report


def compare_asset(body: bytes | None, expected: str) -> Status:
    if body is None:
        return Status.TOOL_ERROR
    actual = "sha384-" + base64.b64encode(hashlib.sha384(body).digest()).decode("ascii")
    return Status.PASS if hmac.compare_digest(actual, expected) else Status.FAIL


def verify_assets() -> list[Check]:
    checks: list[Check] = []
    for asset, digest in (
        ("swagger-ui.css", _SWAGGER_UI_CSS_SRI),
        ("swagger-ui-bundle.js", _SWAGGER_UI_BUNDLE_SRI),
    ):
        body: bytes | None = None
        code: int | None = None
        try:
            process = subprocess.run(
                [
                    "/usr/bin/curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--proto",
                    "=https",
                    "--max-time",
                    "60",
                    "--retry",
                    "2",
                    f"{_SWAGGER_UI_CDN_BASE}/{asset}",
                ],
                capture_output=True,
                check=False,
                timeout=200,
            )
            code = process.returncode
            body = process.stdout if code == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            code = None
        checks.append(
            Check(
                f"sri-{asset}",
                (asset,),
                compare_asset(body, digest),
                code,
                counts={"assets": int(body is not None)},
                tool_versions={"swagger-ui-dist": _SWAGGER_UI_DIST_VERSION, "hash": "sha384"},
                message="Network failure is TOOL_ERROR; received bytes with wrong hash are FAIL.",
            )
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("security-results"))
    return write_report(verify_assets(), parser.parse_args().output)


if __name__ == "__main__":
    raise SystemExit(main())
