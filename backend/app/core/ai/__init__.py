# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared AI primitives used by multiple business modules.

Currently exposes:

* :mod:`app.core.ai.pricing` - per-1k-token USD cost table + helper for
  estimating spend from observed token counts. Used by both
  ``clash_ai_triage`` and ``ai`` (estimate jobs) so per-tenant cost
  rollups stay comparable across modules.
"""

from app.core.ai.pricing import (
    DEFAULT_COST_PER_1K,
    MODEL_COSTS,
    estimate_cost_usd,
)

__all__ = [
    "DEFAULT_COST_PER_1K",
    "MODEL_COSTS",
    "estimate_cost_usd",
]
