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
name-direct match with factor 1, its bucket translated via ``_TIPE_TO_ITEM_TYPE``
(bahan->material, tenaga->upah_harian) — so any resource whose name already lines
up with a real price row resolves without an explicit alias.

``curated_rate`` is a transparent, code-reviewed fallback for a resource that has
NO market price in the scraped Batam set. As of the 2026-07-09 full-house wiring
pass, a real "Mandor" upah_harian row now exists, so no entry currently carries a
``curated_rate`` — the field stays supported for the next resource that ships
without a market price. It is applied ONLY when the price lookup misses, and
every use is surfaced in the RAB result's ``curated_resources`` so it is never
mistaken for a scraped market price. All other numbers remain 100% market-sourced.

Every entry below is a real cost decision pending the user's sign-off (esp. the
"Bata merah" per-piece price, which reads high).
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
    # Mandor: a real "Mandor" upah_harian row now exists in the scraped set,
    # so the curated fallback is dropped -> fully market-sourced like every
    # other trade.
    ("tenaga", "mandor"): PriceRef("upah_harian", "Mandor"),

    # ── Full-house wiring additions (struktur praktis, finishing, bukaan,
    # sanitair, MEP, atap) — see docs/plans/2026-07-09-rab-full-wiring-spec.md
    # §1. Every unit_factor below is a fixed reviewer decision; copied
    # verbatim, never re-derived.
    # -- Materials (AHSP "bahan" -> price "material") --------------------
    ("bahan", "Besi beton"): PriceRef("material", "Besi beton 10 mm", Decimal(1) / Decimal("7.4")),
    ("bahan", "Kawat beton"): PriceRef("material", "Kawat beton"),
    ("bahan", "Semen warna"): PriceRef("material", "Semen putih", Decimal(1) / Decimal(50)),
    ("bahan", "Pasir beton"): PriceRef("material", "Pasir beton"),
    ("bahan", "Kerikil"): PriceRef("material", "Kerikil"),
    # NOTE the price name uses U+00D7 (×), not the ASCII letter "x".
    ("bahan", "Keramik lantai 40x40"): PriceRef("material", "Keramik Lantai 40×40", Decimal(1) / Decimal(6)),
    # ASSUMPTION: dus = 25 pc for 10x20 wall tile.
    ("bahan", "Keramik dinding 10x20"): PriceRef("material", "Keramik dinding", Decimal(1) / Decimal(25)),
    ("bahan", "Gypsum board 9mm"): PriceRef("material", "Gypsum board 9mm"),
    ("bahan", "Paku sekrup"): PriceRef("material", "Paku biasa"),
    ("bahan", "Besi hollow 40x40"): PriceRef("material", "Rangka hollow", Decimal(1) / Decimal(4)),
    ("bahan", "Baja ringan C75"): PriceRef("material", "Baja ringan kanal C75"),
    ("bahan", "Seng gelombang"): PriceRef("material", "Seng gelombang"),
    ("bahan", "Seng pelat"): PriceRef("material", "Seng pelat"),
    ("bahan", "Genteng beton"): PriceRef("material", "Genteng beton"),
    ("bahan", "Kaca polos 5 mm"): PriceRef("material", "Kaca 5 mm"),
    ("bahan", "Kabel NYM 3x2.5 mm2"): PriceRef("material", "Kabel NYM 3x2.5 mm2"),
    ("bahan", "Cat dasar"): PriceRef("material", "Cat dasar/plamir"),
    # ASSUMPTION: kaleng (can) ~= 5 kg.
    ("bahan", "Cat penutup"): PriceRef("material", "Cat interior", Decimal(1) / Decimal(5)),
    ("bahan", "Membran bakar"): PriceRef("material", "Membran bakar"),
    ("bahan", "Cairan primer"): PriceRef("material", "Cairan primer"),
    ("bahan", "Profil aluminium 4 inch"): PriceRef("material", "Profil aluminium 4 inch"),
    ("bahan", "Pipa PVC AW 1/2 inch"): PriceRef("material", "Pipa PVC AW 1/2 inch"),
    ("bahan", "Pipa PVC D 2 inch"): PriceRef("material", "Pipa PVC D 2 inch"),
    ("bahan", "Kayu kelas III"): PriceRef("material", "Kayu kelas III"),
    ("bahan", "Papan kayu kelas III"): PriceRef("material", "Papan kayu kelas III"),
    ("bahan", "Balok kayu 6/12"): PriceRef("material", "Balok kayu 6/12"),
    ("bahan", "Balok kayu kelas II"): PriceRef("material", "Balok kayu kelas II"),
    ("bahan", "Plywood 12mm"): PriceRef("material", "Plywood 12mm"),
    ("bahan", "Dolken kayu 8-10 cm"): PriceRef("material", "Dolken kayu 8-10 cm"),
    ("bahan", "Minyak bekisting"): PriceRef("material", "Minyak bekisting"),
    ("bahan", "Lem kayu"): PriceRef("material", "Lem kayu"),
    ("bahan", "Bata roster"): PriceRef("material", "Bata roster"),
    ("bahan", "Kunci tanam biasa"): PriceRef("material", "Kunci tanam biasa"),
    ("bahan", "Engsel pintu"): PriceRef("material", "Engsel pintu"),
    ("bahan", "Kait angin"): PriceRef("material", "Kait angin"),
    ("bahan", "Kloset duduk"): PriceRef("material", "Kloset duduk"),
    ("bahan", "Kloset jongkok"): PriceRef("material", "Kloset jongkok"),
    ("bahan", "Wastafel lengkap"): PriceRef("material", "Wastafel"),
    ("bahan", "Kran air"): PriceRef("material", "Kran air"),
    ("bahan", "Floor drain"): PriceRef("material", "Floor drain"),
    ("bahan", "Saklar"): PriceRef("material", "Saklar tunggal"),
    ("bahan", "MCB box"): PriceRef("material", "MCB box"),
    ("bahan", "Pompa jet 27 lpm"): PriceRef("material", "Pompa jet 27 lpm"),
    ("bahan", "Tangki toren 0.7 m3"): PriceRef("material", "Tangki toren 0.7 m3"),
    # Paku variants -> the single scraped "Paku biasa" row.
    ("bahan", "Paku 5-10 cm"): PriceRef("material", "Paku biasa"),
    ("bahan", "Paku 5-12 cm"): PriceRef("material", "Paku biasa"),
    ("bahan", "Paku 10 cm"): PriceRef("material", "Paku biasa"),
    # Bare "Papan kayu" (pintu panel / jendela) -> the priced kelas-III board.
    ("bahan", "Papan kayu"): PriceRef("material", "Papan kayu kelas III"),
    # -- Trades (AHSP "tenaga" -> price "upah_harian") --------------------
    ("tenaga", "tukang_kayu"): PriceRef("upah_harian", "Tukang kayu"),
    ("tenaga", "tukang_besi"): PriceRef("upah_harian", "Tukang besi"),
    ("tenaga", "tukang_cat"): PriceRef("upah_harian", "Tukang cat"),
    ("tenaga", "tukang_listrik"): PriceRef("upah_harian", "Tukang listrik"),
    ("tenaga", "tukang_aluminium"): PriceRef("upah_harian", "Tukang aluminium"),
    ("tenaga", "tukang_pipa"): PriceRef("upah_harian", "Tukang pipa"),
    # Generic "tukang" priced at the batu rate.
    ("tenaga", "tukang"): PriceRef("upah_harian", "Tukang Batu"),
}


# AHSP resource `tipe` -> price-table `item_type`. The price table NEVER stores
# the AHSP vocab ("bahan"/"tenaga"/"alat") — only "material"/"upah_harian"/
# "upah_borongan" — so an unaliased resource whose *name* already lines up with a
# real row must still have its bucket translated, or it can never match.
_TIPE_TO_ITEM_TYPE = {"bahan": "material", "tenaga": "upah_harian", "alat": "material"}


def resolve_price_ref(tipe: str, nama: str) -> PriceRef:
    """Return the curated :class:`PriceRef` for a resource, or a name-direct
    fallback (item_type translated from ``tipe``, item_name=nama, factor 1) when
    it is not aliased."""
    ref = RESOURCE_ALIAS.get((tipe, nama))
    if ref is not None:
        return ref
    return PriceRef(item_type=_TIPE_TO_ITEM_TYPE.get(tipe, tipe), item_name=nama)
