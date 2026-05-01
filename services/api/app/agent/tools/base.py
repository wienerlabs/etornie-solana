"""Tool base abstractions for the agent orchestrator.

A `Tool` carries:
  * `name` and JSON schema for the LLM (Together AI tool calling format)
  * `execute` callable that runs the tool with validated arguments

Tools register themselves into the module-level `TOOL_REGISTRY`. The
orchestrator dispatches tool calls by `name`.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


class ToolError(Exception):
    """Raised when a tool fails in a way the model should see.

    The orchestrator catches this and feeds the message back as a tool
    result (`role=tool`) so the model can recover (ask the user, retry
    with corrected args, etc.).
    """


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

    def to_openai_schema(self) -> dict[str, Any]:
        """Render in the OpenAI/Together tool-calling JSON shape."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


TOOL_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.name in TOOL_REGISTRY:
        raise RuntimeError(f"Tool already registered: {tool.name}")
    TOOL_REGISTRY[tool.name] = tool
    return tool
