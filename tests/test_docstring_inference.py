"""Docstring inference (P1-A Phase 2).

Covers inferring ``summary``/``description`` from a handler's docstring at both
decorator-time (``@openapi``) and scan-time (bare ``@app.route`` that also has a
documentable return annotation). Docstring inference is per-field and the
lowest-precedence source: an explicit ``summary=``/``description=`` always wins,
and a missing/blank docstring infers nothing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
import pytest

from azure_functions_openapi.bridge import scan_endpoint_metadata
from azure_functions_openapi.decorator import (
    _infer_doc_metadata,
    clear_openapi_registry,
    get_openapi_registry,
    openapi,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class User(BaseModel):
    id: int
    name: str


# ---------------------------------------------------------------------------
# _infer_doc_metadata (unit)
# ---------------------------------------------------------------------------


def test_infer_summary_and_description_from_docstring() -> None:
    def handler(req: Any) -> Any:  # pragma: no cover - body never executed
        """Get a user.

        Returns the user identified by the path id.
        """
        raise NotImplementedError

    summary, description = _infer_doc_metadata(handler)
    assert summary == "Get a user."
    assert description == "Returns the user identified by the path id."


def test_infer_single_line_docstring_has_empty_description() -> None:
    def handler(req: Any) -> Any:  # pragma: no cover
        """Ping the service."""
        raise NotImplementedError

    summary, description = _infer_doc_metadata(handler)
    assert summary == "Ping the service."
    assert description == ""


def test_infer_no_docstring_yields_empty() -> None:
    def handler(req: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    assert _infer_doc_metadata(handler) == ("", "")


def test_infer_blank_docstring_yields_empty() -> None:
    def handler(req: Any) -> Any:  # pragma: no cover
        """ """
        raise NotImplementedError

    assert _infer_doc_metadata(handler) == ("", "")


def test_infer_dedents_indented_body() -> None:
    def handler(req: Any) -> Any:  # pragma: no cover
        """Create a user.

        Line one.
        Line two.
        """
        raise NotImplementedError

    summary, description = _infer_doc_metadata(handler)
    assert summary == "Create a user."
    assert description == "Line one.\nLine two."


# ---------------------------------------------------------------------------
# Decorator-time inference
# ---------------------------------------------------------------------------


def test_decorator_infers_summary_and_description() -> None:
    @openapi()
    def get_user(req: Any) -> User:  # pragma: no cover
        """Get a user.

        Full description here.
        """
        raise NotImplementedError

    entry = get_openapi_registry()["get_user"]
    assert entry["summary"] == "Get a user."
    assert entry["description"] == "Full description here."


def test_explicit_summary_wins_but_description_is_inferred() -> None:
    # Per-field gap fill: an explicit summary is kept while a missing
    # description is still filled from the docstring body.
    @openapi(summary="Explicit summary")
    def get_user(req: Any) -> User:  # pragma: no cover
        """Doc summary.

        Doc description.
        """
        raise NotImplementedError

    entry = get_openapi_registry()["get_user"]
    assert entry["summary"] == "Explicit summary"
    assert entry["description"] == "Doc description."


def test_explicit_both_win_over_docstring() -> None:
    @openapi(summary="S", description="D")
    def get_user(req: Any) -> User:  # pragma: no cover
        """Doc summary.

        Doc description.
        """
        raise NotImplementedError

    entry = get_openapi_registry()["get_user"]
    assert entry["summary"] == "S"
    assert entry["description"] == "D"


def test_decorator_no_docstring_leaves_empty() -> None:
    @openapi()
    def bare(req: Any) -> User:  # pragma: no cover
        raise NotImplementedError

    entry = get_openapi_registry()["bare"]
    assert entry["summary"] == ""
    assert entry["description"] == ""


# ---------------------------------------------------------------------------
# Scan-time inference (zero-decorator @app.route)
# ---------------------------------------------------------------------------


class _MockBinding:
    def __init__(self, route: str, methods: list[str]) -> None:
        self.route = route
        self.methods = methods
        self.type = "httpTrigger"


class _MockFunction:
    def __init__(self, name: str, func: Any, bindings: list[Any]) -> None:
        self._name = name
        self._func = func
        self._bindings = bindings

    def get_function_name(self) -> str:
        return self._name

    def get_user_function(self) -> Any:
        return self._func

    def get_bindings(self) -> list[Any]:
        return self._bindings

    def is_http_function(self) -> bool:
        return True


class _MockBuilder:
    def __init__(self, function: _MockFunction) -> None:
        self._function = function

    def build(self, auth_level: Any = None) -> _MockFunction:
        return self._function


class _MockApp:
    def __init__(self, builders: list[_MockBuilder]) -> None:
        self._function_builders = builders


def _app_for(handler: Any, *, name: str, route: str, methods: list[str]) -> _MockApp:
    fn = _MockFunction(name=name, func=handler, bindings=[_MockBinding(route, methods)])
    return _MockApp([_MockBuilder(fn)])


def test_scan_infers_docstring_for_bare_route() -> None:
    def get_user(req: Any) -> User:  # pragma: no cover
        """Get a user.

        Scan-time description.
        """
        raise NotImplementedError

    scan_endpoint_metadata(_app_for(get_user, name="get_user", route="users", methods=["GET"]))

    entry = get_openapi_registry()["get::/api/users"]
    assert entry["summary"] == "Get a user."
    assert entry["description"] == "Scan-time description."


def test_scan_bare_route_without_docstring_has_empty_metadata() -> None:
    def get_user(req: Any) -> User:  # pragma: no cover
        raise NotImplementedError

    scan_endpoint_metadata(_app_for(get_user, name="get_user", route="users", methods=["GET"]))

    entry = get_openapi_registry()["get::/api/users"]
    assert entry["summary"] == ""
    assert entry["description"] == ""
