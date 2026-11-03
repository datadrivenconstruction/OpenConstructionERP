"""Project-currency view of catalogue rates.

A catalogue row is priced in its own currency. A project keeps its books in
another one. This turns the question "what is that rate in my project's
currency" into a rate per source currency, resolved by the same FX context the
assemblies use (project override first, then the ``oe_fx`` register), so the two
screens cannot disagree. A currency no source can price is reported as
unpriced; the caller must show the row in its own currency only.
"""

from pydantic import BaseModel, Field

from app.modules.assemblies.fx_bridge import FxContext


class CatalogFxRate(BaseModel):
    """Multiplier from one catalogue currency into the project currency."""

    currency: str
    rate: str | None = Field(default=None, description="Project units per 1 unit of ``currency``; null if unpriced.")
    source: str = Field(default="", description="project_fx_rates | oe_fx | identity; empty when unpriced.")
    as_of: str = Field(default="", description="Rate date (ISO) when the source carries one.")
    reason: str = Field(default="", description="Why no rate: missing_currency | no_rate.")


class CatalogFxView(BaseModel):
    """Rates for the currencies present in a catalogue listing."""

    project_currency: str = ""
    rates: dict[str, CatalogFxRate] = Field(default_factory=dict)


def _clean(codes: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for raw in codes:
        code = str(raw or "").strip().upper()
        if len(code) == 3 and code.isalpha():
            seen[code] = None
    return list(seen)


def build_fx_view(context: FxContext, currencies: list[str]) -> CatalogFxView:
    """Price each catalogue currency into the project currency of ``context``."""
    target = context.project_base
    rates: dict[str, CatalogFxRate] = {}
    for code in _clean(currencies):
        if not target:
            rates[code] = CatalogFxRate(currency=code, reason="missing_currency")
            continue
        rate, provenance = context.rate(code, target)
        if rate is None:
            rates[code] = CatalogFxRate(currency=code, reason=str(provenance.get("reason") or "no_rate"))
            continue
        rates[code] = CatalogFxRate(
            currency=code,
            rate=format(rate, "f"),
            source=str(provenance.get("fx_source") or ""),
            as_of=str(provenance.get("fx_as_of") or ""),
        )
    return CatalogFxView(project_currency=target, rates=rates)
