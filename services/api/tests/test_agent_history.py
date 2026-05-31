"""Unit tests for the EtornieGPT orchestrator history sanitiser.

Pure-function tests (no DB, no LLM): build in-memory AgentMessage rows and
assert _to_llm_messages always produces a well-formed, bounded transcript.
This is the regression guard for the "works for a fresh account, fails for the
owner" bug: an orphaned tool message (Together 400) and unbounded history
replay (context overflow).
"""
import json
import uuid

from app.agent.models import AgentMessage, AgentMessageRole, AgentSession
from app.agent.orchestrator import (
    MAX_CONTEXT_CHARS,
    OLD_TOOL_RESULT_CHARS,
    _to_llm_messages,
)


def _session() -> AgentSession:
    s = AgentSession()
    s.id = uuid.uuid4()
    s.user_id = uuid.uuid4()
    return s


def _user(content: str) -> AgentMessage:
    return AgentMessage(role=AgentMessageRole.user, content=content)


def _assistant_tool_call(
    call_id: str, name: str, args: dict | None = None, content: str | None = None
) -> AgentMessage:
    return AgentMessage(
        role=AgentMessageRole.assistant,
        content=content,
        tool_call_id=call_id,
        tool_name=name,
        tool_arguments=args or {},
    )


def _tool_result(call_id: str, name: str, result: dict) -> AgentMessage:
    return AgentMessage(
        role=AgentMessageRole.tool,
        tool_call_id=call_id,
        tool_name=name,
        tool_result=result,
    )


def _assistant_text(content: str) -> AgentMessage:
    return AgentMessage(role=AgentMessageRole.assistant, content=content)


def _assert_well_formed(msgs: list[dict]) -> None:
    """Together's pairing invariant: every tool message is immediately
    preceded by an assistant whose tool_calls include its tool_call_id, and no
    assistant tool_call is left unanswered. The transcript starts with the
    system message and never with a tool message."""
    assert msgs[0]["role"] == "system"
    assert msgs[0]["role"] != "tool"
    for i, m in enumerate(msgs):
        if m["role"] == "tool":
            assert i > 0
            prev = msgs[i - 1]
            assert prev["role"] == "assistant"
            ids = {tc["id"] for tc in prev.get("tool_calls", [])}
            assert m["tool_call_id"] in ids
        if m["role"] == "assistant" and m.get("tool_calls"):
            assert i + 1 < len(msgs), "dangling assistant tool_call at end"
            nxt = msgs[i + 1]
            assert nxt["role"] == "tool"
            ids = {tc["id"] for tc in m["tool_calls"]}
            assert nxt["tool_call_id"] in ids


class TestToLlmMessages:
    def test_valid_pair_is_preserved(self) -> None:
        history = [
            _user("file a trademark"),
            _assistant_tool_call("call_1", "trademark_search", {"q": "x"}, content="searching"),
            _tool_result("call_1", "trademark_search", {"hits": 3}),
            _assistant_text("Found 3 hits."),
        ]
        msgs = _to_llm_messages(history, session=_session())
        _assert_well_formed(msgs)
        assert [m["role"] for m in msgs] == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant",
        ]

    def test_orphan_tool_without_assistant_is_dropped(self) -> None:
        history = [
            _user("hi"),
            _tool_result("call_x", "trademark_search", {"hits": 1}),  # orphan
            _assistant_text("Hello!"),
        ]
        msgs = _to_llm_messages(history, session=_session())
        _assert_well_formed(msgs)
        assert all(m["role"] != "tool" for m in msgs)

    def test_dangling_assistant_tool_call_with_text_is_demoted(self) -> None:
        history = [
            _user("hi"),
            _assistant_tool_call("call_1", "trademark_search", {}, content="working on it"),
            _user("are you there?"),  # no tool result for call_1
        ]
        msgs = _to_llm_messages(history, session=_session())
        _assert_well_formed(msgs)
        assert all(
            not m.get("tool_calls") for m in msgs if m["role"] == "assistant"
        )

    def test_dangling_assistant_tool_call_without_text_is_dropped(self) -> None:
        history = [
            _user("hi"),
            _assistant_tool_call("call_1", "trademark_search", {}, content=None),
            _user("hello?"),
        ]
        msgs = _to_llm_messages(history, session=_session())
        _assert_well_formed(msgs)
        assert [m["role"] for m in msgs] == ["system", "user", "user"]

    def test_large_history_is_capped_and_keeps_last_user(self) -> None:
        big = {"blob": "z" * 5000}
        history = [_user("start")]
        for k in range(40):
            cid = f"call_{k}"
            history.append(
                _assistant_tool_call(cid, "get_case_by_number", {"n": k})
            )
            history.append(_tool_result(cid, "get_case_by_number", big))
        history.append(_user("final question"))

        msgs = _to_llm_messages(history, session=_session())
        _assert_well_formed(msgs)
        # The current user message always survives the windowing.
        assert any(
            m["role"] == "user" and m["content"] == "final question" for m in msgs
        )
        # Total size is bounded far below the untrimmed ~200k chars.
        total = sum(len(json.dumps(m)) for m in msgs)
        assert total <= MAX_CONTEXT_CHARS + 5000

    def test_old_tool_results_are_trimmed(self) -> None:
        big = {"blob": "z" * 4000}
        history = [_user("start")]
        for k in range(12):
            cid = f"call_{k}"
            history.append(_assistant_tool_call(cid, "trademark_search", {"n": k}))
            history.append(_tool_result(cid, "trademark_search", big))
        history.append(_user("done"))

        msgs = _to_llm_messages(history, session=_session())
        _assert_well_formed(msgs)
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        # The oldest tool results are trimmed to the OLD cap.
        assert any(
            len(m["content"]) <= OLD_TOOL_RESULT_CHARS + 40 for m in tool_msgs
        )
