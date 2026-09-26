"""Focused tests for the route-prefix policy and HTTP method sets (#587).

Covers ``azure_functions_openapi.routes`` — the single source of truth shared
by the spec generator, validation bridge, CLI, and public helpers.
"""

from __future__ import annotations

import pytest

from azure_functions_openapi.routes import (
    ALL_HTTP_METHODS,
    BODYLESS_HTTP_METHODS,
    DEFAULT_ROUTE_PREFIX,
    STANDARD_OPENAPI_METHODS,
    apply_route_prefix,
    normalize_route_prefix,
)


class TestNormalizeRoutePrefix:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", ""),
            ("   ", ""),
            ("/", ""),
            ("api", "/api"),
            ("/api", "/api"),
            ("api/", "/api"),
            ("/api/", "/api"),
            (" /api/ ", "/api"),
            ("v1/items", "/v1/items"),
        ],
    )
    def test_canonical_forms(self, raw: str, expected: str) -> None:
        assert normalize_route_prefix(raw) == expected

    def test_default_constant_is_canonical(self) -> None:
        assert normalize_route_prefix(DEFAULT_ROUTE_PREFIX) == "/api"


class TestApplyRoutePrefix:
    def test_empty_prefix_returns_path_unchanged(self) -> None:
        assert apply_route_prefix("/users", "") == "/users"

    def test_prepends_prefix(self) -> None:
        assert apply_route_prefix("/users", "/api") == "/api/users"

    def test_already_prefixed_is_idempotent(self) -> None:
        assert apply_route_prefix("/api/users", "/api") == "/api/users"

    def test_path_equal_to_prefix_is_idempotent(self) -> None:
        assert apply_route_prefix("/api", "/api") == "/api"

    def test_double_application_is_stable(self) -> None:
        once = apply_route_prefix("/users", "/api")
        assert apply_route_prefix(once, "/api") == once

    def test_segment_boundary_not_confused_by_common_stem(self) -> None:
        # "/api2" only shares a string stem with "/api"; it is not the prefix
        # segment, so the prefix must still be applied.
        assert apply_route_prefix("/api2/users", "/api") == "/api/api2/users"


class TestMethodSets:
    def test_all_http_methods_matches_azure_http_method_enum(self) -> None:
        assert ALL_HTTP_METHODS == (
            "get",
            "post",
            "put",
            "delete",
            "patch",
            "head",
            "options",
        )

    def test_all_http_methods_excludes_trace(self) -> None:
        assert "trace" not in ALL_HTTP_METHODS

    def test_bodyless_methods_are_subset_of_all_http_methods(self) -> None:
        assert BODYLESS_HTTP_METHODS == frozenset({"get", "head", "delete"})
        assert BODYLESS_HTTP_METHODS <= set(ALL_HTTP_METHODS)

    def test_standard_openapi_methods_superset_of_azure_methods(self) -> None:
        assert set(ALL_HTTP_METHODS) <= STANDARD_OPENAPI_METHODS
        assert "trace" in STANDARD_OPENAPI_METHODS
        # CONNECT is intentionally not a first-class path-item operation.
        assert "connect" not in STANDARD_OPENAPI_METHODS
