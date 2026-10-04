# test/test_utils.py

from typing import Annotated, Any, Literal

from openapi_spec_validator import validate
from pydantic import BaseModel, Field, create_model
import pytest

from azure_functions_openapi.utils import model_to_schema, type_to_schema


class MyModel(BaseModel):
    title: str = Field(..., description="The title of the item")
    done: bool = Field(default=False)


@pytest.mark.parametrize("model_cls", [MyModel])
def test_model_to_schema(model_cls: type[BaseModel]) -> None:
    """Verify that the model_to_schema function returns a valid schema for the given model class."""
    components: dict[str, Any] = {"schemas": {}}
    schema: dict[str, Any] = model_to_schema(model_cls, components)

    # Common schema assertions
    assert schema == {"$ref": f"#/components/schemas/{model_cls.__name__}"}
    assert model_cls.__name__ in components["schemas"]

    registered = components["schemas"][model_cls.__name__]
    assert "title" in registered or "properties" in registered
    assert "done" in registered.get("properties", {})
    assert "title" in registered.get("properties", {})
    assert "$defs" not in registered


def test_model_to_schema_non_pydantic_raises_type_error() -> None:
    """model_to_schema must raise TypeError for non-Pydantic v2 classes."""

    class NotAModel:
        pass

    with pytest.raises(TypeError, match="model_json_schema"):
        model_to_schema(NotAModel, {})


def test_model_to_schema_preserves_parents_when_nested_names_collide() -> None:
    # Given: two real Pydantic model trees whose parent and child names collide.
    first_address = create_model("Address", street=(str, ...))
    first_user = create_model("User", address=(first_address, ...))
    second_address = create_model("Address", postcode=(str, ...))
    second_user = create_model("User", address=(second_address, ...))
    components: dict[str, Any] = {"schemas": {}}

    # When: both trees are registered in the same OpenAPI components object.
    first_ref = model_to_schema(first_user, components)
    second_ref = model_to_schema(second_user, components)
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Nested collision", "version": "1.0.0"},
        "paths": {
            "/first": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": first_ref}},
                        }
                    }
                }
            },
            "/second": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": second_ref}},
                        }
                    }
                }
            },
        },
        "components": components,
    }

    # Then: each parent retains its own child shape and the document is valid.
    assert first_ref == {"$ref": "#/components/schemas/User"}
    assert second_ref == {"$ref": "#/components/schemas/User_2"}
    schemas = components["schemas"]
    assert schemas["User"]["properties"]["address"]["$ref"] == "#/components/schemas/Address"
    assert schemas["User_2"]["properties"]["address"]["$ref"] == "#/components/schemas/Address_2"
    assert "street" in schemas["Address"]["properties"]
    assert "postcode" in schemas["Address_2"]["properties"]
    validate(document)


def test_type_to_schema_rewrites_discriminator_mapping_for_generic_union() -> None:
    class Cat(BaseModel):
        kind: Literal["cat"]

    class Dog(BaseModel):
        kind: Literal["dog"]

    # Given: a real Pydantic discriminated union nested in a generic container.
    components: dict[str, Any] = {"schemas": {}}
    animal = Annotated[Cat | Dog, Field(discriminator="kind")]

    # When: the generic type is hoisted into shared OpenAPI components.
    schema = type_to_schema(list[animal], components)
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Discriminator", "version": "1.0.0"},
        "paths": {},
        "components": components,
    }

    # Then: every discriminator mapping target resolves to a hoisted component.
    mapping = schema["items"]["discriminator"]["mapping"]
    assert mapping == {
        "cat": "#/components/schemas/Cat",
        "dog": "#/components/schemas/Dog",
    }
    validate(document)
