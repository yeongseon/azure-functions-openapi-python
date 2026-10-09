from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile


def write_text_atomic(destination: Path, content: str) -> None:
    existing_mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else None
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        if existing_mode is None:
            current_umask = os.umask(0)
            os.umask(current_umask)
            temporary_path.chmod(0o666 & ~current_umask)
        else:
            temporary_path.chmod(existing_mode)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
