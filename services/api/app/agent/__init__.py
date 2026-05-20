"""EtornieGPT agent orchestrator package.

Chat-first surface that wraps existing services (etorniegpt, EUIPO, etc.)
behind a tool-calling loop powered by a Together AI tool-calling LLM
(see ``settings.together_agent_model``).

The legacy `etorniegpt/` and `services/euipo/` packages are intentionally
left untouched; this package consumes them via thin wrappers in
`agent/tools/`.
"""
