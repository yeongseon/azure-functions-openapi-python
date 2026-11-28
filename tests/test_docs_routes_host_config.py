from collections.abc import Iterator
import json
from pathlib import Path

import azure.functions as func
import pytest

from azure_functions_openapi import (
    clear_openapi_registry,
    register_openapi_routes,
    resolve_route_prefix,
)
from azure_functions_openapi.decorator import openapi


@pytest.mark.parametrize("case", [("v1", "/v1/openapi.json"), ("", "/openapi.json")])
def test_swagger_uses_resolved_host_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: tuple[str, str]
) -> None:
    # Given
    prefix, expected_url = case
    monkeypatch.delenv("AzureFunctionsJobHost__extensions__http__routePrefix", raising=False)
    path = tmp_path / "host.json"
    path.write_text(json.dumps({"extensions": {"http": {"routePrefix": prefix}}}), encoding="utf-8")
    routes = register_openapi_routes(
        func.FunctionApp(), title="API", version="1.0.0", route_prefix=resolve_route_prefix(path)
    )
    assert routes.docs is not None
    request = func.HttpRequest(method="GET", url="/docs", body=b"")
    # When
    response = routes.docs(request)
    # Then
    assert f'url: "{expected_url}"' in response.get_body().decode()


_SETTING = "AzureFunctionsJobHost__extensions__http__routePrefix"


def _write_host(path: Path, prefix: str) -> Path:
    host = path / "host.json"
    host.write_text(json.dumps({"extensions": {"http": {"routePrefix": prefix}}}), encoding="utf-8")
    return host


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _docs_and_spec_paths(tmp_path: Path, **kwargs: object) -> tuple[str, list[str]]:
    app = func.FunctionApp()

    @openapi(summary="Ping")
    @app.route(route="ping", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def ping(req: func.HttpRequest) -> func.HttpResponse:
        return func.HttpResponse("ok")

    routes = register_openapi_routes(app, title="API", version="1.0.0", **kwargs)  # type: ignore[arg-type]
    assert routes.docs is not None and routes.json is not None
    html = routes.docs(func.HttpRequest(method="GET", url="/docs", body=b"")).get_body().decode()
    spec = json.loads(
        routes.json(func.HttpRequest(method="GET", url="/openapi.json", body=b"")).get_body()
    )
    return html, sorted(spec["paths"])


@pytest.mark.parametrize(
    ("configured", "ui_url", "ping_path"),
    [
        ("", "/openapi.json", "/ping"),
        ("v1", "/v1/openapi.json", "/v1/ping"),
        ("api", "/api/openapi.json", "/api/ping"),
    ],
)
def test_none_resolves_prefix_from_host_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured: str,
    ui_url: str,
    ping_path: str,
) -> None:
    monkeypatch.delenv(_SETTING, raising=False)
    host = _write_host(tmp_path, configured)

    html, paths = _docs_and_spec_paths(tmp_path, route_prefix=None, host_json=host)

    assert f'url: "{ui_url}"' in html
    assert ping_path in paths


def test_environment_setting_beats_host_json_and_explicit_prefix_beats_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _write_host(tmp_path, "fromhost")
    monkeypatch.setenv(_SETTING, "fromenv")

    html, _ = _docs_and_spec_paths(tmp_path, route_prefix=None, host_json=host)
    assert 'url: "/fromenv/openapi.json"' in html

    html, _ = _docs_and_spec_paths(tmp_path, route_prefix="/explicit", host_json=host)
    assert 'url: "/explicit/openapi.json"' in html


def test_default_is_still_api_and_literal_auto_prefix_is_not_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_SETTING, raising=False)
    host = _write_host(tmp_path, "fromhost")

    html, _ = _docs_and_spec_paths(tmp_path, host_json=host)
    assert 'url: "/api/openapi.json"' in html

    html, _ = _docs_and_spec_paths(tmp_path, route_prefix="auto", host_json=host)
    assert 'url: "/auto/openapi.json"' in html


def test_none_without_host_json_falls_back_to_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_SETTING, raising=False)

    html, _ = _docs_and_spec_paths(tmp_path, route_prefix=None, host_json=tmp_path / "missing.json")

    assert 'url: "/api/openapi.json"' in html


def test_register_openapi_routes_forwards_header_policy(tmp_path: Path) -> None:
    app = func.FunctionApp()
    routes = register_openapi_routes(
        app, title="API", version="1.0.0", hsts=None, send_requested_with_header=False
    )
    assert routes.docs is not None

    response = routes.docs(func.HttpRequest(method="GET", url="/docs", body=b""))

    assert "Strict-Transport-Security" not in response.headers
    assert "X-Requested-With" not in response.get_body().decode()
