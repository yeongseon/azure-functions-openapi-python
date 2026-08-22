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


class TestAdditionalOperations3_2:
    """#471: non-standard HTTP methods via 3.2 ``additionalOperations``."""

    def _register_custom(self, method: str = "purge") -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        register_openapi_metadata(
            "/api/cache",
            method,
            summary="Purge cache",
        )

    def test_custom_method_emitted_under_additional_operations(self) -> None:
        from azure_functions_openapi.decorator import clear_openapi_registry

        self._register_custom("purge")
        try:
            spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
        finally:
            clear_openapi_registry()

        path_item = spec["paths"]["/api/cache"]
        # The non-standard method is NOT a first-class path-item field.
        assert "purge" not in path_item
        # It lives under additionalOperations, keyed by the uppercased method.
        assert "PURGE" in path_item["additionalOperations"]
        op = path_item["additionalOperations"]["PURGE"]
        assert op["summary"] == "Purge cache"
        assert "responses" in op

    def test_standard_methods_are_not_moved(self) -> None:
        from azure_functions_openapi.decorator import clear_openapi_registry

        self._register_custom("post")
        try:
            spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
        finally:
            clear_openapi_registry()

        path_item = spec["paths"]["/api/cache"]
        assert "post" in path_item
        assert "additionalOperations" not in path_item

    def test_custom_method_dropped_with_warning_on_3_1(self) -> None:
        from azure_functions_openapi.decorator import clear_openapi_registry

        self._register_custom("purge")
        try:
            spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_1)
        finally:
            clear_openapi_registry()

        path_item = spec["paths"]["/api/cache"]
        # 3.1 cannot represent it: dropped, and no additionalOperations emitted.
        assert "purge" not in path_item
        assert "additionalOperations" not in path_item

    def test_custom_method_on_3_1_strict_raises(self) -> None:
        from azure_functions_openapi.decorator import clear_openapi_registry

        self._register_custom("purge")
        try:
            with pytest.raises(OpenAPISpecConfigError) as exc_info:
                generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_1, strict=True)
        finally:
            clear_openapi_registry()

        assert "PURGE" in str(exc_info.value)

    def test_additional_operations_sorted_deterministically(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        register_openapi_metadata("/api/r", "purge", summary="a")
        register_openapi_metadata("/api/r", "link", summary="b")
        try:
            spec = generate_openapi_spec(openapi_version=OPENAPI_VERSION_3_2)
        finally:
            clear_openapi_registry()

        additional = spec["paths"]["/api/r"]["additionalOperations"]
        assert list(additional.keys()) == sorted(additional.keys())
        assert set(additional.keys()) == {"LINK", "PURGE"}


class TestValidateMethodTokens:
    """#471: _validate_method accepts HTTP tokens, rejects garbage."""

    def test_non_standard_token_accepted(self) -> None:
        from azure_functions_openapi.decorator import _validate_method

        assert _validate_method("PURGE", "fn") == "purge"
        assert _validate_method("query", "fn") == "query"

    def test_whitespace_in_method_rejected(self) -> None:
        from azure_functions_openapi.decorator import _validate_method

        with pytest.raises(ValueError):
            _validate_method("GET POST", "fn")

    def test_empty_method_rejected(self) -> None:
        from azure_functions_openapi.decorator import _validate_method

        with pytest.raises(ValueError):
            _validate_method("   ", "fn")
