"""Tests for the public exception hierarchy."""

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
