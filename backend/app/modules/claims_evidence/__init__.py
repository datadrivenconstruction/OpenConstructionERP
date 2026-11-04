# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Claims / dispute evidence-pack assembly module.

This module assembles a deterministic, ordered evidence pack for a claim,
dispute or variation from heterogeneous source records - timeline entries,
correspondence, notices, requests for information, approvals, variation
records and delay analyses.

The assembly engine in :mod:`evidence_pack` is intentionally pure: it depends
on the Python standard library alone and imports nothing from the ORM, the
database engine, FastAPI or the rest of the app. That keeps the ordering,
grouping and digest logic a set of pure functions that can be unit-tested in
isolation (and on the local Python 3.11 runner), while the service and router
layers that read source rows off the database and assemble the pack sit on top.

A pack is a stable, content-addressable artifact: feeding the same set of
source entries in any input order yields byte-identical section ordering and
the same content digest, so two parties can independently reproduce and verify
the bundle that backs a claim.

The module loader discovers and mounts the ``router`` submodule at
``/api/v1/claims-evidence`` and calls :func:`on_startup` once at boot. This
``__init__`` deliberately does not import the router at top level so the pure
engine remains importable without the database / framework stack.
"""

__all__ = ["on_startup"]


async def on_startup() -> None:
    """Module startup hook - register the module's permissions."""
    from app.modules.claims_evidence.permissions import (
        register_claims_evidence_permissions,
    )

    register_claims_evidence_permissions()
    from app.modules.claims_evidence.validators import register_claims_evidence_validation_rules

    register_claims_evidence_validation_rules()
