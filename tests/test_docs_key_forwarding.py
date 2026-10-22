from __future__ import annotations

import importlib
import inspect
import logging
from typing import Literal
from urllib.parse import urlencode
import warnings

import azure.functions as func
import pytest

from azure_functions_openapi import register_openapi_routes


@pytest.mark.parametrize(
    "code",
    ["CANARY_KEY_9f3a", "CANARY_KEY_9f3a\"<'\\</script>", "CANARY_KEY_9f3a" * 10000],
    ids=["ordinary", "hostile", "huge"],
)
def test_header_mode_never_echoes_page_key(code: str, caplog: pytest.LogCaptureFixture) -> None:
    # Given: even repeated/hostile query values are browser-owned, not rendered server-side.
    caplog.set_level(logging.DEBUG, logger="azure_functions_openapi")
    routes = register_openapi_routes(
        func.FunctionApp(),
        title="Private",
        version="1",
        auth_level=func.AuthLevel.FUNCTION,
        docs_key_forwarding="header",
    )
    assert routes.docs is not None
    request = func.HttpRequest(
        method="GET",
        url="https://example.test/api/docs?"
        + urlencode([("code", code), ("code", "CANARY_SECOND")]),
        params={"code": code},
        headers={},
        body=b"",
    )

    # When
    response = routes.docs(request)

    # Then: no raw or encoded key in any server-produced channel.
    output = response.get_body().decode() + repr(dict(response.headers)) + repr(caplog.records)
    assert "CANARY_KEY_9f3a" not in output
    assert "CANARY_SECOND" not in output
    assert 'url: "/api/openapi.json"' in output
    assert "history.replaceState" in output
    assert "no-store" in response.headers["Cache-Control"]
    assert not {"Location", "Set-Cookie"}.intersection(response.headers)
    assert all("CANARY" not in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("mode", ["query", "header", "none"])
@pytest.mark.parametrize("auth", list(func.AuthLevel))
def test_explicit_modes_forward_only_when_protected(
    mode: Literal["query", "header", "none"],
    auth: func.AuthLevel,
) -> None:
    # Given
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        routes = register_openapi_routes(
            func.FunctionApp(),
            title="Docs",
            version="1",
            auth_level=auth,
            docs_key_forwarding=mode,
        )
    assert routes.docs is not None

    # When
    body = (
        routes.docs(
            func.HttpRequest(
                method="GET",
                url="/api/docs?code=CANARY",
                params={"code": "CANARY"},
                body=b"",
            )
        )
        .get_body()
        .decode()
    )

    # Then
    protected = auth is not func.AuthLevel.ANONYMOUS
    assert ("?code=CANARY" in body) is (protected and mode == "query")
    assert ("history.replaceState" in body) is (protected and mode == "header")
    assert not caught


@pytest.mark.parametrize("auth", [func.AuthLevel.FUNCTION, func.AuthLevel.ADMIN])
def test_default_warns_once_per_registration_at_caller(auth: func.AuthLevel) -> None:
    # Given
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        line = inspect.currentframe()
        assert line is not None
        expected_line = line.f_lineno + 2
        # When
        routes = register_openapi_routes(
            func.FunctionApp(),
            title="Docs",
            version="1",
            auth_level=auth,
        )
        assert routes.docs is not None
        for _ in range(2):
            routes.docs(func.HttpRequest(method="GET", url="/api/docs", body=b""))

    # Then
    assert len(caught) == 1
    warning = caught[0]
    assert warning.category is DeprecationWarning
    assert warning.filename == __file__
    assert warning.lineno == expected_line
    message = str(warning.message)
    assert 'docs_key_forwarding="header"' in message
    assert '"none"' in message
    assert "future minor release before 1.0" in message
    assert "key-in-URL" in message
    assert "CANARY" not in message


def test_anonymous_default_does_not_warn() -> None:
    # Given / When
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        register_openapi_routes(func.FunctionApp(), title="Docs", version="1")
    # Then
    assert not caught


def test_registered_handler_parameters_match_host_binding_names() -> None:
    # Given
    routes = register_openapi_routes(func.FunctionApp(), title="Docs", version="1")
    # When / Then: the real worker rejects parameters missing from function bindings.
    for handler in (routes.json, routes.yaml, routes.docs):
        assert handler is not None
        assert list(inspect.signature(handler).parameters) == ["req"]


@pytest.mark.parametrize("value", ["invalid", "CANARY_INVALID", 123, [], {}])
def test_invalid_forwarding_is_rejected_without_echo(
    value: str | int | list[str] | dict[str, str],
) -> None:
    # Given: getattr deliberately exercises the untyped public boundary.
    register = getattr(
        importlib.import_module("azure_functions_openapi"), "register_openapi_routes"
    )
    # When / Then
    with pytest.raises((ValueError, TypeError), match="docs_key_forwarding") as error:
        register(func.FunctionApp(), title="Docs", version="1", docs_key_forwarding=value)
    assert "CANARY_INVALID" not in str(error.value)
