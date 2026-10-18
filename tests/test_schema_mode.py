# tests/test_schema_mode.py
"""Response schemas use Pydantic serialization mode, not validation mode (#783).

model_to_schema()/type_to_schema() called model_json_schema()/
TypeAdapter.json_schema() without a mode, which defaults to "validation" --
the shape a model *accepts*. A response describes what a handler's return
value *produces*, which can differ for a model using
validation_alias/serialization_alias, a @computed_field, or a field
serializer. These tests pin that request paths use validation mode and
response paths (explicit, generic, and return-type-inferred) use
serialization mode, verified against actual serialized payloads -- not just
document shape -- the same way the issue's own reproduction did.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer
import pytest

from azure_functions_openapi.decorator import clear_openapi_registry, openapi
from azure_functions_openapi.spec import generate_openapi_report, generate_openapi_spec
from azure_functions_openapi.utils import model_to_schema, type_to_schema


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


class AliasModel(BaseModel):
    name: str = Field(validation_alias="input_name", serialization_alias="output_name")

    # Pydantic auto-wraps a @computed_field with no explicit @property; the
    # explicit form (recommended by Pydantic's own docs for IDE/type-checker
    # support) hits a mypy limitation absent the pydantic mypy plugin, which
    # this project does not enable (a project-wide typecheck-config change is
    # out of scope for this fix).
    @computed_field
    def length(self) -> int:
        return len(self.name)


class SymmetricModel(BaseModel):
    """No aliases, no computed fields -- validation and serialization shapes
    are identical, so request and response must still dedupe to one
    component rather than needlessly aliasing apart."""

    value: int


class FieldSerializerModel(BaseModel):
    amount: int

    @field_serializer("amount")
    def _amount_as_string(self, amount: int) -> str:
        return f"${amount}"


class NestedAliasModel(BaseModel):
    item: AliasModel


class OverrideModel(BaseModel):
    """Pins its own schema mode regardless of what a caller requests."""

    model_config = ConfigDict(json_schema_mode_override="validation")
    name: str = Field(validation_alias="input_name", serialization_alias="output_name")


class TestModelToSchemaMode:
    def test_default_mode_is_validation(self) -> None:
        components: dict[str, Any] = {"schemas": {}}
        model_to_schema(AliasModel, components)
        assert "input_name" in components["schemas"]["AliasModel"]["properties"]

    def test_serialization_mode_differs_from_validation(self) -> None:
        validation_components: dict[str, Any] = {"schemas": {}}
        serialization_components: dict[str, Any] = {"schemas": {}}

        model_to_schema(AliasModel, validation_components, mode="validation")
        model_to_schema(AliasModel, serialization_components, mode="serialization")

        validation_schema = validation_components["schemas"]["AliasModel"]
        serialization_schema = serialization_components["schemas"]["AliasModel"]
        assert set(validation_schema["properties"]) == {"input_name"}
        assert set(serialization_schema["properties"]) == {"output_name", "length"}

    def test_request_and_response_modes_dedupe_when_content_is_identical(self) -> None:
        # A model with no aliases/computed fields produces byte-identical
        # validation and serialization schemas -- both modes must still
        # resolve to the SAME component, not an unnecessary "_2" alias.
        components: dict[str, Any] = {"schemas": {}}
        validation_ref = model_to_schema(SymmetricModel, components, mode="validation")
        serialization_ref = model_to_schema(SymmetricModel, components, mode="serialization")

        assert (
            validation_ref == serialization_ref == {"$ref": "#/components/schemas/SymmetricModel"}
        )
        assert "SymmetricModel_2" not in components["schemas"]

    def test_request_and_response_modes_alias_apart_when_content_differs(self) -> None:
        # The reverse: when the two modes genuinely differ, both must be
        # preserved under distinct, deterministic component identities --
        # neither representation may silently replace the other.
        components: dict[str, Any] = {"schemas": {}}
        validation_ref = model_to_schema(AliasModel, components, mode="validation")
        serialization_ref = model_to_schema(AliasModel, components, mode="serialization")

        assert validation_ref != serialization_ref
        assert {validation_ref["$ref"], serialization_ref["$ref"]} == {
            "#/components/schemas/AliasModel",
            "#/components/schemas/AliasModel_2",
        }

    def test_field_serializer_changes_serialization_shape(self) -> None:
        components: dict[str, Any] = {"schemas": {}}
        model_to_schema(FieldSerializerModel, components, mode="validation")
        model_to_schema(FieldSerializerModel, components, mode="serialization")

        schemas = components["schemas"]
        assert schemas["FieldSerializerModel"]["properties"]["amount"]["type"] == "integer"
        assert schemas["FieldSerializerModel_2"]["properties"]["amount"]["type"] == "string"

    def test_nested_model_uses_requested_mode(self) -> None:
        # A model nested inside another must also compile under the
        # requested mode, not always default to validation.
        components: dict[str, Any] = {"schemas": {}}
        model_to_schema(NestedAliasModel, components, mode="serialization")

        inner = components["schemas"]["AliasModel"]
        assert set(inner["properties"]) == {"output_name", "length"}

    def test_explicit_mode_override_takes_precedence(self) -> None:
        # A model's own json_schema_mode_override pins its shape regardless
        # of the mode requested by the caller (#783's documented interaction
        # with this existing Pydantic mechanism).
        components: dict[str, Any] = {"schemas": {}}
        model_to_schema(OverrideModel, components, mode="serialization")

        assert "input_name" in components["schemas"]["OverrideModel"]["properties"]

    def test_type_to_schema_threads_mode_through_generic_container(self) -> None:
        validation_components: dict[str, Any] = {"schemas": {}}
        serialization_components: dict[str, Any] = {"schemas": {}}

        type_to_schema(list[AliasModel], validation_components, mode="validation")
        type_to_schema(list[AliasModel], serialization_components, mode="serialization")

        assert set(validation_components["schemas"]["AliasModel"]["properties"]) == {"input_name"}
        assert set(serialization_components["schemas"]["AliasModel"]["properties"]) == {
            "output_name",
            "length",
        }


class TestEndToEndResponseSerializationMode:
    def test_explicit_request_and_response_preserve_distinct_contracts(self) -> None:
        # Given: the issue's own reproduction -- one model used as both the
        # request body and the response, with aliases and a computed field.
        @openapi(route="alias", method="post", requests=AliasModel, responses=AliasModel)
        def alias_endpoint() -> None: ...

        # When
        report = generate_openapi_report(strict=True)
        operation = report.spec["paths"]["/api/alias"]["post"]
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]
        response_name = response_ref["$ref"].rsplit("/", 1)[1]
        response_schema = report.spec["components"]["schemas"][response_name]

        # Then: strict, clean generation; request keeps its validation
        # contract, response describes the serialization contract.
        assert report.warnings == ()
        request_name = request_schema["$ref"].rsplit("/", 1)[1]
        assert set(report.spec["components"]["schemas"][request_name]["properties"]) == {
            "input_name"
        }
        assert set(response_schema["properties"]) == {"output_name", "length"}

        # And: the actual serialized response payload validates against the
        # generated response schema -- not just the document's shape.
        instance = AliasModel.model_validate({"input_name": "Bob"}).model_dump(
            mode="json", by_alias=True
        )
        assert instance == {"output_name": "Bob", "length": 3}
        assert list(Draft202012Validator(response_schema).iter_errors(instance)) == []

    def test_return_type_inference_uses_serialization_mode(self) -> None:
        # Given: no explicit responses=; the 200 is inferred from the return
        # annotation (P1-A). Inference must follow the same output-schema
        # rule as an explicit responses=AliasModel declaration.
        @openapi(route="inferred", method="get")
        def inferred_endpoint() -> AliasModel:
            raise NotImplementedError

        # When
        spec = generate_openapi_spec(strict=True)
        schema = spec["paths"]["/api/inferred"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        resolved = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]

        # Then
        assert set(resolved["properties"]) == {"output_name", "length"}

    def test_generic_collection_response_uses_serialization_mode(self) -> None:
        # Given: the per-status shorthand wraps the model in a generic
        # container (#450), exercising type_to_schema's response path.
        @openapi(route="aliases", method="get", responses={200: list[AliasModel]})
        def list_aliases() -> None: ...

        # When
        spec = generate_openapi_spec(strict=True)
        items_ref = spec["paths"]["/api/aliases"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["items"]
        resolved = spec["components"]["schemas"][items_ref["$ref"].rsplit("/", 1)[1]]

        # Then
        assert set(resolved["properties"]) == {"output_name", "length"}

    def test_request_model_shorthand_still_uses_validation_mode(self) -> None:
        # Given / When: requests=AliasModel alone (no response declared).
        @openapi(route="alias-request-only", method="post", requests=AliasModel)
        def alias_request_only() -> None: ...

        spec = generate_openapi_spec(strict=True)
        schema = spec["paths"]["/api/alias-request-only"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        resolved = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]

        # Then: unaffected by #783 -- still the validation contract.
        assert set(resolved["properties"]) == {"input_name"}

    def test_symmetric_model_as_request_and_response_merges_without_false_alias(self) -> None:
        # Given: a model with no aliases/computed fields used for both sides.
        @openapi(
            route="symmetric", method="post", requests=SymmetricModel, responses=SymmetricModel
        )
        def symmetric_endpoint() -> None: ...

        # When
        spec = generate_openapi_spec(strict=True)
        operation = spec["paths"]["/api/symmetric"]["post"]
        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]

        # Then: both sides resolve to the one component -- no spurious "_2".
        assert request_ref == response_ref == "#/components/schemas/SymmetricModel"
        assert "SymmetricModel_2" not in spec["components"]["schemas"]
