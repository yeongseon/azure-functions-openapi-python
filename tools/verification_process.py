"""Bounded subprocess ownership; no child survives timeout or interruption."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
from types import FrameType

from tools.verification_evidence import redact


def terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


@contextmanager
def child(
    command: list[str], log: Path, cwd: Path | None = None
) -> Iterator[subprocess.Popen[str]]:
    log.parent.mkdir(parents=True, exist_ok=True)
    # Raw output stays in an anonymous temporary file until it can be redacted.
    import tempfile

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
        with subprocess.Popen(
            command,
            cwd=cwd,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        ) as process:

            def interrupted(number: int, frame: FrameType | None) -> None:
                terminate(process)
                raise KeyboardInterrupt(number)

            previous = {
                sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)
            }
            try:
                yield process
            finally:
                terminate(process)
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
                output.seek(0)
                text = redact(output.read())
                log.write_text(text, encoding="utf-8")
                print(text, end="")


def run(command: list[str], log: Path, timeout: float = 600) -> int:
    try:
        with child(command, log) as process:
            try:
                return process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return 124
    except FileNotFoundError as error:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(redact(str(error)), encoding="utf-8")
        return 127
