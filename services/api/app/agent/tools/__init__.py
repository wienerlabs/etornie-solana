"""Tool registry for the agent orchestrator.

Each tool is a thin wrapper around an existing service. The model never
talks to the legacy services directly — it goes through these wrappers,
which are the only code path responsible for argument validation,
result shaping, and audit logging.
"""
from app.agent.tools.base import TOOL_REGISTRY, Tool, ToolError

__all__ = ["TOOL_REGISTRY", "Tool", "ToolError"]
