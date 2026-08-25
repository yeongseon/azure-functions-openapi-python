"""Tests for the ``responses=`` generic-shorthand container whitelist (#493).

Only container generics (``list``/``tuple``/``set``/``frozenset``/``dict`` and
their ``collections.abc`` equivalents) and unions/``Optional`` are accepted as a
bare response-body shorthand. Any other generic (most notably ``Callable``)
raises ``ValueError`` at decoration time so misuse fails fast instead of
producing a late or nonsensical schema at spec-generation time.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, Callable, Optional, Union
import warnings

from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    openapi,
)
from azure_functions_openapi.spec import generate_openapi_spec


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class Item(BaseModel):
    id: int
    name: str


def _register(status_value: Any) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @openapi(route="items", method="get", responses={200: status_value})
        def handler(req: Any) -> Any:  # pragma: no cover - never invoked
            return req


# ---------------------------------------------------------------------------
# Accepted container generics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "container",
    [
        list[Item],
        tuple[Item, ...],
        set[int],
        frozenset[int],
        Sequence[Item],
    ],
)
def test_container_generics_are_accepted(container: Any) -> None:
    _register(container)
    spec = generate_openapi_spec(route_prefix="")
    schema = spec["paths"]["/items"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    # Sequence-like containers resolve to an array schema.
    assert schema.get("type") == "array"


def test_dict_generic_is_accepted() -> None:
    _register(dict[str, Item])
    spec = generate_openapi_spec(route_prefix="")
    schema = spec["paths"]["/items"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert schema.get("type") == "object"


@pytest.mark.parametrize("union", [Optional[Item], Union[Item, int]])
def test_union_and_optional_are_accepted(union: Any) -> None:
    # Unions/Optional resolve without raising; the concrete schema shape is
    # owned by TypeAdapter and not asserted here.
    _register(union)
    spec = generate_openapi_spec(route_prefix="")
    assert (
        "schema"
        in spec["paths"]["/items"]["get"]["responses"]["200"]["content"]["application/json"]
    )


# ---------------------------------------------------------------------------
# Rejected non-container generics — must fail at decoration time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unsupported",
    [
        Callable[[int], str],
        Iterator[int],
    ],
)
def test_unsupported_generics_raise_at_decoration_time(unsupported: Any) -> None:
    with pytest.raises(ValueError, match="unsupported generic origin"):
        _register(unsupported)


def test_rejection_message_is_actionable() -> None:
    with pytest.raises(ValueError) as excinfo:
        _register(Callable[[int], str])
    message = str(excinfo.value)
    # Names the offending origin and points at the explicit-mapping escape hatch.
    assert "Callable" in message
    assert "Response Object mapping" in message


def test_plain_pydantic_model_still_accepted() -> None:
    # Regression: the non-generic model shorthand is unaffected by the guard.
    _register(Item)
    spec = generate_openapi_spec(route_prefix="")
    schema = spec["paths"]["/items"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert schema == {"$ref": "#/components/schemas/Item"}
