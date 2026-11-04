# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Structured unit-price breakdown (price analysis) library.

Decomposes a tender position's unit rate into the cost categories every
estimator works with anywhere in the world: labour, material, plant and
equipment, subcontract, and other, plus overhead, risk and profit markup.

This is the international core. The German EFB price sheets (221 own labour,
222 subcontract, 223 material list, from the public procurement handbook) are
one labelled presentation of the same data (see ``presets.py``); the model
itself carries no country assumptions. NRM/CESMM detailed rates, FIDIC and NEC
price breakdowns, and US bid cost breakdowns all map onto the same structure.

Pure library (manifest and validation rules, no router or tables): the domain math lives here
and stays ORM-free and Decimal-exact, exactly like the ``einvoice`` library.
"""

from app.modules.price_breakdown.mapping import from_position
from app.modules.price_breakdown.model import (
    LINE_I18N_KEYS,
    MAX_MARKUP_PCT,
    CostComponent,
    PriceBreakdown,
    PriceBreakdownError,
    ResourceKind,
    build_breakdown,
    coerce_kind,
    kind_i18n_key,
)
from app.modules.price_breakdown.presets import (
    PRESETS,
    Preset,
    efb_221_view,
    get_preset,
    preset_for_country,
    render_csv,
    render_markdown,
)

__all__ = [
    "LINE_I18N_KEYS",
    "MAX_MARKUP_PCT",
    "PRESETS",
    "CostComponent",
    "Preset",
    "PriceBreakdown",
    "PriceBreakdownError",
    "ResourceKind",
    "build_breakdown",
    "coerce_kind",
    "efb_221_view",
    "from_position",
    "get_preset",
    "preset_for_country",
    "kind_i18n_key",
    "render_csv",
    "render_markdown",
]
