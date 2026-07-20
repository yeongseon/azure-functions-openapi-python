"""Read-side mirror of the ``validation`` namespace metadata contract.

The bridge consumes the cross-package ``_azure_functions_metadata`` convention
attribute (namespace ``"validation"``) written by ``azure-functions-validation``.
This module mirrors the *shape the bridge reads* as a ``TypedDict`` so the
consumed contract is explicit and type-checked, without importing the producing
package.

This intentionally duplicates the producer's write-side TypedDict: the two
packages release independently, and a read-side mirror keeps the consumer's
expectations pinned even if the producer evolves. Model-type fields are ``Any``
because they carry user-defined Pydantic classes that vary per handler.
"""

from __future__ import annotations

from typing import Any, TypedDict

# Convention attribute name shared across every Azure Functions toolkit package.
HANDLER_METADATA_ATTR = "_azure_functions_metadata"

# Namespace owned by ``azure-functions-validation``.
VALIDATION_NAMESPACE = "validation"

# Payload ``version`` values this consumer understands.
SUPPORTED_VALIDATION_VERSIONS: frozenset[int] = frozenset({1})


class _ValidationMetadataRequired(TypedDict):
    """Keys present on every validation payload."""

    version: int


class ValidationMetadata(_ValidationMetadataRequired, total=False):
    """The ``validation`` namespace payload read from ``HANDLER_METADATA_ATTR``.

    ``body``/``query``/``path``/``headers``/``response_model`` carry user-defined
    Pydantic model classes (or ``None``), hence ``Any``.
    """

    body: Any
    query: Any
    path: Any
    headers: Any
    response_model: Any
