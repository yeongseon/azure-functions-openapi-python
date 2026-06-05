# tests/test_decorator_enhanced.py

from typing import Any, cast
from unittest.mock import patch

from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import (
    _validate_and_sanitize_operation_id,
    _validate_and_sanitize_route,
    _validate_models,
    _validate_parameters,
    _validate_security,
    _validate_security_scheme,
    _validate_tags,
    get_openapi_registry,
    openapi,
)


class SampleModel(BaseModel):
    """Sample Pydantic model for testing."""

    name: str
    age: int


class TestOpenAPIDecoratorEnhanced:
    """Test enhanced OpenAPI decorator functionality."""

    def test_openapi_decorator_with_validation_error(self) -> None:
        """Test decorator with validation error."""
        with pytest.raises(ValueError):

            @openapi(
                route="<script>alert('xss')</script>",  # Invalid route
                summary="Test",
            )
            def test_func() -> None:
                pass

    def test_openapi_decorator_with_invalid_operation_id(self) -> None:
        """Test decorator with invalid operation ID."""

        # The decorator should sanitize the operation ID instead of raising an error
        @openapi(
            operation_id="<script>alert('xss')</script>",  # Invalid operation ID
            summary="Test",
        )
        def test_func() -> None:
            pass

        # Verify the operation ID was sanitized
        registry = get_openapi_registry()
        assert "test_func" in registry
        # The operation ID should be sanitized to remove dangerous characters
        assert registry["test_func"]["operation_id"] == "script_alert_xss_script"

    def test_openapi_decorator_with_invalid_parameters(self) -> None:
        """Test decorator with invalid parameters."""
        with pytest.raises(ValueError):

            @openapi(
                parameters=cast(Any, "not_a_list"),  # Invalid parameters type
                summary="Test",
            )
            def test_func() -> None:
                pass

    def test_openapi_decorator_with_invalid_parameter_structure(self) -> None:
        """Test decorator with invalid parameter structure."""
        with pytest.raises(ValueError):

            @openapi(
                parameters=[{"name": "test"}],  # Missing required field 'in'
                summary="Test",
            )
            def test_func() -> None:
                pass

    def test_openapi_decorator_with_invalid_tags(self) -> None:
        """Test decorator with invalid tags."""
        with pytest.raises(ValueError):

            @openapi(
                tags=cast(Any, "not_a_list"),  # Invalid tags type
                summary="Test",
            )
            def test_func() -> None:
                pass

    def test_openapi_decorator_with_invalid_security(self) -> None:
        """Test decorator with invalid security."""
        with pytest.raises(ValueError):

            @openapi(
                security=cast(Any, "not_a_list"),
                summary="Test",
            )
            def test_func() -> None:
                pass

    def test_openapi_decorator_with_empty_tag(self) -> None:
        """Test decorator with empty tag."""
        with pytest.raises(ValueError):

            @openapi(
                tags=["valid_tag", ""],  # Empty tag
                summary="Test",
            )
            def test_func() -> None:
                pass

    def test_openapi_decorator_with_invalid_request_model(self) -> None:
        """Test decorator with invalid request model."""
        with pytest.raises(ValueError):

            @openapi(
                request_model=cast(Any, str),  # Not a BaseModel subclass
                summary="Test",
            )
            def test_func() -> None:
                pass

    def test_openapi_decorator_with_invalid_response_model(self) -> None:
        """Test decorator with invalid response model."""
        with pytest.raises(ValueError):

            @openapi(
                response_model=cast(Any, int),  # Not a BaseModel subclass
                summary="Test",
            )
            def test_func() -> None:
                pass

    def test_openapi_decorator_success(self) -> None:
        """Test successful decorator application."""

        @openapi(
            summary="Test function",
            description="A test function",
            tags=["test"],
            operation_id="test_operation",
            route="/test",
            method="get",
            parameters=[
                {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
            ],
            request_model=SampleModel,
            response_model=SampleModel,
        )
        def test_func() -> None:
            pass

        # Verify function is registered
        registry = get_openapi_registry()
        assert "test_func" in registry

        metadata = registry["test_func"]
        assert metadata["summary"] == "Test function"
        assert metadata["description"] == "A test function"
        assert metadata["tags"] == ["test"]
        assert metadata["operation_id"] == "test_operation"
        assert metadata["route"] == "/test"
        assert metadata["method"] == "get"
        assert len(metadata["parameters"]) == 1
        assert metadata["request_model"] == SampleModel
        assert metadata["response_model"] == SampleModel


class TestValidationFunctions:
    """Test validation helper functions."""

    def test_validate_and_sanitize_route_valid(self) -> None:
        """Test route validation with valid route."""
        result = _validate_and_sanitize_route("/api/test", "test_func")
        assert result == "/api/test"

    def test_validate_and_sanitize_route_none(self) -> None:
        """Test route validation with None route."""
        result = _validate_and_sanitize_route(None, "test_func")
        assert result is None

    def test_validate_and_sanitize_route_invalid(self) -> None:
        """Test route validation with invalid route."""
        with pytest.raises(ValueError):
            _validate_and_sanitize_route("<script>alert('xss')</script>", "test_func")

    def test_validate_and_sanitize_operation_id_valid(self) -> None:
        """Test operation ID validation with valid ID."""
        result = _validate_and_sanitize_operation_id("test_operation", "test_func")
        assert result == "test_operation"

    def test_validate_and_sanitize_operation_id_none(self) -> None:
        """Test operation ID validation with None ID."""
        result = _validate_and_sanitize_operation_id(None, "test_func")
        assert result is None

    def test_validate_and_sanitize_operation_id_invalid(self) -> None:
        """Test operation ID validation with invalid ID."""
        # The function should sanitize instead of raising an error
        result = _validate_and_sanitize_operation_id("<script>alert('xss')</script>", "test_func")
        assert result == "script_alert_xss_script"

    def test_validate_parameters_valid(self) -> None:
        """Test parameter validation with valid parameters."""
        params = [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}]
        result = _validate_parameters(params, "test_func")
        assert result == params

    def test_validate_parameters_none(self) -> None:
        """Test parameter validation with None parameters."""
        result = _validate_parameters(None, "test_func")
        assert result == []

    def test_validate_parameters_invalid_type(self) -> None:
        """Test parameter validation with invalid type."""
        with pytest.raises(ValueError):
            _validate_parameters(cast(Any, "not_a_list"), "test_func")

    def test_validate_parameters_invalid_structure(self) -> None:
        """Test parameter validation with invalid structure."""
        with pytest.raises(ValueError):
            _validate_parameters([{"name": "test"}], "test_func")  # Missing 'in' field

    def test_validate_parameters_invalid_item_type(self) -> None:
        """Test parameter validation with invalid item type."""
        with pytest.raises(ValueError):
            _validate_parameters(cast(Any, ["not_a_dict"]), "test_func")

    def test_validate_tags_valid(self) -> None:
        """Test tag validation with valid tags."""
        tags = ["tag1", "tag2"]
        result = _validate_tags(tags, "test_func")
        assert result == tags

    def test_validate_security_valid(self) -> None:
        """Test security validation with valid security requirements."""
        security: list[dict[str, list[str]]] = [{"BearerAuth": []}, {"OAuth2": ["read", "write"]}]
        result = _validate_security(security, "test_func")
        assert result == security

    def test_validate_security_none(self) -> None:
        """Test security validation with None."""
        result = _validate_security(None, "test_func")
        assert result == []

    def test_validate_security_invalid_type(self) -> None:
        """Test security validation with invalid type."""
        with pytest.raises(ValueError):
            _validate_security(cast(Any, "not_a_list"), "test_func")

    def test_validate_security_invalid_item(self) -> None:
        """Test security validation with invalid requirement object."""
        with pytest.raises(ValueError):
            _validate_security(cast(Any, ["not_a_dict"]), "test_func")

    def test_validate_security_invalid_scope_type(self) -> None:
        """Test security validation with invalid scope entries."""
        with pytest.raises(ValueError):
            _validate_security(cast(Any, [{"BearerAuth": [1]}]), "test_func")

    def test_validate_tags_none(self) -> None:
        """Test tag validation with None tags."""
        result = _validate_tags(None, "test_func")
        assert result == ["default"]

    def test_validate_tags_invalid_type(self) -> None:
        """Test tag validation with invalid type."""
        with pytest.raises(ValueError):
            _validate_tags(cast(Any, "not_a_list"), "test_func")

    def test_validate_tags_invalid_item_type(self) -> None:
        """Test tag validation with invalid item type."""
        with pytest.raises(ValueError):
            _validate_tags(cast(Any, [123]), "test_func")

    def test_validate_tags_empty_tag(self) -> None:
        """Test tag validation with empty tag."""
        with pytest.raises(ValueError):
            _validate_tags(["valid", ""], "test_func")

    def test_validate_tags_whitespace_tag(self) -> None:
        """Test tag validation with whitespace-only tag."""
        with pytest.raises(ValueError):
            _validate_tags(["valid", "   "], "test_func")

    def test_validate_models_valid(self) -> None:
        """Test model validation with valid models."""
        _validate_models(SampleModel, SampleModel, "test_func")  # Should not raise

    def test_validate_models_none(self) -> None:
        """Test model validation with None models."""
        _validate_models(None, None, "test_func")  # Should not raise

    def test_validate_models_invalid_request_model(self) -> None:
        """Test model validation with invalid request model."""
        with pytest.raises(ValueError):
            _validate_models(cast(Any, str), None, "test_func")

    def test_validate_models_invalid_response_model(self) -> None:
        """Test model validation with invalid response model."""
        with pytest.raises(ValueError):
            _validate_models(None, cast(Any, int), "test_func")


class TestOpenAPIDecoratorErrorHandling:
    """Test error handling in OpenAPI decorator."""

    @patch("azure_functions_openapi.decorator.logger")
    def test_decorator_error_logging(self, mock_logger: Any) -> None:
        """Test that decorator errors are logged."""
        with pytest.raises(ValueError):

            @openapi(route="<script>alert('xss')</script>", summary="Test")
            def test_func() -> None:
                pass

        # Should log the error
        mock_logger.error.assert_called()

    def test_decorator_exception_conversion(self) -> None:
        """Test that exceptions are converted to RuntimeError."""
        with patch(
            "azure_functions_openapi.decorator._validate_and_sanitize_route"
        ) as mock_validate:
            mock_validate.side_effect = Exception("Unexpected error")
            with pytest.raises(RuntimeError) as exc_info:

                @openapi(summary="Test")
                def test_func() -> None:
                    pass

            assert "Failed to register OpenAPI metadata" in str(exc_info.value)


class TestValidateSecurityScheme:
    """Tests for _validate_security_scheme."""

    def test_validate_security_scheme_valid(self) -> None:
        scheme = {"BearerAuth": {"type": "http", "scheme": "bearer"}}
        result = _validate_security_scheme(scheme, "test_func")
        assert result == scheme

    def test_validate_security_scheme_none(self) -> None:
        result = _validate_security_scheme(None, "test_func")
        assert result == {}

    def test_validate_security_scheme_invalid_type(self) -> None:
        with pytest.raises(ValueError):
            _validate_security_scheme(cast(Any, "not_a_dict"), "test_func")

    def test_validate_security_scheme_missing_type_field(self) -> None:
        with pytest.raises(ValueError, match="valid 'type' field"):
            _validate_security_scheme({"BadScheme": {"scheme": "bearer"}}, "test_func")

    def test_validate_security_scheme_invalid_type_value(self) -> None:
        with pytest.raises(ValueError, match="valid 'type' field"):
            _validate_security_scheme({"BadScheme": {"type": "invalid"}}, "test_func")

    def test_validate_security_scheme_invalid_definition(self) -> None:
        with pytest.raises(ValueError, match="must be a dictionary"):
            _validate_security_scheme(cast(Any, {"BadScheme": "not_a_dict"}), "test_func")

    def test_validate_security_scheme_empty_name(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_security_scheme({"  ": {"type": "http", "scheme": "bearer"}}, "test_func")

    def test_validate_security_scheme_apikey(self) -> None:
        scheme = {"ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}
        result = _validate_security_scheme(scheme, "test_func")
        assert result == scheme

    def test_validate_security_scheme_oauth2(self) -> None:
        scheme = {"OAuth2": {"type": "oauth2", "flows": {}}}
        result = _validate_security_scheme(scheme, "test_func")
        assert result == scheme

    def test_validate_security_scheme_openidconnect(self) -> None:
        scheme = {"OIDC": {"type": "openIdConnect", "openIdConnectUrl": "https://example.com"}}
        result = _validate_security_scheme(scheme, "test_func")
        assert result == scheme

    def test_validate_security_scheme_apikey_missing_name(self) -> None:
        with pytest.raises(ValueError, match="non-empty 'name'"):
            _validate_security_scheme(
                {"ApiKey": {"type": "apiKey", "in": "header"}}, "test_func"
            )

    def test_validate_security_scheme_apikey_invalid_in(self) -> None:
        with pytest.raises(ValueError, match="'in' as one of"):
            _validate_security_scheme(
                {"ApiKey": {"type": "apiKey", "name": "key", "in": "body"}}, "test_func"
            )

    def test_validate_security_scheme_http_missing_scheme(self) -> None:
        with pytest.raises(ValueError, match="non-empty 'scheme'"):
            _validate_security_scheme(
                {"Bearer": {"type": "http"}}, "test_func"
            )

    def test_validate_security_scheme_oauth2_missing_flows(self) -> None:
        with pytest.raises(ValueError, match="'flows' as a dict"):
            _validate_security_scheme(
                {"OAuth": {"type": "oauth2"}}, "test_func"
            )

    def test_validate_security_scheme_openidconnect_missing_url(self) -> None:
        with pytest.raises(ValueError, match="non-empty 'openIdConnectUrl'"):
            _validate_security_scheme(
                {"OIDC": {"type": "openIdConnect"}}, "test_func"
            )
