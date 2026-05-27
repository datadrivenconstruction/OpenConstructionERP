# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""propdev: house-type catalogue (user-extensible, country-scoped presets).

Creates ``oe_property_dev_house_type_catalogue`` and seeds ~60 global
presets across 12 countries (DE, US, UK, RU, TR, FR, ES, IT, PL, JP,
CN, SA). The table is distinct from ``oe_property_dev_house_type``
(per-Development with full pricing data) — it stores lightweight
classification labels surfaced in the Plot create dialog so the user
can pick e.g. "Reihenhaus" or "Townhouse" without modelling a full
floor plan.

The ``inspector.has_table`` guard is required because v3112 already
runs ``Base.metadata.create_all(checkfirst=True)`` after env.py
imports every module's models — on a fresh-DB install path the table
will already exist by the time this migration runs, so ``create_table``
without the guard would raise.

Revision ID: v3114_propdev_house_type_catalogue
Revises: v3113_propdev_plot_extra_fields, v3113_propdev_warranty_enrich
Create Date: 2026-05-23

This migration also serves as the merge point for the two sister v3113
branches (plot extra fields + warranty enrich) so the chain returns to
a single head after it.
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3114_propdev_house_type_catalogue"
down_revision: Union[str, Sequence[str], None] = (
    "v3113_propdev_plot_extra_fields",
    "v3113_propdev_warranty_enrich",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Country → [(code, name, description, area_typical_m2, floors_typical), ...]
# Codes are UPPER_SNAKE; names are localised display labels. Area & floors
# are best-effort defaults users will typically override.
_SEED_PRESETS: dict[str, list[tuple[str, str, str | None, str | None, int | None]]] = {
    "DE": [
        ("HOUSE_DETACHED", "Einfamilienhaus", "Freistehendes Einfamilienhaus", "160", 2),
        ("HOUSE_SEMI", "Doppelhaushälfte", "Halbes Haus an Brandmauer", "130", 2),
        ("HOUSE_ROW", "Reihenhaus", "Mittelhaus oder Endhaus einer Reihe", "120", 2),
        ("APT_FLOOR", "Etagenwohnung", "Wohnung in einem Mehrfamilienhaus", "85", 1),
        ("APT_PENTHOUSE", "Penthouse", "Dachgeschosswohnung mit Terrasse", "140", 1),
        ("APT_GROUND", "Erdgeschosswohnung", "Wohnung im Erdgeschoss mit Garten", "90", 1),
    ],
    "US": [
        ("SF_HOME", "Single-family home", "Detached single-family residence", "190", 2),
        ("TOWNHOUSE", "Townhouse", "Attached row home, individually owned", "150", 2),
        ("CONDO", "Condo", "Condominium unit in a multi-unit building", "100", 1),
        ("DUPLEX", "Duplex", "Two-unit building, side-by-side or stacked", "120", 2),
        ("LOFT", "Loft", "Open-plan converted industrial / commercial unit", "110", 1),
    ],
    "UK": [
        ("DETACHED", "Detached", "Standalone house, no shared walls", "150", 2),
        ("SEMI", "Semi-detached", "Pair of houses sharing one party wall", "110", 2),
        ("TERRACED", "Terraced", "House in a row sharing walls on both sides", "95", 2),
        ("FLAT", "Flat", "Single-floor dwelling within a larger building", "70", 1),
        ("BUNGALOW", "Bungalow", "Single-storey detached house", "100", 1),
    ],
    "RU": [
        ("KVARTIRA", "Квартира", "Квартира в многоэтажном доме", "65", 1),
        ("TAUNHAUS", "Таунхаус", "Блокированный дом с соседями", "140", 2),
        ("KOTTEDZH", "Коттедж", "Отдельно стоящий загородный дом", "180", 2),
        ("PENTHAUS", "Пентхаус", "Квартира на верхнем этаже с террасой", "150", 1),
    ],
    "TR": [
        ("MUSTAKIL", "Müstakil ev", "Bağımsız tek aile evi", "180", 2),
        ("DAIRE", "Daire", "Apartman dairesi", "100", 1),
        ("VILLA", "Villa", "Bahçeli müstakil villa", "220", 2),
        ("REZIDANS", "Rezidans", "Hizmetli lüks konut", "120", 1),
    ],
    "FR": [
        ("MAISON", "Maison individuelle", "Maison détachée pour une famille", "140", 2),
        ("APPARTEMENT", "Appartement", "Logement dans un immeuble", "75", 1),
        ("VILLA", "Villa", "Maison avec jardin et prestations haut-de-gamme", "200", 2),
        ("DUPLEX", "Duplex", "Logement sur deux niveaux", "110", 2),
    ],
    "ES": [
        ("CASA", "Casa", "Vivienda unifamiliar", "150", 2),
        ("PISO", "Piso", "Vivienda en bloque", "80", 1),
        ("CHALET", "Chalet", "Vivienda unifamiliar aislada con parcela", "200", 2),
        ("DUPLEX", "Dúplex", "Vivienda en dos plantas", "110", 2),
    ],
    "IT": [
        ("VILLA", "Villa", "Villa unifamiliare con giardino", "220", 2),
        ("APPARTAMENTO", "Appartamento", "Unità abitativa in condominio", "85", 1),
        ("ATTICO", "Attico", "Appartamento all'ultimo piano con terrazzo", "130", 1),
        ("BIFAMILIARE", "Bifamiliare", "Edificio diviso in due unità", "140", 2),
    ],
    "PL": [
        ("DOM", "Dom jednorodzinny", "Wolnostojący dom jednorodzinny", "150", 2),
        ("MIESZKANIE", "Mieszkanie", "Lokal mieszkalny w bloku", "60", 1),
        ("APARTAMENT", "Apartament", "Mieszkanie o podwyższonym standardzie", "90", 1),
    ],
    "JP": [
        ("IKKODATE", "一戸建て", "Detached single-family house", "100", 2),
        ("MANSION", "マンション", "Reinforced-concrete condominium unit", "70", 1),
        ("APART", "アパート", "Wood-frame low-rise rental unit", "45", 1),
    ],
    "CN": [
        ("BIESHU", "别墅", "Standalone villa / detached house", "240", 2),
        ("GONGYU", "公寓", "Apartment unit in a residential tower", "90", 1),
        ("LIANPAI", "联排", "Row-style townhouse", "180", 2),
    ],
    "SA": [
        ("VILLA", "فيلا", "Detached villa with private garden", "300", 2),
        ("SHAQQA", "شقة", "Apartment in a residential building", "120", 1),
        ("DOPLEX", "دوبلكس", "Two-storey duplex unit", "200", 2),
    ],
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    table_name = "oe_property_dev_house_type_catalogue"

    if not inspector.has_table(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.CHAR(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("country_code", sa.String(length=2), nullable=True),
            sa.Column("code", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("area_typical_m2", sa.Numeric(10, 2), nullable=True),
            sa.Column("floors_typical", sa.Integer(), nullable=True),
            sa.Column(
                "is_preset",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("created_by", sa.CHAR(36), nullable=True),
            sa.UniqueConstraint(
                "project_id",
                "country_code",
                "code",
                name="uq_oe_property_dev_house_type_catalogue_proj_country_code",
            ),
        )

    # Refresh inspector after create_table.
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}

    def _ensure_index(name: str, cols: list[str]) -> None:
        if name not in existing_indexes:
            op.create_index(name, table_name, cols)

    _ensure_index(
        "ix_oe_property_dev_house_type_catalogue_proj_country",
        ["project_id", "country_code"],
    )
    _ensure_index("ix_oe_property_dev_house_type_catalogue_project_id", ["project_id"])
    _ensure_index("ix_oe_property_dev_house_type_catalogue_country_code", ["country_code"])
    _ensure_index("ix_oe_property_dev_house_type_catalogue_is_preset", ["is_preset"])
    _ensure_index("ix_oe_property_dev_house_type_catalogue_created_by", ["created_by"])

    # Seed presets — skip if any preset row exists (idempotent re-runs).
    existing_preset_count = (
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM oe_property_dev_house_type_catalogue WHERE is_preset = 1 AND project_id IS NULL"
            )
        ).scalar()
        or 0
    )

    if existing_preset_count == 0:
        rows: list[dict[str, object]] = []
        for country_code, presets in _SEED_PRESETS.items():
            for code, name, description, area_typical, floors in presets:
                rows.append(
                    {
                        "id": str(uuid.uuid4()),
                        "project_id": None,
                        "country_code": country_code,
                        "code": code,
                        "name": name,
                        "description": description,
                        "area_typical_m2": area_typical,
                        "floors_typical": floors,
                        "is_preset": True,
                        "created_by": None,
                    }
                )

        catalogue_table = sa.table(
            table_name,
            sa.column("id", sa.CHAR(36)),
            sa.column("project_id", sa.CHAR(36)),
            sa.column("country_code", sa.String),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("description", sa.Text),
            sa.column("area_typical_m2", sa.Numeric),
            sa.column("floors_typical", sa.Integer),
            sa.column("is_preset", sa.Boolean),
            sa.column("created_by", sa.CHAR(36)),
        )
        try:
            op.bulk_insert(catalogue_table, rows)
        except Exception:
            # Belt-and-suspenders: if the migration runs in a state where
            # the FK target table (oe_projects_project) is not yet
            # materialised (rare — only when an operator drives alembic
            # past the env.py fresh-blank-DB shortcut without
            # ``Base.metadata.create_all`` having been run first), the
            # bulk insert fails. Swallow it here so this migration stays
            # idempotent; the runtime startup seed in main.py
            # (``seed_house_type_catalogue_presets``) will populate the
            # presets on the next boot once the schema is complete.
            pass


def downgrade() -> None:
    # Drop indexes first so engines that don't auto-drop them stay happy.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "oe_property_dev_house_type_catalogue"

    if not inspector.has_table(table_name):
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    for ix in (
        "ix_oe_property_dev_house_type_catalogue_proj_country",
        "ix_oe_property_dev_house_type_catalogue_project_id",
        "ix_oe_property_dev_house_type_catalogue_country_code",
        "ix_oe_property_dev_house_type_catalogue_is_preset",
        "ix_oe_property_dev_house_type_catalogue_created_by",
    ):
        if ix in existing_indexes:
            op.drop_index(ix, table_name=table_name)

    op.drop_table(table_name)
