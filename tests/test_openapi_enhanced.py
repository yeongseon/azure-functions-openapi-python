# tests/test_openapi_enhanced.py

import importlib
from typing import Any, Dict
from unittest.mock import patch

from pydantic import BaseModel, Field
import pytest

from azure_functions_openapi.spec import (
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
)

OPENAPI_MODULE = importlib.import_module("azure_functions_openapi.spec")


class SampleRequestModel(BaseModel):
    """Sample request model."""

    name: str = Field(..., description="The name")
    age: int = Field(default=18, description="The age")


class SampleResponseModel(BaseModel):
    """Sample response model."""

    id: int = Field(..., description="The ID")
    name: str = Field(..., description="The name")
    age: int = Field(..., description="The age")


class TestGenerateOpenAPISpecEnhanced:
    """Test enhanced generate_openapi_spec function."""

    def test_generate_openapi_spec_with_error_handling(self) -> None:
        """Test OpenAPI spec generation with error handling."""
        # Mock registry with problematic function
        mock_registry: Dict[str, Any] = {
            "test_func": {
                "summary": "Test function",
                "description": "A test function",
                "tags": ["test"],
                "operation_id": "test_operation",
                "route": "/test",
                "method": "get",
                "parameters": [],
                "request_model": None,
                "request_body": None,
                "response_model": None,
                "response": {},
            }
        }

        with patch.object(OPENAPI_MODULE, "get_openapi_registry", return_value=mock_registry):
            spec = generate_openapi_spec("Test API", "1.0.0", route_prefix="")

            assert spec["openapi"] == "3.0.0"
            assert spec["info"]["title"] == "Test API"
            assert spec["info"]["version"] == "1.0.0"
            assert "/test" in spec["paths"]
            assert "get" in spec["paths"]["/test"]

    def test_generate_openapi_spec_with_model_errors(self) -> None:
        """Test OpenAPI spec generation when model schema generation fails."""
        mock_registry: Dict[str, Any] = {
            "test_func": {
                "summary": "Test function",
                "description": "A test function",
                "tags": ["test"],
                "operation_id": "test_operation",
                "route": "/test",
                "method": "post",
                "parameters": [],
                "request_model": SampleRequestModel,
                "request_body": None,
                "response_model": SampleResponseModel,
                "response": {},
            }
        }

        with patch.object(OPENAPI_MODULE, "get_openapi_registry", return_value=mock_registry):
            with patch.object(OPENAPI_MODULE, "model_to_schema") as mock_model_to_schema:
                # First call succeeds, second call fails
                mock_model_to_schema.side_effect = [{"type": "object"}, Exception("Schema error")]

                spec = generate_openapi_spec("Test API", "1.0.0", route_prefix="")

                assert spec["openapi"] == "3.0.0"
                assert "/test" in spec["paths"]
                assert "post" in spec["paths"]["/test"]

                # Should have fallback schema for response
                post_op = spec["paths"]["/test"]["post"]
                assert "requestBody" in post_op
                assert "responses" in post_op
                assert "200" in post_op["responses"]

    def test_generate_openapi_spec_with_function_processing_error(self) -> None:
        """Test OpenAPI spec generation when individual function processing fails."""
        mock_registry: Dict[str, Any] = {
            "good_func": {
                "summary": "Good function",
                "description": "A good function",
                "tags": ["test"],
                "operation_id": "good_operation",
                "route": "/good",
                "method": "get",
                "parameters": [],
                "request_model": None,
                "request_body": None,
                "response_model": None,
                "response": {},
            },
            "bad_func": {
                "summary": "Bad function",
                "description": "A bad function",
                "tags": ["test"],
                "operation_id": "bad_operation",
                "route": "/bad",
                "method": "get",
                "parameters": [],
                "request_model": None,
                "request_body": None,
                "response_model": None,
                "response": {},
            },
        }

        with patch.object(OPENAPI_MODULE, "get_openapi_registry", return_value=mock_registry):
            with patch.object(OPENAPI_MODULE, "logger"):
                # Mock the processing to fail for bad_func
                original_spec = generate_openapi_spec("Test API", "1.0.0", route_prefix="")

                # Should still generate spec for good functions
                assert original_spec["openapi"] == "3.0.0"
                assert "/good" in original_spec["paths"]
                # bad_func might be excluded due to processing error

    def test_generate_openapi_spec_general_error(self) -> None:
        """Test OpenAPI spec generation with general error."""
        with patch.object(OPENAPI_MODULE, "get_openapi_registry") as mock_registry:
            mock_registry.side_effect = Exception("Registry error")

            with pytest.raises(RuntimeError) as exc_info:
                generate_openapi_spec("Test API", "1.0.0")

            assert "Failed to generate OpenAPI specification" in str(exc_info.value)
            assert "Registry error" in str(exc_info.value.__cause__)

    def test_generate_openapi_spec_logging(self) -> None:
        """Test that OpenAPI spec generation logs correctly."""
        mock_registry: Dict[str, Any] = {
            "func1": {"summary": "Function 1", "route": "/func1", "method": "get"},
            "func2": {"summary": "Function 2", "route": "/func2", "method": "post"},
        }

        with patch.object(OPENAPI_MODULE, "get_openapi_registry", return_value=mock_registry):
            with patch.object(OPENAPI_MODULE, "logger") as mock_logger:
                generate_openapi_spec("Test API", "1.0.0")

                # Should log successful generation
                mock_logger.info.assert_called_once()
                call_args = mock_logger.info.call_args[0][0]
                assert "Generated OpenAPI" in call_args
                assert "2 paths" in call_args
                assert "2 functions" in call_args


class TestGetOpenAPIJSONEnhanced:
    """Test enhanced get_openapi_json function."""

    def test_get_openapi_json_success(self) -> None:
        """Test successful JSON generation."""
        with patch.object(OPENAPI_MODULE, "generate_openapi_spec") as mock_generate:
            mock_generate.return_value = {"openapi": "3.0.0", "info": {"title": "Test API"}}

            result = get_openapi_json("Test API", "1.0.0")

            assert (
                result == '{\n  "openapi": "3.0.0",\n  "info": {\n    "title": "Test API"\n  }\n}'
            )
            mock_generate.assert_called_once_with(
                "Test API",
                "1.0.0",
                "3.0.0",
                description="Auto-generated OpenAPI documentation. "
                "Markdown supported in descriptions (CommonMark).",
                security_schemes=None,
                route_prefix="/api",
                strict=False,
            )

    def test_get_openapi_json_error(self) -> None:
        """Test JSON generation with error."""
        with patch.object(OPENAPI_MODULE, "generate_openapi_spec") as mock_generate:
            mock_generate.side_effect = Exception("Spec error")

            with pytest.raises(RuntimeError) as exc_info:
                get_openapi_json("Test API", "1.0.0")

            assert "Failed to generate OpenAPI JSON" in str(exc_info.value)
            assert "Spec error" in str(exc_info.value.__cause__)

    def test_get_openapi_json_passes_custom_description(self) -> None:
        """Test custom description forwarding for JSON generation."""
        with patch.object(OPENAPI_MODULE, "generate_openapi_spec") as mock_generate:
            mock_generate.return_value = {"openapi": "3.0.0", "info": {"title": "Test API"}}

            get_openapi_json("Test API", "1.0.0", description="Custom description")

            mock_generate.assert_called_once_with(
                "Test API",
                "1.0.0",
                "3.0.0",
                description="Custom description",
                security_schemes=None,
                route_prefix="/api",
                strict=False,
            )

    def test_get_openapi_json_logging(self) -> None:
        """Test that JSON generation logs errors."""
        with patch.object(OPENAPI_MODULE, "generate_openapi_spec") as mock_generate:
            mock_generate.side_effect = Exception("Spec error")

            with patch.object(OPENAPI_MODULE, "logger") as mock_logger:
                with pytest.raises(RuntimeError):
                    get_openapi_json("Test API", "1.0.0")

                mock_logger.error.assert_called_once()
                call_args = mock_logger.error.call_args[0][0]
                assert "Failed to generate OpenAPI JSON" in call_args


class TestGetOpenAPIYAMLEnhanced:
    """Test enhanced get_openapi_yaml function."""

    def test_get_openapi_yaml_success(self) -> None:
        """Test successful YAML generation."""
        with patch.object(OPENAPI_MODULE, "generate_openapi_spec") as mock_generate:
            mock_generate.return_value = {"openapi": "3.0.0", "info": {"title": "Test API"}}

            result = get_openapi_yaml("Test API", "1.0.0")

            assert "openapi: 3.0.0" in result
            assert "title: Test API" in result
            mock_generate.assert_called_once_with(
                "Test API",
                "1.0.0",
                "3.0.0",
                description="Auto-generated OpenAPI documentation. "
                "Markdown supported in descriptions (CommonMark).",
                security_schemes=None,
                route_prefix="/api",
                strict=False,
            )

    def test_get_openapi_yaml_error(self) -> None:
        """Test YAML generation with error."""
        with patch.object(OPENAPI_MODULE, "generate_openapi_spec") as mock_generate:
            mock_generate.side_effect = Exception("Spec error")

            with pytest.raises(RuntimeError) as exc_info:
                get_openapi_yaml("Test API", "1.0.0")

            assert "Failed to generate OpenAPI YAML" in str(exc_info.value)
            assert "Spec error" in str(exc_info.value.__cause__)

    def test_get_openapi_yaml_passes_custom_description(self) -> None:
        """Test custom description forwarding for YAML generation."""
        with patch.object(OPENAPI_MODULE, "generate_openapi_spec") as mock_generate:
            mock_generate.return_value = {"openapi": "3.0.0", "info": {"title": "Test API"}}

            get_openapi_yaml("Test API", "1.0.0", description="Custom description")

            mock_generate.assert_called_once_with(
                "Test API",
                "1.0.0",
                "3.0.0",
                description="Custom description",
                security_schemes=None,
                route_prefix="/api",
                strict=False,
            )

    def test_get_openapi_yaml_logging(self) -> None:
        """Test that YAML generation logs errors."""
        with patch.object(OPENAPI_MODULE, "generate_openapi_spec") as mock_generate:
            mock_generate.side_effect = Exception("Spec error")

            with patch.object(OPENAPI_MODULE, "logger") as mock_logger:
                with pytest.raises(RuntimeError):
                    get_openapi_yaml("Test API", "1.0.0")

                mock_logger.error.assert_called_once()
                call_args = mock_logger.error.call_args[0][0]
                assert "Failed to generate OpenAPI YAML" in call_args


class TestOpenAPISpecComplexScenarios:
    """Test complex OpenAPI spec generation scenarios."""

    def test_generate_openapi_spec_with_all_components(self) -> None:
        """Test OpenAPI spec generation with all components."""
        mock_registry: Dict[str, Any] = {
            "complex_func": {
                "summary": "Complex function",
                "description": "A complex function with all features",
                "tags": ["complex", "test"],
                "operation_id": "complex_operation",
                "route": "/complex/{id}",
                "method": "put",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                ],
                "request_model": SampleRequestModel,
                "request_body": None,
                "response_model": SampleResponseModel,
                "response": {
                    400: {"description": "Bad Request"},
                    404: {"description": "Not Found"},
                    500: {"description": "Internal Server Error"},
                },
            }
        }

        with patch.object(OPENAPI_MODULE, "get_openapi_registry", return_value=mock_registry):
            with patch.object(OPENAPI_MODULE, "model_to_schema") as mock_model_to_schema:
                mock_model_to_schema.return_value = {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }

                spec = generate_openapi_spec("Complex API", "2.0.0", route_prefix="")

                assert spec["openapi"] == "3.0.0"
                assert spec["info"]["title"] == "Complex API"
                assert spec["info"]["version"] == "2.0.0"

                # Check path
                assert "/complex/{id}" in spec["paths"]
                put_op = spec["paths"]["/complex/{id}"]["put"]

                # Check operation details
                assert put_op["summary"] == "Complex function"
                assert put_op["description"] == "A complex function with all features"
                assert put_op["operationId"] == "complex_operation"
                assert put_op["tags"] == ["complex", "test"]

                # Check parameters
                assert len(put_op["parameters"]) == 2
                param_names = [p["name"] for p in put_op["parameters"]]
                assert "id" in param_names
                assert "limit" in param_names

                # Check request body
                assert "requestBody" in put_op
                assert put_op["requestBody"]["required"] is True

                # Check responses
                assert "200" in put_op["responses"]
                assert "400" in put_op["responses"]
                assert "404" in put_op["responses"]
                assert "500" in put_op["responses"]

    def test_generate_openapi_spec_multiple_methods_same_route(self) -> None:
        """Test OpenAPI spec generation with multiple methods on same route."""
        mock_registry: Dict[str, Any] = {
            "get_user": {
                "summary": "Get user",
                "route": "/users/{id}",
                "method": "get",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                ],
            },
            "update_user": {
                "summary": "Update user",
                "route": "/users/{id}",
                "method": "put",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                ],
                "request_model": SampleRequestModel,
            },
            "delete_user": {
                "summary": "Delete user",
                "route": "/users/{id}",
                "method": "delete",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                ],
            },
        }

        with patch.object(OPENAPI_MODULE, "get_openapi_registry", return_value=mock_registry):
            spec = generate_openapi_spec("User API", "1.0.0", route_prefix="")

            # Check that all methods are on the same path
            assert "/users/{id}" in spec["paths"]
            path_obj = spec["paths"]["/users/{id}"]

            assert "get" in path_obj
            assert "put" in path_obj
            assert "delete" in path_obj

            # Check method details
            assert path_obj["get"]["summary"] == "Get user"
            assert path_obj["put"]["summary"] == "Update user"
            assert path_obj["delete"]["summary"] == "Delete user"


class TestDeterministicOrdering:
    """Verify that paths and schemas are always sorted alphabetically."""

    def test_paths_are_sorted(self) -> None:
        """Paths in the spec must be in ascending alphabetical order."""
        mock_registry = {
            "func_z": {"route": "/z", "method": "get", "response": {}, "tags": ["t"]},
            "func_a": {"route": "/a", "method": "get", "response": {}, "tags": ["t"]},
            "func_m": {"route": "/m", "method": "get", "response": {}, "tags": ["t"]},
        }
        with patch.object(
            OPENAPI_MODULE,
            "get_openapi_registry",
            return_value=mock_registry,
        ):
            spec = generate_openapi_spec("Test", "1.0.0", route_prefix="")

        assert list(spec["paths"].keys()) == ["/a", "/m", "/z"]

    def test_schemas_are_sorted(self) -> None:
        """Component schemas must be in ascending alphabetical order."""
        from pydantic import BaseModel as PydanticModel

        class ZebraModel(PydanticModel):
            x: int

        class AppleModel(PydanticModel):
            y: str

        mock_registry = {
            "func_z": {
                "route": "/z",
                "method": "get",
                "response_model": ZebraModel,
                "response": {},
                "tags": ["t"],
            },
            "func_a": {
                "route": "/a",
                "method": "get",
                "response_model": AppleModel,
                "response": {},
                "tags": ["t"],
            },
        }
        with patch.object(
            OPENAPI_MODULE,
            "get_openapi_registry",
            return_value=mock_registry,
        ):
            spec = generate_openapi_spec("Test", "1.0.0", route_prefix="")

        schema_keys = list(spec["components"]["schemas"].keys())
        assert schema_keys == sorted(schema_keys)

    def test_empty_registry_produces_sorted_empty_paths(self) -> None:
        """Empty registry produces an empty (but sorted) paths dict."""
        with patch.object(
            OPENAPI_MODULE,
            "get_openapi_registry",
            return_value={},
        ):
            spec = generate_openapi_spec("Test", "1.0.0", route_prefix="")

        assert spec["paths"] == {}
