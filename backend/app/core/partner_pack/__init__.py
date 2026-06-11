"""Partner-pack system - Shape A (preset bundles).

A partner pack is a separate pip-installable Python package that registers
itself via an ``importlib.metadata`` entry-point in the group
``openconstructionerp.partner_packs``. At boot, the core scans for installed
packs, picks one (or none) based on env var ``OE_PARTNER_PACK`` or the
first registered entry, and applies its preset: branding, default locale,
CWICR region preloads, validation rule packs, onboarding script.

Packs cannot ship new Python modules (that needs Shape B / multi-tenancy
refactor). They are pure *configuration* layered on top of the existing
core. Co-branding is the contract: every UI surface shows
``Powered by OpenConstructionERP · In partnership with <Partner>``.

Public API:
    discover_packs() -> list[PartnerPackManifest]
    get_active_pack() -> PartnerPackManifest | None
    apply_pack(manifest) -> None
"""

from app.core.partner_pack.discovery import (
    discover_packs,
    get_active_pack,
    get_pack_by_slug,
)
from app.core.partner_pack.manifest import PackType, PartnerPackManifest

__all__ = [
    "discover_packs",
    "get_active_pack",
    "get_pack_by_slug",
    "PackType",
    "PartnerPackManifest",
]
