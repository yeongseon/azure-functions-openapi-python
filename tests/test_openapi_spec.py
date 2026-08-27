# tests/test_openapi_spec.py
import json

from azure_functions_openapi.decorator import openapi
from azure_functions_openapi.spec import get_openapi_json


def _register_http_trigger() -> None:
    @openapi(
        route="/api/http_trigger",
        summary="HTTP Trigger with name parameter",
        description=(
            "Returns a greeting using the **name** from query or body.\n\n"
            "### Usage\n\n"
            "`?name=Azure`\n\n"
            "```json\n"
            '{"name": "Azure"}\n'
            "```"
        ),
        tags=["Example"],
        operation_id="greetUser",
        responses={200: {"description": "OK"}},
    )
    def http_trigger() -> None:
        pass


def test_openapi_spec_http_trigger_metadata() -> None:
    """Verify that the generated spec for /api/http_trigger contains the expected metadata."""
    _register_http_trigger()
    spec = json.loads(get_openapi_json())

    # Ensure the path exists
    assert "/api/http_trigger" in spec["paths"]

    http_get = spec["paths"]["/api/http_trigger"]["get"]

    # Basic metadata
    # #347: bare @openapi (no route binding, no method=) emits a single GET
    # operation, so the explicit operation_id is used verbatim (no method suffix).
    assert http_get["operationId"] == "greetUser"
    # Only the single GET operation is emitted (no all-method expansion).
    assert set(spec["paths"]["/api/http_trigger"]) == {"get"}
    assert http_get["tags"] == ["Example"]
    assert http_get["summary"] == "HTTP Trigger with name parameter"

    # Markdown description checks
    description = http_get["description"]
    assert "Returns a greeting using the **name**" in description
    assert "### Usage" in description
    assert "```json" in description

    # Response schema
    assert "responses" in http_get
    assert "200" in http_get["responses"]
