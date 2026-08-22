from __future__ import annotations

import json

import pytest
import yaml

from azure_functions_openapi.exceptions import OpenAPISpecConfigError
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



class TestQuerystring3_2:
    def test_dict_querystring_emitted_under_3_2(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        try:
            register_openapi_metadata(
                "/api/search",
                "get",
                querystring={
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
            )
            spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
        finally:
            clear_openapi_registry()

        params = spec["paths"]["/api/search"]["get"]["parameters"]
        qs = [p for p in params if p.get("in") == "querystring"]
        assert len(qs) == 1
        schema = qs[0]["content"]["application/x-www-form-urlencoded"]["schema"]
        assert schema["properties"]["q"]["type"] == "string"

    def test_pydantic_querystring_emitted_under_3_2(self) -> None:
        from pydantic import BaseModel

        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        class SearchQuery(BaseModel):
            q: str
            limit: int = 10

        clear_openapi_registry()
        try:
            register_openapi_metadata(
                "/api/search",
                "get",
                querystring=SearchQuery,
                querystring_media_type="application/json",
            )
            spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
        finally:
            clear_openapi_registry()

        params = spec["paths"]["/api/search"]["get"]["parameters"]
        qs = [p for p in params if p.get("in") == "querystring"]
        assert len(qs) == 1
        assert "application/json" in qs[0]["content"]
        schema = qs[0]["content"]["application/json"]["schema"]
        # Pydantic models resolve to a $ref into components.schemas.
        assert "$ref" in schema or "properties" in schema

    def test_querystring_rejected_under_3_1(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        try:
            register_openapi_metadata(
                "/api/search",
                "get",
                querystring={"type": "object"},
            )
            with pytest.raises(OpenAPISpecConfigError) as exc_info:
                generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_1)
        finally:
            clear_openapi_registry()

        assert "querystring" in str(exc_info.value)

    def test_querystring_and_query_coexistence_rejected(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        try:
            register_openapi_metadata(
                "/api/search",
                "get",
                parameters=[
                    {"name": "page", "in": "query", "schema": {"type": "integer"}}
                ],
                querystring={"type": "object"},
            )
            with pytest.raises(OpenAPISpecConfigError) as exc_info:
                generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
        finally:
            clear_openapi_registry()

        assert "query" in str(exc_info.value)

    def test_multiple_querystring_rejected(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        try:
            register_openapi_metadata(
                "/api/search",
                "get",
                parameters=[
                    {
                        "in": "querystring",
                        "content": {
                            "application/x-www-form-urlencoded": {
                                "schema": {"type": "object"}
                            }
                        },
                    }
                ],
                querystring={"type": "object"},
            )
            with pytest.raises(OpenAPISpecConfigError) as exc_info:
                generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
        finally:
            clear_openapi_registry()

        assert "multiple" in str(exc_info.value).lower()

    def test_querystring_content_schema_gets_3_1_conversion(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        try:
            register_openapi_metadata(
                "/api/search",
                "get",
                querystring={
                    "type": "object",
                    "properties": {"q": {"type": "string", "nullable": True}},
                },
            )
            spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
        finally:
            clear_openapi_registry()

        params = spec["paths"]["/api/search"]["get"]["parameters"]
        qs = [p for p in params if p.get("in") == "querystring"][0]
        schema = qs["content"]["application/x-www-form-urlencoded"]["schema"]
        q_schema = schema["properties"]["q"]
        # 3.1 conversion drops the 3.0-only 'nullable' keyword in favour of a
        # null type union.
        assert "nullable" not in q_schema

    def test_decorator_rejects_invalid_querystring_type(self) -> None:
        from azure_functions_openapi.decorator import clear_openapi_registry, openapi

        clear_openapi_registry()
        try:
            with pytest.raises(ValueError, match="querystring"):

                @openapi(method="get", querystring=123)  # type: ignore[arg-type]
                def handler(req: object) -> object:  # pragma: no cover
                    return req
        finally:
            clear_openapi_registry()

    def test_openapi_decorator_emits_querystring(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            get_openapi_registry,
            openapi,
        )

        clear_openapi_registry()
        try:

            @openapi(
                method="get",
                route="decorated-search",
                querystring={
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
            )
            def handler(req: object) -> object:
                return req

            # Metadata stored on the registry captures the querystring schema.
            meta = get_openapi_registry()["handler"]
            assert meta["querystring_schema"]["properties"]["q"]["type"] == "string"

            spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
            params = spec["paths"]["/api/decorated-search"]["get"]["parameters"]
            qs = [p for p in params if p.get("in") == "querystring"]
            assert len(qs) == 1
        finally:
            clear_openapi_registry()

    def test_raw_querystring_missing_content_rejected(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        try:
            with pytest.raises(ValueError, match="content"):
                register_openapi_metadata(
                    "/api/search",
                    "get",
                    parameters=[{"in": "querystring"}],
                )
        finally:
            clear_openapi_registry()

    def test_register_metadata_rejects_invalid_querystring_type(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        try:
            with pytest.raises(ValueError, match="querystring"):
                register_openapi_metadata(
                    "/api/search",
                    "get",
                    querystring=123,  # type: ignore[arg-type]
                )
        finally:
            clear_openapi_registry()