"""Public partner API — answer-only Q&A surface over EtornieGPT.

A trusted external platform (same Etornie product family) reaches our more
advanced EtornieGPT here, server-to-server, for question/answer only. There
are no agent actions (no filings, attestations, payments) and no x402 — just
ask a question, get an answer. Access is gated by an API key, not a user JWT.
"""
