#!/usr/bin/env python3
"""Staleness checker for documentation screenshots.

Reads ``docs/assets/screenshots.yml`` and verifies that every screenshot is
well-formed and still matches the source it was captured from. It recomputes a
combined SHA-256 over each entry's ``source.inputs`` and compares it against the
declared ``source.hash``.

Failure modes are split by severity so this can gate PRs without blocking on
expected, human-reviewed drift:

Hard failures (exit 1):
  * manifest missing / unreadable / not ``schema_version: 1``
  * missing required keys, duplicate ``id``, malformed entry
  * declared ``image`` file does not exist
  * declared ``source.inputs`` file does not exist

Soft warnings (exit 0, unless ``--strict``):
  * recomputed source hash differs from the declared hash — the inputs changed
    but the manifest (and likely the screenshot) was not refreshed

``--update`` rewrites ``source.hash`` / ``output.hash`` in place after a
re-capture, so maintainers do not compute hashes by hand.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "assets" / "screenshots.yml"

_REQUIRED_CAPTURED = ("package_version", "git_sha", "date", "method")


def _combined_source_hash(inputs: list[str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(inputs):
        digest.update(rel.encode() + b"\0")
        digest.update((REPO_ROOT / rel).read_bytes() + b"\0")
    return "sha256:" + digest.hexdigest()


def _image_hash(rel: str) -> str:
    return "sha256:" + hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a mapping")
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported schema_version: {data.get('schema_version')!r} (expected 1)")
    screenshots = data.get("screenshots")
    if not isinstance(screenshots, list) or not screenshots:
        raise ValueError("manifest 'screenshots' must be a non-empty list")
    return data


def _validate_entry(entry: Any, index: int) -> tuple[list[str], str, list[str]]:
    """Return (hard_errors, entry_id, source_inputs) for one entry."""
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"screenshots[{index}] must be a mapping"], "", []

    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        errors.append(f"screenshots[{index}] missing string 'id'")
        entry_id = ""

    image = entry.get("image")
    if not isinstance(image, str) or not image:
        errors.append(f"{entry_id or index}: missing string 'image'")
    elif not (REPO_ROOT / image).is_file():
        errors.append(f"{entry_id or index}: image not found: {image}")

    captured = entry.get("captured")
    if not isinstance(captured, dict):
        errors.append(f"{entry_id or index}: missing 'captured' mapping")
    else:
        for key in _REQUIRED_CAPTURED:
            if key not in captured:
                errors.append(f"{entry_id or index}: captured.{key} is required")

    source = entry.get("source")
    inputs: list[str] = []
    if not isinstance(source, dict):
        errors.append(f"{entry_id or index}: missing 'source' mapping")
    else:
        raw_inputs = source.get("inputs")
        if not isinstance(raw_inputs, list) or not raw_inputs:
            errors.append(f"{entry_id or index}: source.inputs must be a non-empty list")
        else:
            for rel in raw_inputs:
                if not isinstance(rel, str) or not (REPO_ROOT / rel).is_file():
                    errors.append(f"{entry_id or index}: source input not found: {rel}")
                else:
                    inputs.append(rel)
        if "hash" not in source:
            errors.append(f"{entry_id or index}: source.hash is required")

    return errors, entry_id, inputs


def _check(path: Path, strict: bool) -> int:
    try:
        manifest = _load_manifest(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"screenshot manifest invalid: {exc}")
        return 1

    hard_errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()

    for index, entry in enumerate(manifest["screenshots"]):
        entry_errors, entry_id, inputs = _validate_entry(entry, index)
        hard_errors.extend(entry_errors)
        if entry_id:
            if entry_id in seen_ids:
                hard_errors.append(f"duplicate id: {entry_id}")
            seen_ids.add(entry_id)
        if entry_errors or not inputs:
            continue
        declared = entry["source"].get("hash")
        actual = _combined_source_hash(inputs)
        if declared != actual:
            warnings.append(
                f"{entry_id}: source inputs changed since capture "
                f"(declared {declared}, actual {actual}); re-capture screenshot "
                f"and refresh the manifest"
            )

    if hard_errors:
        print("Screenshot manifest check FAILED:")
        for err in hard_errors:
            print(f"  error: {err}")
        return 1

    if warnings:
        print("Screenshot manifest drift detected:")
        for warn in warnings:
            print(f"  warning: {warn}")
        if strict:
            return 1
        return 0

    print(f"Screenshot manifest OK: {len(seen_ids)} screenshot(s) verified.")
    return 0


def _update(path: Path) -> int:
    manifest = _load_manifest(path)
    for entry in manifest["screenshots"]:
        source = entry["source"]
        source["hash"] = _combined_source_hash(list(source["inputs"]))
        if "output" in entry and isinstance(entry["output"], dict):
            entry["output"]["hash"] = _image_hash(entry["image"])
    path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Updated hashes for {len(manifest['screenshots'])} screenshot(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat source-hash drift warnings as failures",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="recompute and rewrite source/output hashes in place",
    )
    args = parser.parse_args(argv)

    if not args.manifest.is_file():
        print(f"screenshot manifest not found: {args.manifest}")
        return 1
    if args.update:
        return _update(args.manifest)
    return _check(args.manifest, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
