"""‌⁠‍Schedule Intelligence module manifest.

Edit the placeholders below. The ``make module-new`` target drops
this package into ``backend/app/modules/schedule_intelligence/`` (note:
short name, no ``oe_`` prefix — matches the existing core modules).
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_schedule_intelligence",
    version="0.1.0",
    display_name="Schedule Intelligence",
    description=(
        "Watch → Score → Attribute → Quantify → Decide layer that flags delay "
        "risk early, attributes cause/responsibility, quantifies critical-path "
        "impact, and presents human-approved claim-vs-accelerate decisions. "
        "Orchestrates schedule_advanced, risk, variations, contracts and evm "
        "rather than duplicating them."
    ),
    author="Leaders International",
    category="business",  # one of: core, integration, regional, community
    depends=[
        "oe_projects",
        "oe_schedule",
        "oe_schedule_advanced",
        "oe_risk",
        "oe_variations",
        "oe_contracts",
        "oe_full_evm",
    ],
    optional_depends=[
        "oe_claims_evidence",
        "oe_retrieval",
        "oe_file_search",
    ],
    auto_install=False,  # set True to enable on first boot
    enabled=True,
)
