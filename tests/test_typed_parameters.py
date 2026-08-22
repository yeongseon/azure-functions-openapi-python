from __future__ import annotations

from enum import Enum
from typing import Optional

import azure.functions as func
from pydantic import BaseModel, Field
import pytest

from azure_functions_openapi.decorator import (
    _expand_model_parameters,
    _merge_typed_parameters,
    clear_openapi_registry,
    openapi,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.spec import generate_openapi_spec


class Color(str, Enum):
    red = "red"
    blue = "blue"


class PathModel(BaseModel):
    id: int
    color: Color


class HeaderModel(BaseModel):
    x_request_id: str = Field(alias="X-Request-Id")
    x_trace: Optional[str] = None
    verbose: bool = Field(default=False, description="Enable verbose output")


class TestExpandModelParameters:
    def test_path_fields_are_all_required(self) -> None:
        params = _expand_model_parameters(PathModel, "path", "h")
        assert [p["name"] for p in params] == ["id", "color"]
        assert all(p["in"] == "path" for p in params)
        assert all(p["required"] is True for p in params)

    def test_enum_field_is_inlined_not_ref(self) -> None:
        params = _expand_model_parameters(PathModel, "path", "h")
        color = next(p for p in params if p["name"] == "color")
        assert "$ref" not in color["schema"]
        assert color["schema"]["enum"] == ["red", "blue"]

    def test_scalar_schema_is_preserved(self) -> None:
        params = _expand_model_parameters(PathModel, "path", "h")
        ident = next(p for p in params if p["name"] == "id")
        assert ident["schema"] == {"type": "integer"}

    def test_header_alias_becomes_parameter_name(self) -> None:
        params = _expand_model_parameters(HeaderModel, "header", "h")
        names = [p["name"] for p in params]
        assert "X-Request-Id" in names
        assert "x_request_id" not in names

    def test_header_requiredness_follows_model(self) -> None:
        params = _expand_model_parameters(HeaderModel, "header", "h")
        by_name = {p["name"]: p for p in params}
        assert by_name["X-Request-Id"]["required"] is True
        assert by_name["x_trace"]["required"] is False
        assert by_name["verbose"]["required"] is False

    def test_description_flows_to_parameter_level(self) -> None:
        params = _expand_model_parameters(HeaderModel, "header", "h")
        verbose = next(p for p in params if p["name"] == "verbose")
        assert verbose["description"] == "Enable verbose output"
        assert "description" not in verbose["schema"]

    def test_none_model_returns_empty(self) -> None:
        assert _expand_model_parameters(None, "path", "h") == []

    def test_non_model_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Pydantic BaseModel"):
            _expand_model_parameters(dict, "path", "h")  # type: ignore[arg-type]

    def test_nested_object_field_rejected(self) -> None:
        class Nested(BaseModel):
            inner: PathModel

        with pytest.raises(OpenAPISpecConfigError, match="object schema"):
            _expand_model_parameters(Nested, "path", "h")

    def test_array_of_scalars_allowed(self) -> None:
        class Q(BaseModel):
            ids: list[int]

        params = _expand_model_parameters(Q, "header", "h")
        assert params[0]["schema"]["type"] == "array"
        assert params[0]["schema"]["items"] == {"type": "integer"}

    def test_array_of_objects_rejected(self) -> None:
        class Q(BaseModel):
            rows: list[PathModel]

        with pytest.raises(OpenAPISpecConfigError, match="object schema"):
            _expand_model_parameters(Q, "header", "h")


class TestMergeTypedParameters:
    def test_no_typed_models_returns_base_unchanged(self) -> None:
        base = [{"name": "q", "in": "query", "schema": {"type": "string"}}]
        assert _merge_typed_parameters(base, None, None, "h") is base

    def test_typed_params_appended_to_base(self) -> None:
        base = [{"name": "q", "in": "query", "schema": {"type": "string"}}]
        merged = _merge_typed_parameters(base, PathModel, None, "h")
        assert len(merged) == 3
        assert {p["name"] for p in merged} == {"q", "id", "color"}

    def test_same_name_different_location_is_allowed(self) -> None:
        class P(BaseModel):
            token: str

        class H(BaseModel):
            token: str

        merged = _merge_typed_parameters([], P, H, "h")
        locations = {(p["name"], p["in"]) for p in merged}
        assert locations == {("token", "path"), ("token", "header")}

    def test_collision_with_raw_parameters_fails_fast(self) -> None:
        base = [{"name": "id", "in": "path", "schema": {"type": "string"}}]
        with pytest.raises(OpenAPISpecConfigError, match="Duplicate parameter"):
            _merge_typed_parameters(base, PathModel, None, "h")


class TestIntegration:
    def teardown_method(self) -> None:
        clear_openapi_registry()

    def test_spec_includes_typed_path_and_header_params(self) -> None:
        clear_openapi_registry()
        app = func.FunctionApp()

        @openapi(summary="get item", path=PathModel, headers=HeaderModel)
        @app.route(route="items/{id}", methods=["GET"])
        def handler(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
            return func.HttpResponse("ok")

        spec = generate_openapi_spec()
        key = next(k for k in spec["paths"] if k.endswith("/items/{id}"))
        params = spec["paths"][key]["get"]["parameters"]
        by_name = {p["name"]: p for p in params}
        assert by_name["id"]["in"] == "path"
        assert by_name["id"]["required"] is True
        assert by_name["X-Request-Id"]["in"] == "header"

    def test_typed_and_raw_parameters_merge_in_spec(self) -> None:
        clear_openapi_registry()
        app = func.FunctionApp()

        @openapi(
            summary="list",
            parameters=[{"name": "q", "in": "query", "schema": {"type": "string"}}],
            headers=HeaderModel,
        )
        @app.route(route="search", methods=["GET"])
        def handler(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
            return func.HttpResponse("ok")

        spec = generate_openapi_spec()
        key = next(k for k in spec["paths"] if k.endswith("/search"))
        names = {p["name"] for p in spec["paths"][key]["get"]["parameters"]}
        assert "q" in names
        assert "X-Request-Id" in names
