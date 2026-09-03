# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team Standup module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_team_standup",
    version="0.1.0",
    display_name="Team Standup",
    description=(
        "Daily standup board for the PM team - one entry per person per "
        "day (status, yesterday, today, blockers), comments on each "
        "other's updates, and a rolling open-blockers digest."
    ),
    author="Projects Team",
    category="community",
    # Projects supply the job tags on entries; tasks supply the open-work
    # lists on member cards (both bridged natively, no parallel systems).
    depends=["oe_users", "oe_projects", "oe_tasks"],
    auto_install=False,
    enabled=True,
)
