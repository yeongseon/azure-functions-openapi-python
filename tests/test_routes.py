"""Tests for the shared Azure Functions route-prefix helpers."""

import pytest

from azure_functions_openapi.routes import (
    ALL_HTTP_METHODS,
    BODYLESS_HTTP_METHODS,
    DEFAULT_ROUTE_PREFIX,
    STANDARD_OPENAPI_METHODS,
    apply_route_prefix,
    normalize_route_prefix,
)


@pytest.mark.parametrize(
    ("route_prefix", "expected"),
    [
        ("", ""),
        ("/", ""),
        ("api", "/api"),
        (" /v1/ ", "/v1"),
    ],
)
def test_normalize_route_prefix(route_prefix: str, expected: str) -> None:
    assert normalize_route_prefix(route_prefix) == expected


@pytest.mark.parametrize(
    ("path", "prefix", "expected"),
    [
        ("/users", "/api", "/api/users"),
        ("/api/users", "/api", "/api/users"),
        ("/api", "/api", "/api"),
        ("/users", "", "/users"),
    ],
)
def test_apply_route_prefix_is_idempotent(path: str, prefix: str, expected: str) -> None:
    assert apply_route_prefix(path, prefix) == expected


def test_default_constant_is_canonical() -> None:
    assert normalize_route_prefix(DEFAULT_ROUTE_PREFIX) == "/api"


def test_segment_boundary_not_confused_by_common_stem() -> None:
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
