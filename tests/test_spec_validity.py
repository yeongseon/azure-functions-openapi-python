# tests/test_spec_validity.py
"""Validate generated OpenAPI specs against the official OpenAPI spec validator.

These tests ensure the library produces VALID OpenAPI documents, not just
dicts that match our expectations. This catches subtle schema incompatibilities
(e.g., Pydantic v2 anyOf in 3.0 mode, missing required fields, etc.).
"""

from __future__ import annotations

import json
from typing import Any

from openapi_spec_validator import validate
from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import _openapi_registry, _registry_lock, openapi
from azure_functions_openapi.spec import generate_openapi_spec


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    """Clear registry before/after each test."""
    with _registry_lock:
        _openapi_registry.clear()
    yield
    with _registry_lock:
        _openapi_registry.clear()


class SimpleModel(BaseModel):
    name: str
    age: int


class NullableModel(BaseModel):
    """Model with optional/nullable fields — Pydantic v2 generates anyOf."""

    name: str
    nickname: str | None = None
    score: int | None = None


class NestedModel(BaseModel):
    user: SimpleModel
    tags: list[str] = []


# --- OpenAPI 3.1 validity tests ---


class TestSpecValidity31:
    """Validate generated specs are valid OpenAPI 3.1.0."""

    def test_simple_get_endpoint(self) -> None:
        @openapi(route="/items", method="get", summary="List items")
        def list_items() -> None:
            pass

        spec = generate_openapi_spec(title="Test API", version="1.0.0", route_prefix="")
        validate(spec)

    def test_path_parameters(self) -> None:
        @openapi(
            route="/items/{id}",
            method="get",
            summary="Get item",
            parameters=[
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
        )
        def get_item() -> None:
            pass

        spec = generate_openapi_spec(title="Test API", version="1.0.0", route_prefix="")
        validate(spec)

    def test_request_model(self) -> None:
        @openapi(
            route="/items",
            method="post",
            summary="Create item",
            requests=SimpleModel,
            responses={201: {"description": "Created"}},
        )
        def create_item() -> None:
            pass

        spec = generate_openapi_spec(title="Test API", version="1.0.0", route_prefix="")
        validate(spec)

    def test_response_model(self) -> None:
        @openapi(
            route="/items/{id}",
            method="get",
            summary="Get item",
            parameters=[
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            responses=SimpleModel,
        )
        def get_item() -> None:
            pass

        spec = generate_openapi_spec(title="Test API", version="1.0.0", route_prefix="")
        validate(spec)

    def test_nullable_model_3_1(self) -> None:
        """Pydantic v2 nullable fields should produce valid OpenAPI 3.1."""

        @openapi(
            route="/users",
            method="post",
            summary="Create user",
            requests=NullableModel,
            responses=NullableModel,
        )
        def create_user() -> None:
            pass

        spec = generate_openapi_spec(title="Test API", version="1.0.0", route_prefix="")
        validate(spec)

    def test_nested_model(self) -> None:
        @openapi(
            route="/profiles",
            method="post",
            summary="Create profile",
            requests=NestedModel,
            responses=NestedModel,
        )
        def create_profile() -> None:
            pass

        spec = generate_openapi_spec(title="Test API", version="1.0.0", route_prefix="")
        validate(spec)

    def test_multiple_endpoints(self) -> None:
        @openapi(route="/items", method="get", summary="List items")
        def list_items() -> None:
            pass

        @openapi(
            route="/items",
            method="post",
            summary="Create item",
            requests=SimpleModel,
        )
        def create_item() -> None:
            pass

        @openapi(
            route="/items/{id}",
            method="get",
            summary="Get item",
            parameters=[
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            responses=SimpleModel,
        )
        def get_item() -> None:
            pass

        spec = generate_openapi_spec(title="Test API", version="1.0.0", route_prefix="")
        validate(spec)

    def test_security_scheme(self) -> None:
        @openapi(
            route="/secure",
            method="get",
            summary="Secure endpoint",
            security=[{"BearerAuth": []}],
            security_scheme={"BearerAuth": {"type": "http", "scheme": "bearer"}},
        )
        def secure_endpoint() -> None:
            pass

        spec = generate_openapi_spec(title="Test API", version="1.0.0", route_prefix="")
        validate(spec)

    def test_manual_request_body(self) -> None:
        @openapi(
            route="/items",
            method="post",
            summary="Create item",
            requests={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            responses={201: {"description": "Created"}},
        )
        def create_item() -> None:
            pass

        spec = generate_openapi_spec(title="Test API", version="1.0.0", route_prefix="")
        validate(spec)


# --- OpenAPI 3.0 validity tests ---


class TestSpecValidity30:
    """Validate generated specs are valid OpenAPI 3.0.0."""

    def test_simple_get_endpoint(self) -> None:
        @openapi(route="/items", method="get", summary="List items")
        def list_items() -> None:
            pass

        spec = generate_openapi_spec(
            title="Test API",
            version="1.0.0",
            openapi_version="3.0.0",
            route_prefix="",
        )
        validate(spec)

    def test_manual_request_body_3_0(self) -> None:
        """Manual dict schemas should produce valid 3.0 spec."""

        @openapi(
            route="/items",
            method="post",
            summary="Create item",
            requests={
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
            responses={200: {"description": "OK"}},
        )
        def create_item() -> None:
            pass

        spec = generate_openapi_spec(
            title="Test API",
            version="1.0.0",
            openapi_version="3.0.0",
            route_prefix="",
        )
        validate(spec)

    def test_path_parameters_3_0(self) -> None:
        @openapi(
            route="/items/{id}",
            method="get",
            summary="Get item",
            parameters=[
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
        )
        def get_item() -> None:
            pass

        spec = generate_openapi_spec(
            title="Test API",
            version="1.0.0",
            openapi_version="3.0.0",
            route_prefix="",
        )
        validate(spec)


# --- OpenAPI 3.0 + Pydantic v2 compatibility tests ---


class TestPydanticV2Compat30:
    """Pydantic v2 models with nullable fields down-convert to valid 3.0 (#562)."""

    def test_nullable_model_3_0_strict_downconverts(self) -> None:
        """Strict mode down-converts Pydantic nullable schema to valid 3.0 (#562)."""

        @openapi(
            route="/users",
            method="post",
            summary="Create user",
            requests=NullableModel,
        )
        def create_user() -> None:
            pass

        # #562: nullable fields are down-converted to ``nullable: true`` form,
        # so strict mode produces a valid 3.0 document instead of raising.
        spec = generate_openapi_spec(
            title="Test",
            version="1.0.0",
            openapi_version="3.0.0",
            route_prefix="",
            strict=True,
        )
        assert spec["openapi"] == "3.0.0"
        props = spec["components"]["schemas"]["NullableModel"]["properties"]
        nickname = props["nickname"]
        assert nickname["type"] == "string"
        assert nickname["nullable"] is True
        assert "anyOf" not in nickname
        score = props["score"]
        assert score["type"] == "integer"
        assert score["nullable"] is True
        assert "anyOf" not in score
        # No 3.1-only null sentinel leaks into the 3.0 document.
        assert '"type": "null"' not in json.dumps(spec)

    def test_nullable_model_3_0_non_strict_warns(self) -> None:
        """Non-strict mode also down-converts and generates a valid 3.0 spec."""

        @openapi(
            route="/users",
            method="post",
            summary="Create user",
            requests=NullableModel,
        )
        def create_user() -> None:
            pass

        # Non-strict: down-converts to valid 3.0 (no raise, no warning)
        spec = generate_openapi_spec(
            title="Test",
            version="1.0.0",
            openapi_version="3.0.0",
            route_prefix="",
            strict=False,
        )
        # Spec is generated (user was warned via logger)
        assert spec["openapi"] == "3.0.0"
        assert "/users" in spec["paths"]

    def test_simple_model_3_0_no_error(self) -> None:
        """Models without nullable fields work fine in 3.0."""

        @openapi(
            route="/items",
            method="post",
            summary="Create item",
            requests=SimpleModel,
        )
        def create_item() -> None:
            pass

        spec = generate_openapi_spec(
            title="Test",
            version="1.0.0",
            openapi_version="3.0.0",
            route_prefix="",
            strict=True,
        )
        assert spec["openapi"] == "3.0.0"
        assert "/items" in spec["paths"]


class TestInlineSchemaConversion31:
    """Verify inline schemas (requestBody, responses) are converted in 3.1 mode."""

    def test_inline_nullable_converted_in_3_1(self) -> None:
        """Manual request_body with nullable:true gets converted to type array in 3.1."""

        @openapi(
            route="/items",
            method="post",
            summary="Create item",
            requests={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "nullable": True},
                },
            },
            responses={200: {"description": "OK"}},
        )
        def create_item() -> None:
            pass

        spec = generate_openapi_spec(title="Test", version="1.0.0", route_prefix="")

        # In 3.1, nullable should be converted to type array
        schema = spec["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"][
            "schema"
        ]
        name_prop = schema["properties"]["name"]
        assert "nullable" not in name_prop
        assert name_prop["type"] == ["string", "null"]

    def test_inline_param_schema_converted_in_3_1(self) -> None:
        """Parameter schema with nullable:true gets converted in 3.1."""

        @openapi(
            route="/items",
            method="get",
            summary="List items",
            parameters=[
                {
                    "name": "filter",
                    "in": "query",
                    "schema": {"type": "string", "nullable": True},
                }
            ],
        )
        def list_items() -> None:
            pass

        spec = generate_openapi_spec(title="Test", version="1.0.0", route_prefix="")

        param_schema = spec["paths"]["/items"]["get"]["parameters"][0]["schema"]
        assert "nullable" not in param_schema
        assert param_schema["type"] == ["string", "null"]
