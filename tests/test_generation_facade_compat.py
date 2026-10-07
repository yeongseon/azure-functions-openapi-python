from __future__ import annotations

from collections.abc import Callable
import importlib
from types import ModuleType

import pytest

import azure_functions_openapi as package_api
from azure_functions_openapi.exceptions import OpenAPISpecConfigError


@pytest.fixture(scope="module")
def root_api() -> ModuleType:
    return package_api


@pytest.fixture(scope="module")
def shim_api() -> ModuleType:
    with pytest.warns(DeprecationWarning):
        return importlib.import_module("azure_functions_openapi.openapi")


@pytest.mark.parametrize("module_fixture", ["root_api", "shim_api"])
@pytest.mark.parametrize(
    ("function_name", "message"),
    [
        ("get_openapi_json", "Failed to generate OpenAPI JSON"),
        ("get_openapi_yaml", "Failed to generate OpenAPI YAML"),
    ],
)
def test_serialization_facades_wrap_unexpected_generation_errors(
    module_fixture: str,
    function_name: str,
    message: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: spec generation fails unexpectedly through a public facade import.
    module = request.getfixturevalue(module_fixture)
    cause = TypeError("unexpected generation failure")

    def fail_generation(*args: object, **kwargs: object) -> dict[str, object]:
        raise cause

    monkeypatch.setattr(package_api, "generate_openapi_spec", fail_generation)
    facade: Callable[[], str] = getattr(module, function_name)

    # When: the facade generates serialized output.
    with pytest.raises(RuntimeError, match=f"^{message}$") as exc_info:
        facade()

    # Then: it preserves the historical RuntimeError contract and cause.
    assert exc_info.value.__cause__ is cause


@pytest.mark.parametrize("module_fixture", ["root_api", "shim_api"])
@pytest.mark.parametrize("function_name", ["get_openapi_json", "get_openapi_yaml"])
def test_serialization_facades_preserve_configuration_errors(
    module_fixture: str,
    function_name: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: spec generation reports a caller-fixable configuration error.
    module = request.getfixturevalue(module_fixture)
    error = OpenAPISpecConfigError("invalid configuration")

    def fail_generation(*args: object, **kwargs: object) -> dict[str, object]:
        raise error

    monkeypatch.setattr(package_api, "generate_openapi_spec", fail_generation)
    facade: Callable[[], str] = getattr(module, function_name)

    # When/Then: the facade passes the original typed error through unchanged.
    with pytest.raises(OpenAPISpecConfigError) as exc_info:
        facade()
    assert exc_info.value is error


@pytest.mark.parametrize("module_fixture", ["root_api", "shim_api"])
@pytest.mark.parametrize(
    ("function_name", "message"),
    [
        ("get_openapi_json", "Failed to generate OpenAPI JSON"),
        ("get_openapi_yaml", "Failed to generate OpenAPI YAML"),
    ],
)
def test_serialization_facades_wrap_plain_value_errors(
    module_fixture: str,
    function_name: str,
    message: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: spec generation raises a plain ValueError (not a config error).
    module = request.getfixturevalue(module_fixture)
    cause = ValueError("plain value error")

    def fail_generation(*args: object, **kwargs: object) -> dict[str, object]:
        raise cause

    monkeypatch.setattr(package_api, "generate_openapi_spec", fail_generation)
    facade: Callable[[], str] = getattr(module, function_name)

    # When/Then: it is wrapped exactly like the low-level spec.py facades.
    with pytest.raises(RuntimeError, match=f"^{message}$") as exc_info:
        facade()
    assert exc_info.value.__cause__ is cause
