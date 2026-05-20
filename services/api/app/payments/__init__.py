"""Payment provider integrations (Stripe, etc.).

The x402 / Solana flow lives in ``app/agent/tools/prepare_payment.py``
and the chain-specific code under ``app/solana/``. This package hosts
the off-chain providers (Stripe today; nowpayments / coinbase commerce
later) behind a shared ``PaymentIntent`` table.
"""
