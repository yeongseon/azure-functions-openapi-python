from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_screenshots.py"
MANIFEST = REPO_ROOT / "docs" / "assets" / "screenshots.yml"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_committed_manifest_is_clean() -> None:
    result = _run("--strict")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verified" in result.stdout


def test_valid_manifest_matches_source_inputs() -> None:
    result = _run("--manifest", str(MANIFEST))
    assert result.returncode == 0
    assert "OK" in result.stdout


def _write(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


def test_unsupported_schema_version_fails(tmp_path: Path) -> None:
    manifest = tmp_path / "m.yml"
    _write(manifest, "schema_version: 2\n")
    result = _run("--manifest", str(manifest))
    assert result.returncode == 1
    assert "schema_version" in result.stdout


def test_missing_image_and_duplicate_id_fail(tmp_path: Path) -> None:
    manifest = tmp_path / "m.yml"
    _write(
        manifest,
        """
        schema_version: 1
        screenshots:
          - id: dupe
            image: docs/assets/does_not_exist.png
            captured: {package_version: "0.0.0", git_sha: x, date: "2026-01-01", method: manual}
            source: {inputs: [examples/webhook_receiver/function_app.py], hash: "sha256:x"}
          - id: dupe
            image: docs/assets/webhook_receiver_swagger_ui.png
            captured: {package_version: "0.0.0", git_sha: x, date: "2026-01-01", method: manual}
            source: {inputs: [examples/webhook_receiver/function_app.py], hash: "sha256:x"}
        """,
    )
    result = _run("--manifest", str(manifest))
    assert result.returncode == 1
    assert "image not found" in result.stdout
    assert "duplicate id: dupe" in result.stdout


def test_source_drift_warns_but_passes_without_strict(tmp_path: Path) -> None:
    manifest = tmp_path / "m.yml"
    _write(
        manifest,
        """
        schema_version: 1
        screenshots:
          - id: drift
            image: docs/assets/webhook_receiver_swagger_ui.png
            captured: {package_version: "0.0.0", git_sha: x, date: "2026-01-01", method: manual}
            source: {inputs: [examples/webhook_receiver/function_app.py], hash: "sha256:stale"}
        """,
    )
    ok = _run("--manifest", str(manifest))
    assert ok.returncode == 0
    assert "drift detected" in ok.stdout

    strict = _run("--manifest", str(manifest), "--strict")
    assert strict.returncode == 1
    assert "drift detected" in strict.stdout


def test_secret_in_manifest_fails(tmp_path: Path) -> None:
    sub_id = "/subscriptions/12345678-1234-1234-1234-1234567890ab"
    manifest = tmp_path / "m.yml"
    _write(
        manifest,
        f"""
        schema_version: 1
        note: "deployed to {sub_id}/resourceGroups/rg"
        screenshots:
          - id: leaky
            image: docs/assets/webhook_receiver_swagger_ui.png
            captured: {{package_version: "0.0.0", git_sha: x, date: "2026-01-01", method: manual}}
            source: {{inputs: [examples/webhook_receiver/function_app.py], hash: "sha256:x"}}
        """,
    )
    result = _run("--manifest", str(manifest))
    assert result.returncode == 1
    assert "subscription id" in result.stdout
    # The matched secret itself must never be echoed back into CI logs.
    assert sub_id not in result.stdout


def test_secret_scan_allow_exempts_reviewed_match(tmp_path: Path) -> None:
    sub_id = "/subscriptions/12345678-1234-1234-1234-1234567890ab"
    manifest = tmp_path / "m.yml"
    _write(
        manifest,
        f"""
        schema_version: 1
        secret_scan_allow: ["{sub_id}"]
        note: "documented example {sub_id}"
        screenshots:
          - id: exempt
            image: docs/assets/webhook_receiver_swagger_ui.png
            captured: {{package_version: "0.0.0", git_sha: x, date: "2026-01-01", method: manual}}
            source: {{inputs: [examples/webhook_receiver/function_app.py], hash: "sha256:x"}}
        """,
    )
    result = _run("--manifest", str(manifest))
    # Secret is allowlisted, so the only remaining signal is soft hash drift.
    assert result.returncode == 0
    assert "subscription id" not in result.stdout
