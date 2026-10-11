from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat


def write_text_atomic(destination: Path, content: str) -> None:
    existing_mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else None
    temporary_path: Path | None = None
    try:
        while True:
            temporary_path = destination.parent / f".{destination.name}.{secrets.token_hex(8)}"
            try:
                descriptor = os.open(
                    temporary_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o666,
                )
                break
            except FileExistsError:
                continue

        with os.fdopen(descriptor, mode="w", encoding="utf-8") as temporary_file:
            if existing_mode is not None:
                os.fchmod(temporary_file.fileno(), existing_mode)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
