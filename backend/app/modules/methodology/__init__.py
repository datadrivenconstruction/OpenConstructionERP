# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimating-methodology module.

Houses the data-driven per-country estimating methodology engine. The pure
markup-cascade math core lives in :mod:`.cascade` and depends only on the
standard library so it can be unit-tested standalone on Python 3.11.
"""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions."""
    from app.modules.methodology.permissions import (
        register_methodology_permissions,
    )

    register_methodology_permissions()
    from app.modules.methodology.validators import register_methodology_validation_rules

    register_methodology_validation_rules()
