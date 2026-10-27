# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks module.

Completed projects become benchmark records (final cost, GFA, functional units,
element groups); an estimate is compared with a filtered, normalised cohort of them.
"""

from app.modules.cost_benchmarks.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions and validation rules."""
    from app.modules.cost_benchmarks.permissions import register_cost_benchmarks_permissions
    from app.modules.cost_benchmarks.validators import register_cost_benchmarks_rules

    register_cost_benchmarks_permissions()
    register_cost_benchmarks_rules()
