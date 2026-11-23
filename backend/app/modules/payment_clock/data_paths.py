# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the payment_clock module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Sum, Where

DATA_PATHS = DataPaths(
    why="data_paths.why.payment_clock",
    roles=(
        "accountant",
        "contractor",
        "client",
    ),
    entities=(
        Entity(
            "StatutoryPaymentApplication",
            label="data_paths.entity.payment_application",
            route="/payment-clock",
            measure=Sum("applied_amount"),
        ),
        Entity("PaymentNotice", label="data_paths.entity.payment_notice", route="/payment-clock"),
        Entity("PaymentClockEvent", label="data_paths.entity.payment_event", route="/payment-clock"),
    ),
    inputs=(
        DataPath(
            "oe_contracts",
            "StatutoryPaymentApplication",
            via="StatutoryPaymentApplication.source_id",
            label="data_paths.entity.progress_claim",
            route="/contracts",
            where=(Where("source_type", "eq", "contracts_progress_claim"),),
            measure=Sum("applied_amount"),
            importance="high",
            breaks="data_paths.breaks.no_payment_due",
        ),
        DataPath(
            "oe_subcontractors",
            "StatutoryPaymentApplication",
            via="StatutoryPaymentApplication.source_id",
            label="data_paths.entity.sub_payment_application",
            route="/subcontractors",
            where=(Where("source_type", "eq", "subcontractors_payment_application"),),
            measure=Sum("applied_amount"),
            importance="high",
            breaks="data_paths.breaks.no_payment_due",
        ),
    ),
    parameters=(
        Param(
            "StatutoryPaymentApplication.application_date",
            drives=(
                "StatutoryPaymentApplication.due_date",
                "StatutoryPaymentApplication.final_date",
                "StatutoryPaymentApplication.pay_less_deadline",
            ),
            label="data_paths.param.application_date",
        ),
    ),
)
