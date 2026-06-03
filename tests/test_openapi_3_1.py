from __future__ import annotations

import pytest

from azure_functions_openapi.spec import (
    OPENAPI_VERSION_3_0,
    OPENAPI_VERSION_3_1,
    _convert_anyof_null_to_nullable,
    _convert_nullable_to_type_array,
    _convert_schema_to_3_0,
    _convert_schema_to_3_1,
    _convert_schemas_to_3_0,
    _convert_schemas_to_3_1,
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
)


class TestConvertAnyOfNullToNullable:
    """Test Pydantic v2 anyOf-null → OpenAPI 3.0 nullable conversion."""

    def test_anyof_string_null(self) -> None:
        schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        result = _convert_anyof_null_to_nullable(schema)
        assert result == {"type": "string", "nullable": True}

    def test_anyof_integer_null(self) -> None:
        schema = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
        result = _convert_anyof_null_to_nullable(schema)
        assert result == {"type": "integer", "nullable": True}

    def test_anyof_null_first(self) -> None:
        schema = {"anyOf": [{"type": "null"}, {"type": "number"}]}
        result = _convert_anyof_null_to_nullable(schema)
        assert result == {"type": "number", "nullable": True}

    def test_anyof_three_types_not_converted(self) -> None:
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]}
        result = _convert_anyof_null_to_nullable(schema)
        assert "anyOf" in result  # not converted — complex union

    def test_anyof_no_null_not_converted(self) -> None:
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        result = _convert_anyof_null_to_nullable(schema)
        assert "anyOf" in result

    def test_no_anyof(self) -> None:
        schema = {"type": "string"}
        result = _convert_anyof_null_to_nullable(schema)
        assert result == {"type": "string"}

    def test_preserves_extra_keys(self) -> None:
        schema = {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "X"}
        result = _convert_anyof_null_to_nullable(schema)
        assert result["type"] == "string"
        assert result["nullable"] is True
        assert result["default"] is None
        assert result["title"] == "X"
        assert "anyOf" not in result


class TestConvertSchemaTo30:
    """Test recursive OpenAPI 3.1 → 3.0 downgrade."""

    def test_anyof_nullable_in_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            },
        }
        result = _convert_schema_to_3_0(schema)
        prop = result["properties"]["name"]
        assert prop["type"] == "string"
        assert prop["nullable"] is True
        assert "anyOf" not in prop

    def test_type_array_with_null(self) -> None:
        schema = {"type": ["string", "null"]}
        result = _convert_schema_to_3_0(schema)
        assert result == {"type": "string", "nullable": True}

    def test_examples_to_example(self) -> None:
        schema = {"type": "string", "examples": ["foo", "bar"]}
        result = _convert_schema_to_3_0(schema)
        assert result["example"] == "foo"
        assert "examples" not in result

    def test_const_to_enum(self) -> None:
        schema = {"const": "fixed_value"}
        result = _convert_schema_to_3_0(schema)
        assert result == {"enum": ["fixed_value"]}

    def test_nested_items(self) -> None:
        schema = {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}}
        result = _convert_schema_to_3_0(schema)
        assert result["items"] == {"type": "string", "nullable": True}

    def test_nested_allof(self) -> None:
        schema = {"allOf": [{"anyOf": [{"type": "string"}, {"type": "null"}]}]}
        result = _convert_schema_to_3_0(schema)
        assert result["allOf"][0] == {"type": "string", "nullable": True}

    def test_non_dict_passthrough(self) -> None:
        result = _convert_schema_to_3_0("not a dict")  # type: ignore[arg-type]
        assert result == "not a dict"  # type: ignore[comparison-overlap]


class TestConvertSchemasTo30:
    def test_converts_multiple_schemas(self) -> None:
        schemas = {
            "User": {
                "type": "object",
                "properties": {
                    "email": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
            },
            "Item": {"type": "string", "examples": ["a"]},
        }
        result = _convert_schemas_to_3_0(schemas)
        assert result["User"]["properties"]["email"] == {"type": "string", "nullable": True}
        assert result["Item"]["example"] == "a"


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
    def test_default_version_is_3_0(self) -> None:
        spec = generate_openapi_spec()

        assert spec["openapi"] == "3.0.0"

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

    def test_default_3_0(self) -> None:
        result = get_openapi_json()

        assert '"3.0.0"' in result

    def test_3_1_version(self) -> None:
        result = get_openapi_json(openapi_version=OPENAPI_VERSION_3_1)

        assert '"3.1.0"' in result


class TestGetOpenapiYaml:
    def test_returns_yaml_string(self) -> None:
        result = get_openapi_yaml()

        assert isinstance(result, str)
        assert "openapi:" in result

    def test_default_3_0(self) -> None:
        result = get_openapi_yaml()

        assert "3.0.0" in result

    def test_3_1_version(self) -> None:
        result = get_openapi_yaml(openapi_version=OPENAPI_VERSION_3_1)

        assert "3.1.0" in result
