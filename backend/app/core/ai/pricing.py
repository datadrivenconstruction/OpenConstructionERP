# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Per-model USD cost table - shared across AI modules.

Both ``clash_ai_triage`` (verdict persistence) and ``ai`` (estimate jobs)
write ``cost_usd_estimate`` columns alongside ``tokens_used`` so per-tenant
spend rollups can pivot across modules on a single comparable unit (USD,
not provider-specific tokens). Anthropic counts tokens differently from
OpenAI, so tokens alone are not a fair comparison.

The rates are public list prices blended (input + output averaged) into
one per-1k figure so the persisted cost stays a single Numeric column
instead of a JSON breakdown - coordinators want one number for reports.

Sources (Jan 2026): Anthropic + OpenAI + Google public pricing pages.
Rounded to 4 decimals to match downstream ``Numeric(10, 4)`` precision.
Refresh this table when a provider re-prices.
"""

from __future__ import annotations

from decimal import Decimal

#: Per-1k-token USD rate by model id. Keys are the exact provider model
#: names; partial / alias matches deliberately fall through to
#: :data:`DEFAULT_COST_PER_1K` so unknown models do not get silently
#: priced at zero.
MODEL_COSTS: dict[str, Decimal] = {
    # Anthropic - Haiku 4.5 is the "cheap, fast, JSON-good" pick.
    # ~$0.80/M in, $4/M out → blended ~$0.0024/k.
    "claude-haiku-4-5-20251001": Decimal("0.0024"),
    "claude-haiku-4-5": Decimal("0.0024"),
    # Sonnet is roughly 5x - opt-in for sensitive workloads.
    "claude-sonnet-4-6": Decimal("0.0090"),
    "claude-sonnet-4-20250514": Decimal("0.0090"),
    "claude-sonnet-4": Decimal("0.0090"),
    "claude-sonnet": Decimal("0.0090"),
    # Opus - top tier reasoning, ~3x Sonnet.
    "claude-opus-4-8": Decimal("0.0300"),
    "claude-opus-4": Decimal("0.0300"),
    "claude-opus": Decimal("0.0300"),
    # OpenAI - gpt-4.1-mini comparable to Haiku.
    "gpt-4.1-mini": Decimal("0.0008"),
    "gpt-4.1": Decimal("0.0040"),
    "gpt-4o": Decimal("0.0050"),
    "gpt-4o-mini": Decimal("0.0006"),
    # Google Gemini 2.5 family - cheapest of the three big providers.
    "gemini-2.5-flash": Decimal("0.0005"),
    "gemini-2.5-pro": Decimal("0.0050"),
}

#: Conservative fallback rate when the model name is unknown. Picks the
#: lowest published mid-tier rate so unknown models don't drastically
#: under-report cost.
DEFAULT_COST_PER_1K: Decimal = Decimal("0.0020")


def estimate_cost_usd(model_name: str | None, tokens: int) -> Decimal:
    """Return the USD cost estimate for ``tokens`` charged at ``model_name``.

    Zero or negative ``tokens`` always returns ``Decimal("0.0")``. Unknown
    or empty ``model_name`` falls back to :data:`DEFAULT_COST_PER_1K`.
    Arithmetic stays in :class:`~decimal.Decimal` until the caller chooses
    a persistence type (``Numeric`` or ``Float``) so we don't lose
    sub-cent precision in the call chain.
    """
    if tokens <= 0:
        return Decimal("0.0")
    rate = MODEL_COSTS.get(model_name or "", DEFAULT_COST_PER_1K)
    return (Decimal(tokens) / Decimal(1000)) * rate


__all__ = [
    "DEFAULT_COST_PER_1K",
    "MODEL_COSTS",
    "estimate_cost_usd",
]
