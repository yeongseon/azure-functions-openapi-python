"""Schema-only OpenAPI version conversion and residual compatibility checks.

Inputs are schema dictionaries (including inline operation schema positions), the
original complete component map, recursion guards, and optional loss accumulators.
Registry publication, discovery, logging, and CLI warning policy belong to callers.

The conversion family is intentionally kept intact for #819: traversal order and
both nullable-collapse phases preserve output and loss-message encounter order.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

from azure_functions_openapi.exceptions import OpenAPISpecConfigError

# Media Type Object keys shared with document assembly (3.2 adds itemSchema).
_MEDIA_SCHEMA_KEYS = ("schema", "itemSchema")


def _convert_nullable_to_type_array(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert OpenAPI 3.0 nullable to 3.1 type array syntax."""
    result = schema.copy()

    if result.get("nullable") is True and "type" in result:
        original_type = result["type"]
        if isinstance(original_type, str):
            result["type"] = [original_type, "null"]
        elif isinstance(original_type, list) and "null" not in original_type:
            result["type"] = original_type + ["null"]
        del result["nullable"]

    return result


def _convert_schema_to_3_1(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively convert a schema from OpenAPI 3.0 to 3.1 format."""
    if not isinstance(schema, dict):
        return schema

    result = _convert_nullable_to_type_array(schema)

    if "example" in result and "examples" not in result:
        result["examples"] = [result.pop("example")]

    if "properties" in result:
        result["properties"] = {
            k: _convert_schema_to_3_1(v) for k, v in result["properties"].items()
        }

    if "items" in result:
        result["items"] = _convert_schema_to_3_1(result["items"])

    if "allOf" in result:
        result["allOf"] = [_convert_schema_to_3_1(s) for s in result["allOf"]]

    if "anyOf" in result:
        result["anyOf"] = [_convert_schema_to_3_1(s) for s in result["anyOf"]]

    if "oneOf" in result:
        result["oneOf"] = [_convert_schema_to_3_1(s) for s in result["oneOf"]]

    if "additionalProperties" in result and isinstance(result["additionalProperties"], dict):
        result["additionalProperties"] = _convert_schema_to_3_1(result["additionalProperties"])

    return result


def _convert_schemas_to_3_1(schemas: dict[str, Any]) -> dict[str, Any]:
    """Convert all schemas in components to OpenAPI 3.1 format."""
    return {name: _convert_schema_to_3_1(schema) for name, schema in schemas.items()}


# Keywords whose presence on BOTH an ``anyOf`` wrapper node and its sole non-null
# member makes an up-merge ambiguous: they constrain validation, so a conflict
# must not be silently resolved. Annotation-only keys (description/title/...) are
# safe to overlay and are intentionally excluded.
_STRUCTURAL_MERGE_KEYS: frozenset[str] = frozenset(
    {
        "type",
        "format",
        "items",
        "properties",
        "enum",
        "required",
        "additionalProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "pattern",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "multipleOf",
    }
)


def _ensure_null_accepting(schema: dict[str, Any]) -> dict[str, Any]:
    """Return *schema* modified so it genuinely validates a ``null`` instance.

    ``nullable: true`` only exempts the ``type`` keyword's own check (OAS
    3.0.3); it is never consulted by a SIBLING ``enum``/``const``, nor by a
    nested ``anyOf``/``oneOf`` the schema already carries on its own account
    (e.g. a ``RootModel[str | int]``'s compiled union, as opposed to the
    OUTER nullable-collapsing union this module rewrites). Setting
    ``nullable: true`` alone on such a schema looks like a fix but still
    rejects a valid ``null`` (#782 follow-up): a closed ``enum``/``const``
    must have ``null`` added as an explicit member, and a nested combinator's
    OWN branches must each individually carry ``nullable: true`` instead.

    This deliberately does NOT add a synthetic ``{"type": "null"}`` member to
    a nested combinator: OpenAPI 3.0's restricted ``type`` enum (inherited
    from JSON Schema Draft 4) has no ``"null"`` value at all -- that absence
    is exactly why ``nullable`` exists as a separate OpenAPI keyword in the
    first place, and `openapi_spec_validator` rejects a document containing
    ``{"type": "null"}`` as a schema-meta-schema violation. Instead, each
    EXISTING type-bearing branch gets its own ``nullable: true`` sibling, so
    a null instance matches whichever branch it lands on, the same valid
    idiom this module already uses for a top-level nullable union.
    """
    result = dict(schema)
    if "const" in result:
        result["enum"] = [result.pop("const"), None]
    elif isinstance(result.get("enum"), list) and None not in result["enum"]:
        result["enum"] = [*result["enum"], None]
    for combinator in ("anyOf", "oneOf"):
        members = result.get(combinator)
        if isinstance(members, list):
            result[combinator] = [
                _ensure_null_accepting(m) if isinstance(m, dict) and "$ref" not in m else m
                for m in members
            ]
    result["nullable"] = True
    return result


def _inline_ref_nullable(
    ref: str,
    extra_keys: dict[str, Any],
    schemas: dict[str, Any] | None,
    resolving: frozenset[str],
    lossy: list[str] | None = None,
) -> dict[str, Any] | None:
    """Resolve ``ref`` and return its content, recursively converted, with
    ``nullable`` genuinely accepted (see :func:`_ensure_null_accepting`) --
    or ``None`` when it cannot be resolved against *schemas* or is already
    being expanded higher up this same chain (*resolving*), a direct or
    indirect self-reference that would otherwise inline forever. When
    *lossy* is supplied, a self-/mutually-referential ref that is skipped
    for this reason is reported: the caller's fallback (a bare ``$ref``,
    which cannot carry ``nullable`` at all under OpenAPI 3.0) is a known,
    demonstrable loss at that recursive edge, not a faithful re-expression.
    """
    if not ref.startswith("#/components/schemas/"):
        return None
    name = ref.rsplit("/", 1)[-1]
    if schemas is None:
        return None
    if name in resolving:
        if lossy is not None:
            lossy.append(
                f"a nullable self- or mutually-recursive reference to '{name}' cannot "
                "be inlined without expanding forever; the recursive edge falls back "
                "to a bare $ref, which OpenAPI 3.0 cannot mark nullable, so a null "
                "value at that position is rejected"
            )
        return None
    target = schemas.get(name)
    if not isinstance(target, dict):
        return None
    inlined = _convert_schema_to_3_0(dict(target), schemas, resolving | {name}, lossy)
    inlined = _ensure_null_accepting(inlined)
    for k, v in extra_keys.items():
        inlined.setdefault(k, v)
    return inlined


def _collapse_nullable_combinator(
    schema: dict[str, Any],
    schemas: dict[str, Any] | None = None,
    resolving: frozenset[str] = frozenset(),
    lossy: list[str] | None = None,
) -> dict[str, Any]:
    """Collapse a Pydantic ``anyOf``/``oneOf`` nullable union into OpenAPI 3.0 form.

    OpenAPI 3.0 has no ``{"type": "null"}`` and ``nullable: true`` only takes
    effect when it sits on the *same* schema object as the ``type`` keyword it
    exempts (OAS 3.0.3; this is also how the reference
    ``openapi-schema-validator`` implements it, and how it treats ``anyOf``/
    ``oneOf``: it descends into each branch independently, so a ``nullable``
    sibling of the combinator itself is never consulted and null is rejected
    by every branch). A bare ``$ref`` cannot carry a sibling ``nullable`` at
    all (3.0 ignores every other key next to ``$ref``), and wrapping it in
    ``allOf`` does not help either: resolving the ``$ref`` inside ``allOf``
    validates the instance against the *referenced* schema object, which has
    no ``nullable`` of its own, so a valid ``null`` is still rejected as e.g.
    ``"None is not of type 'object'"``. This rewrites that node to the 3.0
    ``nullable: true`` idiom (#562), making sure ``nullable`` always lands
    somewhere it actually takes effect, and that the schema it lands on
    actually accepts null once it is there (#782, and #782's own follow-up
    review): an inlined ``enum``/``const`` gains an explicit ``null`` member,
    and an inlined schema that itself carries a nested ``anyOf``/``oneOf``
    gains its own ``{"type": "null"}`` branch -- see
    :func:`_ensure_null_accepting`.

    * single ``$ref`` member, resolvable against *schemas* and not already
      being expanded higher up this same chain (*resolving*) -> the
      referenced schema's own content, recursively converted and merged with
      this node's own existing keys (this node's value wins a conflict,
      except a shared numeric bound keeps the tighter of the two so neither
      constraint is silently dropped), plus genuine null-acceptance. Falls
      back to the pre-#782 ``{"allOf": [<ref>], "nullable": true}`` form
      (structurally valid, but does not itself satisfy the null case, and is
      reported via *lossy* when supplied) when the ref cannot be resolved or
      would recurse into itself.
    * single inline member -> the member's keys merged up (existing node keys
      such as ``description`` win) + ``nullable: true``; already lands
      ``nullable`` next to the merged-in ``type``, so this form was already
      correct before #782.
    * multiple members -> the combinator is kept (null member removed), with
      genuine null-acceptance applied to whichever first branch can carry it
      (a branch with its own ``type``, or an inlineable ``$ref``) so at least
      one branch in the union actually accepts null, plus the same sibling
      ``nullable: true`` for discoverability (ignored by validation once a
      branch already accepts null, but documents the field's shape).
    * null members alone -> the combinator is dropped and the schema stays
      null-only (an ``enum`` of ``null`` plus ``nullable: true``), because
      ``nullable`` without a ``type`` accepts every value.

    Nodes without a null-bearing ``anyOf``/``oneOf`` are returned unchanged.
    """
    result = schema
    for key in ("anyOf", "oneOf"):
        members = result.get(key)
        if not isinstance(members, list):
            continue
        if not any(isinstance(m, dict) and m.get("type") == "null" for m in members):
            continue
        non_null = [m for m in members if not (isinstance(m, dict) and m.get("type") == "null")]
        result = {k: v for k, v in result.items() if k != key}
        result["nullable"] = True
        if len(non_null) == 1:
            sole = non_null[0]
            if isinstance(sole, dict) and "$ref" in sole:
                extra_keys = {k: v for k, v in sole.items() if k != "$ref"}
                inlined = _inline_ref_nullable(sole["$ref"], extra_keys, schemas, resolving, lossy)
                if inlined is not None:
                    # Merge, not replace: `result` may carry wrapper-level
                    # annotations (description/default/readOnly/maxProperties/
                    # ...) from the ORIGINAL node this anyOf/oneOf lived on,
                    # which `inlined` (the referenced schema's own content)
                    # knows nothing about. Replacing `result` outright
                    # silently discarded all of them. This node's own value
                    # wins a plain conflict (it is the more specific,
                    # field-level context the author actually wrote); a
                    # shared numeric bound instead keeps whichever of the two
                    # is tighter, so neither original constraint is lost.
                    merged = dict(inlined)
                    for wrapper_key, wrapper_value in result.items():
                        if wrapper_key == "nullable":
                            continue
                        if wrapper_key not in merged:
                            merged[wrapper_key] = wrapper_value
                        elif merged[wrapper_key] != wrapper_value:
                            merged[wrapper_key] = _tighter_bound(
                                wrapper_key, merged[wrapper_key], wrapper_value
                            )
                    result = merged
                else:
                    # A $ref must not carry sibling keys in 3.0; wrap the bare
                    # ref in allOf and lift any annotation siblings up to this
                    # node. Documented above as not satisfying the null case
                    # by itself -- kept only as a last-resort fallback for an
                    # unresolvable or self-referential ref.
                    result["allOf"] = [{"$ref": sole["$ref"]}]
                    for k, v in extra_keys.items():
                        result.setdefault(k, v)
            elif isinstance(sole, dict):
                conflict = any(
                    k in result and result[k] != v
                    for k, v in sole.items()
                    if k in _STRUCTURAL_MERGE_KEYS
                )
                if conflict:
                    # Ambiguous structural overlap: keep the (single-member)
                    # combinator rather than silently dropping a constraint.
                    result[key] = [sole]
                else:
                    for k, v in sole.items():
                        result.setdefault(k, v)
            else:
                result[key] = non_null
        elif not non_null:
            result.setdefault("enum", [None])
        elif len(non_null) > 1:
            patched_members: list[Any] = []
            patched_one = False
            for member in non_null:
                if patched_one or not isinstance(member, dict):
                    patched_members.append(member)
                    continue
                if "$ref" in member:
                    extra_keys = {k: v for k, v in member.items() if k != "$ref"}
                    inlined = _inline_ref_nullable(
                        member["$ref"], extra_keys, schemas, resolving, lossy
                    )
                    if inlined is not None:
                        patched_members.append(inlined)
                        patched_one = True
                        continue
                elif "type" in member or "const" in member or "enum" in member:
                    patched_members.append(_ensure_null_accepting(member))
                    patched_one = True
                    continue
                patched_members.append(member)
            result[key] = patched_members
    return result


def _tighter_bound(key: str, first: Any, second: Any) -> Any:
    """Return whichever of two conflicting values for *key* is the tighter
    (more restrictive) bound, for the numeric constraint keywords a wrapper
    node and an inlined referenced schema can both legitimately declare.
    Anything else keeps *first* (the wrapper's own explicit value): it is the
    more specific, field-level annotation the author actually wrote.
    """
    if key in ("maxProperties", "maxLength", "maximum", "maxItems"):
        try:
            return min(first, second)
        except TypeError:
            return first
    if key in ("minProperties", "minLength", "minimum", "minItems"):
        try:
            return max(first, second)
        except TypeError:
            return first
    return first


def _expand_type_union(schema: dict[str, Any], types: list[str]) -> None:
    """Replace the multi-type ``type`` array of *schema* with an ``anyOf`` of single-type schemas.

    Sibling keywords stay where they are: type-specific ones (``minLength``, ``items``,
    ...) only constrain instances of their own type, so the result accepts the same
    values. Three details keep each branch valid and faithful under OpenAPI 3.0:

    * ``nullable`` only takes effect beside the ``type`` it exempts, so a nullable
      *schema* hands it to the first branch, the idiom the nullable-union collapse
      already uses.
    * Every ``array`` schema needs ``items``, so an ``array`` branch gets an empty one;
      the sibling ``items`` of *schema* still applies as before.
    * An ``anyOf`` that *schema* already carries is kept by adding the new union to its
      ``allOf``.
    """
    del schema["type"]
    nullable = schema.get("nullable") is True
    union: list[dict[str, Any]] = []
    for index, name in enumerate(types):
        branch: dict[str, Any] = {"type": name}
        if name == "array":
            branch["items"] = {}
        if nullable and index == 0:
            branch["nullable"] = True
        union.append(branch)
    if "anyOf" in schema:
        all_of = schema.get("allOf")
        schema["allOf"] = [*(all_of if isinstance(all_of, list) else []), {"anyOf": union}]
    else:
        schema["anyOf"] = union


def _wrap_ref_siblings(schema: dict[str, Any]) -> None:
    """Move the ``$ref`` of *schema* into ``allOf``.

    OpenAPI 3.0 ignores every sibling of a Reference Object, so keywords that conversion
    just wrote beside a ``$ref`` would silently stop constraining anything.
    """
    all_of = schema.get("allOf")
    schema["allOf"] = [{"$ref": schema.pop("$ref")}, *(all_of if isinstance(all_of, list) else [])]


def _convert_schema_to_3_0(
    schema: dict[str, Any],
    schemas: dict[str, Any] | None = None,
    resolving: frozenset[str] = frozenset(),
    lossy: list[str] | None = None,
) -> dict[str, Any]:
    """Recursively down-convert a JSON-Schema-2020-12 schema to OpenAPI 3.0.

    Mirrors :func:`_convert_schema_to_3_1` in reverse: the 3.1/Pydantic
    nullability idioms (``type: [T, "null"]`` and ``anyOf: [T, {type: null}]``)
    are rewritten to the 3.0 ``nullable: true`` form so the emitted schema is
    valid under OpenAPI 3.0 (#562) and -- for a nullable ``$ref``, when
    *schemas* is supplied -- actually accepts a ``null`` instance (#782).
    Non-nullable schemas pass through unchanged.

    *schemas* (the complete ``components.schemas`` registry) and *resolving*
    (the set of component names currently being inlined higher up this same
    call chain, used to stop a self- or mutually-referencing nullable ref from
    inlining forever) are threaded through every recursive call so a nullable
    ``$ref`` can be resolved no matter how deeply nested it is.

    *lossy* is an optional accumulator for conversions that are not merely
    re-expressed but demonstrably weakened -- currently, a heterogeneous
    ``tuple`` (differing ``prefixItems``), whose positional constraints
    OpenAPI 3.0 cannot express at all. When supplied, each such occurrence
    appends a human-readable message instead of silently approximating it;
    the caller decides whether that is a strict-mode error or a logged
    warning, mirroring the existing :func:`_check_schemas_3_0_compatible`
    strict/non-strict gate.
    """
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    if "const" in result:
        result["enum"] = [result.pop("const")]

    examples = result.pop("examples", None)
    if isinstance(examples, list) and examples:
        result["example"] = examples[0]

    pattern_properties = result.pop("patternProperties", None)
    if "additionalProperties" not in result and isinstance(pattern_properties, dict):
        pattern_schemas = [
            _convert_schema_to_3_0(value, schemas, resolving, lossy)
            for value in pattern_properties.values()
            if isinstance(value, dict)
        ]
        if len(pattern_schemas) == 1:
            result["additionalProperties"] = pattern_schemas[0]
        elif pattern_schemas:
            result["additionalProperties"] = {"anyOf": pattern_schemas}

    for exclusive_key, bound_key in (
        ("exclusiveMinimum", "minimum"),
        ("exclusiveMaximum", "maximum"),
    ):
        exclusive_bound = result.get(exclusive_key)
        if isinstance(exclusive_bound, (int, float)) and not isinstance(exclusive_bound, bool):
            result[bound_key] = exclusive_bound
            result[exclusive_key] = True

    # ``type: [T, "null"]`` -> ``type: T`` + ``nullable: true``. OpenAPI 3.0
    # requires ``type`` to be a single string, so a multi-type union is expressed
    # as ``anyOf`` of single-type schemas rather than a (3.0-invalid) type array.
    type_val = result.get("type")
    type_array_rewritten = False
    if isinstance(type_val, list) and "null" in type_val:
        non_null_types = [t for t in type_val if t != "null"]
        result["nullable"] = True
        if len(non_null_types) == 1:
            result["type"] = non_null_types[0]
        elif not non_null_types:
            del result["type"]
            result.setdefault("enum", [None])
        else:
            _expand_type_union(result, non_null_types)
        type_array_rewritten = True
    elif isinstance(type_val, list) and type_val and all(isinstance(t, str) for t in type_val):
        # A type array without ``null`` takes the same shape. Type-specific keywords
        # (minLength, items, properties, ...) only constrain instances of their own
        # type, so leaving them beside the ``anyOf`` accepts exactly the same values.
        # A sibling ``discriminator`` would start constraining instances once a
        # combinator appears, so a multi-type array there is left for the audit to
        # report; a single type adds no combinator and converts regardless.
        if len(type_val) == 1:
            result["type"] = type_val[0]
            type_array_rewritten = True
        elif "discriminator" not in result:
            _expand_type_union(result, type_val)
            type_array_rewritten = True
    if type_array_rewritten and "$ref" in result:
        _wrap_ref_siblings(result)

    # ``enum: [None, ...]`` -> keep ``null`` IN the enum (``nullable: true``
    # alone does not exempt a sibling ``enum`` from its own closed-list check,
    # #782 follow-up) and also set ``nullable: true`` for discoverability.
    enum_val = result.get("enum")
    if isinstance(enum_val, list) and None in enum_val:
        result["nullable"] = True

    if result.get("type") == "null":
        # Without ``type``, ``nullable`` alone accepts every value, so a null-only schema
        # keeps an ``enum`` of ``null``; a ``not`` over it would otherwise reject everything.
        del result["type"]
        result["nullable"] = True
        result.setdefault("enum", [None])

    result = _collapse_nullable_combinator(result, schemas, resolving, lossy)

    # Recurse into nested structures first so inner unions are converted before
    # the combinator at this level is collapsed.
    if "properties" in result and isinstance(result["properties"], dict):
        result["properties"] = {
            k: _convert_schema_to_3_0(v, schemas, resolving, lossy)
            for k, v in result["properties"].items()
        }
    if "items" in result:
        result["items"] = _convert_schema_to_3_0(result["items"], schemas, resolving, lossy)
    prefix_items = result.pop("prefixItems", None)
    if isinstance(prefix_items, list) and prefix_items:
        converted_items = [
            _convert_schema_to_3_0(item, schemas, resolving, lossy) for item in prefix_items
        ]
        if all(item == converted_items[0] for item in converted_items[1:]):
            # Every position shares the identical schema: a plain ``items``
            # array faithfully represents it, with nothing position-specific
            # to lose.
            result["items"] = converted_items[0]
        else:
            # A heterogeneous tuple has no OpenAPI-3.0-native representation:
            # ``oneOf`` looks closest to the original intent, but JSON
            # Schema's "integer" is a subset of "number", so a value valid at
            # one position can also be valid at another and match more than
            # one oneOf branch -- oneOf then wrongly rejects it (requires
            # exactly one match). ``anyOf`` never has that failure mode, but,
            # like oneOf here, it cannot express *which* position requires
            # *which* schema: this is a genuine, not cosmetic, loss of the
            # tuple's positional constraints, so it is reported rather than
            # silently emitted as if it were faithful (#782).
            result["items"] = {"anyOf": converted_items}
            if lossy is not None:
                item_types = ", ".join(
                    str(item.get("type", "object")) if isinstance(item, dict) else "unknown"
                    for item in converted_items
                )
                lossy.append(
                    f"tuple[{item_types}] positional constraints cannot be "
                    "preserved in OpenAPI 3.0 and were approximated as "
                    "items.anyOf; a value valid at any position is now "
                    "accepted at every position"
                )
    for combinator in ("allOf", "anyOf", "oneOf"):
        if combinator in result and isinstance(result[combinator], list):
            result[combinator] = [
                _convert_schema_to_3_0(s, schemas, resolving, lossy) for s in result[combinator]
            ]
    if "additionalProperties" in result and isinstance(result["additionalProperties"], dict):
        result["additionalProperties"] = _convert_schema_to_3_0(
            result["additionalProperties"], schemas, resolving, lossy
        )
    if "not" in result and isinstance(result["not"], dict):
        result["not"] = _convert_schema_to_3_0(result["not"], schemas, resolving, lossy)
    if "$defs" in result and isinstance(result["$defs"], dict):
        result["$defs"] = {
            k: _convert_schema_to_3_0(v, schemas, resolving, lossy)
            for k, v in result["$defs"].items()
        }

    return _collapse_nullable_combinator(result, schemas, resolving, lossy)


def _convert_schemas_to_3_0(schemas: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Down-convert all component schemas to OpenAPI 3.0 nullable form (#562).

    Returns the converted schemas alongside a list of human-readable lossy-
    conversion messages (currently: heterogeneous tuples, #782), one entry per
    affected named schema, each prefixed with that schema's name the same way
    :func:`_check_schemas_3_0_compatible` labels its own warnings.
    """
    converted: dict[str, Any] = {}
    lossy_messages: list[str] = []
    for name, schema in schemas.items():
        schema_lossy: list[str] = []
        converted[name] = _convert_schema_to_3_0(schema, schemas, frozenset(), schema_lossy)
        lossy_messages.extend(f"Schema '{name}': {message}" for message in schema_lossy)
    return converted, lossy_messages


_NESTED_SCHEMA_KEYS = (
    "properties",
    "items",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "additionalProperties",
    "$defs",
)


def _find_3_1_only_construct(schema: dict[str, Any]) -> str | None:
    """Name the first construct in *schema* that OpenAPI 3.0 cannot express, if any.

    Detects:
    - ``type`` as a list (JSON Schema 2020-12 / OpenAPI 3.1 syntax)
    - ``anyOf`` containing ``{"type": "null"}`` (Pydantic v2 nullable pattern)
    """
    if not isinstance(schema, dict):
        return None

    if isinstance(schema.get("type"), list):
        return 'a "type" array'

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        for item in any_of:
            if isinstance(item, dict) and item.get("type") == "null":
                return 'an "anyOf" with a null type'

    for key in _NESTED_SCHEMA_KEYS:
        val = schema.get(key)
        children: Iterable[Any]
        if isinstance(val, dict):
            children = val.values() if key in ("properties", "$defs") else [val]
        elif isinstance(val, list):
            children = val
        else:
            continue
        for child in children:
            if (found := _find_3_1_only_construct(child)) is not None:
                return found

    return None


def _has_3_1_only_constructs(schema: dict[str, Any]) -> bool:
    """Check if a schema contains constructs incompatible with OpenAPI 3.0."""
    return _find_3_1_only_construct(schema) is not None


def _incompatibility_message(subject: str, construct: str) -> str:
    return (
        f"{subject} contains OpenAPI 3.1-only constructs ({construct}) incompatible with "
        "OpenAPI 3.0. Use openapi_version='3.1.0' (default) or provide a manual "
        "3.0-compatible schema."
    )


def _report_incompatibilities(findings: list[str], strict: bool) -> list[str]:
    if strict and findings:
        raise OpenAPISpecConfigError(
            "OpenAPI 3.0 compatibility error:\n" + "\n".join(f"  - {f}" for f in findings)
        )
    return findings


def _check_schemas_3_0_compatible(schemas: dict[str, Any], strict: bool) -> list[str]:
    """Check component schemas for OpenAPI 3.1-only constructs when targeting 3.0.

    Returns a list of warning messages for incompatible schemas.
    In strict mode, raises OpenAPISpecConfigError if any are found.
    """
    findings = [
        _incompatibility_message(f"Schema '{name}'", construct)
        for name, schema in schemas.items()
        if (construct := _find_3_1_only_construct(schema)) is not None
    ]
    return _report_incompatibilities(findings, strict)


def _operation_schema_slots(
    operation: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any], str]]:
    """Yield ``(location, container, key)`` for every inline schema of one operation.

    Covers:
    - requestBody.content.*.schema
    - responses.*.content.*.schema and .itemSchema
    - responses.*.headers.*.schema and .content.*.schema
    - parameters[].schema (and querystring parameters' content.*.schema)
    """
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        content = request_body.get("content")
        if isinstance(content, dict):
            for media, media_obj in content.items():
                if isinstance(media_obj, dict) and "schema" in media_obj:
                    yield f"requestBody.content.{media}.schema", media_obj, "schema"

    responses = operation.get("responses")
    if isinstance(responses, dict):
        for status, resp in responses.items():
            if not isinstance(resp, dict):
                continue
            content = resp.get("content")
            if isinstance(content, dict):
                for media, media_obj in content.items():
                    if not isinstance(media_obj, dict):
                        continue
                    for schema_key in _MEDIA_SCHEMA_KEYS:
                        if schema_key in media_obj:
                            yield (
                                f"responses.{status}.content.{media}.{schema_key}",
                                media_obj,
                                schema_key,
                            )
            headers = resp.get("headers")
            if isinstance(headers, dict):
                for name, header in headers.items():
                    if not isinstance(header, dict):
                        continue
                    if "schema" in header:
                        yield f"responses.{status}.headers.{name}.schema", header, "schema"
                    header_content = header.get("content")
                    if isinstance(header_content, dict):
                        for media, media_obj in header_content.items():
                            if isinstance(media_obj, dict) and "schema" in media_obj:
                                yield (
                                    f"responses.{status}.headers.{name}.content.{media}.schema",
                                    media_obj,
                                    "schema",
                                )

    for index, param in enumerate(operation.get("parameters", [])):
        if not isinstance(param, dict):
            continue
        if "schema" in param:
            yield f"parameters[{index}].schema", param, "schema"
        # querystring parameters (OpenAPI 3.2) carry a content map instead of a
        # bare schema.
        param_content = param.get("content")
        if isinstance(param_content, dict):
            for media, media_obj in param_content.items():
                if isinstance(media_obj, dict) and "schema" in media_obj:
                    yield f"parameters[{index}].content.{media}.schema", media_obj, "schema"


def _convert_operation_schemas(
    paths: dict[str, Any],
    converter: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Apply *converter* to every inline schema in operations, in place."""
    for _path, methods in paths.items():
        for _method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            for _location, container, key in _operation_schema_slots(operation):
                container[key] = converter(container[key])

    return paths


def _check_operation_schemas_3_0_compatible(paths: dict[str, Any], strict: bool) -> list[str]:
    """Check inline operation schemas for OpenAPI 3.1-only constructs when targeting 3.0.

    Counterpart of :func:`_check_schemas_3_0_compatible` for schemas that sit directly
    in an operation rather than in ``components.schemas``. Each message names the
    operation and the schema location. In strict mode, raises OpenAPISpecConfigError
    if any are found.
    """
    findings = [
        _incompatibility_message(f"{method.upper()} {path} {location}", construct)
        for path, methods in paths.items()
        for method, operation in methods.items()
        if isinstance(operation, dict)
        for location, container, key in _operation_schema_slots(operation)
        if (construct := _find_3_1_only_construct(container[key])) is not None
    ]
    return _report_incompatibilities(findings, strict)


def _convert_operation_schemas_to_3_1(paths: dict[str, Any]) -> dict[str, Any]:
    """Apply 3.1 schema conversion to inline schemas in operations."""
    return _convert_operation_schemas(paths, _convert_schema_to_3_1)


def _convert_operation_schemas_to_3_0(
    paths: dict[str, Any], schemas: dict[str, Any] | None = None
) -> list[str]:
    """Down-convert inline operation schemas to valid OpenAPI 3.0 form (#562).

    *schemas* is the (not-yet-converted) ``components.schemas`` registry, used
    to resolve a nullable ``$ref`` that appears directly in a raw endpoint
    schema rather than inside a registered component (#782). Returns lossy-
    conversion messages collected while converting these inline schemas, the
    same shape :func:`_convert_schemas_to_3_0` returns for named components.
    """
    lossy: list[str] = []
    _convert_operation_schemas(
        paths, lambda s: _convert_schema_to_3_0(s, schemas, frozenset(), lossy)
    )
    return lossy
