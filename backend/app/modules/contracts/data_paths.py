# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the contracts module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Sum, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.contracts",
    roles=(
        "client",
        "contractor",
        "subcontractor",
        "quantity_surveyor",
    ),
    entities=(
        Entity("Contract", label="data_paths.entity.contract", route="/contracts", measure=Sum("total_value")),
        Entity("ContractLine", label="data_paths.entity.contract_line", route="/contracts"),
        Entity(
            "ProgressClaim", label="data_paths.entity.progress_claim", route="/contracts", measure=Sum("gross_amount")
        ),
        Entity("EOTClaim", label="data_paths.entity.eot_claim", route="/contracts"),
        Entity("FinalAccount", label="data_paths.entity.final_account", route="/contracts"),
    ),
    inputs=(
        DataPath(
            "oe_tendering",
            "Contract",
            via="Contract.metadata_.tender_package_id",
            label="data_paths.entity.tender_package",
            route="/tendering",
            importance="critical",
            breaks="data_paths.breaks.no_contract_value",
            missing="data_paths.missing.no_contract_for_tender",
        ),
        DataPath(
            "oe_contacts",
            "Contract",
            via="Contract.counterparty_id",
            label="data_paths.entity.contact",
            route="/contacts",
        ),
    ),
    outputs=(
        DataPath(
            "oe_finance",
            "Invoice",
            via="Invoice.source_claim_id",
            label="data_paths.entity.invoice",
            route="/finance",
            measure=Sum("amount_total"),
            importance="critical",
            breaks="data_paths.breaks.no_invoices",
            missing="data_paths.missing.no_invoice_for_contract",
        ),
        DataPath(
            "oe_payment_clock",
            "StatutoryPaymentApplication",
            via="StatutoryPaymentApplication.source_id",
            label="data_paths.entity.payment_application",
            route="/payment-clock",
            where=(Where("source_type", "eq", "contracts_progress_claim"),),
            importance="high",
            breaks="data_paths.breaks.no_payment_due",
        ),
        DataPath(
            "oe_costmodel",
            "Contract",
            via="Contract.cost_line_id",
            label="data_paths.entity.cost_line",
            route="/cost-model",
        ),
    ),
    parameters=(
        Param(
            "Contract.retention_percent",
            drives=(
                "ProgressClaim.retention_amount",
                "ProgressClaimLine.retention_to_date",
                "oe_finance.Invoice.retention_amount",
                "oe_costmodel:cash_flow",
            ),
            label="data_paths.param.retention",
        ),
        Param(
            "Contract.retention_release_event",
            drives=("FinalAccount.retention_released",),
            label="data_paths.param.retention_release",
        ),
        Param(
            "EOTClaim.revised_completion_date",
            drives=("oe_schedule:end_date",),
            label="data_paths.param.completion_date",
        ),
    ),
)
