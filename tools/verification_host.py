"""Real host contract, with isolated emulator storage and owned processes."""

from __future__ import annotations

import base64
from contextlib import ExitStack
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen
import xml.etree.ElementTree as ET

from tools.verification_process import child


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(process: subprocess.Popen[str], url: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("service exited before readiness")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except (OSError, URLError, HTTPException):
            time.sleep(0.25)
    raise TimeoutError("service readiness deadline exceeded")


def host_smoke(directory: Path) -> int:
    directory = directory.resolve()
    suite = ET.Element("testsuite", name="real-functions-host")
    case = ET.SubElement(suite, "testcase", name="documented_route_matches_live_host")
    try:
        with tempfile.TemporaryDirectory(prefix="openapi-host-") as temporary, ExitStack() as stack:
            work = Path(temporary)
            for name in ("function_app.py", "host.json"):
                (work / name).write_bytes((Path("tests/host_smoke") / name).read_bytes())
            blob, queue, table, port = (free_port() for _ in range(4))
            key = base64.b64encode(b"openapi-local-emulator-only" * 2).decode()
            emulator = stack.enter_context(
                child(
                    [
                        "env",
                        f"AZURITE_ACCOUNTS=openapidev:{key}",
                        "azurite",
                        "--silent",
                        "--location",
                        str(work / "storage"),
                        "--blobPort",
                        str(blob),
                        "--queuePort",
                        str(queue),
                        "--tablePort",
                        str(table),
                    ],
                    directory / "logs/azurite.log",
                )
            )
            deadline = time.monotonic() + 30
            for service in (blob, queue, table):
                while True:
                    if emulator.poll() is not None or time.monotonic() >= deadline:
                        raise TimeoutError("Azurite failed readiness")
                    try:
                        with socket.create_connection(("127.0.0.1", service), timeout=1):
                            break
                    except OSError:
                        time.sleep(0.25)
            (work / "local.settings.json").write_text(
                json.dumps(
                    {
                        "IsEncrypted": False,
                        "Values": {
                            "FUNCTIONS_WORKER_RUNTIME": "python",
                            "AzureWebJobsStorage": (
                                f"DefaultEndpointsProtocol=http;AccountName=openapidev;AccountKey={key};"
                                f"BlobEndpoint=http://127.0.0.1:{blob}/openapidev;"
                                f"QueueEndpoint=http://127.0.0.1:{queue}/openapidev;"
                                f"TableEndpoint=http://127.0.0.1:{table}/openapidev;"
                            ),
                        },
                    }
                )
            )
            env_path = str(Path(sys.executable).parent)
            previous_path = os.environ.get("PATH", "")
            os.environ["PATH"] = env_path + os.pathsep + previous_path
            try:
                host = stack.enter_context(
                    child(
                        ["func", "start", "--verbose", "--port", str(port)],
                        directory / "logs/host.log",
                        work,
                    )
                )
                base = f"http://127.0.0.1:{port}"
                wait_ready(host, base + "/api/custom_name")
                with urlopen(base + "/api/custom_name", timeout=5) as response:
                    assert json.load(response) == {"function_name": "custom_name"}
                with urlopen(base + "/api/openapi.json", timeout=5) as response:
                    spec = json.load(response)
                assert spec["openapi"]
                paths = [p for p in spec["paths"] if p not in ("/api/openapi.json", "/api/docs")]
                assert paths == ["/api/custom_name"], paths
                with urlopen(base + paths[0], timeout=5) as response:
                    assert json.load(response) == {"function_name": "custom_name"}
                with urlopen(base + "/api/docs", timeout=5) as response:
                    assert "SwaggerUIBundle" in response.read().decode()
            finally:
                os.environ["PATH"] = previous_path
        text = (directory / "logs/host.log").read_text()
        assert not re.search(
            r"0 functions (loaded|found \(Worker\))|No job functions found|"
            r"Executed 'Functions\..*' \(Failed",
            text,
        )
        code = 0
    except (OSError, RuntimeError, TimeoutError, AssertionError, ValueError) as error:
        ET.SubElement(case, "failure").text = str(error)
        code = 1
    finally:
        destination = directory / "junit/junit.xml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(suite).write(destination, encoding="unicode")
    return code
