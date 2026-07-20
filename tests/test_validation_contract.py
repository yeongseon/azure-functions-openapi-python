"""Tests for the read-side validation metadata contract."""

from __future__ import annotations

from azure_functions_openapi._validation_contract import (
    HANDLER_METADATA_ATTR,
    SUPPORTED_VALIDATION_VERSIONS,
    VALIDATION_NAMESPACE,
    ValidationMetadata,
)


def test_handler_metadata_attr() -> None:
    assert HANDLER_METADATA_ATTR == "_azure_functions_metadata"


def test_validation_namespace() -> None:
    assert VALIDATION_NAMESPACE == "validation"


def test_supported_versions() -> None:
    assert SUPPORTED_VALIDATION_VERSIONS == frozenset({1})


def test_validation_metadata_shape() -> None:
    meta: ValidationMetadata = {"version": 1, "body": object()}
    assert meta["version"] == 1
