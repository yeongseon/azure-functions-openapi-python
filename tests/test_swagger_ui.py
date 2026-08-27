from azure_functions_openapi.swagger_ui import render_swagger_ui


def test_render_swagger_ui_returns_html_response() -> None:
    """Verify that the Swagger UI HTML response is correctly rendered."""
    # When
    response = render_swagger_ui()

    # Then
    assert response is not None
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert b'<div id="swagger-ui"></div>' in response.get_body()
    assert b"SwaggerUIBundle" in response.get_body()
    assert b"/api/openapi.json" in response.get_body()


def test_render_swagger_ui_pins_swagger_ui_dist_version() -> None:
    # Given
    response = render_swagger_ui()
    body = response.get_body()

    # Then
    # Assert literal pinned URLs so a stray bump of the module-level constant
    # is caught here instead of silently propagating to every Function App.
    assert b"https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.4/swagger-ui.css" in body
    assert b"https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.4/swagger-ui-bundle.js" in body
    assert b"https://cdn.jsdelivr.net/npm/swagger-ui-dist/swagger-ui" not in body


def test_render_swagger_ui_sets_subresource_integrity() -> None:
    """CDN <script>/<link> tags carry SRI + crossorigin so a compromised or
    repointed CDN asset cannot execute in the browser."""
    # Given
    from azure_functions_openapi.swagger_ui import (
        _SWAGGER_UI_BUNDLE_SRI,
        _SWAGGER_UI_CSS_SRI,
    )

    response = render_swagger_ui()
    body = response.get_body().decode()

    # Then
    # Both pinned assets are hardened with a sha384 SRI hash and CORS.
    assert _SWAGGER_UI_CSS_SRI.startswith("sha384-")
    assert _SWAGGER_UI_BUNDLE_SRI.startswith("sha384-")
    assert f'integrity="{_SWAGGER_UI_CSS_SRI}"' in body
    assert f'integrity="{_SWAGGER_UI_BUNDLE_SRI}"' in body
    # crossorigin is mandatory for SRI validation to run against a CDN.
    assert body.count('crossorigin="anonymous"') >= 2
