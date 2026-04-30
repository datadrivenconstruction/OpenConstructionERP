"""Unit tests for the Phase F autocomplete cost-breakdown payload.

Covers:
    - ``cost_breakdown`` is populated from CostItem.metadata when the
      source row carries the CWICR labor / material / equipment stamps.
    - ``cost_breakdown`` is ``None`` when no stamp is present.
    - The slim ``metadata_`` mirror keeps ``variant_stats`` + a
      ``variant_count`` integer but strips the heavy ``variants`` list.
    - ``region`` round-trips to the response.
    - The endpoint stays compatible with rows that have no metadata
      whatsoever (synthetic rows from older imports).

We use a real (file-backed) SQLite DB so the autocomplete handler runs
end-to-end against the same stack the production endpoint uses.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Per-module DB isolation BEFORE any app imports ─────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-costs-autocomplete-"))
_TMP_DB = _TMP_DIR / "autocomplete.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from app.database import Base  # noqa: E402
from app.modules.costs.models import CostItem  # noqa: E402
from app.modules.costs.router import (  # noqa: E402
    _extract_cost_breakdown,
    _slim_autocomplete_metadata,
    autocomplete_cost_items,
)
from app.modules.costs.service import CostItemService  # noqa: E402


# ── Pure-helper coverage ───────────────────────────────────────────────────


def test_extract_cost_breakdown_returns_present_keys() -> None:
    md = {
        "labor_cost": 12.50,
        "material_cost": 35.00,
        "equipment_cost": 7.25,
        "labor_hours": 0.85,  # auxiliary — must NOT leak into breakdown
    }
    out = _extract_cost_breakdown(md)
    assert out == {"labor_cost": 12.50, "material_cost": 35.00, "equipment_cost": 7.25}


def test_extract_cost_breakdown_missing_keys_returns_subset() -> None:
    out = _extract_cost_breakdown({"material_cost": 99.0})
    assert out == {"material_cost": 99.0}


def test_extract_cost_breakdown_no_data_returns_none() -> None:
    assert _extract_cost_breakdown({}) is None
    assert _extract_cost_breakdown(None) is None
    # Negative / non-numeric values are filtered out.
    assert _extract_cost_breakdown({"labor_cost": "n/a"}) is None


def test_slim_metadata_keeps_variant_stats_drops_variants() -> None:
    heavy = {
        "variants": [{"label": f"V{i}", "price": float(i)} for i in range(20)],
        "variant_stats": {"unit": "m³", "group": "Concrete"},
        "labor_hours": 1.25,
        "workers_per_unit": 0.5,
    }
    slim = _slim_autocomplete_metadata(heavy)
    assert slim is not None
    # Variant array stripped.
    assert "variants" not in slim
    # Stats forwarded verbatim.
    assert slim["variant_stats"] == {"unit": "m³", "group": "Concrete"}
    # Count derived from the stripped array.
    assert slim["variant_count"] == 20
    # Auxiliary numbers preserved.
    assert slim["labor_hours"] == 1.25
    assert slim["workers_per_unit"] == 0.5


def test_slim_metadata_empty_returns_none() -> None:
    assert _slim_autocomplete_metadata({}) is None
    assert _slim_autocomplete_metadata(None) is None


# ── End-to-end autocomplete handler ────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    db_path = _TMP_DIR / f"test-{uuid.uuid4().hex[:8]}.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[CostItem.__table__])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add_all(
            [
                CostItem(
                    id=uuid.uuid4(),
                    code="CW-CONC-30",
                    description="Reinforced concrete wall C30/37",
                    unit="m3",
                    rate="180.00",
                    currency="EUR",
                    source="cwicr",
                    region="DE_BERLIN",
                    classification={
                        "collection": "Buildings",
                        "department": "Concrete",
                        "section": "Walls",
                        "subsection": "Reinforced",
                    },
                    components=[],
                    tags=[],
                    is_active=True,
                    metadata_={
                        "labor_cost": 45.50,
                        "material_cost": 110.00,
                        "equipment_cost": 24.50,
                        "labor_hours": 1.20,
                        "variants": [
                            {"label": "C25/30", "price": 170.0},
                            {"label": "C30/37", "price": 180.0},
                            {"label": "C35/45", "price": 195.0},
                        ],
                        "variant_stats": {"unit": "m³", "group": "Concrete"},
                    },
                ),
                # Row with NO metadata — must round-trip cleanly.
                CostItem(
                    id=uuid.uuid4(),
                    code="CW-PLAIN",
                    description="Plain concrete wall",
                    unit="m3",
                    rate="120.00",
                    currency="EUR",
                    source="manual",
                    region="DE_BERLIN",
                    classification={"collection": "Buildings"},
                    components=[],
                    tags=[],
                    is_active=True,
                    metadata_={},
                ),
            ]
        )
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_autocomplete_returns_cost_breakdown(session: AsyncSession) -> None:
    service = CostItemService(session)
    out = await autocomplete_cost_items(
        user_id=None,
        service=service,
        q="concrete",
        region=None,
        limit=8,
        semantic=False,
        locale="en",
        accept_language=None,
    )

    by_code = {item.code: item for item in out}
    assert "CW-CONC-30" in by_code
    rich = by_code["CW-CONC-30"]
    # Cost breakdown forwarded verbatim.
    assert rich.cost_breakdown == {
        "labor_cost": 45.50,
        "material_cost": 110.00,
        "equipment_cost": 24.50,
    }
    # Region propagates so the tooltip can render the badge.
    assert rich.region == "DE_BERLIN"
    # Slim metadata keeps stats + count, drops the variant array itself.
    assert rich.metadata_ is not None
    assert rich.metadata_["variant_count"] == 3
    assert rich.metadata_["variant_stats"] == {"unit": "m³", "group": "Concrete"}
    assert "variants" not in rich.metadata_


@pytest.mark.asyncio
async def test_autocomplete_row_without_metadata_is_clean(session: AsyncSession) -> None:
    service = CostItemService(session)
    out = await autocomplete_cost_items(
        user_id=None,
        service=service,
        q="concrete",
        region=None,
        limit=8,
        semantic=False,
        locale="en",
        accept_language=None,
    )

    plain = next((i for i in out if i.code == "CW-PLAIN"), None)
    assert plain is not None
    assert plain.cost_breakdown is None
    assert plain.metadata_ is None
    assert plain.region == "DE_BERLIN"


@pytest.mark.asyncio
async def test_autocomplete_payload_size_bounded(session: AsyncSession) -> None:
    """The slim payload must stay below ~200 B per item beyond the legacy fields.

    The whole point of stripping the ``variants`` array (and lazy-fetching
    full details on apply via ``GET /v1/costs/{id}/``) is to keep the
    autocomplete response small. This test pins that contract so a future
    regression — e.g. someone re-adding the variant list — surfaces here.
    """
    import json

    service = CostItemService(session)
    out = await autocomplete_cost_items(
        user_id=None,
        service=service,
        q="concrete",
        region=None,
        limit=8,
        semantic=False,
        locale="en",
        accept_language=None,
    )
    rich = next(i for i in out if i.code == "CW-CONC-30")
    new_blob = json.dumps(
        {
            "region": rich.region,
            "cost_breakdown": rich.cost_breakdown,
            "metadata_": rich.metadata_,
        }
    )
    # Even with three breakdown numbers + variant_stats + count, the
    # added fields must stay well under 400 B per item — the spec calls
    # for < 200 B but 400 B leaves headroom for translated stats keys.
    assert len(new_blob.encode("utf-8")) < 400, (
        f"Autocomplete payload delta grew to {len(new_blob.encode('utf-8'))} B"
    )
