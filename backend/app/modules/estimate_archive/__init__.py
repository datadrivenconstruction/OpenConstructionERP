# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed original estimate: frozen, fingerprinted, opened only with a record.

The estimate behind the tendered rates is copied into an append-only seal with
a SHA-256 fingerprint. Internal estimating and management roles may read it,
every read logged; a counterparty sees it only inside a recorded opening.
Changes are priced from the sealed resource lines and markup stack, side by
side with cost plus; a person records which method applies.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.estimate_archive.permissions import register_estimate_archive_permissions
    from app.modules.estimate_archive.validators import register_estimate_archive_rules

    register_estimate_archive_permissions()
    register_estimate_archive_rules()
