"""Custom tools: the agent requests them, your Python process runs them."""

from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass

import pydantic


@dataclass(frozen=True)
class Tool:
    """A local Python function exposed to the agent as a custom tool."""

    name: str
    description: str
    input_schema: typing.Dict[str, typing.Any]
    fn: typing.Callable[..., typing.Any]

    def definition(self) -> typing.Dict[str, typing.Any]:
        """The ``ToolDefinition`` payload carried by the agent spec."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}

    def __call__(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        return self.fn(*args, **kwargs)


ToolInput = typing.Union[Tool, typing.Callable[..., typing.Any]]


def _schema_from_signature(fn: typing.Callable[..., typing.Any]) -> typing.Dict[str, typing.Any]:
    hints = typing.get_type_hints(fn)
    fields: typing.Dict[str, typing.Any] = {}
    for param_name, param in inspect.signature(fn).parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise ValueError(f"Tool {fn.__name__!r} cannot use *args/**kwargs; declare explicit parameters.")
        annotation = hints.get(param_name, typing.Any)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (annotation, default)
    schema = pydantic.create_model(f"{fn.__name__}_args", **fields).model_json_schema()
    schema.pop("title", None)
    return schema


def tool(
    fn: typing.Optional[typing.Callable[..., typing.Any]] = None,
    *,
    name: typing.Optional[str] = None,
    description: typing.Optional[str] = None,
) -> typing.Any:
    """Wrap a function as a custom :class:`Tool` executed in your process; the input schema is derived from its signature."""

    def wrap(f: typing.Callable[..., typing.Any]) -> Tool:
        resolved = description or inspect.getdoc(f)
        if not resolved:
            raise ValueError(f"Tool {f.__name__!r} needs a description: add a docstring or pass description=.")
        return Tool(
            name=name or f.__name__,
            description=resolved.strip(),
            input_schema=_schema_from_signature(f),
            fn=f,
        )

    return wrap if fn is None else wrap(fn)


def as_tools(tools: typing.Sequence[ToolInput]) -> typing.List[Tool]:
    """Normalize a mix of :class:`Tool` objects and bare callables, rejecting duplicate names."""
    normalized = [t if isinstance(t, Tool) else tool(t) for t in tools]
    names = [t.name for t in normalized]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"Duplicate tool names: {sorted(duplicates)}.")
    return normalized
