"""Architecture guardrail: keep the OpenAPI core SDK-free.

The OpenAPI *core* — spec compilation, the metadata registry, and the schema
normalization helpers — must be able to run without importing the Azure
Functions SDK. Discovery of live functions (which does need the SDK) lives in
the Azure-facing surface (``decorator``, ``swagger_ui``, and the ``adapters``
package introduced in #325).

This test statically walks the transitive first-party import closure of each
core module and asserts none of them:

* import ``azure.functions`` (directly or transitively),
* reference the ``FunctionBuilder`` SDK type, or
* touch the SDK-private ``_function_builders`` attribute.

See issue #324 for the module classification this enforces.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = "azure_functions_openapi"
SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / PACKAGE

# Modules that form the SDK-free core. Their entire first-party import closure
# must stay free of the Azure Functions SDK.
CORE_MODULES = ("spec", "registry", "utils")

# Substrings that, if they appear as an *import target* or *referenced symbol*,
# indicate SDK coupling. Kept deliberately narrow so docstrings mentioning these
# names (e.g. exceptions.py explaining a traceback) do not trip the guard.
FORBIDDEN_IMPORT_ROOTS = ("azure.functions", "azure_functions")
FORBIDDEN_SYMBOLS = ("FunctionBuilder",)
FORBIDDEN_ATTRS = ("_function_builders",)


def _resolve(dotted: str) -> Path | None:
    """Resolve a first-party dotted module (relative to PACKAGE) to its file.

    Handles both plain modules (``spec`` -> ``spec.py``) and packages
    (``adapters`` -> ``adapters/__init__.py``, ``adapters.azure_functions`` ->
    ``adapters/azure_functions.py``) so SDK coupling hidden inside a subpackage
    is not silently dropped by truncating to the first path segment.
    """
    parts = dotted.split(".")
    module_file = SRC_ROOT.joinpath(*parts).with_suffix(".py")
    if module_file.exists():
        return module_file
    package_init = SRC_ROOT.joinpath(*parts, "__init__.py")
    if package_init.exists():
        return package_init
    return None


def _first_party_imports(tree: ast.AST) -> set[str]:
    """Return first-party modules (dotted, relative to PACKAGE) imported by *tree*.

    The full relative path after the package prefix is preserved so a submodule
    import such as ``azure_functions_openapi.adapters.azure_functions`` resolves
    to ``adapters/azure_functions.py`` instead of being truncated to
    ``adapters`` (which would miss SDK coupling living in the submodule).
    """
    prefix = f"{PACKAGE}."
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if not mod.startswith(prefix):
                continue
            base = mod[len(prefix) :]
            if _resolve(base) is not None:
                modules.add(base)
            # ``from pkg.sub import name`` may import a submodule, not a symbol.
            for alias in node.names:
                candidate = f"{base}.{alias.name}"
                if _resolve(candidate) is not None:
                    modules.add(candidate)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(prefix):
                    base = alias.name[len(prefix) :]
                    if _resolve(base) is not None:
                        modules.add(base)
    return modules


def _import_closure(root: str) -> set[str]:
    """Transitively collect all first-party modules reachable from *root*."""
    seen: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        path = _resolve(current)
        if path is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        stack.extend(_first_party_imports(tree) - seen)
    return seen


def _sdk_violations(module: str) -> list[str]:
    """Return human-readable SDK-coupling violations for a single module."""
    path = _resolve(module)
    if path is None:
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        # Forbidden imports (direct SDK import).
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if any(mod == root or mod.startswith(root + ".") for root in FORBIDDEN_IMPORT_ROOTS):
                violations.append(f"{module}: imports from '{mod}'")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(
                    alias.name == root or alias.name.startswith(root + ".")
                    for root in FORBIDDEN_IMPORT_ROOTS
                ):
                    violations.append(f"{module}: imports '{alias.name}'")
        # Forbidden referenced symbols (e.g. FunctionBuilder used as a name).
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_SYMBOLS:
            violations.append(f"{module}: references symbol '{node.id}'")
        # Forbidden SDK-private attribute access (e.g. app._function_builders).
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            violations.append(f"{module}: accesses SDK-private attribute '.{node.attr}'")
    return violations


@pytest.mark.parametrize("core_module", CORE_MODULES)
def test_core_module_import_closure_is_sdk_free(core_module: str) -> None:
    """Every module reachable from a core module must stay SDK-free."""
    closure = _import_closure(core_module)
    all_violations: list[str] = []
    for module in sorted(closure):
        all_violations.extend(_sdk_violations(module))
    assert not all_violations, (
        f"OpenAPI core module '{core_module}' has SDK coupling in its import "
        f"closure {sorted(closure)}:\n  " + "\n  ".join(all_violations)
    )


def test_spec_does_not_import_decorator() -> None:
    """spec.py must read the registry directly, never via decorator.py (#324)."""
    closure = _import_closure("spec")
    assert "decorator" not in closure, (
        "spec.py must not depend on decorator.py; obtain the registry from "
        f"registry.py instead. Closure was: {sorted(closure)}"
    )


def test_azure_facing_modules_are_allowed_to_import_sdk() -> None:
    """Sanity check: the classification is meaningful, not vacuous.

    At least one Azure-facing module must actually touch the SDK, otherwise the
    core-vs-Azure split this test enforces would be trivially satisfied.
    """
    azure_facing = ("decorator", "swagger_ui")
    assert any(_sdk_violations(module) for module in azure_facing), (
        "Expected at least one Azure-facing module to import the Azure Functions "
        "SDK; if this fails the SDK-free-core guard is vacuous."
    )
