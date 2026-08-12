#!/usr/bin/env python3
"""Capture documentation screenshots from a deployed example app.

Run during the release e2e workflow while the Azure Functions app is still
live (before the resource group is torn down). Each screenshot listed in
``docs/assets/screenshots.yml`` that declares an ``output.route`` is rendered
with Playwright and written to the output directory using the same basename as
its manifest ``image``. A ``capture-metadata.json`` file records the package
version, git SHA, and capture date so the manifest can be refreshed after the
images are copied into ``docs/assets``.

Environment:
  E2E_BASE_URL  Base URL of the deployed app, e.g.
                https://af-e2e-openapi-123.azurewebsites.net

Usage:
  python scripts/capture_screenshots.py --out capture-out
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - dependency guard
    sys.stderr.write("error: PyYAML is required (pip install pyyaml)\n")
    raise SystemExit(1) from None

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - dependency guard
    sys.stderr.write("error: Playwright is required (pip install playwright)\n")
    raise SystemExit(1) from None

MANIFEST_REL = "docs/assets/screenshots.yml"
VIEWPORT = {"width": 1440, "height": 900}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _package_version(manifest: dict) -> str:
    return str(manifest.get("package", {}).get("version", ""))


def capture(root: Path, base_url: str, out_dir: Path) -> int:
    manifest = yaml.safe_load((root / MANIFEST_REL).read_text(encoding="utf-8"))
    shots = [s for s in manifest.get("screenshots", []) if (s.get("output") or {}).get("route")]
    if not shots:
        sys.stderr.write("error: no screenshots with an output.route to capture\n")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    captured: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        for shot in shots:
            route = shot["output"]["route"]
            url = base_url.rstrip("/") + route
            target = out_dir / Path(shot["image"]).name
            page.goto(url, wait_until="networkidle")
            page.screenshot(path=str(target), full_page=True)
            captured.append({"id": shot["id"], "image": target.name, "url": url})
            print(f"captured {shot['id']} -> {target.name} ({url})")
        browser.close()

    metadata = {
        "package_version": _package_version(manifest),
        "git_sha": _git_sha(root),
        "date": date.today().isoformat(),
        "base_url": base_url,
        "screenshots": captured,
    }
    (out_dir / "capture-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'capture-metadata.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="capture-out", help="output directory")
    args = parser.parse_args(argv)

    base_url = os.environ.get("E2E_BASE_URL", "").strip()
    if not base_url:
        sys.stderr.write("error: E2E_BASE_URL is not set\n")
        return 1

    return capture(_repo_root(), base_url, Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
