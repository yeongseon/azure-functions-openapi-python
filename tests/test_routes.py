"""Tests for the shared Azure Functions route-prefix helpers."""

import pytest

from azure_functions_openapi.routes import apply_route_prefix, normalize_route_prefix


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
