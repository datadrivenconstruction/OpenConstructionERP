"""Idempotent seed for the property_dev house-type catalogue presets.

Mirrors the bulk_insert in migration ``v3114_propdev_house_type_catalogue``
so that the fresh-blank-DB shortcut in ``alembic/env.py`` (which calls
``Base.metadata.create_all`` and stamps head without running individual
migrations) still ends up with the country presets populated.

Idempotent: skips entirely when any preset row exists.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.property_dev.models import PropertyDevHouseType

# Country → [(code, name, description, area_typical_m2, floors_typical), ...]
_SEED_PRESETS: dict[str, list[tuple[str, str, str | None, Decimal | None, int | None]]] = {
    "DE": [
        ("HOUSE_DETACHED", "Einfamilienhaus", "Freistehendes Einfamilienhaus", Decimal("160"), 2),
        ("HOUSE_SEMI", "Doppelhaushälfte", "Halbes Haus an Brandmauer", Decimal("130"), 2),
        ("HOUSE_ROW", "Reihenhaus", "Mittelhaus oder Endhaus einer Reihe", Decimal("120"), 2),
        ("APT_FLOOR", "Etagenwohnung", "Wohnung in einem Mehrfamilienhaus", Decimal("85"), 1),
        ("APT_PENTHOUSE", "Penthouse", "Dachgeschosswohnung mit Terrasse", Decimal("140"), 1),
        ("APT_GROUND", "Erdgeschosswohnung", "Wohnung im Erdgeschoss mit Garten", Decimal("90"), 1),
    ],
    "US": [
        ("SF_HOME", "Single-family home", "Detached single-family residence", Decimal("190"), 2),
        ("TOWNHOUSE", "Townhouse", "Attached row home, individually owned", Decimal("150"), 2),
        ("CONDO", "Condo", "Condominium unit in a multi-unit building", Decimal("100"), 1),
        ("DUPLEX", "Duplex", "Two-unit building, side-by-side or stacked", Decimal("120"), 2),
        ("LOFT", "Loft", "Open-plan converted industrial / commercial unit", Decimal("110"), 1),
    ],
    "UK": [
        ("DETACHED", "Detached", "Standalone house, no shared walls", Decimal("150"), 2),
        ("SEMI", "Semi-detached", "Pair of houses sharing one party wall", Decimal("110"), 2),
        ("TERRACED", "Terraced", "House in a row sharing walls on both sides", Decimal("95"), 2),
        ("FLAT", "Flat", "Single-floor dwelling within a larger building", Decimal("70"), 1),
        ("BUNGALOW", "Bungalow", "Single-storey detached house", Decimal("100"), 1),
    ],
    "RU": [
        ("KVARTIRA", "Квартира", "Квартира в многоэтажном доме", Decimal("65"), 1),
        ("TAUNHAUS", "Таунхаус", "Блокированный дом с соседями", Decimal("140"), 2),
        ("KOTTEDZH", "Коттедж", "Отдельно стоящий загородный дом", Decimal("180"), 2),
        ("PENTHAUS", "Пентхаус", "Квартира на верхнем этаже с террасой", Decimal("150"), 1),
    ],
    "TR": [
        ("MUSTAKIL", "Müstakil ev", "Bağımsız tek aile evi", Decimal("180"), 2),
        ("DAIRE", "Daire", "Apartman dairesi", Decimal("100"), 1),
        ("VILLA", "Villa", "Bahçeli müstakil villa", Decimal("220"), 2),
        ("REZIDANS", "Rezidans", "Hizmetli lüks konut", Decimal("120"), 1),
    ],
    "FR": [
        ("MAISON", "Maison individuelle", "Maison détachée pour une famille", Decimal("140"), 2),
        ("APPARTEMENT", "Appartement", "Logement dans un immeuble", Decimal("75"), 1),
        ("VILLA", "Villa", "Maison avec jardin et prestations haut-de-gamme", Decimal("200"), 2),
        ("DUPLEX", "Duplex", "Logement sur deux niveaux", Decimal("110"), 2),
    ],
    "ES": [
        ("CASA", "Casa", "Vivienda unifamiliar", Decimal("150"), 2),
        ("PISO", "Piso", "Vivienda en bloque", Decimal("80"), 1),
        ("CHALET", "Chalet", "Vivienda unifamiliar aislada con parcela", Decimal("200"), 2),
        ("DUPLEX", "Dúplex", "Vivienda en dos plantas", Decimal("110"), 2),
    ],
    "IT": [
        ("VILLA", "Villa", "Villa unifamiliare con giardino", Decimal("220"), 2),
        ("APPARTAMENTO", "Appartamento", "Unità abitativa in condominio", Decimal("85"), 1),
        ("ATTICO", "Attico", "Appartamento all'ultimo piano con terrazzo", Decimal("130"), 1),
        ("BIFAMILIARE", "Bifamiliare", "Edificio diviso in due unità", Decimal("140"), 2),
    ],
    "PL": [
        ("DOM", "Dom jednorodzinny", "Wolnostojący dom jednorodzinny", Decimal("150"), 2),
        ("MIESZKANIE", "Mieszkanie", "Lokal mieszkalny w bloku", Decimal("60"), 1),
        ("APARTAMENT", "Apartament", "Mieszkanie o podwyższonym standardzie", Decimal("90"), 1),
    ],
    "JP": [
        ("IKKODATE", "一戸建て", "Detached single-family house", Decimal("100"), 2),
        ("MANSION", "マンション", "Reinforced-concrete condominium unit", Decimal("70"), 1),
        ("APART", "アパート", "Wood-frame low-rise rental unit", Decimal("45"), 1),
    ],
    "CN": [
        ("BIESHU", "别墅", "Standalone villa / detached house", Decimal("240"), 2),
        ("GONGYU", "公寓", "Apartment unit in a residential tower", Decimal("90"), 1),
        ("LIANPAI", "联排", "Row-style townhouse", Decimal("180"), 2),
    ],
    "SA": [
        ("VILLA", "فيلا", "Detached villa with private garden", Decimal("300"), 2),
        ("SHAQQA", "شقة", "Apartment in a residential building", Decimal("120"), 1),
        ("DOPLEX", "دوبلكس", "Two-storey duplex unit", Decimal("200"), 2),
    ],
}


def _all_preset_rows() -> Iterable[PropertyDevHouseType]:
    for country_code, presets in _SEED_PRESETS.items():
        for code, name, description, area_typical, floors in presets:
            yield PropertyDevHouseType(
                project_id=None,
                country_code=country_code,
                code=code,
                name=name,
                description=description,
                area_typical_m2=area_typical,
                floors_typical=floors,
                is_preset=True,
                created_by=None,
            )


async def seed_house_type_catalogue_presets(session: AsyncSession) -> int:
    """Seed the global presets if no preset rows exist yet.

    Returns the number of rows inserted (0 when the table already has
    presets — idempotent re-run safe).
    """
    existing = (
        await session.execute(
            select(PropertyDevHouseType.id)
            .where(PropertyDevHouseType.is_preset.is_(True))
            .where(PropertyDevHouseType.project_id.is_(None))
            .limit(1)
        )
    ).first()
    if existing is not None:
        return 0

    rows = list(_all_preset_rows())
    session.add_all(rows)
    await session.flush()
    return len(rows)


__all__ = ["seed_house_type_catalogue_presets"]
