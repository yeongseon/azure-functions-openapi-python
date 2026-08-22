from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import (
    OPENAPI_VERSION_3_1,
    OPENAPI_VERSION_3_2,
    generate_openapi_spec,
    get_openapi_json,
    get_openapi_yaml,
)


class TestGenerateOpenapiSpec3_2:
    def test_emits_3_2_document(self) -> None:
        spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)

        assert spec["openapi"] == "3.2.0"

    def test_3_2_includes_info_summary(self) -> None:
        # 3.2, like 3.1, mirrors the title into info.summary.
        spec = generate_openapi_spec(title="My 3.2 API", openapi_version=OPENAPI_VERSION_3_2)

        assert spec["info"]["summary"] == "My 3.2 API"

    def test_3_2_reuses_3_1_schema_conversion(self) -> None:
        # 3.2 is a backward-compatible superset of 3.1 and shares the same
        # JSON Schema 2020-12 dialect, so nullable/example conversions apply.
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        try:
            register_openapi_metadata(
                "/api/conv",
                "get",
                request_body={
                    "type": "object",
                    "properties": {"name": {"type": "string", "nullable": True}},
                },
            )
            spec_3_1 = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_1)
            spec_3_2 = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
        finally:
            clear_openapi_registry()

        # Same conversion path: everything except the version banner matches.
        spec_3_1["openapi"] = spec_3_2["openapi"]
        assert spec_3_1 == spec_3_2

    def test_unsupported_version_still_raises(self) -> None:
        with pytest.raises(OpenAPISpecConfigError) as exc_info:
            generate_openapi_spec(openapi_version="4.0.0")

        assert "Unsupported OpenAPI version" in str(exc_info.value)


class TestGetOpenapiJson3_2:
    def test_json_emits_3_2(self) -> None:
        result = get_openapi_json(openapi_version=OPENAPI_VERSION_3_2)

        assert json.loads(result)["openapi"] == "3.2.0"


class TestGetOpenapiYaml3_2:
    def test_yaml_emits_3_2(self) -> None:
        result = get_openapi_yaml(openapi_version=OPENAPI_VERSION_3_2)

        assert yaml.safe_load(result)["openapi"] == "3.2.0"



class TestStreamingItemSchema3_2:
    """OpenAPI 3.2 sequential/streaming media types via ``itemSchema`` (#473)."""

    def _register(self, response: dict[int, dict[str, Any]], *, registry: OpenAPIRegistry) -> None:
        from azure_functions_openapi.decorator import register_openapi_metadata

        register_openapi_metadata(
            "/api/events",
            "get",
            response=response,
            registry=registry,
        )

    def test_item_schema_model_resolves_to_ref(self) -> None:
        from pydantic import BaseModel

        from azure_functions_openapi.registry import OpenAPIRegistry

        class SseEvent(BaseModel):
            id: int
            message: str

        registry = OpenAPIRegistry()
        self._register(
            {
                200: {
                    "description": "Event stream",
                    "content": {"text/event-stream": {"itemSchema": SseEvent}},
                }
            },
            registry=registry,
        )

        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_2, registry=registry, route_prefix=""
        )
        media = spec["paths"]["/api/events"]["get"]["responses"]["200"]["content"][
            "text/event-stream"
        ]
        assert media["itemSchema"] == {"$ref": "#/components/schemas/SseEvent"}
        assert "SseEvent" in spec["components"]["schemas"]

    def test_item_schema_generic_alias_resolves_to_array(self) -> None:
        from pydantic import BaseModel

        from azure_functions_openapi.registry import OpenAPIRegistry

        class Item(BaseModel):
            name: str

        registry = OpenAPIRegistry()
        self._register(
            {
                200: {
                    "description": "Sequential items",
                    "content": {"application/jsonl": {"itemSchema": list[Item]}},
                }
            },
            registry=registry,
        )

        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_2, registry=registry, route_prefix=""
        )
        media = spec["paths"]["/api/events"]["get"]["responses"]["200"]["content"][
            "application/jsonl"
        ]
        assert media["itemSchema"]["type"] == "array"

    def test_item_schema_inline_dict_passes_through(self) -> None:
        from azure_functions_openapi.registry import OpenAPIRegistry

        registry = OpenAPIRegistry()
        self._register(
            {
                200: {
                    "description": "Event stream",
                    "content": {
                        "text/event-stream": {
                            "itemSchema": {
                                "type": "object",
                                "properties": {"message": {"type": "string"}},
                            }
                        }
                    },
                }
            },
            registry=registry,
        )

        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_2, registry=registry, route_prefix=""
        )
        media = spec["paths"]["/api/events"]["get"]["responses"]["200"]["content"][
            "text/event-stream"
        ]
        assert media["itemSchema"]["properties"]["message"] == {"type": "string"}

    def test_item_schema_and_schema_coexist(self) -> None:
        from pydantic import BaseModel

        from azure_functions_openapi.registry import OpenAPIRegistry

        class Event(BaseModel):
            seq: int

        registry = OpenAPIRegistry()
        self._register(
            {
                200: {
                    "description": "Event stream",
                    "content": {
                        "text/event-stream": {
                            "schema": {"type": "array"},
                            "itemSchema": Event,
                        }
                    },
                }
            },
            registry=registry,
        )

        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_2, registry=registry, route_prefix=""
        )
        media = spec["paths"]["/api/events"]["get"]["responses"]["200"]["content"][
            "text/event-stream"
        ]
        assert media["schema"] == {"type": "array"}
        assert media["itemSchema"] == {"$ref": "#/components/schemas/Event"}

    def test_item_schema_warns_on_pre_3_2_version(self) -> None:
        from azure_functions_openapi.registry import OpenAPIRegistry

        registry = OpenAPIRegistry()
        self._register(
            {
                200: {
                    "description": "Event stream",
                    "content": {
                        "text/event-stream": {
                            "itemSchema": {"type": "object"},
                        }
                    },
                }
            },
            registry=registry,
        )

        with pytest.warns(RuntimeWarning, match="itemSchema"):
            generate_openapi_spec(
                openapi_version=OPENAPI_VERSION_3_1, registry=registry, route_prefix=""
            )

    def test_item_schema_no_warning_on_3_2(self, recwarn: pytest.WarningsRecorder) -> None:
        from azure_functions_openapi.registry import OpenAPIRegistry

        registry = OpenAPIRegistry()
        self._register(
            {
                200: {
                    "description": "Event stream",
                    "content": {
                        "text/event-stream": {
                            "itemSchema": {"type": "object"},
                        }
                    },
                }
            },
            registry=registry,
        )

        generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_2, registry=registry, route_prefix=""
        )
        assert not [w for w in recwarn.list if issubclass(w.category, RuntimeWarning)]

    def test_plain_schema_response_unaffected(self) -> None:
        """Regression: schema-only responses keep resolving as before."""
        from pydantic import BaseModel

        from azure_functions_openapi.registry import OpenAPIRegistry

        class Body(BaseModel):
            ok: bool

        registry = OpenAPIRegistry()
        self._register(
            {
                200: {
                    "description": "JSON body",
                    "content": {"application/json": {"schema": Body}},
                }
            },
            registry=registry,
        )

        spec = generate_openapi_spec(
            openapi_version=OPENAPI_VERSION_3_2, registry=registry, route_prefix=""
        )
        media = spec["paths"]["/api/events"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]
        assert media["schema"] == {"$ref": "#/components/schemas/Body"}
        assert "itemSchema" not in media