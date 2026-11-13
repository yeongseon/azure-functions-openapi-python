"""Pin the 3.0 vs 3.1/3.2 nullable comparison documented in docs/configuration.md.

The excerpts are produced by the real ``generate_openapi_spec`` conversion path;
the documentation JSON blocks are parsed and compared against them, so the guide
cannot drift from the library's output.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from openapi_schema_validator import OAS30Validator, OAS31Validator
from pydantic import BaseModel
import pytest

from azure_functions_openapi.decorator import clear_openapi_registry, register_openapi_metadata
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import generate_openapi_spec

_DOC = Path(__file__).resolve().parent.parent / "docs" / "configuration.md"
_HEADING = "### Nullable fields side by side (3.0 vs 3.1/3.2)"


class Address(BaseModel):
    city: str


class Profile(BaseModel):
    user_id: int
    nickname: str | None = None
    address: Address | None = None


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _spec(version: str) -> dict[str, Any]:
    registry = OpenAPIRegistry()
    register_openapi_metadata(
        "/profile",
        "GET",
        response_model=Profile,
        response={200: {"description": "ok"}},
        registry=registry,
    )
    return generate_openapi_spec(openapi_version=version, registry=registry, strict=True)


def _profile_properties(spec: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = spec["components"]["schemas"]["Profile"]["properties"]
    return {k: properties[k] for k in ("nickname", "address")}


def _documented_excerpts() -> list[dict[str, Any]]:
    text = _DOC.read_text(encoding="utf-8")
    section = text.split(_HEADING, 1)[1].split("\n### ", 1)[0]
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", section, re.S)]


def test_three_one_nullable_shape_is_a_json_schema_union() -> None:
    props = _profile_properties(_spec("3.1.0"))

    assert props["nickname"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": None,
        "title": "Nickname",
    }
    assert props["address"] == {
        "anyOf": [{"$ref": "#/components/schemas/Address"}, {"type": "null"}],
        "default": None,
    }
    assert '"nullable"' not in json.dumps(props)


def test_three_zero_nullable_shape_uses_the_nullable_keyword() -> None:
    props = _profile_properties(_spec("3.0.0"))

    assert props["nickname"] == {
        "default": None,
        "title": "Nickname",
        "nullable": True,
        "type": "string",
    }
    assert props["address"]["nullable"] is True
    assert props["address"]["type"] == "object"
    assert "$ref" not in props["address"]
    assert '"null"' not in json.dumps(props)


def test_three_two_matches_three_one_for_this_model() -> None:
    assert _profile_properties(_spec("3.2.0")) == _profile_properties(_spec("3.1.0"))


def test_documentation_excerpts_match_generated_output() -> None:
    three_zero, three_one = _documented_excerpts()

    assert three_zero == _profile_properties(_spec("3.0.0"))
    assert three_one == _profile_properties(_spec("3.1.0"))
    assert three_one == _profile_properties(_spec("3.2.0"))


@pytest.mark.parametrize(
    ("version", "validator_cls"),
    [("3.0.0", OAS30Validator), ("3.1.0", OAS31Validator), ("3.2.0", OAS31Validator)],
)
def test_each_form_accepts_null_and_populated_values(version: str, validator_cls: Any) -> None:
    spec = _spec(version)
    schema = spec["paths"]["/api/profile"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    validator = validator_cls({**schema, "components": spec["components"]})

    null_payload = Profile(user_id=1).model_dump(mode="json")
    populated = Profile(user_id=1, nickname="ada", address=Address(city="Paris")).model_dump(
        mode="json"
    )

    assert null_payload["nickname"] is None and null_payload["address"] is None
    assert list(validator.iter_errors(null_payload)) == []
    assert list(validator.iter_errors(populated)) == []
    assert list(validator.iter_errors({"user_id": 1, "nickname": 5})) != []


def test_faq_links_the_comparison() -> None:
    faq = (_DOC.parent / "faq.md").read_text(encoding="utf-8")
    assert "configuration.md#nullable-fields-side-by-side-30-vs-3132" in faq
