# tests/test_cli_docs_examples.py
"""Regression guard for #788: docs/cli.md's CI recipe must actually work.

The CLI Guide's "CI example" previously generated and validated a spec
without ever passing `--app`, so in a fresh process the registry was empty,
`generate` succeeded with `paths: {}`, and a schema validator accepted that
empty document too -- a copyable CI recipe that could report success without
inspecting any application endpoint.

These tests run the exact documented command (via the installed console
script, the same way a CI job would invoke it) against a representative
example app (`examples/webhook_receiver`, the repository's own canonical
minimal-workflow example per docs/contributing.md) and assert it produces at
least one known, real path -- not just that the output parses as valid
JSON/OpenAPI. A companion negative case proves `--fail-on-empty-paths`
actually gates an application with no registered routes, and that omitting
the flag preserves the legitimate ability to generate an empty document.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONSOLE_SCRIPT = Path(sys.executable).parent / "azure-functions-openapi"


def _generate(*extra_args: str, cwd: Path, env: dict[str, str] | None = None) -> tuple[int, Path]:
    output = cwd / "openapi.json"
    result = subprocess.run(
        [str(_CONSOLE_SCRIPT), "generate", *extra_args, "--output", str(output)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return result.returncode, output


class TestDocumentedCIRecipeAgainstARealApp:
    def test_documented_command_discovers_the_app_s_known_path(self, tmp_path: Path) -> None:
        # Given: an isolated directory with a copy of the representative example app,
        # so generation does not modify the live checkout.
        example_app_src = _REPO_ROOT / "examples" / "webhook_receiver" / "function_app.py"
        example_app_dst = tmp_path / "function_app.py"
        example_app_dst.write_text(example_app_src.read_text(encoding="utf-8"), encoding="utf-8")

        # When: the exact flags docs/cli.md's CI example documents,
        # run from the isolated temp directory, against the copied app.
        returncode, output = _generate(
            "--app",
            "function_app:app",
            "--openapi-version",
            "3.1",
            "--strict",
            "--fail-on-warnings",
            "--fail-on-empty-paths",
            cwd=tmp_path,
        )

        # Then: success, and the generated document names a real, known
        # endpoint -- not merely a document that happens to parse.
        assert returncode == 0
        spec = json.loads(output.read_text(encoding="utf-8"))
        assert "/api/webhooks/orders" in spec["paths"]


class TestFailOnEmptyPathsGatesAnUnregisteredApp:
    def _empty_app_dir(self, tmp_path: Path) -> Path:
        (tmp_path / "empty_function_app.py").write_text(
            "import azure.functions as func\n\napp = func.FunctionApp()\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_guard_enabled_fails_the_build(self, tmp_path: Path) -> None:
        # Given: an app with no @openapi-decorated routes at all -- the
        # forgotten-target/wrong-module scenario the guard exists to catch.
        app_dir = self._empty_app_dir(tmp_path)

        # When: generating with the documented CI flags.
        returncode, _output = _generate(
            "--app",
            "empty_function_app:app",
            "--openapi-version",
            "3.1",
            "--strict",
            "--fail-on-warnings",
            "--fail-on-empty-paths",
            cwd=app_dir,
        )

        # Then: the build fails (exit 1, per the documented exit-codes
        # table), rather than silently producing an empty-but-valid document.
        assert returncode == 1

    def test_guard_omitted_still_allows_a_deliberate_empty_document(self, tmp_path: Path) -> None:
        # The CLI Guide preserves this as legitimate -- e.g. smoke-testing
        # the toolchain itself before any routes are decorated yet.
        app_dir = self._empty_app_dir(tmp_path)

        returncode, output = _generate(
            "--app",
            "empty_function_app:app",
            "--openapi-version",
            "3.1",
            cwd=app_dir,
        )

        assert returncode == 0
        spec = json.loads(output.read_text(encoding="utf-8"))
        assert spec["paths"] == {}
