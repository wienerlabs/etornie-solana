# ADR-0004: Agent orchestrator LLM = Llama-3.3-70B-Instruct-Turbo

- **Status:** Accepted
- **Date:** 2026-05-20
- **Deciders:** Etornie engineering
- **Reference:** code comment in [`app/config.py`](../../services/api/app/config.py)

## Context

EtornieGPT's agent orchestrator is a chat-first surface that drives a
multi-tool filing flow. It needs reliable **structured tool-calling**
and sub-10s latency per turn. We evaluated several models on Together
AI against a realistic ~16-tool prompt.

Findings:
- `moonshotai/Kimi-K2.5` — reasoning model, 60–180s per turn. Too slow
  for an interactive agent.
- `openai/gpt-oss-120b` — its "harmony" channels leak as plain text on
  Together's serving: the model emits `assistant…commentary
  to=functions.X json{…}` as message *content* instead of structured
  `tool_calls`, then hallucinates the tool result. Unusable as the
  primary agent today.
- `meta-llama/Llama-3.3-70B-Instruct-Turbo` — Meta-native function
  calling, ~3–6s on tool-using turns, no harmony leaks.

## Decision

We will use `meta-llama/Llama-3.3-70B-Instruct-Turbo` as the agent
orchestrator (`together_agent_model`) and session-title model. Vision
document intake uses a separate model
(`meta-llama/Llama-4-Scout-17B-16E-Instruct`) because the orchestrator
model is text-only. RAG embeddings use
`intfloat/multilingual-e5-large-instruct`.

## Consequences

- Reliable structured tool-calls and acceptable latency for the
  interactive flow.
- Model choice is config-driven (`together_*` settings), so swapping is
  a config change — but any candidate must be re-validated on a
  tool-heavy prompt for harmony-style leakage before adoption.
- We are coupled to Together AI's serving behaviour; the gpt-oss leak is
  a serving-side issue to re-check if we reconsider that model.
