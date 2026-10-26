# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule Advanced module (Last Planner System).

Implements the Last Planner System (LPS) workflow on top of the existing
schedule / tasks modules:

* MasterSchedule + PhasePlan (pull planning sessions)
* LookAheadPlan + Constraint (constraint management / make-ready)
* WeeklyWorkPlan + Commitment + ReasonForNonCompletion (weekly commitments + PPC)
* Baseline + BaselineDelta (planned vs current variance tracking)
* Calendar (working calendars for commitment validation)

This is a NEW sister module to ``oe_schedule`` and ``oe_tasks`` - it does not
modify their source.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.schedule_advanced.permissions import register_schedule_advanced_permissions

    register_schedule_advanced_permissions()
    from app.modules.schedule_advanced.lps_rules import register_lps_rules

    register_lps_rules()
