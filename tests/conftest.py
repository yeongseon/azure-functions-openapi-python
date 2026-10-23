"""Keep synthetic verification evidence out of the enclosing Actions summary."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_verification_summary(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if request.node.path.name.startswith("test_verification"):
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "isolated-job-summary"))
