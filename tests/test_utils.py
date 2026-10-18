# test/test_utils.py

import copy
from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from pydantic import BaseModel, Field, TypeAdapter, create_model
import pytest

from azure_functions_openapi.decorator import clear_openapi_registry, openapi
from azure_functions_openapi.spec import generate_openapi_report
from azure_functions_openapi.utils import hoist_inline_defs, model_to_schema, type_to_schema


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _list_of(model: Any) -> Any:
    """Build ``list[model]`` for a runtime-dynamic ``create_model()`` class.

    A bare ``list[model]`` subscript is parsed by mypy as type-annotation
    syntax requiring a statically-known type, which a ``create_model()``
    result can never be -- yet ``type_to_schema``/``TypeAdapter`` must accept
    exactly this dynamic pattern at runtime. Routing the subscript through an
    ``Any``-typed parameter keeps the annotation honest (this value truly has
    no static type) without suppressing an error with ``cast``/``# type:
    ignore``; the produced generic alias is identical to ``list[model]``.
    """
    return list[model]


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


# ---------------------------------------------------------------------------
# Shared graph registration across direct/generic/raw paths (issue #779)
# ---------------------------------------------------------------------------


def test_type_to_schema_preserves_parents_when_nested_names_collide() -> None:
    # Given: the same nested-collision scenario as the direct-path test above,
    # fed through the GENERIC container path instead.
    first_address = create_model("Address", street=(str, ...))
    first_user = create_model("User", address=(first_address, ...))
    second_address = create_model("Address", postcode=(str, ...))
    second_user = create_model("User", address=(second_address, ...))
    components: dict[str, Any] = {"schemas": {}}

    # When
    first_schema = type_to_schema(_list_of(first_user), components)
    second_schema = type_to_schema(_list_of(second_user), components)

    # Then: each parent retains its own child shape.
    assert first_schema["items"] == {"$ref": "#/components/schemas/User"}
    assert second_schema["items"] == {"$ref": "#/components/schemas/User_2"}
    schemas = components["schemas"]
    assert schemas["User"]["properties"]["address"]["$ref"] == "#/components/schemas/Address"
    assert schemas["User_2"]["properties"]["address"]["$ref"] == "#/components/schemas/Address_2"
    assert "street" in schemas["Address"]["properties"]
    assert "postcode" in schemas["Address_2"]["properties"]


def test_hoist_inline_defs_preserves_parents_when_nested_names_collide() -> None:
    # Given: the same nested-collision scenario, fed through the RAW producer
    # path (hoist_inline_defs) the way a TypeAdapter-based producer would.
    first_address = create_model("Address", street=(str, ...))
    first_user = create_model("User", address=(first_address, ...))
    second_address = create_model("Address", postcode=(str, ...))
    second_user = create_model("User", address=(second_address, ...))
    components: dict[str, Any] = {"schemas": {}}

    # When
    first_schema = hoist_inline_defs(TypeAdapter(_list_of(first_user)).json_schema(), components)
    second_schema = hoist_inline_defs(TypeAdapter(_list_of(second_user)).json_schema(), components)

    # Then
    assert first_schema["items"] == {"$ref": "#/components/schemas/User"}
    assert second_schema["items"] == {"$ref": "#/components/schemas/User_2"}
    schemas = components["schemas"]
    assert schemas["User"]["properties"]["address"]["$ref"] == "#/components/schemas/Address"
    assert schemas["User_2"]["properties"]["address"]["$ref"] == "#/components/schemas/Address_2"
    assert "street" in schemas["Address"]["properties"]
    assert "postcode" in schemas["Address_2"]["properties"]


@pytest.mark.parametrize(
    "convert",
    [
        lambda model, components: model_to_schema(model, components),
        lambda model, components: type_to_schema(_list_of(model), components),
        lambda model, components: hoist_inline_defs(
            TypeAdapter(_list_of(model)).json_schema(), components
        ),
    ],
    ids=["direct", "generic", "raw"],
)
def test_direct_generic_raw_paths_never_overwrite_existing_parent(convert: Any) -> None:
    # Given: a first-registered parent/child pair, then a second pair that
    # reuses both names with different child content.
    first_address = create_model("Address", street=(str, ...))
    first_user = create_model("User", address=(first_address, ...))
    second_address = create_model("Address", postcode=(str, ...))
    second_user = create_model("User", address=(second_address, ...))
    components: dict[str, Any] = {"schemas": {}}

    # When
    convert(first_user, components)
    original_user = copy.deepcopy(components["schemas"]["User"])
    convert(second_user, components)

    # Then: the first User registration is untouched by the second, for all
    # three schema-producing paths alike.
    assert components["schemas"]["User"] == original_user


def test_hoist_inline_defs_rewrites_discriminator_mapping_on_collision() -> None:
    # Given: components already defines a differently-shaped "Cat"; the new
    # raw schema's discriminated union references "Cat" via both a oneOf
    # $ref and a discriminator.mapping entry -- the exact shape Pydantic
    # emits for Annotated[Cat | Dog, Field(discriminator="kind")].
    components: dict[str, Any] = {
        "schemas": {"Cat": {"type": "object", "properties": {"old": {"type": "string"}}}}
    }
    raw_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pet": {
                "discriminator": {
                    "propertyName": "kind",
                    "mapping": {"cat": "#/$defs/Cat", "dog": "#/$defs/Dog"},
                },
                "oneOf": [{"$ref": "#/$defs/Cat"}, {"$ref": "#/$defs/Dog"}],
            }
        },
        "$defs": {
            "Cat": {"type": "object", "properties": {"new": {"type": "integer"}}},
            "Dog": {"type": "object", "properties": {"kind": {"const": "dog"}}},
        },
    }

    # When
    root = hoist_inline_defs(raw_schema, components)

    # Then: the oneOf $ref and the discriminator mapping entry agree on the
    # SAME renamed component -- neither is left pointing at the stale name.
    pet = root["properties"]["pet"]
    cat_ref = next(branch["$ref"] for branch in pet["oneOf"] if "Cat" in branch["$ref"])
    assert pet["discriminator"]["mapping"]["cat"] == cat_ref
    assert cat_ref == "#/components/schemas/Cat_2"
    assert components["schemas"]["Cat_2"]["properties"] == {"new": {"type": "integer"}}
    assert components["schemas"]["Cat"]["properties"] == {"old": {"type": "string"}}


def test_hoist_inline_defs_reserves_names_against_same_batch() -> None:
    # Given: components already defines "Thing"; a new raw schema's own
    # $defs batch separately introduces both "Thing" and "Thing_2" -- a
    # pre-existing collision plus a same-batch name clash in one call.
    components: dict[str, Any] = {"schemas": {"Thing": {"type": "integer"}}}
    raw_schema: dict[str, Any] = {
        "anyOf": [
            {"$ref": "#/$defs/Thing"},
            {"$ref": "#/$defs/Thing_2"},
        ],
        "$defs": {
            "Thing": {"type": "string"},
            "Thing_2": {"type": "boolean"},
        },
    }

    # When
    root = hoist_inline_defs(raw_schema, components)

    # Then: both the pre-existing "Thing" and the batch's two distinct
    # definitions survive under distinct names -- neither is silently
    # dropped by a same-batch alias collision.
    schemas = components["schemas"]
    referenced_names = {branch["$ref"].rsplit("/", 1)[1] for branch in root["anyOf"]}
    assert len(referenced_names) == 2
    assert {schemas[name]["type"] for name in referenced_names} == {"string", "boolean"}
    assert schemas["Thing"] == {"type": "integer"}


def test_generate_openapi_report_preserves_distinct_response_payloads_end_to_end() -> None:
    # Given: two endpoints returning differently-shaped same-named nested
    # models, registered via the public @openapi decorator + full report path.
    first_address = create_model("Address", street=(str, ...))
    first_user = create_model("User", address=(first_address, ...))
    second_address = create_model("Address", postcode=(str, ...))
    second_user = create_model("User", address=(second_address, ...))

    @openapi(route="first", method="get", responses={200: _list_of(first_user)})
    def first() -> None: ...

    @openapi(route="second", method="get", responses={200: _list_of(second_user)})
    def second() -> None: ...

    # When
    report = generate_openapi_report(strict=True)
    validate(report.spec)

    # Then: strict generation is clean and the document is structurally valid.
    assert report.warnings == ()

    def _response_schema(path: str) -> dict[str, Any]:
        ref = report.spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        return {**ref, "components": report.spec["components"]}

    first_schema = _response_schema("/api/first")
    second_schema = _response_schema("/api/second")
    first_payload = [first_user(address=first_address(street="Main St")).model_dump(mode="json")]
    second_payload = [second_user(address=second_address(postcode="12345")).model_dump(mode="json")]

    # Each endpoint's actual serialized payload validates against its OWN
    # schema -- and is rejected by the OTHER endpoint's schema -- proving the
    # two model graphs were kept distinct, not merely that the document
    # parses as structurally valid OpenAPI.
    assert list(Draft202012Validator(first_schema).iter_errors(first_payload)) == []
    assert list(Draft202012Validator(second_schema).iter_errors(second_payload)) == []
    assert list(Draft202012Validator(second_schema).iter_errors(first_payload)) != []
    assert list(Draft202012Validator(first_schema).iter_errors(second_payload)) != []
