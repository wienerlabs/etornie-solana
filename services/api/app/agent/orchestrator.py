"""Tool-calling orchestrator for the EtornieGPT agent.

One round trip: takes a user message that's already been persisted, runs
the tool-calling loop with the LLM, persists every assistant/tool turn
along the way, and returns the final assistant message.

Provider: Together AI — model configured in
``settings.together_agent_model``.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from together import AsyncTogether

from app.agent.models import (
    AgentMessage,
    AgentMessageRole,
    AgentSession,
)
from app.agent.tools import TOOL_REGISTRY, ToolError
from app.config import settings

# Importing tool modules registers their Tool instances with TOOL_REGISTRY.
from app.agent.tools import trademark_search as _trademark_search  # noqa: F401
from app.agent.tools import validate_logo as _validate_logo  # noqa: F401
from app.agent.tools import decide_platform as _decide_platform  # noqa: F401
from app.agent.tools import quote_fees as _quote_fees  # noqa: F401
from app.agent.tools import create_case_draft as _create_case_draft  # noqa: F401
from app.agent.tools import prepare_payment as _prepare_payment  # noqa: F401
from app.agent.tools import submit_filing as _submit_filing  # noqa: F401
from app.agent.tools import start_ukipo_filing as _start_ukipo_filing  # noqa: F401
from app.agent.tools import check_filing_progress as _check_filing_progress  # noqa: F401
from app.agent.tools import validate_uploaded_document as _validate_uploaded_document  # noqa: F401
from app.agent.tools import list_session_uploads as _list_session_uploads  # noqa: F401
from app.agent.tools import get_case_by_number as _get_case_by_number  # noqa: F401
from app.agent.tools import goods_services_search as _goods_services_search  # noqa: F401
from app.agent.tools import goods_services_validate as _goods_services_validate  # noqa: F401
from app.agent.tools import design_search as _design_search  # noqa: F401
from app.agent.tools import export_case as _export_case  # noqa: F401

logger = logging.getLogger(__name__)


MAX_TOOL_ITERATIONS = 10
SYSTEM_PROMPT = (
    "You are EtornieGPT, an agent that helps users file IP applications "
    "across EUIPO, WIPO, USPTO, and UKIPO. You MUST use tools to take any "
    "concrete action; never claim you filed something without calling the "
    "tool. If a required slot is missing, ask the user; do not invent "
    "values. If the user gives invalid input (e.g., Nice class > 45), "
    "reject with a reason and ask for correction. Respond in the same "
    "language as the user.\n\n"
    "Output style: use light Markdown that renders cleanly: **bold** for "
    "emphasis, simple bullet points with hyphens, numbered lists when "
    "ordering matters. Do not use em dashes (the long dash character) "
    "anywhere; use a comma, a period, a colon, or parentheses instead. "
    "Do not use emojis. Do not use code blocks or tables. Keep paragraphs "
    "short.\n\n"
    "Tool retry policy: if a tool returns an error, a failed status, or "
    "an unexpected result, DO NOT call the same tool again with the same "
    "or similar arguments. Report the failure to the user in plain "
    "language, explain what went wrong, and ask how they want to "
    "proceed.\n\n"
    "Robot tools (start_ukipo_filing): once it returns successfully, "
    "tell the user the robot started and can be watched in the live "
    "progress panel, then STOP. Do not call check_filing_progress more "
    "than once per turn.\n\n"
    "File uploads: when you need a document, ask the user to upload it "
    "via the attachment button and name the document type. After upload, "
    "call list_session_uploads, then validate_uploaded_document with the "
    "upload_id. If ok=false, explain the issues and ask for the correct "
    "file. Never file with an unvalidated upload.\n\n"
    "Payment flow: after quote_fees succeeds, do NOT ask the user which "
    "payment method to use. The frontend renders both options "
    "(card via Stripe, wallet via x402) automatically once "
    "prepare_payment returns. Your next move is always: call "
    "prepare_payment immediately, then in your final reply tell the "
    "user the payment options are ready below the message and STOP. "
    "Do not invent payment method buttons in chat text."
)


class OrchestratorError(RuntimeError):
    """Unrecoverable orchestrator failure (LLM API down, infinite loop, etc.)."""


def _build_system_prompt(*, session_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return (
        SYSTEM_PROMPT
        + "\n\nRuntime context: your current session_id is "
        + str(session_id)
        + " and the authenticated user_id is "
        + str(user_id)
        + ". When a tool requires session_id or user_id, pass these "
        + "exact values; never invent or alter them."
    )


async def _load_history(db: AsyncSession, session_id: uuid.UUID) -> list[AgentMessage]:
    # Secondary sort on id keeps ordering deterministic if two rows
    # happen to share a timestamp. (Each persist sets `created_at` via
    # `datetime.now(timezone.utc)` at construction so collisions are
    # rare, but the secondary key guarantees a stable order — Together
    # rejects the request with a 400 'Input validation error' when a
    # tool message is not immediately preceded by its assistant
    # tool_call, which the random uuid4 ordering could otherwise cause.)
    result = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
    )
    return list(result.scalars().all())


def _to_llm_messages(
    history: list[AgentMessage], *, session: AgentSession
) -> list[dict[str, Any]]:
    """Convert ORM rows to the OpenAI/Together chat format."""
    out: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": _build_system_prompt(
                session_id=session.id, user_id=session.user_id
            ),
        }
    ]

    for m in history:
        if m.role == AgentMessageRole.user:
            out.append({"role": "user", "content": m.content or ""})
        elif m.role == AgentMessageRole.assistant:
            # Per OpenAI chat format, an assistant message MUST include
            # a `content` field even when only tool_calls are present
            # (set to null). Together's Llama-3.3 serving rejects the
            # request with a 400 "Input validation error" when the key
            # is missing entirely, so we always emit it explicitly.
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": m.content if m.content else None,
            }
            if m.tool_call_id and m.tool_name:
                msg["tool_calls"] = [
                    {
                        "id": m.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": m.tool_name,
                            "arguments": json.dumps(m.tool_arguments or {}),
                        },
                    }
                ]
            out.append(msg)
        elif m.role == AgentMessageRole.tool:
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": json.dumps(m.tool_result or {}),
                }
            )

    return out


def _registered_tools() -> list[dict[str, Any]]:
    return [tool.to_openai_schema() for tool in TOOL_REGISTRY.values()]


async def _persist_assistant_with_tool_call(
    db: AsyncSession,
    session: AgentSession,
    *,
    tool_call_id: str,
    tool_name: str,
    tool_arguments: dict[str, Any],
    content: str | None,
    input_tokens: int,
    output_tokens: int,
) -> AgentMessage:
    msg = AgentMessage(
        session_id=session.id,
        role=AgentMessageRole.assistant,
        content=content,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        # Pin timestamp at construction time. The default
        # ``server_default=func.now()`` returns the transaction start
        # time, so every message persisted in the same orchestrator
        # turn collided on the same microsecond and `_load_history`
        # could return them in arbitrary order — see [[project_llm_model]].
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    await db.flush()
    return msg


async def _persist_tool_result(
    db: AsyncSession,
    session: AgentSession,
    *,
    tool_call_id: str,
    tool_name: str,
    tool_result: dict[str, Any],
) -> AgentMessage:
    msg = AgentMessage(
        session_id=session.id,
        role=AgentMessageRole.tool,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_result=tool_result,
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    await db.flush()
    return msg


async def _persist_assistant_text(
    db: AsyncSession,
    session: AgentSession,
    *,
    content: str,
    input_tokens: int,
    output_tokens: int,
) -> AgentMessage:
    msg = AgentMessage(
        session_id=session.id,
        role=AgentMessageRole.assistant,
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    await db.flush()
    return msg


async def run_turn(
    db: AsyncSession,
    session: AgentSession,
) -> list[AgentMessage]:
    """Run the tool-calling loop until the model emits a final reply.

    Returns the list of new messages persisted during this turn (assistant
    + tool messages, in chronological order).
    """
    import time as _time

    if not settings.together_api_key:
        raise OrchestratorError("TOGETHER_API_KEY is not configured")

    # Multi-tool turns chained with image vision can occasionally push past
    # the SDK's default 60s timeout; 120s leaves headroom without making
    # genuine hangs invisible.
    client = AsyncTogether(
        api_key=settings.together_api_key,
        timeout=120.0,
    )
    new_messages: list[AgentMessage] = []
    tools_schema = _registered_tools()
    turn_started = _time.monotonic()
    # Memo of (tool_name, args_json) we have already executed in this turn.
    # Some LLMs occasionally re-emit the same tool call after seeing the
    # result; we short-circuit that so the model does not waste a round
    # trip on a duplicate.
    seen_tool_calls: dict[tuple[str, str], dict[str, Any]] = {}

    for iteration in range(MAX_TOOL_ITERATIONS):
        history = await _load_history(db, session.id)
        llm_messages = _to_llm_messages(history, session=session)

        llm_started = _time.monotonic()
        active_model = session.model or settings.together_agent_model
        # gpt-oss models default to medium reasoning effort, which burns
        # 30k+ hidden thinking tokens per turn (a tool-using turn ballooned
        # from ~2s to 160s+). Force low effort for any gpt-oss variant so
        # the agent stays interactive. Passed via extra_body so the
        # Together SDK forwards it verbatim.
        extra_body: dict[str, Any] = {}
        if "gpt-oss" in active_model:
            extra_body["reasoning_effort"] = "low"
        try:
            response = await client.chat.completions.create(
                model=active_model,
                messages=llm_messages,
                tools=tools_schema if tools_schema else None,
                tool_choice="auto" if tools_schema else None,
                temperature=0.3,
                max_tokens=4096,
                extra_body=extra_body or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM call failed at iter=%d: %s",
                iteration,
                exc,
            )
            fallback_msg = await _persist_assistant_text(
                db,
                session,
                content=(
                    f"The model call failed ({type(exc).__name__}). "
                    "Please resend your last message."
                ),
                input_tokens=0,
                output_tokens=0,
            )
            new_messages.append(fallback_msg)
            return new_messages

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        session.total_input_tokens += input_tokens
        session.total_output_tokens += output_tokens

        message = choice.message
        tool_calls = getattr(message, "tool_calls", None) or []
        content = getattr(message, "content", None)
        # Some Together AI models surface final answers in
        # `message.reasoning` instead of `message.content` — when there
        # are no tool calls the reasoning field IS the user-facing
        # reply, not internal thinking. Keep the fallback in place so
        # the orchestrator stays model-agnostic.
        if not tool_calls and not content:
            reasoning_text = getattr(message, "reasoning", None)
            if reasoning_text:
                content = reasoning_text
        # LLMs occasionally derail into a hallucination loop — 10-100k
        # of the same character (`ooooo…`), sometimes laced with NUL
        # bytes that crash the Postgres insert. Strip the NULs, detect
        # the run-on character pattern, and clamp any remaining absurdly
        # long reply before it reaches the DB or the UI.
        if content:
            if "\x00" in content:
                content = content.replace("\x00", "")
            # Catch a run of 30+ identical characters (the classic
            # `ooooo…` failure) and cut everything from that point on.
            import re as _re
            _runaway = _re.search(r"(.)\1{29,}", content)
            if _runaway:
                content = content[: _runaway.start()].rstrip()
                if content:
                    content += "\n\n…(model output truncated — please rephrase your question)"
                else:
                    content = (
                        "The model output became unstable mid-response. "
                        "Please resend your last message or rephrase it."
                    )
            if len(content) > 8000:
                content = content[:8000] + "\n\n…(truncated)"
        finish_reason = getattr(choice, "finish_reason", None)

        llm_seconds = _time.monotonic() - llm_started
        logger.warning(
            "[TURN] iter=%d llm=%.2fs total=%.2fs finish=%s tool_calls=%d "
            "content=%d in=%d out=%d",
            iteration,
            llm_seconds,
            _time.monotonic() - turn_started,
            finish_reason,
            len(tool_calls),
            len(content or ""),
            input_tokens,
            output_tokens,
        )

        if not tool_calls:
            if not content:
                logger.warning(
                    "LLM produced empty content with no tool calls "
                    "(iter=%d, finish_reason=%s)",
                    iteration,
                    finish_reason,
                )
                content = (
                    "I returned an empty response. Please resend your "
                    "last message or rephrase it."
                )
            final = await _persist_assistant_text(
                db,
                session,
                content=content or "",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            new_messages.append(final)
            return new_messages

        # The model emitted one or more tool calls. Persist each call as a
        # separate assistant message (single tool_call per row keeps the
        # schema simple) and run the tool.
        for call in tool_calls:
            try:
                tool_args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                logger.warning("Tool args JSON decode failed: %s", exc)
                tool_args = {}

            assistant_msg = await _persist_assistant_with_tool_call(
                db,
                session,
                tool_call_id=call.id,
                tool_name=call.function.name,
                tool_arguments=tool_args,
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            new_messages.append(assistant_msg)

            tool = TOOL_REGISTRY.get(call.function.name)
            tool_started = _time.monotonic()
            dedupe_key = (
                call.function.name,
                json.dumps(tool_args, sort_keys=True, default=str),
            )
            if dedupe_key in seen_tool_calls:
                # Re-feed the cached result; surface a hint so the model
                # stops asking and answers the user.
                cached = seen_tool_calls[dedupe_key]
                tool_result = {
                    "duplicate_call": True,
                    "note": (
                        "This tool was already called with the same "
                        "arguments earlier in this turn. Use the prior "
                        "result and answer the user; do not call this "
                        "tool again."
                    ),
                    "previous_result": cached,
                }
            elif tool is None:
                tool_result: dict[str, Any] = {
                    "error": f"Unknown tool: {call.function.name}"
                }
            else:
                try:
                    tool_result = await tool.execute(tool_args)
                except ToolError as exc:
                    tool_result = {"error": str(exc)}
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Tool %s crashed", call.function.name)
                    tool_result = {"error": f"Tool crashed: {exc}"}
                seen_tool_calls[dedupe_key] = tool_result
            logger.warning(
                "[TOOL] %s took %.2fs (cached=%s)",
                call.function.name,
                _time.monotonic() - tool_started,
                dedupe_key in seen_tool_calls
                and "previous_result" in tool_result,
            )

            tool_msg = await _persist_tool_result(
                db,
                session,
                tool_call_id=call.id,
                tool_name=call.function.name,
                tool_result=tool_result,
            )
            new_messages.append(tool_msg)

            # Token attribution: only attribute the LLM input/output once
            # per round trip — already done on the assistant message above.
            input_tokens = 0
            output_tokens = 0

        # Loop continues: feed the tool result(s) back into the model.

    # We've burned the iteration budget without the model emitting a
    # plain text answer. Persist a graceful assistant message so the
    # user sees the failure (and so the user message + every tool call
    # we already wrote is committed alongside it) instead of raising
    # and rolling the whole turn back.
    logger.warning(
        "Hit MAX_TOOL_ITERATIONS=%d for session %s",
        MAX_TOOL_ITERATIONS,
        session.id,
    )
    fallback = await _persist_assistant_text(
        db,
        session,
        content=(
            "I could not complete this turn within the tool iteration "
            "budget. Some tool calls returned errors or behaved "
            "unexpectedly. Please check the steps above and either "
            "summarize the situation in your own words or send a new "
            "message to redirect."
        ),
        input_tokens=0,
        output_tokens=0,
    )
    new_messages.append(fallback)
    return new_messages
