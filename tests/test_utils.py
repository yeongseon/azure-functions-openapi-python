# test/test_utils.py

from typing import Any, Dict

from pydantic import BaseModel, Field
import pytest

from azure_functions_openapi.utils import model_to_schema


class MyModel(BaseModel):
    title: str = Field(..., description="The title of the item")
    done: bool = Field(default=False)


@pytest.mark.parametrize("model_cls", [MyModel])
def test_model_to_schema(model_cls: type[BaseModel]) -> None:
    """Verify that the model_to_schema function returns a valid schema for the given model class."""
    components: Dict[str, Any] = {"schemas": {}}
    schema: Dict[str, Any] = model_to_schema(model_cls, components)

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
