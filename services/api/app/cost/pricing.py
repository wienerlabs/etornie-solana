"""Per-model token pricing.

Numbers are sourced from each provider's published pricing page and
expressed as USD per 1M input tokens / 1M output tokens. Keeping the
table in code (instead of a DB row) makes the cost calculation
deterministic and easy to audit; a price change ships as a code
change reviewed alongside the model swap.

When the orchestrator picks a model that isn't listed here we fall
back to ``DEFAULT_RATE`` so the admin cost dashboard still gets a
reasonable estimate instead of returning zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final


@dataclass(frozen=True)
class ModelRate:
    """Per-1M-token rates in USD.

    ``input`` is the prompt cost (system + history + new user
    message). ``output`` is the completion cost. The agent
    orchestrator records both ``total_input_tokens`` and
    ``total_output_tokens`` on ``AgentSession`` so the cost helper
    can multiply directly.
    """

    input_per_million: Decimal
    output_per_million: Decimal


# Source: together.ai pricing as of 2026-05 (manual update on each
# provider price change). USD per 1M tokens.
TOGETHER_PRICING: Final[dict[str, ModelRate]] = {
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": ModelRate(
        input_per_million=Decimal("0.88"),
        output_per_million=Decimal("0.88"),
    ),
    "meta-llama/Llama-3.3-70B-Instruct": ModelRate(
        input_per_million=Decimal("0.88"),
        output_per_million=Decimal("0.88"),
    ),
    "meta-llama/Llama-4-Scout-17B-16E-Instruct": ModelRate(
        input_per_million=Decimal("0.18"),
        output_per_million=Decimal("0.59"),
    ),
    "openai/gpt-oss-120b": ModelRate(
        input_per_million=Decimal("0.15"),
        output_per_million=Decimal("0.60"),
    ),
    "openai/gpt-oss-20b": ModelRate(
        input_per_million=Decimal("0.05"),
        output_per_million=Decimal("0.20"),
    ),
}


# Fallback when the model name does not match an entry above. Set to
# the median of the live entries so an unknown model neither
# over-counts nor zeroes the cost.
DEFAULT_RATE: Final[ModelRate] = ModelRate(
    input_per_million=Decimal("0.50"),
    output_per_million=Decimal("0.70"),
)


def rate_for_model(model_name: str | None) -> ModelRate:
    """Return the rate row for ``model_name``, or DEFAULT_RATE.

    Case-insensitive match — Together AI is inconsistent about
    case in the model field on its responses.
    """
    if not model_name:
        return DEFAULT_RATE
    normalised = model_name.strip()
    if normalised in TOGETHER_PRICING:
        return TOGETHER_PRICING[normalised]
    folded = normalised.casefold()
    for key, rate in TOGETHER_PRICING.items():
        if key.casefold() == folded:
            return rate
    return DEFAULT_RATE


def compute_cost_usd(
    *,
    model_name: str | None,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Return the estimated cost for one (model, in_tok, out_tok) row."""
    rate = rate_for_model(model_name)
    million = Decimal(1_000_000)
    return (
        (Decimal(input_tokens) / million) * rate.input_per_million
        + (Decimal(output_tokens) / million) * rate.output_per_million
    )
