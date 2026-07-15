"""Schedule Intelligence module.

A thin orchestration + governance layer over ``schedule_advanced`` / ``risk`` /
``variations`` / ``contracts`` / ``full_evm``: it flags delay risk early,
attributes cause/responsibility, quantifies critical-path impact, and presents
human-approved claim-vs-accelerate decisions — with commercially-sensitive
figures locked (E5.2) and a uniform confidence framework (E5.3) gating every
insight. Applies changes only through the existing ``app/core`` approval gate;
it adds no gate of its own.

The module loader discovers this package automatically when it lives under
``backend/app/modules/schedule_intelligence/``.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions at app boot.

    Kept fast and side-effect-light; the loader awaits each module's hook in
    sequence. Governance (approval gate + audit) is reused from ``app/core`` —
    nothing new is registered here beyond this module's permission set.
    """
    from app.modules.schedule_intelligence.permissions import (
        register_schedule_intelligence_permissions,
    )

    register_schedule_intelligence_permissions()
