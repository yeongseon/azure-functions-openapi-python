"""Tests for the public exception hierarchy."""

import pytest

from azure_functions_openapi.exceptions import (
    OpenAPISpecConfigError,
    SDKIncompatibleError,
)


def test_openapi_spec_config_error_preserves_value_error_behaviour() -> None:
    error = OpenAPISpecConfigError("invalid OpenAPI configuration")

    assert isinstance(error, ValueError)
    assert str(error) == "invalid OpenAPI configuration"


def test_sdk_incompatible_error_is_a_config_error() -> None:
    error = SDKIncompatibleError("unsupported azure-functions SDK")

    assert isinstance(error, OpenAPISpecConfigError)
    assert isinstance(error, ValueError)
    assert str(error) == "unsupported azure-functions SDK"


def test_unsupported_route_template_error_supports_notes_and_stays_read_only() -> None:
    import dataclasses

    from azure_functions_openapi.exceptions import UnsupportedRouteTemplateError

    err = UnsupportedRouteTemplateError("fn", "items/{x:guid}", "x:guid")
    err.add_note("context")
    assert err.__notes__ == ["context"]
    assert isinstance(err, ValueError)
    assert "x:guid" in str(err)
    with pytest.raises(dataclasses.FrozenInstanceError):
        err.route = "other"  # type: ignore[misc]
    assert hash(err) == hash(UnsupportedRouteTemplateError("fn", "items/{x:guid}", "x:guid"))

    try:
        try:
            raise err
        except UnsupportedRouteTemplateError as caught:
            caught.add_note("more")
            raise
    except UnsupportedRouteTemplateError as final:
        assert final is err
        assert final.__traceback__ is not None
        assert final.__notes__ == ["context", "more"]
