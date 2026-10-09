from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "ci_classify_changes.sh"


def classify(files: list[str]) -> dict[str, str]:
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input="\n".join(files) + ("\n" if files else ""),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


@pytest.mark.parametrize(
    "files",
    [
        ["README.md"],
        ["README.ko.md", "README.ja.md", "README.zh-CN.md"],
        ["CHANGELOG.md", "CONTRIBUTING.md"],
        ["docs/guide.md", "docs/assets/shot.png"],
        ["docs/index.md", "docs/diagram.svg"],
    ],
)
def test_documentation_only_changes_skip_the_matrix(files: list[str]) -> None:
    assert classify(files) == {
        "docs_only": "true",
        "docs_changed": "true",
        "full_required": "false",
    }


@pytest.mark.parametrize(
    "files",
    [
        ["src/pkg/module.py"],
        ["tests/test_x.py"],
        ["tests/fixtures/sample.md"],
        ["src/pkg/README.md"],
        ["examples/app/README.md"],
        ["pyproject.toml"],
        ["Makefile"],
        ["requirements.txt"],
        ["uv.lock"],
        [".github/workflows/ci-test.yml"],
        [".github/PULL_REQUEST_TEMPLATE.md"],
        ["tools/lint.py"],
        ["scripts/run.sh"],
        ["llms.txt"],
        ["llms-full.txt"],
        ["unknown.bin"],
        [".release-please-manifest.json"],
        ["README.md", "src/pkg/module.py"],
        ["docs/guide.md", "tests/test_x.py"],
    ],
)
def test_anything_that_may_affect_code_runs_the_full_matrix(files: list[str]) -> None:
    assert classify(files)["full_required"] == "true"
    assert classify(files)["docs_only"] == "false"


@pytest.mark.parametrize(
    "files",
    [["mkdocs.yml"], ["pyproject.toml"], ["docs/hooks.py"], ["docs/extra.css"]],
)
def test_docs_build_inputs_run_the_matrix_and_the_docs_build(files: list[str]) -> None:
    assert classify(files)["full_required"] == "true"
    assert classify(files)["docs_changed"] == "true"


@pytest.mark.parametrize(
    "files",
    [
        ["src/azure_functions_openapi/openapi.py"],
        ["scripts/lint_mermaid.py"],
        ["scripts/check_screenshots.py"],
        ["tests/test_screenshot_manifest.py"],
        ["docs/assets/screenshots.yml"],
        [".github/workflows/ci-test.yml"],
    ],
)
def test_docs_check_inputs_run_the_matrix_and_the_docs_build(files: list[str]) -> None:
    assert classify(files) == {
        "docs_only": "false",
        "docs_changed": "true",
        "full_required": "true",
    }


def test_mixed_docs_and_code_run_both() -> None:
    assert classify(["README.md", "src/pkg/module.py"]) == {
        "docs_only": "false",
        "docs_changed": "true",
        "full_required": "true",
    }


def test_code_only_does_not_require_the_docs_build() -> None:
    assert classify(["tests/test_x.py"]) == {
        "docs_only": "false",
        "docs_changed": "false",
        "full_required": "true",
    }


def test_deleted_documentation_is_still_documentation() -> None:
    assert classify(["docs/removed.md"])["docs_only"] == "true"


def test_empty_diff_fails_safe_to_the_full_matrix() -> None:
    assert classify([]) == {"docs_only": "false", "docs_changed": "true", "full_required": "true"}


def test_blank_lines_are_ignored() -> None:
    assert classify(["", "README.md", ""])["docs_only"] == "true"


def test_a_single_unknown_path_defeats_docs_only() -> None:
    assert classify(["README.md", "docs/guide.md", "weird.dat"])["full_required"] == "true"
