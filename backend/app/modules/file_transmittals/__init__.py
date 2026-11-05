# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Transmittals module (Wave W7).

A transmittal is a formal record of "I sent these files to these
parties on this date for this reason." It auto-generates a PDF (or,
when ``reportlab`` is unavailable, a structured plain-text TXT) cover
sheet so the audit trail is permanent even after the underlying file
is renamed, superseded, or deleted.

Persisted entities
------------------
* :class:`Transmittal` (``oe_file_transmittal``)
* :class:`TransmittalItem` (``oe_file_transmittal_item``)
* :class:`TransmittalRecipient` (``oe_file_transmittal_recipient``)

Snapshots
---------
Each item snapshots ``canonical_name`` + ``file_version_snapshot`` at
send time so a later rename in the source module does not break the
historical record. Recipients carry single-use ``acknowledge_token``
values minted at send time; the public ACK endpoint matches by token
and flips ``acknowledged_at``.
"""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions."""
    from app.modules.file_transmittals.permissions import (
        register_file_transmittal_permissions,
    )

    register_file_transmittal_permissions()

    from app.modules.file_transmittals.validators import register_file_transmittals_validation_rules

    register_file_transmittals_validation_rules()
