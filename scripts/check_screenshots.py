#!/usr/bin/env python3
"""Validate the documentation screenshot manifest and detect stale screenshots.

Documentation screenshots (Swagger UI, OpenAPI JSON, ...) are captured from
deployed example apps during the release e2e run. Over time the example
sources or the generated OpenAPI output drift, leaving screenshots stale.

This tool reads ``docs/assets/screenshots.yml`` and, for every screenshot,
recomputes a deterministic hash of its declared ``source.inputs`` (git-style
glob expansion over tracked files). It then compares that hash to the stored
``source.hash`` recorded when the screenshot was last captured.

Version numbers are treated as *provenance only*: a screenshot is considered
stale when the files that materially produced it change, not when the package
version is bumped for unrelated reasons.

Modes:
  check   (default) Validate the manifest and report drift.
            Hard-fails on structural problems (invalid manifest, missing image,
            duplicate id, empty input globs). Reports source drift as a warning
            by default, or as a failure with ``--strict``.
  update  Recompute and rewrite every ``source.hash`` (and ``captured.date``
            when ``--stamp`` is given). Use this right after re-capturing.

Exit code 0 when clean, 1 when any hard failure (or drift under ``--strict``).
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
from pathlib import Path
import sys
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - dependency guard
    sys.stderr.write("error: PyYAML is required (pip install pyyaml)\n")
    raise SystemExit(1) from None

MANIFEST_REL = "docs/assets/screenshots.yml"
HASH_ALGO = "sha256"
COMBINE_PREFIX = "screenshots-v1\n"

IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".eggs",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _is_ignored(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    return any(part in IGNORED_PARTS for part in rel_parts)


def _expand_inputs(root: Path, globs: list[str]) -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if not path.is_file() or _is_ignored(path, root):
                continue
            if path not in seen:
                seen.add(path)
                files.append(path)
    return files


def _hash_file(path: Path) -> str:
    h = hashlib.new(HASH_ALGO)
    h.update(path.read_bytes())
    return h.hexdigest()


def _combined_hash(root: Path, files: list[Path]) -> str:
    h = hashlib.new(HASH_ALGO)
    h.update(COMBINE_PREFIX.encode("utf-8"))
    for path in sorted(files):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(_hash_file(path).encode("utf-8"))
        h.update(b"\n")
    return f"{HASH_ALGO}:{h.hexdigest()}"


def _load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a mapping")
    return data


def _validate_structure(manifest: dict[str, Any], root: Path) -> list[str]:
    errors: list[str] = []
    shots = manifest.get("screenshots")
    if not isinstance(shots, list) or not shots:
        errors.append("`screenshots` must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    for idx, shot in enumerate(shots):
        where = f"screenshots[{idx}]"
        if not isinstance(shot, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        sid = shot.get("id")
        if not sid:
            errors.append(f"{where}: missing `id`")
        elif sid in seen_ids:
            errors.append(f"{where}: duplicate id '{sid}'")
        else:
            seen_ids.add(sid)

        image = shot.get("image")
        if not image:
            errors.append(f"{where} ({sid}): missing `image`")
        elif not (root / image).is_file():
            errors.append(f"{where} ({sid}): image not found: {image}")

        source = shot.get("source") or {}
        inputs = source.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            errors.append(f"{where} ({sid}): `source.inputs` must be a non-empty list")
        else:
            matched = _expand_inputs(root, inputs)
            if not matched:
                errors.append(f"{where} ({sid}): `source.inputs` matched no files")
    return errors


def _iter_shots(manifest: dict[str, Any]):
    for shot in manifest.get("screenshots", []):
        if isinstance(shot, dict):
            yield shot


def run_check(root: Path, strict: bool) -> int:
    manifest_path = root / MANIFEST_REL
    if not manifest_path.is_file():
        sys.stderr.write(f"error: manifest not found: {MANIFEST_REL}\n")
        return 1

    manifest = _load_manifest(manifest_path)
    errors = _validate_structure(manifest, root)
    if errors:
        sys.stderr.write("Manifest validation failed:\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    stale: list[str] = []
    for shot in _iter_shots(manifest):
        sid = shot["id"]
        source = shot.get("source") or {}
        stored = source.get("hash")
        current = _combined_hash(root, _expand_inputs(root, source["inputs"]))
        if stored != current:
            stale.append(sid)
            sys.stderr.write(
                f"STALE: '{sid}' source changed since capture\n"
                f"       stored : {stored}\n"
                f"       current: {current}\n"
            )

    if stale:
        msg = (
            f"{len(stale)} screenshot(s) stale: {', '.join(stale)}\n"
            "Re-capture on the next release, then run "
            "`python scripts/check_screenshots.py update --stamp`.\n"
        )
        if strict:
            sys.stderr.write("error: " + msg)
            return 1
        sys.stderr.write("warning: " + msg)
        return 0

    print("OK: all screenshots up to date.")
    return 0


def run_update(root: Path, stamp: bool) -> int:
    manifest_path = root / MANIFEST_REL
    if not manifest_path.is_file():
        sys.stderr.write(f"error: manifest not found: {MANIFEST_REL}\n")
        return 1

    manifest = _load_manifest(manifest_path)
    errors = _validate_structure(manifest, root)
    if errors:
        sys.stderr.write("Refusing to update an invalid manifest:\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    today = date.today().isoformat()
    changed = 0
    for shot in _iter_shots(manifest):
        source = shot["source"]
        new_hash = _combined_hash(root, _expand_inputs(root, source["inputs"]))
        if source.get("hash") != new_hash:
            source["hash"] = new_hash
            source.setdefault("hash_algorithm", HASH_ALGO)
            if stamp:
                shot.setdefault("captured", {})["date"] = today
            changed += 1

    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Updated {changed} screenshot hash(es) in {MANIFEST_REL}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode")

    p_check = sub.add_parser("check", help="validate manifest and report drift")
    p_check.add_argument(
        "--strict",
        action="store_true",
        help="treat stale screenshots as a hard failure",
    )

    p_update = sub.add_parser("update", help="recompute and rewrite source hashes")
    p_update.add_argument(
        "--stamp",
        action="store_true",
        help="also refresh captured.date to today for changed entries",
    )

    args = parser.parse_args(argv)
    root = _repo_root()

    if args.mode == "update":
        return run_update(root, stamp=args.stamp)
    return run_check(root, strict=getattr(args, "strict", False))


if __name__ == "__main__":
    raise SystemExit(main())
