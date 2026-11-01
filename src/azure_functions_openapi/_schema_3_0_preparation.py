"""Remove unsupported predicates before conversion can relocate or revisit them."""

from __future__ import annotations

from typing import Any, Final

_DROPPED_KEYWORDS: Final = {
    "propertyNames": "key names are no longer restricted",
    "if": "the conditional constraint is no longer enforced",
    "then": "the conditional constraint is no longer enforced",
    "else": "the conditional constraint is no longer enforced",
    "contains": "matching array elements are no longer required",
    "minContains": "the minimum matching element count is no longer enforced",
    "maxContains": "the maximum matching element count is no longer enforced",
    "unevaluatedProperties": "unevaluated object properties are no longer restricted",
    "unevaluatedItems": "unevaluated array elements are no longer restricted",
    "dependentRequired": "dependent properties are no longer required",
    "dependentSchemas": "dependent object constraints are no longer enforced",
}
_SCHEMA_VALUED_DROPS: Final = frozenset(
    {"propertyNames", "if", "then", "else", "contains", "unevaluatedProperties", "unevaluatedItems"}
)
_MAP_KEYS: Final = frozenset({"properties", "patternProperties", "$defs"})
_SCHEMA_KEYS: Final = frozenset({"items", "additionalItems", "additionalProperties", "not"})
_LIST_KEYS: Final = frozenset({"items", "prefixItems", "allOf", "anyOf", "oneOf"})


def _escape(name: str) -> str:
    return name.replace("~", "~0").replace("/", "~1")


def _prepare_schema_for_3_0(
    schema: dict[str, Any], lossy: list[str] | None, location: str = ""
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in schema.items():
        path = f"{location}/{_escape(key)}"
        if key in _DROPPED_KEYWORDS:
            if lossy is not None:
                lossy.append(
                    f"dropped '{key}' at {path}: OpenAPI 3.0 does not define it; "
                    f"{_DROPPED_KEYWORDS[key]}"
                )
                # What the dropped keyword held is dropped with it, so report its own occurrences.
                if key in _SCHEMA_VALUED_DROPS and isinstance(value, dict):
                    _prepare_schema_for_3_0(value, lossy, path)
                elif key == "dependentSchemas" and isinstance(value, dict):
                    for name, child in value.items():
                        if isinstance(child, dict):
                            _prepare_schema_for_3_0(child, lossy, f"{path}/{_escape(name)}")
            continue
        if key in _MAP_KEYS and isinstance(value, dict):
            result[key] = {
                name: _prepare_schema_for_3_0(child, lossy, f"{path}/{_escape(name)}")
                if isinstance(child, dict)
                else child
                for name, child in value.items()
            }
        elif key in _SCHEMA_KEYS and isinstance(value, dict):
            result[key] = _prepare_schema_for_3_0(value, lossy, path)
        elif key in _LIST_KEYS and isinstance(value, list):
            result[key] = [
                _prepare_schema_for_3_0(child, lossy, f"{path}/{index}")
                if isinstance(child, dict)
                else child
                for index, child in enumerate(value)
            ]
        else:
            result[key] = value
    if isinstance(result.get("items"), list):
        result["prefixItems"] = result.pop("items")
        if "additionalItems" in result:
            result["items"] = result.pop("additionalItems")
    return result
