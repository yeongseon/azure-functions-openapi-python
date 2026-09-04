"""Shared scan-time test scaffolding for inference test modules.

Minimal in-memory doubles for the ``azure-functions`` public discovery surface
(``FunctionBuilder.build()`` + ``Function`` accessors + ``app._function_builders``)
that ``scan_endpoint_metadata`` reads. Extracted here so return-type and
docstring inference tests share one definition and scanner changes touch a
single place.
"""

from __future__ import annotations

from typing import Any


class _MockBinding:
    def __init__(self, route: str, methods: list[str]) -> None:
        self.route = route
        self.methods = methods
        self.type = "httpTrigger"


class _MockFunction:
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
        return True


class _MockBuilder:
    def __init__(self, function: _MockFunction) -> None:
        self._function = function

    def build(self, auth_level: Any = None) -> _MockFunction:
        return self._function


class _MockApp:
    def __init__(self, builders: list[_MockBuilder]) -> None:
        self._function_builders = builders


def _app_for(handler: Any, *, name: str, route: str, methods: list[str]) -> _MockApp:
    fn = _MockFunction(name=name, func=handler, bindings=[_MockBinding(route, methods)])
    return _MockApp([_MockBuilder(fn)])
