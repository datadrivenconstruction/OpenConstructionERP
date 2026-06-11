# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval Routes module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_approval_routes",
    version="1.0.0",
    display_name="Approval Routes",
    description=(
        "Generic multi-step approval engine: routes (templates), steps "
        "(ordered approvers), instances (running workflows for a "
        "specific target row), step states (per-step decisions). "
        "Consumed by markup/submittal/change-order/RFI/contract modules "
        "instead of every module hard-coding its own approve/reject."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
)
