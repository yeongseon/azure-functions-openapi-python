import json
from pathlib import Path

import azure.functions as func
import pytest

from azure_functions_openapi import register_openapi_routes, resolve_route_prefix


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
