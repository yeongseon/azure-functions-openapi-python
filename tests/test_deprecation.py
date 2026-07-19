"""Tests for the discrete-parameter deprecation (issue #285)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
import warnings

from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    get_openapi_registry,
    openapi,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class ReqModel(BaseModel):
    name: str


class RespModel(BaseModel):
    id: int


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_model": ReqModel},
        {"request_body": {"type": "object"}},
        {"response_model": RespModel},
        {"response": {200: {"description": "ok"}}},
    ],
)
def test_discrete_parameters_emit_deprecation_warning(kwargs: dict[str, Any]) -> None:
    with pytest.warns(DeprecationWarning, match="unified"):

        @openapi(route="items", method="post", **kwargs)
        def handler(req: Any) -> Any:
            return req


def test_unified_parameters_do_not_warn() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)

        @openapi(route="items", method="post", requests=ReqModel, responses=RespModel)
        def handler(req: Any) -> Any:
            return req


def test_discrete_and_unified_produce_identical_metadata() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @openapi(route="a", method="post", request_model=ReqModel, response_model=RespModel)
        def discrete(req: Any) -> Any:
            return req

    @openapi(route="b", method="post", requests=ReqModel, responses=RespModel)
    def unified(req: Any) -> Any:
        return req

    reg = get_openapi_registry()
    d = reg["discrete"]
    u = reg["unified"]
    assert d["request_model"] is u["request_model"] is ReqModel
    assert d["response_model"] is u["response_model"] is RespModel


def test_no_deprecation_warning_when_mixed_style_raises() -> None:
    # A caller mixing unified and discrete parameters gets a ValueError; the
    # deprecation warning must not also fire in that case.
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with pytest.raises(ValueError, match="Cannot provide both"):

            @openapi(
                route="items",
                method="post",
                requests=ReqModel,
                request_model=ReqModel,
            )
            def handler(req: Any) -> Any:
                return req


def test_deprecation_warning_lists_names_comma_separated() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)

        @openapi(
            route="items",
            method="post",
            request_model=ReqModel,
            response_model=RespModel,
        )
        def handler(req: Any) -> Any:
            return req

    messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    assert messages, "expected a DeprecationWarning"
    message = messages[0]
    assert "request_model, response_model" in message
    # Must not be rendered as a Python list repr.
    assert "['" not in message
