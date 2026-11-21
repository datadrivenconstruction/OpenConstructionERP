# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the funding module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Duty, Entity, External, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.funding",
    roles=(
        "project_manager",
        "accountant",
        "client",
    ),
    duties=(
        Duty("project_manager", "data_paths.duty.funding.project_manager"),
        Duty("accountant", "data_paths.duty.funding.accountant"),
        Duty("client", "data_paths.duty.funding.client"),
    ),
    external=(External("party", "data_paths.external.funding_body"),),
    entities=(
        Entity("FundingApplication", label="data_paths.entity.funding_application", route="/funding"),
        Entity("FundingDisbursement", label="data_paths.entity.funding_disbursement", route="/funding"),
        Entity("FundingObligation", label="data_paths.entity.funding_obligation", route="/funding"),
    ),
    inputs=(
        DataPath(
            "oe_boq",
            "FundingApplication",
            via="FundingApplication.linked_estimate_id",
            label="data_paths.entity.boq",
            where=(Where("linked_estimate_id", "not_null"),),
        ),
        DataPath(
            "oe_schedule",
            "FundingApplication",
            via="FundingApplication.linked_schedule_id",
            label="data_paths.entity.schedule",
            where=(Where("linked_schedule_id", "not_null"),),
        ),
    ),
)
