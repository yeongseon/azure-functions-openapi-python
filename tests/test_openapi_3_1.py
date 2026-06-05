from __future__ import annotations

import pytest

from azure_functions_openapi.spec import (
    OPENAPI_VERSION_3_0,
    OPENAPI_VERSION_3_1,
    _convert_nullable_to_type_array,
    _convert_schema_to_3_1,
    _convert_schemas_to_3_1,
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
)


class TestConvertNullableToTypeArray:
    def test_nullable_string(self) -> None:
        schema = {"type": "string", "nullable": True}

        result = _convert_nullable_to_type_array(schema)

        assert result["type"] == ["string", "null"]
        assert "nullable" not in result

    def test_nullable_integer(self) -> None:
        schema = {"type": "integer", "nullable": True}

        result = _convert_nullable_to_type_array(schema)

        assert result["type"] == ["integer", "null"]

    def test_not_nullable(self) -> None:
        schema = {"type": "string"}

        result = _convert_nullable_to_type_array(schema)

        assert result["type"] == "string"
        assert "nullable" not in result

    def test_nullable_false(self) -> None:
        schema = {"type": "string", "nullable": False}

        result = _convert_nullable_to_type_array(schema)

        assert result["type"] == "string"
        assert result.get("nullable") is False

    def test_already_type_array(self) -> None:
        schema = {"type": ["string", "integer"], "nullable": True}

        result = _convert_nullable_to_type_array(schema)

        assert result["type"] == ["string", "integer", "null"]

    def test_no_type(self) -> None:
        schema = {"nullable": True}

        result = _convert_nullable_to_type_array(schema)

        assert result.get("nullable") is True


class TestConvertSchemaTo31:
    def test_example_to_examples(self) -> None:
        schema = {"type": "string", "example": "test"}

        result = _convert_schema_to_3_1(schema)

        assert result["examples"] == ["test"]
        assert "example" not in result

    def test_preserves_existing_examples(self) -> None:
        schema = {"type": "string", "example": "old", "examples": ["existing"]}

        result = _convert_schema_to_3_1(schema)

        assert result["examples"] == ["existing"]

    def test_nested_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "nullable": True},
                "age": {"type": "integer", "example": 25},
            },
        }

        result = _convert_schema_to_3_1(schema)

        assert result["properties"]["name"]["type"] == ["string", "null"]
        assert result["properties"]["age"]["examples"] == [25]

    def test_array_items(self) -> None:
        schema = {"type": "array", "items": {"type": "string", "nullable": True}}

        result = _convert_schema_to_3_1(schema)

        assert result["items"]["type"] == ["string", "null"]

    def test_allof(self) -> None:
        schema = {
            "allOf": [
                {"type": "string", "nullable": True},
                {"minLength": 1},
            ]
        }

        result = _convert_schema_to_3_1(schema)

        assert result["allOf"][0]["type"] == ["string", "null"]

    def test_anyof(self) -> None:
        schema = {"anyOf": [{"type": "string", "nullable": True}]}

        result = _convert_schema_to_3_1(schema)

        assert result["anyOf"][0]["type"] == ["string", "null"]

    def test_oneof(self) -> None:
        schema = {"oneOf": [{"type": "string", "nullable": True}]}

        result = _convert_schema_to_3_1(schema)

        assert result["oneOf"][0]["type"] == ["string", "null"]

    def test_additional_properties(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": {"type": "string", "nullable": True},
        }

        result = _convert_schema_to_3_1(schema)

        assert result["additionalProperties"]["type"] == ["string", "null"]

    def test_non_dict_passthrough(self) -> None:
        result = _convert_schema_to_3_1("not a dict")  # type: ignore[arg-type]
        assert result == "not a dict"  # type: ignore[comparison-overlap]


class TestConvertSchemasTo31:
    def test_converts_multiple_schemas(self) -> None:
        schemas = {
            "User": {
                "type": "object",
                "properties": {"name": {"type": "string", "nullable": True}},
            },
            "Item": {"type": "object", "properties": {"value": {"type": "integer", "example": 10}}},
        }

        result = _convert_schemas_to_3_1(schemas)

        assert result["User"]["properties"]["name"]["type"] == ["string", "null"]
        assert result["Item"]["properties"]["value"]["examples"] == [10]


class TestGenerateOpenapiSpec:
    def test_default_version_is_3_1(self) -> None:
        spec = generate_openapi_spec()

        assert spec["openapi"] == "3.1.0"

    def test_explicit_3_0_version(self) -> None:
        spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_0)

        assert spec["openapi"] == "3.0.0"

    def test_3_1_version(self) -> None:
        spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_1)

        assert spec["openapi"] == "3.1.0"
        assert "summary" in spec["info"]

    def test_invalid_version_raises_error(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            generate_openapi_spec(openapi_version="2.0.0")

        assert "Unsupported OpenAPI version" in str(exc_info.value)

    def test_custom_title_and_version(self) -> None:
        spec = generate_openapi_spec(title="My API", version="2.0.0")

        assert spec["info"]["title"] == "My API"
        assert spec["info"]["version"] == "2.0.0"


class TestGetOpenapiJson:
    def test_returns_json_string(self) -> None:
        result = get_openapi_json()

        assert isinstance(result, str)
        assert '"openapi"' in result

    def test_default_3_1(self) -> None:
        result = get_openapi_json()

        assert '"3.1.0"' in result

    def test_3_1_version(self) -> None:
        result = get_openapi_json(openapi_version=OPENAPI_VERSION_3_1)

        assert '"3.1.0"' in result


class TestGetOpenapiYaml:
    def test_returns_yaml_string(self) -> None:
        result = get_openapi_yaml()

        assert isinstance(result, str)
        assert "openapi:" in result

    def test_default_3_1(self) -> None:
        result = get_openapi_yaml()

        assert "3.1.0" in result

    def test_3_1_version(self) -> None:
        result = get_openapi_yaml(openapi_version=OPENAPI_VERSION_3_1)

        assert "3.1.0" in result
