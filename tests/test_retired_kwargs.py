"""Retired-kwargs guard for ``@openapi`` (#557).

The four discrete request/response params (``request_model``, ``request_body``,
``response_model``, ``response``) were removed from ``@openapi`` in 0.24.0 (#509)
in favor of the unified ``requests=`` / ``responses=`` forms. Passing one now
must raise a clear, actionable error naming the replacement rather than an
opaque ``TypeError``. Genuinely unknown kwargs keep the standard behavior.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import (
    _RETIRED_KWARGS,
    clear_openapi_registry,
    openapi,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class Model(BaseModel):
    id: int


@pytest.mark.parametrize(
    ("kwarg", "replacement"),
    [
        ("request_model", "requests="),
        ("request_body", "requests="),
        ("response_model", "responses="),
        ("response", "responses="),
    ],
)
def test_retired_kwarg_raises_with_guidance(kwarg: str, replacement: str) -> None:
    kw: dict[str, Any] = {kwarg: Model}
    with pytest.raises(TypeError) as excinfo:

        @openapi(summary="x", **kw)
        def handler(req: Any) -> Any:  # pragma: no cover - never registered
            raise NotImplementedError

    message = str(excinfo.value)
    assert kwarg in message
    assert "removed in 0.24.0" in message
    assert replacement in message


def test_retired_map_covers_exactly_the_four_discrete_params() -> None:
    assert set(_RETIRED_KWARGS) == {
        "request_model",
        "request_body",
        "response_model",
        "response",
    }


def test_unknown_kwarg_raises_standard_typeerror() -> None:
    with pytest.raises(TypeError) as excinfo:

        @openapi(summary="x", not_a_real_param=123)
        def handler(req: Any) -> Any:  # pragma: no cover - never registered
            raise NotImplementedError

    message = str(excinfo.value)
    assert "unexpected keyword argument" in message
    assert "not_a_real_param" in message


def test_valid_kwargs_unaffected() -> None:
    @openapi(summary="ok", responses=Model)
    def handler(req: Any) -> Any:  # pragma: no cover - body never executed
        raise NotImplementedError

    # No exception, handler registered normally.
    from azure_functions_openapi.decorator import get_openapi_registry

    assert get_openapi_registry()["handler"]["response_model"] is Model
