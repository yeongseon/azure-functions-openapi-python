"""Python 3.10 is deprecated ahead of its removal in the next minor release."""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest

import azure_functions_openapi


def test_warns_on_python_310(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 10, 0, "final", 0))
    with pytest.warns(FutureWarning, match="drop support for Python 3.10"):
        importlib.reload(azure_functions_openapi)


def test_silent_on_python_311(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 11, 0, "final", 0))
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        importlib.reload(azure_functions_openapi)
