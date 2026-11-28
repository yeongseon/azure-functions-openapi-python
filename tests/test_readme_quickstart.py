"""Every README landing page must ship the same working quick start."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import re
from typing import Any

import pytest

import azure_functions_openapi
from azure_functions_openapi import clear_openapi_registry, generate_openapi_spec
from azure_functions_openapi.decorator import openapi

ROOT = Path(__file__).resolve().parent.parent
READMES = ["README.md", "README.ko.md", "README.ja.md", "README.zh-CN.md"]
REGISTRATION = 'register_openapi_routes(app, title="Sample API", version="1.0.0")'


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Importing the deprecated shim elsewhere rebinds the package attribute
    # `openapi` to the submodule; the README imports the decorator by that name.
    monkeypatch.setattr(azure_functions_openapi, "openapi", openapi)
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _quick_start(readme: str) -> str:
    text = (ROOT / readme).read_text(encoding="utf-8")
    section = text.split("## Quick Start", 1)[1]
    match = re.search(r"```python\n(.*?)```", section, re.DOTALL)
    assert match is not None, f"{readme} has no Quick Start python block"
    return match.group(1)


@pytest.mark.parametrize("readme", READMES)
def test_quick_start_documents_the_endpoint_and_registers_routes(readme: str) -> None:
    namespace: dict[str, Any] = {"__name__": "readme_quickstart"}
    exec(compile(_quick_start(readme), readme, "exec"), namespace)  # noqa: S102

    spec = generate_openapi_spec(title="Sample API", version="1.0.0", app=namespace["app"])

    assert "post" in spec["paths"]["/api/http_trigger"]


@pytest.mark.parametrize("readme", READMES)
def test_registration_call_and_install_name_match_english(readme: str) -> None:
    text = (ROOT / readme).read_text(encoding="utf-8")

    assert REGISTRATION in text
    assert "pip install azure-functions-openapi" in text
    assert "register_openapi_routes," in _quick_start(readme)
