"""National-base language swap: translated work-item text overlaid in place.

The national cost bases ship one English work-item parquet plus a translated
parquet per app language. Switching a base to a market whose language differs
swaps the region's descriptions, categories and component names to that language
WITHOUT deleting the cost items - their ids are referenced by user element->cost
matches, assemblies and the usage ledger (FK), so a delete+reinsert would cascade
those away. This test proves the swap:

  * preserves every cost-item id (no delete+reinsert),
  * preserves the row count,
  * replaces the description and component names with the translated text,
  * cleans up the transient staging region.

Runs against the session PostgreSQL database (embedded cluster from conftest);
``_process_and_insert_cwicr`` uses the PG COPY path, so this is a PG-lane test.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

# Register the cost-item ORM tables on Base.metadata before the module-scoped
# ``_create_tables`` fixture runs create_all - conftest eagerly imports several
# modules' models but not costs, so without this import oe_costs_item is never
# created in the session database.
import app.modules.costs.models  # noqa: E402,F401

CYRILLIC = re.compile(r"[Ѐ-ӿ]")

# Minimal EN/RU text for a two-position base. Same rate_codes and resource_codes
# in both languages (the join key is the code, never the text), only the human
# strings differ, mirroring how the real translated parquets are produced.
_TEXT = {
    "en": {
        "desc": {"R001": "Concrete pour C25", "R002": "Brick wall 120mm"},
        "collection": "Concrete works",
        "department": "Structural",
        "section": "Foundations",
        "unit": "m3",
        "resources": {"L1": "Mason labour", "M1": "Cement bag"},
    },
    "ru": {
        "desc": {"R001": "Укладка бетона C25", "R002": "Кирпичная стена 120мм"},
        "collection": "Бетонные работы",
        "department": "Конструктив",
        "section": "Фундаменты",
        "unit": "м3",
        "resources": {"L1": "Труд каменщика", "M1": "Мешок цемента"},
    },
}


def _write_cwicr_parquet(path: Path, lang: str) -> None:
    """Write a tiny long-format CWICR parquet (two positions, two resources each)."""
    import pandas as pd

    t = _TEXT[lang]
    rows: list[dict] = []
    for rate_code in ("R001", "R002"):
        for res_code, res_name in t["resources"].items():
            rows.append(
                {
                    "rate_code": rate_code,
                    "rate_original_name": t["desc"][rate_code],
                    "rate_final_name": "",
                    "rate_unit": t["unit"],
                    "collection_name": t["collection"],
                    "department_name": t["department"],
                    "section_name": t["section"],
                    "resource_code": res_code,
                    "resource_name": res_name,
                    "resource_unit": t["unit"],
                    "resource_quantity": 1.0,
                    "resource_price_per_unit_current": 10.0,
                    "resource_cost": 10.0,
                    "row_type": "Labour" if res_code.startswith("L") else "Material",
                    "is_labor": res_code.startswith("L"),
                    "is_material": res_code.startswith("M"),
                    "is_machine": False,
                }
            )
    pd.DataFrame(rows).to_parquet(path, index=False)


@pytest.fixture(scope="module", autouse=True)
def _create_tables() -> None:
    """Create ORM tables in the per-session PostgreSQL database."""
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.database import Base

    engine = create_engine(get_settings().database_sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


def _load(engine, region: str) -> dict[str, tuple]:
    from sqlalchemy import text

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT code, id, description, components FROM oe_costs_item WHERE region = :r"),
            {"r": region},
        ).fetchall()
    return {row[0]: (str(row[1]), row[2], row[3]) for row in rows}


def test_language_swap_preserves_ids_and_translates(tmp_path: Path) -> None:
    from sqlalchemy import create_engine, text

    from app.config import get_settings
    from app.modules.costs.router import _process_and_insert_cwicr, _swap_region_text_sync

    sync_url = get_settings().database_sync_url
    # Unique region so a re-run (or a parallel worker) never collides.
    region = f"TESTXLATE_{uuid.uuid4().hex[:8]}"
    staging = f"__xlate_{region}"

    en_parquet = tmp_path / "base_en.parquet"
    ru_parquet = tmp_path / "base_ru.parquet"
    _write_cwicr_parquet(en_parquet, "en")
    _write_cwicr_parquet(ru_parquet, "ru")

    engine = create_engine(sync_url)
    try:
        # 1. Load the English base.
        _process_and_insert_cwicr(str(en_parquet), region, sync_url)
        before = _load(engine, region)
        assert set(before) == {"R001", "R002"}, "English base failed to load both positions"
        assert all(not CYRILLIC.search(desc) for _id, desc, _comp in before.values())

        # 2. Swap to Russian.
        updated = _swap_region_text_sync(sync_url, str(ru_parquet), region, staging)
        assert updated == len(before), "swap must update exactly the loaded rows"

        after = _load(engine, region)
        with engine.begin() as conn:
            staging_left = conn.execute(
                text("SELECT count(*) FROM oe_costs_item WHERE region = :r"), {"r": staging}
            ).scalar_one()

        # 3a. Same set of positions, same row count.
        assert set(after) == set(before)

        # 3b. Every id preserved (FK-safe: no delete+reinsert).
        for code in before:
            assert after[code][0] == before[code][0], f"id changed for {code}"

        # 3c. Descriptions now Russian.
        assert all(CYRILLIC.search(after[code][1]) for code in after), "descriptions not translated"

        # 3d. Component names now Russian (reprice later keeps these names).
        def _names(components) -> list[str]:
            return [c.get("name", "") for c in (components or []) if isinstance(c, dict)]

        translated_components = [n for code in after for n in _names(after[code][2]) if CYRILLIC.search(n)]
        assert translated_components, "no component name was translated"

        # 3e. Staging region cleaned up.
        assert staging_left == 0, "transient staging region left behind"
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM oe_costs_item WHERE region = :a OR region = :b"),
                {"a": region, "b": staging},
            )
        engine.dispose()
