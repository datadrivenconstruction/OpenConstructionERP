"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The import path must decide the work-name join from the base type.

``_join_work_name_columns`` is unit-tested on both sides already; what this pins
is the WIRING, that ``_process_and_insert_cwicr`` passes the right flag for the
region it is loading. That is the part the defect turned on: nothing in the data
distinguished a classic parquet from a national one, both diverge in ~100% of
rows, so a bug here is invisible until someone reads a description in the UI.

Runs against the session PostgreSQL database (embedded cluster from conftest);
``_process_and_insert_cwicr`` uses the PG COPY path, so this is a PG-lane test.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

# Register the cost-item ORM tables on Base.metadata before the module-scoped
# ``_create_tables`` fixture runs create_all - conftest eagerly imports several
# modules' models but not costs.
import app.modules.costs.models  # noqa: E402,F401

# Classic CIS shape: one sentence split across the two columns.
CLASSIC_PARENT = "Soil excavation using single-bucket dragline excavators with a capacity of:"
CLASSIC_VARIANT = "15 m3, soil group 1"

# National shape: two full renderings of the same item, in the same language.
NATIONAL_A = "Demolition of the Catalan vault, including manual loading"
NATIONAL_B = "Demolition of the vault to the flat arch, including manual loading"


def _write_parquet(path: Path, orig: str, final: str) -> None:
    import pandas as pd

    pd.DataFrame(
        [
            {
                "rate_code": "R001",
                "rate_original_name": orig,
                "rate_final_name": final,
                "rate_unit": "m3",
                "collection_name": "Works",
                "department_name": "Structural",
                "section_name": "Demolition",
                "resource_code": "L1",
                "resource_name": "Labour",
                "resource_unit": "hr",
                "resource_quantity": 1.0,
                "resource_price_per_unit_current": 10.0,
                "resource_cost": 10.0,
                "row_type": "Labour",
                "is_labor": True,
                "is_material": False,
                "is_machine": False,
            }
        ]
    ).to_parquet(path, index=False)


@pytest.fixture(scope="module", autouse=True)
def _create_tables() -> None:
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.database import Base

    engine = create_engine(get_settings().database_sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


def _load_description(region: str, orig: str, final: str, tmp_path: Path) -> str:
    from sqlalchemy import create_engine, text

    from app.config import get_settings
    from app.modules.costs.router import _process_and_insert_cwicr

    sync_url = get_settings().database_sync_url
    parquet = tmp_path / f"{region}.parquet"
    _write_parquet(parquet, orig, final)

    engine = create_engine(sync_url)
    try:
        _process_and_insert_cwicr(str(parquet), region, sync_url)
        with engine.begin() as conn:
            return conn.execute(
                text("SELECT description FROM oe_costs_item WHERE region = :r"), {"r": region}
            ).scalar_one()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM oe_costs_item WHERE region = :r"), {"r": region})
        engine.dispose()


def test_a_classic_region_still_joins_both_columns(tmp_path: Path) -> None:
    """RU_MOSCOW is a market of the global base, so the sentence must be rebuilt."""
    region = f"RU_MOSCOW_{uuid.uuid4().hex[:6]}"
    desc = _load_description(region, CLASSIC_PARENT, CLASSIC_VARIANT, tmp_path)
    assert desc == f"{CLASSIC_PARENT} {CLASSIC_VARIANT}"


def test_a_national_region_does_not_double_the_description(tmp_path: Path) -> None:
    """ZH_CHINA is a national base, so the item must appear once, not twice."""
    region = f"ZH_CHINA_{uuid.uuid4().hex[:6]}"
    desc = _load_description(region, NATIONAL_A, NATIONAL_B, tmp_path)
    assert desc == NATIONAL_B
    assert NATIONAL_A not in desc


def test_a_national_staging_region_does_not_double_either(tmp_path: Path) -> None:
    """The language swap imports through ``__xlate_``; that path doubled too."""
    region = f"__xlate_ZH_CHINA_{uuid.uuid4().hex[:6]}"
    desc = _load_description(region, NATIONAL_A, NATIONAL_B, tmp_path)
    assert desc == NATIONAL_B
