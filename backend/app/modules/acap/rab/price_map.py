# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Reconciliation layer: AHSP resource  ->  Batam price row.

The seeded AHSP coefficients (Phase 1, from SNI) and the scraped Batam prices
(Phase 2) use DIFFERENT vocabularies, so a naive (tipe, nama) == (item_type,
item_name) match finds nothing and every RAB line falls to PRICE_MISSING. This
module is the curated bridge, and it reconciles THREE divergences:

  1. item_type  — AHSP {bahan, tenaga, alat}  vs  price {material, upah_harian,
     upah_borongan}.
  2. item_name  — AHSP "Semen portland" / "kepala_tukang"  vs  price
     "Semen (50 kg)" / "Kepala Tukang".
  3. UNIT       — the money-critical one. An AHSP koefisien is per its own unit
     (semen in kg, pasir in m3, labour in OH); the price row may be quoted per a
     DIFFERENT unit (semen per 50-kg sak). ``unit_factor`` converts the price's
     unit to the koefisien's unit:  rate += koef * price * unit_factor.
     For semen: koef is per-kg, price is per-50kg-sak  ->  factor = 1/50.

Design: this is an OVERRIDE layer. A resource NOT listed here falls back to a
direct (tipe, nama) match with factor 1 — so controlled/test data and any future
resource whose names already line up keep working unchanged.

``curated_rate`` is a transparent, code-reviewed fallback for a resource that has
NO market price in the scraped Batam set (only ``mandor`` today — arsiteqi did
not publish it). It is applied ONLY when the price lookup misses, and every use
is surfaced in the RAB result's ``curated_resources`` so it is never mistaken for
a scraped market price. All other numbers remain 100% market-sourced.

Every entry below is a real cost decision pending the user's sign-off (esp. the
"Bata merah" per-piece price, which reads high, and the mandor curated rate).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PriceRef:
    """Where (and how) to price one AHSP resource from the Batam price table."""

    item_type: str  # MaterialPrice.item_type to query
    item_name: str  # MaterialPrice.item_name to query (exact, case-insensitive)
    unit_factor: Decimal = Decimal(1)  # price-unit -> koef-unit conversion
    curated_rate: Decimal | None = None  # fallback ONLY if no price row matches


# Keyed by (AHSP AhspResource.tipe, AHSP AhspResource.nama).
RESOURCE_ALIAS: dict[tuple[str, str], PriceRef] = {
    # ── Materials (AHSP "bahan" -> price "material") ────────────────────────
    # Bata merah: koef in buah, price quoted per buah. FLAG: 1000-2600/pc reads
    # high for Batam retail; sanity-check the source before pilot.
    ("bahan", "Bata merah"): PriceRef("material", "Bata merah"),
    # Semen: koef in kg, price per 50-kg sak -> divide by 50.
    ("bahan", "Semen portland"): PriceRef("material", "Semen (50 kg)", Decimal(1) / Decimal(50)),
    # Pasir pasang (masonry sand): koef in m3, generic "Pasir m3" per m3.
    ("bahan", "Pasir pasang"): PriceRef("material", "Pasir m³"),
    # ── Labour (AHSP "tenaga" -> price "upah_harian", per orang/hari = OH) ──
    ("tenaga", "pekerja"): PriceRef("upah_harian", "Pembantu Tukang"),
    ("tenaga", "tukang_batu"): PriceRef("upah_harian", "Tukang Batu"),
    ("tenaga", "kepala_tukang"): PriceRef("upah_harian", "Kepala Tukang"),
    # Mandor: NOT in the scraped set -> curated fallback (supervisory rate,
    # ~ kepala tukang level). Every use is reported as curated, not market.
    ("tenaga", "mandor"): PriceRef("upah_harian", "Mandor", curated_rate=Decimal("180000")),
}


def resolve_price_ref(tipe: str, nama: str) -> PriceRef:
    """Return the curated :class:`PriceRef` for a resource, or a direct-match
    fallback (item_type=tipe, item_name=nama, factor 1) when it is not aliased."""
    ref = RESOURCE_ALIAS.get((tipe, nama))
    if ref is not None:
        return ref
    return PriceRef(item_type=tipe, item_name=nama)
