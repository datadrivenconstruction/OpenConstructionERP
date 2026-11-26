# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""External-review-authority (expertise cycle) module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.review_authority.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_review_authority",
    version="0.1.0",
    display_name="Review Authority",
    description=(
        "Manages the external review cycle a project runs with an approving "
        "authority - state expertise, building control, an authority having "
        "jurisdiction, or a technical review board. Tracks the submission, the "
        "document version pinned at submission, the remarks the authority "
        "issues, the responses back, and the final decision, with an SLA clock, "
        "a stale-version detector, a contestability classifier that never "
        "auto-decides a missing norm reference, and a repeat-remark radar. "
        "Jurisdiction-neutral: it models the cycle and its evidence, never a "
        "country's rulebook; regional packs supply the authority vocabularies."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
