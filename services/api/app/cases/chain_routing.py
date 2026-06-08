"""Per-case cross-chain routing policy (#73).

Decides which chain(s) a case's on-chain artefacts target: Solana
(default), Moca (opt-in), or both. Solana is the live path; Moca is
gated behind ``settings.moca_enabled`` — until that is true, a case
routed to Moca is recorded with ``moca_status = pending`` (its intent is
captured, but nothing is faked on Moca).
"""
from __future__ import annotations

from app.cases.models import Case, ChainRouting, MocaStatus
from app.config import settings


def default_routing() -> ChainRouting:
    """The system default routing for new cases."""

    try:
        return ChainRouting(settings.default_chain_routing)
    except ValueError:
        return ChainRouting.solana


def resolve_routing(routing: ChainRouting | str | None) -> ChainRouting:
    """Resolve an explicit routing value, falling back to the default."""

    if routing is None:
        return default_routing()
    if isinstance(routing, ChainRouting):
        return routing
    try:
        return ChainRouting(routing)
    except ValueError:
        return default_routing()


def wants_solana(routing: ChainRouting) -> bool:
    return routing in (ChainRouting.solana, ChainRouting.both)


def wants_moca(routing: ChainRouting) -> bool:
    return routing in (ChainRouting.moca, ChainRouting.both)


def initial_moca_status(routing: ChainRouting) -> MocaStatus:
    """The Moca status a freshly-routed case should start in.

    Routed to Moca but the integration isn't live yet → pending. Once
    ``moca_enabled`` is true the Moca writer flips it to written/failed.
    """

    if not wants_moca(routing):
        return MocaStatus.not_routed
    return MocaStatus.pending


def apply_routing(case: Case, routing: ChainRouting | str | None) -> None:
    """Stamp a case's routing + derived Moca status in one place."""

    resolved = resolve_routing(routing)
    case.chain_routing = resolved
    case.moca_status = initial_moca_status(resolved)
