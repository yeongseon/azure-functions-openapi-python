# tests/test_validate_http_shorthand_conflict.py
"""Real @validate_http integration: requests=/responses= model shorthand vs
the raw schema @validate_http discovers (issue #780).

@openapi(requests=Model, responses=Model) stores the class under
request_model/response_model. @validate_http's endpoint convention always
reports a compiled raw request_body/response schema. Before this fix,
_find_model_conflict() only ever compared request_model-vs-request_model,
request_body-vs-request_body, and response-vs-response -- so an authored
model that disagreed with the validated body/response was silently
discarded by generation rather than rejected at scan time. These tests run
against the real companion package end to end.
"""

from __future__ import annotations

import importlib
from typing import Any

import azure.functions as func
from pydantic import BaseModel
import pytest

from azure_functions_openapi import (
    clear_openapi_registry,
    generate_openapi_spec,
    openapi,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError

try:
    importlib.import_module("azure_functions_validation")
    HAS_VALIDATION = True
except ImportError:
    HAS_VALIDATION = False

pytestmark = pytest.mark.skipif(
    not HAS_VALIDATION,
    reason="azure-functions-validation not installed",
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class _Authored(BaseModel):
    customer_id: int


class _Validated(BaseModel):
    email: str


class _OtherValidated(BaseModel):
    other: str


@pytest.mark.parametrize(
    "openapi_above_route", [True, False], ids=["openapi-above", "openapi-below"]
)
def test_conflicting_request_model_shorthand_raises(openapi_above_route: bool) -> None:
    from azure_functions_validation import validate_http

    app = func.FunctionApp()

    if openapi_above_route:

        @openapi(requests=_Authored)
        @app.route(route="orders", methods=["POST"])
        @validate_http(body=_Validated)
        def orders(req: Any, body: Any) -> Any:
            return body
    else:

        @app.route(route="orders", methods=["POST"])
        @openapi(requests=_Authored)
        @validate_http(body=_Validated)
        def orders(req: Any, body: Any) -> Any:  # noqa: F811
            return body

    with pytest.raises(OpenAPISpecConfigError, match="Conflicting request body"):
        generate_openapi_spec(app=app, strict=True)


def test_conflicting_response_model_shorthand_raises() -> None:
    from azure_functions_validation import validate_http

    app = func.FunctionApp()

    @openapi(responses=_Authored)
    @app.route(route="orders", methods=["GET"])
    @validate_http(response_model=_Validated)
    def orders(req: Any) -> Any: ...

    with pytest.raises(OpenAPISpecConfigError, match="Conflicting status 200"):
        generate_openapi_spec(app=app, strict=True)


def test_request_conflict_detected_even_when_response_matches() -> None:
    from azure_functions_validation import validate_http

    app = func.FunctionApp()

    @openapi(requests=_Authored, responses=_Validated)
    @app.route(route="orders", methods=["POST"])
    @validate_http(body=_Validated, response_model=_Validated)
    def orders(req: Any, body: Any) -> Any:
        return body

    with pytest.raises(OpenAPISpecConfigError, match="Conflicting request body"):
        generate_openapi_spec(app=app, strict=True)


def test_response_conflict_detected_even_when_request_matches() -> None:
    from azure_functions_validation import validate_http

    app = func.FunctionApp()

    @openapi(requests=_Validated, responses=_Authored)
    @app.route(route="orders", methods=["POST"])
    @validate_http(body=_Validated, response_model=_OtherValidated)
    def orders(req: Any, body: Any) -> Any:
        return body

    with pytest.raises(OpenAPISpecConfigError, match="Conflicting status 200"):
        generate_openapi_spec(app=app, strict=True)


def test_equivalent_model_declared_through_both_decorators_merges() -> None:
    from azure_functions_validation import validate_http

    app = func.FunctionApp()

    @openapi(requests=_Validated, responses=_Validated)
    @app.route(route="orders", methods=["POST"])
    @validate_http(body=_Validated, response_model=_Validated)
    def orders(req: Any, body: Any) -> Any:
        return body

    spec = generate_openapi_spec(app=app, strict=True)
    operation = spec["paths"]["/api/orders"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert "email" in request_schema["properties"]
    assert "email" in response_schema["properties"]


def test_inferred_response_is_still_superseded_by_validation_metadata() -> None:
    from azure_functions_validation import validate_http

    app = func.FunctionApp()

    @openapi()
    @app.route(route="orders", methods=["GET"])
    @validate_http(response_model=_Validated)
    def orders(req: Any) -> _Authored:
        raise NotImplementedError

    spec = generate_openapi_spec(app=app, strict=True)
    schema = spec["paths"]["/api/orders"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert "email" in schema["properties"]
    assert "customer_id" not in schema["properties"]
