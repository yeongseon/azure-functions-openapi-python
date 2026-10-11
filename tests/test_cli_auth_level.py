from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import sys
from typing import Any
from unittest import mock

import azure.functions as func
import pytest
import yaml

from azure_functions_openapi.cli import main
from azure_functions_openapi.decorator import clear_openapi_registry, openapi
from azure_functions_openapi.spec import AZURE_FUNCTION_KEY_SCHEME_NAME


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


def _app_with_route(
    auth_level: func.AuthLevel,
    *,
    security: list[dict[str, list[str]]] | None = None,
) -> func.FunctionApp:
    app = func.FunctionApp()

    @openapi(
        summary="secured route",
        security=security,
        security_scheme=(
            {"MyAuth": {"type": "http", "scheme": "bearer"}} if security is not None else None
        ),
    )
    @app.route(route="secured", auth_level=auth_level, methods=["GET"])
    def secured(req: func.HttpRequest) -> func.HttpResponse:  # pragma: no cover
        return func.HttpResponse("ok")

    return app


def _run_cli(
    app: func.FunctionApp,
    tmp_path: Path,
    *,
    output_format: str = "json",
    infer_auth_level: bool = True,
) -> dict[str, Any]:
    output = tmp_path / f"openapi.{output_format}"
    argv = [
        "azure-functions-openapi",
        "generate",
        "--app",
        "function_app:app",
        "--format",
        output_format,
        "--output",
        str(output),
    ]
    if infer_auth_level:
        argv.append("--infer-auth-level")

    with mock.patch.object(sys, "argv", argv):
        with mock.patch(
            "azure_functions_openapi.cli._import_app_module",
            return_value=(app, True),
        ):
            assert main() == 0

    content = output.read_text(encoding="utf-8")
    parsed = json.loads(content) if output_format == "json" else yaml.safe_load(content)
    assert isinstance(parsed, dict)
    return parsed


@pytest.mark.parametrize(
    ("auth_level", "output_format"),
    [
        (func.AuthLevel.FUNCTION, "json"),
        (func.AuthLevel.ADMIN, "yaml"),
    ],
)
def test_cli_infers_function_key_security_for_keyed_routes(
    auth_level: func.AuthLevel,
    output_format: str,
    tmp_path: Path,
) -> None:
    # Given: a real FunctionApp route whose binding requires a Functions key.
    app = _app_with_route(auth_level)

    # When: CLI generation opts into binding auth-level inference.
    spec = _run_cli(app, tmp_path, output_format=output_format)

    # Then: JSON and YAML output carry the shared x-functions-key scheme.
    operation = spec["paths"]["/api/secured"]["get"]
    assert operation["security"] == [{AZURE_FUNCTION_KEY_SCHEME_NAME: []}]
    scheme = spec["components"]["securitySchemes"][AZURE_FUNCTION_KEY_SCHEME_NAME]
    assert scheme == {"type": "apiKey", "in": "header", "name": "x-functions-key"}


def test_cli_anonymous_route_has_no_inferred_security(tmp_path: Path) -> None:
    # Given: a real FunctionApp route that permits anonymous requests.
    app = _app_with_route(func.AuthLevel.ANONYMOUS)

    # When: CLI generation opts into binding auth-level inference.
    spec = _run_cli(app, tmp_path)

    # Then: the operation remains public and no key scheme is emitted.
    assert "security" not in spec["paths"]["/api/secured"]["get"]
    assert "securitySchemes" not in spec.get("components", {})


def test_cli_explicit_security_takes_precedence_over_inference(tmp_path: Path) -> None:
    # Given: explicit bearer security on a route whose binding requires a function key.
    app = _app_with_route(func.AuthLevel.FUNCTION, security=[{"MyAuth": []}])

    # When: CLI auth-level inference is enabled.
    spec = _run_cli(app, tmp_path)

    # Then: authored security wins and no inferred scheme is added.
    assert spec["paths"]["/api/secured"]["get"]["security"] == [{"MyAuth": []}]
    schemes = spec["components"]["securitySchemes"]
    assert schemes == {"MyAuth": {"type": "http", "scheme": "bearer"}}


def test_cli_auth_level_inference_remains_off_by_default(tmp_path: Path) -> None:
    # Given: a function-key route and no inference flag.
    app = _app_with_route(func.AuthLevel.FUNCTION)

    # When: the CLI generates with its default options.
    spec = _run_cli(app, tmp_path, infer_auth_level=False)

    # Then: existing output stays unchanged.
    assert "security" not in spec["paths"]["/api/secured"]["get"]
    assert "securitySchemes" not in spec.get("components", {})


@pytest.mark.parametrize("app_args", [[], ["--app", "function_app"]])
def test_cli_inference_requires_scan_capable_app(
    app_args: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: inference is requested without a scan-capable module:variable target.
    argv = ["azure-functions-openapi", "generate", *app_args, "--infer-auth-level"]

    # When: the CLI validates the request.
    with mock.patch.object(sys, "argv", argv):
        with pytest.raises(SystemExit) as exc_info:
            main()

    # Then: it exits like an argparse usage error and names the required form.
    assert exc_info.value.code == 2
    message = capsys.readouterr().err
    assert "--infer-auth-level" in message
    assert "--app module:variable" in message


@pytest.mark.parametrize("target", [":app", "function_app:", "a:b:c", "  : app", "app:  "])
def test_cli_rejects_malformed_inference_app_target(
    target: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    argv = [
        "azure-functions-openapi",
        "generate",
        "--app",
        target,
        "--infer-auth-level",
    ]

    # When
    with mock.patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc_info:
        main()

    # Then
    assert exc_info.value.code == 2
    assert "--app module:variable" in capsys.readouterr().err


@pytest.mark.parametrize("resolved_app", [func.FunctionApp(), 42])
def test_cli_inference_fails_closed_when_discovery_is_empty_or_skipped(
    resolved_app: Any,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    output = tmp_path / "openapi.json"
    argv = [
        "azure-functions-openapi",
        "generate",
        "--app",
        "function_app:app",
        "--infer-auth-level",
        "--output",
        str(output),
    ]

    # When
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch(
            "azure_functions_openapi.cli._import_app_module",
            return_value=(resolved_app, True),
        ),
    ):
        result = main()

    # Then
    assert result != 0
    assert not output.exists()
    assert "auth-level inference" in capsys.readouterr().err


def test_cli_inference_fails_when_any_operation_lacks_auth_and_explicit_security(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    app = _app_with_route(func.AuthLevel.FUNCTION)

    @openapi(route="unresolved", method="GET", summary="unresolved")
    def unresolved() -> None:
        pass

    output = tmp_path / "openapi.json"
    argv = [
        "azure-functions-openapi",
        "generate",
        "--app",
        "function_app:app",
        "--infer-auth-level",
        "--output",
        str(output),
    ]

    # When
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch(
            "azure_functions_openapi.cli._import_app_module",
            return_value=(app, True),
        ),
    ):
        result = main()

    # Then
    assert result != 0
    assert not output.exists()
    assert "unresolved" in capsys.readouterr().err
