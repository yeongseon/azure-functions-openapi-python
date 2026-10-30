import json
from pathlib import Path
import warnings

import pytest

from azure_functions_openapi import resolve_route_prefix

SETTING = "AzureFunctionsJobHost__extensions__http__routePrefix"


@pytest.fixture(autouse=True)
def clear_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SETTING, raising=False)


@pytest.mark.parametrize("prefix", ["gateway", ""])
def test_environment_beats_host_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    # Given
    path = tmp_path / "host.json"
    path.write_text('{"extensions":{"http":{"routePrefix":"v1"}}}', encoding="utf-8")
    monkeypatch.setenv(SETTING, prefix)
    # When
    result = resolve_route_prefix(path)
    # Then
    assert result == ("/gateway" if prefix else "")


@pytest.mark.parametrize("case", [("", ""), ("api", "/api"), ("/v1/", "/v1"), ("v1", "/v1")])
def test_host_json_prefix_is_normalized(tmp_path: Path, case: tuple[str, str]) -> None:
    # Given
    prefix, expected = case
    path = tmp_path / "host.json"
    path.write_text(json.dumps({"extensions": {"http": {"routePrefix": prefix}}}), encoding="utf-8")
    # When
    result = resolve_route_prefix(str(path))
    # Then
    assert result == expected


def test_utf8_byte_order_mark_is_ignored(tmp_path: Path) -> None:
    # Given
    path = tmp_path / "host.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"extensions":{"http":{"routePrefix":"v1"}}}')
    # When
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = resolve_route_prefix(path)
    # Then
    assert result == "/v1"
    assert captured == []


@pytest.mark.parametrize("content", [None, "{}", '{"extensions":{"http":{}}}', "[]"])
def test_absent_configuration_silently_uses_default(tmp_path: Path, content: str | None) -> None:
    # Given
    path = tmp_path / "host.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    # When
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = resolve_route_prefix(path)
    # Then
    assert result == "/api"
    assert captured == []


@pytest.mark.parametrize(
    "case",
    [
        ("{", "Could not read route prefix"),
        ('{"extensions":{"http":{"routePrefix":null}}}', "must be a string"),
        ('{"extensions":{"http":{"routePrefix":42}}}', "must be a string"),
        ('{"extensions":{"http":{"routePrefix":false}}}', "must be a string"),
    ],
)
def test_invalid_configuration_warns_and_falls_back(tmp_path: Path, case: tuple[str, str]) -> None:
    # Given
    content, reason = case
    path = tmp_path / "host.json"
    path.write_text(content, encoding="utf-8")
    # When
    with pytest.warns(RuntimeWarning, match=reason) as captured:
        result = resolve_route_prefix(path)
    # Then
    assert result == "/api"
    assert str(path) in str(captured[0].message)
    assert captured[0].filename == __file__


def test_unreadable_directory_warns_and_falls_back(tmp_path: Path) -> None:
    # Given
    path = tmp_path
    # When
    with pytest.warns(RuntimeWarning, match="Could not read route prefix") as captured:
        result = resolve_route_prefix(path)
    # Then
    assert result == "/api"
    assert str(path) in str(captured[0].message)


def test_invalid_encoding_warns_and_falls_back(tmp_path: Path) -> None:
    # Given
    path = tmp_path / "host.json"
    path.write_bytes(b"\xff")
    # When
    with pytest.warns(RuntimeWarning, match="Could not read route prefix"):
        result = resolve_route_prefix(path)
    # Then
    assert result == "/api"


def test_default_location_is_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    monkeypatch.chdir(tmp_path)
    (tmp_path / "host.json").write_text(
        '{"extensions":{"http":{"routePrefix":"local"}}}', encoding="utf-8"
    )
    # When
    result = resolve_route_prefix()
    # Then
    assert result == "/local"
