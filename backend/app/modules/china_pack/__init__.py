# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""China regional pack: GB 50500 bills, VAT, 预缴 and 数电票 data."""


async def on_startup() -> None:
    """Register the ``cn_vat`` rules and the 数电票 payload builder. Idempotent."""
    from app.modules.china_pack.fapiao import DOCUMENT_FORMAT, build_from_invoice
    from app.modules.china_pack.validators import register_cn_vat_rules

    register_cn_vat_rules()
    try:
        from app.modules.einvoice_clearance.service import register_payload_builder
    except ImportError:  # clearance module not installed; the export endpoint still works
        return
    register_payload_builder(DOCUMENT_FORMAT, build_from_invoice)
