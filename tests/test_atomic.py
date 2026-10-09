from __future__ import annotations

import os
from pathlib import Path
import stat
from unittest import mock

import pytest

from azure_functions_openapi._atomic import write_text_atomic


def test_write_failure_preserves_output_and_removes_temp_file(tmp_path: Path) -> None:
    output_path = tmp_path / "openapi.json"
    output_path.write_text("trusted specification", encoding="utf-8")

    with mock.patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            write_text_atomic(output_path, "replacement specification")

    assert output_path.read_text(encoding="utf-8") == "trusted specification"
    assert list(tmp_path.glob(f".{output_path.name}.*")) == []


def test_write_preserves_existing_output_mode(tmp_path: Path) -> None:
    output_path = tmp_path / "openapi.json"
    output_path.write_text("stale specification", encoding="utf-8")
    output_path.chmod(0o640)

    write_text_atomic(output_path, "replacement specification")

    assert stat.S_IMODE(output_path.stat().st_mode) == 0o640


def test_new_output_uses_process_default_mode(tmp_path: Path) -> None:
    output_path = tmp_path / "openapi.json"
    current_umask = os.umask(0)
    os.umask(current_umask)

    write_text_atomic(output_path, "new specification")

    assert stat.S_IMODE(output_path.stat().st_mode) == 0o666 & ~current_umask
