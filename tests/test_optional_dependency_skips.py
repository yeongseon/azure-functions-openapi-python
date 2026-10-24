import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "target",
    [
        "tests/test_with_validation_example.py",
        "tests/test_partner_import_bridge_example.py",
        "tests/test_snapshots.py::TestNotificationRequestSnapshot::test_openapi_3_0_spec",
        "tests/test_snapshots.py::TestPartnerImportBridgeSnapshot::test_openapi_3_0_spec",
    ],
)
@pytest.mark.parametrize(
    "scenario",
    [
        (
            "ModuleNotFoundError('absent companion', name='azure_functions_validation')",
            pytest.ExitCode.OK,
        ),
        ("ImportError('broken companion API')", None),
        ("ModuleNotFoundError('missing transitive dependency', name='companion_internal')", None),
        (
            "ModuleNotFoundError('missing companion submodule', "
            "name='azure_functions_validation.internal')",
            None,
        ),
    ],
)
def test_pytest_skips_only_when_companion_is_absent(
    tmp_path: Path, target: str, scenario: tuple[str, pytest.ExitCode | None]
) -> None:
    failure, exit_code = scenario
    # Given an import finder that deterministically blocks the companion, even if installed.
    plugin = tmp_path / "companion_failure.py"
    plugin.write_text(
        "import sys\n"
        "from importlib.abc import MetaPathFinder\n"
        "class CompanionFailure(MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'azure_functions_validation':\n"
        f"            raise {failure}\n"
        "sys.meta_path.insert(0, CompanionFailure())\n",
        encoding="utf-8",
    )
    # When pytest collects or runs the actual optional-dependency tests.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "--no-cov",
            "-p",
            "companion_failure",
            "-q",
            target,
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    # Then only the absent top-level companion produces a successful skipped run.
    output = result.stdout + result.stderr
    if exit_code is not None:
        assert result.returncode == exit_code, output
        assert "skipped" in output, output
    else:
        assert result.returncode in (
            pytest.ExitCode.TESTS_FAILED,
            pytest.ExitCode.INTERRUPTED,
        ), output
        assert "skipped" not in output, output
