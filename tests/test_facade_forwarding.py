from __future__ import annotations

from collections.abc import Callable
import inspect
from typing import Any
from unittest.mock import patch

import pytest

import azure_functions_openapi as api
from azure_functions_openapi.registry import OpenAPIRegistry
from azure_functions_openapi.spec import SpecReport


@pytest.mark.parametrize(
    "facade", [api.get_openapi_json, api.get_openapi_yaml, api.generate_openapi_report]
)
def test_facade_parameters_match_spec_signature(facade: Callable[..., Any]) -> None:
    # Given/When: inspect the explicit public signatures.
    actual = inspect.signature(facade).parameters
    expected = inspect.signature(api.generate_openapi_spec).parameters
    # Then: order, defaults, annotations and positional compatibility agree.
    assert actual == expected
    assert all(p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD for p in actual.values())


@pytest.mark.parametrize(
    "facade", [api.get_openapi_json, api.get_openapi_yaml, api.generate_openapi_report]
)
@pytest.mark.parametrize("positional", [False, True])
def test_facades_forward_every_distinct_argument(
    facade: Callable[..., Any], positional: bool
) -> None:
    # Given: distinct values exercise every forwarding slot, including adjacent booleans.
    options = {
        "title": "distinct title",
        "version": "2.3",
        "openapi_version": "3.2.0",
        "description": "description",
        "security_schemes": {"key": {"type": "apiKey"}},
        "route_prefix": "/custom",
        "strict": True,
        "registry": OpenAPIRegistry(),
        "hoist_flat_schemas": True,
        "infer_auth_level": False,
        "servers": [{"url": "https://example.test"}],
        "contact": {"name": "contact"},
        "license": {"name": "license"},
        "external_docs": {"url": "https://example.test/docs"},
        "tags": [{"name": "tag"}],
        "app": None,
    }
    report_facade = facade is api.generate_openapi_report
    target = "_generate_openapi_report" if report_facade else "generate_openapi_spec"
    result: SpecReport | dict[str, Any] = SpecReport(spec={}, warnings=()) if report_facade else {}
    # When: callers use either supported argument form.
    with patch.object(api, target, return_value=result) as generate:
        if positional:
            facade(*options.values())
        else:
            facade(**options)
    # Then: binding the underlying call recovers every input without reordering or omission.
    signature = inspect.signature(api.generate_openapi_spec)
    bound = signature.bind(*generate.call_args.args, **generate.call_args.kwargs)
    expected = {k: v for k, v in options.items() if not report_facade or k != "app"}
    assert bound.arguments == expected
    assert generate.call_args.args == ()
