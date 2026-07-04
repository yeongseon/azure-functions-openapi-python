# tests/test_sdk_compat.py
"""SDK shape sanity tests for azure-functions.

These tests assert that the azure-functions SDK internals we depend on —
namely ``FunctionBuilder._function._func`` and ``FunctionBuilder._function._bindings``
— are present and usable in the currently installed SDK.

They act as an early-warning tripwire in CI: any SDK release that removes,
renames, or restructures these private attributes will fail here loudly
(with a message pointing at the tracking issue) before end-users are
impacted at import time.

Companion issue: https://github.com/yeongseon/azure-functions-openapi-python/issues/258
"""

from __future__ import annotations

import importlib.metadata as _metadata

import azure.functions as func
from azure.functions.decorators.function_app import FunctionBuilder

from azure_functions_openapi.decorator import (
    _extract_binding_hints,
    _resolve_metadata_target,
)


def test_installed_azure_functions_version_meets_pin() -> None:
    """The installed SDK must satisfy the ``>=1.19.0,<2.0.0`` pin from pyproject.toml.

    This catches accidental downgrades in dev environments and confirms that
    the CI matrix installed the version it intended to.
    """
    installed = _metadata.version("azure-functions")
    major_minor = tuple(int(p) for p in installed.split(".")[:2])
    assert major_minor >= (1, 19), (
        f"azure-functions {installed} is below the >=1.19.0 pin declared in "
        "pyproject.toml. Update the pin or bump the installed version."
    )
    assert major_minor < (2, 0), (
        f"azure-functions {installed} is above the <2.0.0 pin declared in "
        "pyproject.toml. See issue #258 before widening the ceiling."
    )


def test_function_builder_exposes_private_attributes_we_depend_on() -> None:
    """Direct existence assertion for ``FunctionBuilder._function._func``
    and ``._bindings``.

    ``decorator._resolve_metadata_target`` reads ``_function._func`` and
    ``decorator._extract_binding_hints`` reads ``_function._bindings``.
    If the SDK renames/removes either attribute, this test fails immediately
    with an actionable message pointing at issue #258.
    """
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="sdk_shape_probe", methods=["GET"])
    def sdk_shape_probe(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=200)

    assert isinstance(sdk_shape_probe, FunctionBuilder), (
        "app.route no longer returns FunctionBuilder — SDK internal shape "
        "has changed. See issue #258."
    )
    assert hasattr(sdk_shape_probe, "_function"), (
        "FunctionBuilder no longer exposes '_function' — SDK internal "
        "shape has changed. See issue #258."
    )
    assert hasattr(sdk_shape_probe._function, "_func"), (
        "FunctionBuilder._function no longer exposes '_func' — SDK "
        "internal shape has changed. See issue #258."
    )
    assert hasattr(sdk_shape_probe._function, "_bindings"), (
        "FunctionBuilder._function no longer exposes '_bindings' — SDK "
        "internal shape has changed. See issue #258."
    )


def test_resolve_metadata_target_returns_original_and_callable() -> None:
    """``_resolve_metadata_target`` must extract the underlying callable
    from a real ``FunctionBuilder`` produced by the current SDK."""
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="resolve_probe", methods=["GET"])
    def resolve_probe(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=200)

    original, extracted_callable = _resolve_metadata_target(resolve_probe)
    assert original is resolve_probe
    assert callable(extracted_callable)
    assert extracted_callable.__name__ == "resolve_probe"


def test_extract_binding_hints_reads_route_and_method_from_real_binding() -> None:
    """``_extract_binding_hints`` must read the httptrigger binding produced
    by the current SDK and return ``(route, method, multiple_methods)``.

    This exercises the full integration between the SDK's binding shape
    (``binding.type``, ``binding.route``, ``binding.methods``) and our
    extraction logic.
    """
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="items/{id}", methods=["PUT"])
    def update_item(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=200)

    route, method, multi = _extract_binding_hints(update_item)
    assert route == "items/{id}"
    assert method == "put"
    assert multi is False


def test_extract_binding_hints_signals_multiple_methods_from_real_binding() -> None:
    """``_extract_binding_hints`` must set the ``multi`` flag when the binding
    declares more than one HTTP method.

    The ``decorator.openapi`` decorator relies on this flag to raise
    ``OpenAPISpecConfigError`` for ambiguous bindings — if the SDK ever
    normalizes multi-method bindings differently, this test catches it.
    """
    app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

    @app.route(route="collection", methods=["GET", "POST"])
    def collection(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("OK", status_code=200)

    route, method, multi = _extract_binding_hints(collection)
    assert route == "collection"
    assert method is None
    assert multi is True
