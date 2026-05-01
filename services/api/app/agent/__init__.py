"""EtornieGPT agent orchestrator package.

Chat-first surface that wraps existing services (etorniegpt, EUIPO, etc.)
behind a tool-calling loop powered by Together AI's Kimi K2.5.

The legacy `etorniegpt/` and `services/euipo/` packages are intentionally
left untouched; this package consumes them via thin wrappers in
`agent/tools/`.
"""
