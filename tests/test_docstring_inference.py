"""Docstring inference (P1-A Phase 2).

Covers inferring ``summary``/``description`` from a handler's docstring at both
decorator-time (``@openapi``) and scan-time (bare ``@app.route``, with or
without a documentable return annotation). Docstring inference is per-field and
lowest-precedence source: an explicit ``summary=``/``description=`` always wins,
and a missing/blank docstring infers nothing.
"""

from __future__ import annotations

from typing import Any

from _scan_helpers import _app_for
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


def test_explicit_empty_string_suppresses_docstring_inference() -> None:
    # ``None`` is the "unset" sentinel; an explicit ``""`` is an intentional
    # override and must NOT be back-filled from the docstring (#532 review).
    @openapi(summary="", description="")
    def get_user(req: Any) -> User:  # pragma: no cover
        """Doc summary.

        Doc description.
        """
        raise NotImplementedError

    entry = get_openapi_registry()["get_user"]
    assert entry["summary"] == ""
    assert entry["description"] == ""


def test_explicit_empty_summary_still_infers_description() -> None:
    # Per-field sentinel: suppressing summary with ``""`` must not stop the
    # description from being inferred (it was left as ``None``).
    @openapi(summary="")
    def get_user(req: Any) -> User:  # pragma: no cover
        """Doc summary.

        Doc description.
        """
        raise NotImplementedError

    entry = get_openapi_registry()["get_user"]
    assert entry["summary"] == ""
    assert entry["description"] == "Doc description."


# ---------------------------------------------------------------------------
# Scan-time inference (zero-decorator @app.route)
# ---------------------------------------------------------------------------


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


def test_scan_infers_docstring_for_bare_route_without_documentable_return() -> None:
    # Regression (#534): a bare route whose return type is NOT documentable
    # (a scalar here) still has a docstring — its summary/description must be
    # registered, not silently dropped because no response was inferred.
    def get_user(req: Any) -> str:  # pragma: no cover
        """Get a user.

        Docstring-only description.
        """
        raise NotImplementedError

    scan_endpoint_metadata(_app_for(get_user, name="get_user", route="users", methods=["GET"]))

    entry = get_openapi_registry()["get::/api/users"]
    assert entry["summary"] == "Get a user."
    assert entry["description"] == "Docstring-only description."
    # No response was inferred, so the private supersession tag must be absent.
    assert "_response_inferred" not in entry
    assert not entry.get("response")
    assert entry.get("response_model") is None


def test_scan_infers_docstring_for_unannotated_bare_route() -> None:
    # Regression (#534): a bare route with no return annotation at all but a
    # docstring must still register its summary/description.
    def get_user(req: Any):  # type: ignore[no-untyped-def]  # pragma: no cover
        """Ping."""
        raise NotImplementedError

    scan_endpoint_metadata(_app_for(get_user, name="get_user", route="users", methods=["GET"]))

    entry = get_openapi_registry()["get::/api/users"]
    assert entry["summary"] == "Ping."
    assert entry["description"] == ""
    assert "_response_inferred" not in entry
