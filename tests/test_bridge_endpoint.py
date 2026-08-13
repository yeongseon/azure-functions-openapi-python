from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel
import pytest

from azure_functions_openapi._warnings import WarningCode
from azure_functions_openapi.bridge import (
    _HANDLER_METADATA_ATTR,
    _discovered_operation_from_endpoint,
    _models_conflict,
    _read_endpoint_hints,
    scan_endpoint_metadata,
)
from azure_functions_openapi.decorator import (
    clear_openapi_registry,
    get_openapi_registry,
    register_openapi_metadata,
)
from azure_functions_openapi.exceptions import OpenAPISpecConfigError
from azure_functions_openapi.spec import collect_spec_warnings, generate_openapi_spec

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_openapi_registry()
    yield
    clear_openapi_registry()


# A representative flat endpoint payload (all JSON Schema, no model classes).
FLAT_ENDPOINT: dict[str, Any] = {
    "version": 1,
    "request_body": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    "request_body_required": True,
    "parameters": [
        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
    ],
    "responses": {
        "200": {"schema": {"type": "object", "properties": {"id": {"type": "integer"}}}},
    },
}


class MockBinding:
    def __init__(self, route: str, methods: list[str] | None, type: str = "httpTrigger") -> None:
        self.route = route
        self.methods = methods
        self.type = type


class MockFunction:
    def __init__(self, name: str, func: Any, bindings: list[Any]) -> None:
        self._name = name
        self._func = func
        self._bindings = bindings

    def get_function_name(self) -> str:
        return self._name

    def get_user_function(self) -> Any:
        return self._func

    def get_bindings(self) -> list[Any]:
        return self._bindings

    def is_http_function(self) -> bool:
        return any(str(getattr(b, "type", "")).lower() == "httptrigger" for b in self._bindings)


class MockBuilder:
    def __init__(self, function: MockFunction) -> None:
        self._function = function

    def build(self, auth_level: Any = None) -> MockFunction:
        return self._function


class MockApp:
    def __init__(self, builders: list[MockBuilder]) -> None:
        self._function_builders = builders


def _make_handler(namespaces: dict[str, Any]) -> Any:
    def handler(req: Any) -> Any:
        return req

    setattr(handler, _HANDLER_METADATA_ATTR, namespaces)
    return handler


def _make_app(
    namespaces: dict[str, Any],
    *,
    name: str = "create_user",
    route: str = "users",
    methods: list[str] | None = None,
) -> MockApp:
    handler = _make_handler(namespaces)
    binding = MockBinding(route=route, methods=methods or ["POST"])
    fn = MockFunction(name=name, func=handler, bindings=[binding])
    return MockApp([MockBuilder(fn)])


# ---------------------------------------------------------------------------
# _read_endpoint_hints
# ---------------------------------------------------------------------------


def test_read_endpoint_hints_accepts_version_1() -> None:
    handler = _make_handler({"endpoint": FLAT_ENDPOINT})
    result = _read_endpoint_hints(handler)
    assert result is not None
    assert result["request_body"]["properties"]["name"]["type"] == "string"


def test_read_endpoint_hints_missing_version_rejected() -> None:
    # ``version`` is a required key for the endpoint contract (unlike validation).
    handler = _make_handler({"endpoint": {"request_body": {"type": "object"}}})
    assert _read_endpoint_hints(handler) is None


def test_read_endpoint_hints_unsupported_version_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler = _make_handler({"endpoint": {"version": 999}})
    with caplog.at_level("WARNING", logger="azure_functions_openapi.bridge"):
        assert _read_endpoint_hints(handler) is None
    assert any("unsupported version" in m for m in caplog.messages)


def test_read_endpoint_hints_boolean_version_rejected() -> None:
    handler = _make_handler({"endpoint": {"version": True}})
    assert _read_endpoint_hints(handler) is None


def test_read_endpoint_hints_walks_wrapped_chain() -> None:
    inner: Any = lambda req: req  # noqa: E731
    setattr(inner, _HANDLER_METADATA_ATTR, {"endpoint": FLAT_ENDPOINT})
    outer: Any = lambda req: inner(req)  # noqa: E731
    outer.__wrapped__ = inner

    result = _read_endpoint_hints(outer)
    assert result is not None
    assert result["version"] == 1


def test_read_endpoint_hints_invalid_outer_valid_inner() -> None:
    inner: Any = lambda req: req  # noqa: E731
    setattr(inner, _HANDLER_METADATA_ATTR, {"endpoint": FLAT_ENDPOINT})
    outer: Any = lambda req: inner(req)  # noqa: E731
    setattr(outer, _HANDLER_METADATA_ATTR, {"endpoint": {"version": 999}})
    outer.__wrapped__ = inner

    result = _read_endpoint_hints(outer)
    assert result is not None
    assert result["version"] == 1


def test_read_endpoint_hints_self_referencing_stops() -> None:
    handler: Any = lambda req: req  # noqa: E731
    setattr(handler, _HANDLER_METADATA_ATTR, {"endpoint": {"version": 999}})
    handler.__wrapped__ = handler
    assert _read_endpoint_hints(handler) is None


def test_read_endpoint_hints_returns_deep_copy() -> None:
    handler = _make_handler({"endpoint": FLAT_ENDPOINT})
    result = _read_endpoint_hints(handler)
    assert result is not None
    result["request_body"]["properties"]["name"]["type"] = "mutated"

    stored = getattr(handler, _HANDLER_METADATA_ATTR)["endpoint"]
    assert stored["request_body"]["properties"]["name"]["type"] == "string"


def test_read_endpoint_hints_absent_namespace() -> None:
    handler = _make_handler({"validation": {"body": None}})
    assert _read_endpoint_hints(handler) is None


# ---------------------------------------------------------------------------
# _discovered_operation_from_endpoint
# ---------------------------------------------------------------------------


def test_discovered_operation_from_endpoint_shape() -> None:
    discovered = _discovered_operation_from_endpoint(
        "create_user", FLAT_ENDPOINT, "/api/users", "post"
    )
    assert discovered["request_body"]["type"] == "object"
    assert discovered["request_body_required"] is True
    assert discovered["parameters"][0]["name"] == "limit"
    assert discovered["response"][200]["content"]["application/json"]["schema"] == {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
    }
    assert discovered["response"][200]["description"] == ""


def test_discovered_operation_from_endpoint_defaults_and_filters() -> None:
    payload: dict[str, Any] = {
        "version": 1,
        "request_body": "not-a-dict",
        "parameters": ["bad", {"name": "ok", "in": "query"}],
        "responses": {
            "not-an-int": {"schema": {"type": "string"}},
            "201": "not-a-dict",
            "204": {"schema": {"type": "null"}},
        },
    }
    discovered = _discovered_operation_from_endpoint("fn", payload, "/api/x", "post")
    assert discovered["request_body"] is None
    assert discovered["request_body_required"] is True  # defaulted
    assert discovered["parameters"] == [{"name": "ok", "in": "query"}]
    assert set(discovered["response"].keys()) == {204}


def test_discovered_operation_from_endpoint_non_dict_responses() -> None:
    payload: dict[str, Any] = {"version": 1, "responses": "nope"}
    discovered = _discovered_operation_from_endpoint("fn", payload, "/api/x", "get")
    assert discovered["response"] == {}


def test_discovered_operation_rejects_boolean_status_keys() -> None:
    # ``bool`` is an ``int`` subclass; ``True``/``False`` must not coerce to 1/0.
    payload: dict[str, Any] = {
        "version": 1,
        "responses": {
            True: {"schema": {"type": "string"}},
            False: {"schema": {"type": "null"}},
            "200": {"schema": {"type": "object"}},
        },
    }
    discovered = _discovered_operation_from_endpoint("fn", payload, "/api/x", "post")
    assert set(discovered["response"].keys()) == {200}


def test_discovered_operation_request_body_required_rejects_non_bool() -> None:
    # Non-boolean truthy values (e.g. the string "false") must not be honored;
    # only real booleans are accepted, otherwise default to True.
    payload: dict[str, Any] = {"version": 1, "request_body_required": "false"}
    discovered = _discovered_operation_from_endpoint("fn", payload, "/api/x", "post")
    assert discovered["request_body_required"] is True


# ---------------------------------------------------------------------------
# scan_endpoint_metadata — endpoint namespace happy path
# ---------------------------------------------------------------------------


def test_scan_registers_from_endpoint_namespace() -> None:
    app = _make_app({"endpoint": FLAT_ENDPOINT})
    scan_endpoint_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["request_body"]["properties"]["name"]["type"] == "string"
    assert entry["request_body_required"] is True
    assert entry["response"][200]["content"]["application/json"]["schema"]["properties"] == {
        "id": {"type": "integer"}
    }
    assert entry["parameters"][0]["name"] == "limit"


def test_scan_endpoint_request_body_not_required() -> None:
    payload = dict(FLAT_ENDPOINT)
    payload["request_body_required"] = False
    app = _make_app({"endpoint": payload})
    scan_endpoint_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["request_body_required"] is False


def test_scan_empty_app_records_empty_discovery() -> None:
    # Regression (#373/#380): an app exposing no discoverable functions must
    # record a structured EMPTY_DISCOVERY warning (not just a debug log) so
    # ``--fail-on-warnings`` can catch a silently-empty scan -- and it must NOT
    # be mislabelled as a builder-build failure, nor predict empty final paths.
    from azure_functions_openapi.registry import registry

    app = MockApp([])
    scan_endpoint_metadata(app)

    assert registry.empty_discoveries == ["MockApp"]
    # No builder-failure record was created for the empty app.
    assert registry.discovery_warnings == []

    warnings = collect_spec_warnings(generate_openapi_spec("t", "1"))
    empty = [w for w in warnings if w.code == WarningCode.EMPTY_DISCOVERY]
    assert len(empty) == 1
    assert "MockApp" in empty[0].message
    # The false builder-failure and empty-paths clauses must be gone.
    assert "could not be built" not in empty[0].message
    assert "empty paths" not in empty[0].message


class _UnbuildableBuilder:
    """A builder whose build() always raises, so the adapter skips it."""

    def __init__(self, name: str) -> None:
        self._function = MockFunction(name=name, func=lambda req: req, bindings=[])

    def build(self, auth_level: Any = None) -> Any:
        name = self._function.get_function_name()
        raise ValueError(f"Function {name} does not have a trigger")


def test_scan_all_builders_fail_records_skip_not_empty_discovery() -> None:
    # Regression (#380 review): iter_functions returns [] both when no builders
    # exist AND when every builder fails to build. The latter is NOT an empty
    # discovery -- builders were present and each fired a DISCOVERY_SKIPPED
    # warning, so recording EMPTY_DISCOVERY too would be semantically wrong and
    # would double-trip --fail-on-warnings.
    from azure_functions_openapi.registry import registry

    app = MockApp([cast(MockBuilder, _UnbuildableBuilder("orphan"))])
    scan_endpoint_metadata(app)

    # The build failure was recorded, but no empty-discovery signal was emitted.
    assert registry.empty_discoveries == []
    assert len(registry.discovery_warnings) == 1

    warnings = collect_spec_warnings(generate_openapi_spec("t", "1"))
    assert not [w for w in warnings if w.code == WarningCode.EMPTY_DISCOVERY]
    assert [w for w in warnings if w.code == WarningCode.DISCOVERY_SKIPPED]


# ---------------------------------------------------------------------------
# Version-skew: endpoint preferred, validation fallback
# ---------------------------------------------------------------------------


class _Body(BaseModel):
    name: str


class _Resp(BaseModel):
    id: int


def test_scan_registers_from_endpoint_and_ignores_validation_sibling() -> None:
    app = _make_app({"endpoint": FLAT_ENDPOINT})
    scan_endpoint_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    # Endpoint path does NOT set response_model (it uses the raw ``response`` slot).
    assert entry["response_model"] is None
    assert entry["response"][200]["content"]["application/json"]["schema"]["properties"] == {
        "id": {"type": "integer"}
    }


def test_scan_ignores_validation_only_namespace() -> None:
    # Post-#313: the bridge reads ONLY the endpoint namespace. A handler that
    # carries just the legacy validation namespace registers nothing.
    app = _make_app({"validation": {"body": _Body, "response_model": _Resp}})
    scan_endpoint_metadata(app)

    assert get_openapi_registry() == {}


def test_scan_registers_bare_skew_op_when_endpoint_version_unsupported() -> None:
    # A present-but-rejected endpoint namespace (unsupported version) with no
    # canonical @openapi entry registers a BARE binding-derived operation and
    # flags it VERSION_SKEW. The sibling validation namespace is NOT read.
    app = _make_app(
        {
            "endpoint": {"version": 999, "request_body": {"type": "object"}},
            "validation": {"body": _Body, "response_model": _Resp},
        }
    )
    scan_endpoint_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    # validation namespace ignored: the bare op carries no derived body/response.
    assert entry.get("response_model") is None
    assert entry.get("request_body") is None
    assert entry.get("response") == {}
    assert entry.get("_skew_flags") == ["version-skew"]

    # The degraded op is flagged VERSION_SKEW (no NAMESPACE_FALLBACK anymore).
    warnings = collect_spec_warnings(generate_openapi_spec())
    skew = [w for w in warnings if w.code is WarningCode.VERSION_SKEW]
    assert skew
    assert any(w.function_name == "post::/api/users" for w in skew)


# ---------------------------------------------------------------------------
# Merge into existing @openapi entry
# ---------------------------------------------------------------------------


def test_scan_endpoint_merges_into_existing_openapi_entry() -> None:
    register_openapi_metadata(path="/api/users", method="post", summary="explicit")
    app = _make_app({"endpoint": FLAT_ENDPOINT})
    scan_endpoint_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    assert entry["summary"] == "explicit"  # explicit metadata preserved
    assert entry["request_body"]["properties"]["name"]["type"] == "string"
    assert entry["request_body_required"] is True
    assert 200 in entry["response"]


def test_scan_endpoint_conflicting_response_raises() -> None:
    register_openapi_metadata(
        path="/api/users",
        method="post",
        response={200: {"content": {"application/json": {"schema": {"type": "string"}}}}},
    )
    app = _make_app({"endpoint": FLAT_ENDPOINT})
    with pytest.raises(OpenAPISpecConfigError):
        scan_endpoint_metadata(app)


# ---------------------------------------------------------------------------
# _models_conflict — response dict
# ---------------------------------------------------------------------------


def test_models_conflict_response_dict_same_status_differs() -> None:
    assert (
        _models_conflict(
            {"response": {200: {"a": 1}}},
            {"response": {200: {"a": 2}}},
        )
        is True
    )


def test_models_conflict_response_dict_disjoint_status_ok() -> None:
    assert (
        _models_conflict(
            {"response": {200: {"a": 1}}},
            {"response": {404: {"a": 1}}},
        )
        is False
    )


# ---------------------------------------------------------------------------
# Nested-model $defs hoisting into components.schemas (issue #315)
# ---------------------------------------------------------------------------


def test_scan_endpoint_keeps_nested_defs_verbatim_in_registry() -> None:
    """The bridge still stores producer schemas verbatim in the registry;
    hoisting is a spec-generation concern handled by ``generate_openapi_spec``.
    """
    nested_payload: dict[str, Any] = {
        "version": 1,
        "request_body": {
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/Child"}},
            "$defs": {"Child": {"type": "object", "properties": {"x": {"type": "integer"}}}},
        },
        "request_body_required": True,
    }
    app = _make_app({"endpoint": nested_payload})
    scan_endpoint_metadata(app)

    entry = get_openapi_registry()["post::/api/users"]
    # Bridge contract: producer $defs are preserved inline in the registry.
    assert entry["request_body"]["$defs"]["Child"]["properties"]["x"]["type"] == "integer"
    assert entry["request_body"]["properties"]["child"]["$ref"] == "#/$defs/Child"


def test_generate_spec_hoists_request_body_defs() -> None:
    """Inline ``$defs`` in an endpoint request body are hoisted into
    ``components.schemas`` and the ``#/$defs/`` ref is rewritten (issue #315)."""
    nested_payload: dict[str, Any] = {
        "version": 1,
        "request_body": {
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/Child"}},
            "$defs": {"Child": {"type": "object", "properties": {"x": {"type": "integer"}}}},
        },
        "request_body_required": True,
    }
    app = _make_app({"endpoint": nested_payload})
    scan_endpoint_metadata(app)

    spec = generate_openapi_spec()
    schema = spec["paths"]["/api/users"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    # Root stays inline, but its ref now points at components.schemas.
    assert schema["properties"]["child"]["$ref"] == "#/components/schemas/Child"
    assert "$defs" not in schema
    # Child is hoisted into the shared components.schemas section.
    assert spec["components"]["schemas"]["Child"]["properties"]["x"]["type"] == "integer"


def test_generate_spec_hoists_response_and_parameter_defs() -> None:
    """``$defs`` in response and parameter schemas are also hoisted (issue #315)."""
    payload: dict[str, Any] = {
        "version": 1,
        "parameters": [
            {
                "name": "body",
                "in": "query",
                "required": False,
                "schema": {
                    "properties": {"p": {"$ref": "#/$defs/ParamModel"}},
                    "$defs": {"ParamModel": {"type": "object"}},
                },
            }
        ],
        "responses": {
            "200": {
                "schema": {
                    "properties": {"r": {"$ref": "#/$defs/RespModel"}},
                    "$defs": {"RespModel": {"type": "object"}},
                }
            }
        },
    }
    app = _make_app({"endpoint": payload})
    scan_endpoint_metadata(app)

    spec = generate_openapi_spec()
    op = spec["paths"]["/api/users"]["post"]
    param_schema = op["parameters"][0]["schema"]
    resp_schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert param_schema["properties"]["p"]["$ref"] == "#/components/schemas/ParamModel"
    assert resp_schema["properties"]["r"]["$ref"] == "#/components/schemas/RespModel"
    assert "ParamModel" in spec["components"]["schemas"]
    assert "RespModel" in spec["components"]["schemas"]


def test_generate_spec_hoists_nested_of_nested_defs() -> None:
    """Recursively nested ``$defs`` (a def that references another def) are all
    hoisted flat into ``components.schemas``."""
    payload: dict[str, Any] = {
        "version": 1,
        "request_body": {
            "type": "object",
            "properties": {"parent": {"$ref": "#/$defs/Parent"}},
            "$defs": {
                "Parent": {
                    "type": "object",
                    "properties": {"kid": {"$ref": "#/$defs/Kid"}},
                    "$defs": {"Kid": {"type": "object", "properties": {"y": {"type": "integer"}}}},
                }
            },
        },
        "request_body_required": True,
    }
    app = _make_app({"endpoint": payload})
    scan_endpoint_metadata(app)

    spec = generate_openapi_spec()
    schemas = spec["components"]["schemas"]
    assert "Parent" in schemas
    assert "Kid" in schemas
    assert schemas["Parent"]["properties"]["kid"]["$ref"] == "#/components/schemas/Kid"
    assert "$defs" not in schemas["Parent"]


def test_generate_spec_hoists_defs_referenced_inside_allof_items() -> None:
    """A local ``#/$defs/`` ref buried inside ``allOf[].items`` is detected by the
    recursive ``_needs_hoisting`` walk (through nested dict/list levels) and the
    definition is hoisted rather than embedded verbatim (issue #315)."""
    payload: dict[str, Any] = {
        "version": 1,
        "request_body": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"allOf": [{"items": {"$ref": "#/$defs/Buried"}}]},
                }
            },
            "$defs": {"Buried": {"type": "object", "properties": {"z": {"type": "string"}}}},
        },
        "request_body_required": True,
    }
    app = _make_app({"endpoint": payload})
    scan_endpoint_metadata(app)

    spec = generate_openapi_spec()
    schema = spec["paths"]["/api/users"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    buried_ref = schema["properties"]["items"]["items"]["allOf"][0]["items"]["$ref"]
    assert buried_ref == "#/components/schemas/Buried"
    assert "$defs" not in schema
    assert spec["components"]["schemas"]["Buried"]["properties"]["z"]["type"] == "string"


def test_generate_spec_flat_schema_embedded_verbatim() -> None:
    """Flat schemas (no ``$defs``) are embedded verbatim with no components entry
    created for them (no regression to #311)."""
    app = _make_app({"endpoint": FLAT_ENDPOINT})
    scan_endpoint_metadata(app)

    spec = generate_openapi_spec()
    schema = spec["paths"]["/api/users"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    assert schema["properties"]["name"]["type"] == "string"
    assert "$defs" not in schema
    assert "components" not in spec or "schemas" not in spec.get("components", {})


def test_generate_spec_resolves_conflicting_defs_across_operations() -> None:
    """Two operations that each define a differently-shaped ``Child`` get a
    collision-resolved second component name."""
    payload_a: dict[str, Any] = {
        "version": 1,
        "request_body": {
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/Child"}},
            "$defs": {"Child": {"type": "object", "properties": {"x": {"type": "integer"}}}},
        },
        "request_body_required": True,
    }
    payload_b: dict[str, Any] = {
        "version": 1,
        "request_body": {
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/Child"}},
            "$defs": {"Child": {"type": "object", "properties": {"z": {"type": "string"}}}},
        },
        "request_body_required": True,
    }
    handler_a = _make_handler({"endpoint": payload_a})
    handler_b = _make_handler({"endpoint": payload_b})
    app = MockApp(
        [
            MockBuilder(MockFunction("create_a", handler_a, [MockBinding("a", ["POST"])])),
            MockBuilder(MockFunction("create_b", handler_b, [MockBinding("b", ["POST"])])),
        ]
    )
    scan_endpoint_metadata(app)

    spec = generate_openapi_spec()
    schemas = spec["components"]["schemas"]
    # Both distinct shapes are present under collision-resolved names.
    assert "Child" in schemas
    assert "Child_2" in schemas
    shapes = {"Child": schemas["Child"], "Child_2": schemas["Child_2"]}
    property_keys = {name: set(s["properties"]) for name, s in shapes.items()}
    assert {"x"} in property_keys.values()
    assert {"z"} in property_keys.values()


# ---------------------------------------------------------------------------
# Deprecated alias: scan_validation_metadata (#319)
# ---------------------------------------------------------------------------


def test_scan_validation_metadata_alias_emits_deprecation_warning() -> None:
    from azure_functions_openapi.bridge import scan_validation_metadata

    app = _make_app({"endpoint": FLAT_ENDPOINT})
    with pytest.warns(DeprecationWarning, match="scan_endpoint_metadata"):
        scan_validation_metadata(app)

    # Behavior is identical to the canonical function.
    assert "post::/api/users" in get_openapi_registry()


def test_scan_validation_metadata_alias_matches_canonical_output() -> None:
    from azure_functions_openapi.bridge import scan_validation_metadata

    app_alias = _make_app({"endpoint": FLAT_ENDPOINT})
    with pytest.warns(DeprecationWarning):
        scan_validation_metadata(app_alias)
    via_alias = generate_openapi_spec()

    clear_openapi_registry()

    app_canonical = _make_app({"endpoint": FLAT_ENDPOINT})
    scan_endpoint_metadata(app_canonical)
    via_canonical = generate_openapi_spec()

    assert via_alias == via_canonical


# ---------------------------------------------------------------------------
# Additive non-success response metadata (issue #328)
# ---------------------------------------------------------------------------


def test_endpoint_v1_additive_422_response_is_preserved_in_spec() -> None:
    """A non-success ``"422"`` response in an endpoint v1 payload survives the
    scan/consumer path into the generated OpenAPI spec.

    ``422`` is the first real *additive* ``version: 1`` case (validation #283):
    adding a non-success response is an additive change that keeps ``version``
    at ``1``. This test pins that contract with a payload authored **inline**,
    so coverage does not depend on which ``azure-functions-validation`` release
    happens to be installed on a given CI cell.
    """
    payload: dict[str, Any] = {
        "version": 1,
        "request_body": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        "request_body_required": True,
        "responses": {
            "200": {"schema": {"type": "object", "properties": {"id": {"type": "integer"}}}},
            "422": {
                "description": "Validation error",
                "schema": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
            },
        },
    }
    app = _make_app({"endpoint": payload})
    scan_endpoint_metadata(app)

    spec = generate_openapi_spec()
    responses = spec["paths"]["/api/users"]["post"]["responses"]
    # The additive non-success status is present alongside the success status.
    assert "200" in responses
    assert "422" in responses
    # The 422 response schema is carried through, not dropped or flattened away.
    schema = responses["422"]["content"]["application/json"]["schema"]
    assert schema["properties"]["detail"]["type"] == "string"
