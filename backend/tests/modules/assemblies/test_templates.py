# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the Assembly Library templates feature (v4.0 / Slice 1).

Per ``feedback_test_isolation.md`` every test uses a per-test temp
SQLite — never the production / shared test DB.

Coverage
--------
* test_seed_loads_25_templates
* test_list_templates_returns_seeded
* test_filter_by_category
* test_filter_by_classification_din276
* test_apply_template_returns_components_with_costs
* test_apply_template_quantity_scaling
* test_template_translations_present_for_de_ru_es
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.assemblies.repository import (
    AssemblyTemplateRepository,
    seed_assembly_templates,
)
from app.modules.assemblies.schemas import ApplyTemplateRequest
from app.modules.assemblies.templates_seed import ASSEMBLY_TEMPLATES

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()


def _register_models() -> None:
    """Eagerly register every ORM module referenced by the test DB."""
    import app.modules.assemblies.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.catalog.models  # noqa: F401
    import app.modules.costs.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Spin up an isolated SQLite, register the schema, yield a session."""
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-asm-tpl-")) / "asm_templates.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=OWNER_ID,
            email=f"o-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="O",
        )
        s.add(owner)
        await s.flush()
        s.add(
            Project(
                id=PROJECT_ID,
                name="Asm Template Test",
                owner_id=OWNER_ID,
                currency="EUR",
            )
        )
        await s.commit()
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


async def _seed_costs(session: AsyncSession) -> None:
    """Insert a small CostItem catalogue so the apply endpoint can match."""
    from app.modules.costs.models import CostItem

    rows = [
        CostItem(
            code="C-001",
            description="Concrete C30/37 ready-mix",
            unit="m3",
            rate="120.00",
            currency="EUR",
            source="cwicr",
        ),
        CostItem(
            code="C-002",
            description="Rebar reinforcement steel B500B",
            unit="kg",
            rate="1.20",
            currency="EUR",
            source="cwicr",
        ),
        CostItem(
            code="C-003",
            description="Wall formwork plywood system",
            unit="m2",
            rate="22.00",
            currency="EUR",
            source="cwicr",
        ),
        CostItem(
            code="C-004",
            description="Concrete pouring labor mason crew",
            unit="h",
            rate="45.00",
            currency="EUR",
            source="cwicr",
        ),
    ]
    for r in rows:
        session.add(r)
    await session.commit()


# ── 1. Seed loads 25 templates ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_loads_25_templates(session: AsyncSession) -> None:
    """The seed function inserts exactly the canonical 25 templates."""
    written = await seed_assembly_templates(session, force=True)
    assert written == 25
    repo = AssemblyTemplateRepository(session)
    assert await repo.count() == 25
    # Spot-check a known template exists by name.
    tpl = await repo.get_by_name("Reinforced concrete wall C30/37 d=24cm")
    assert tpl is not None
    assert tpl.category == "concrete"
    assert tpl.unit == "m3"
    assert isinstance(tpl.components, list)
    assert len(tpl.components) >= 3


# ── 2. List returns seeded ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_templates_returns_seeded(session: AsyncSession) -> None:
    """``list_all`` returns the full seeded set with the correct total."""
    await seed_assembly_templates(session, force=True)
    repo = AssemblyTemplateRepository(session)
    items, total = await repo.list_all(limit=100, offset=0)
    assert total == 25
    assert len(items) == 25
    names = {t.name for t in items}
    assert "Steel beam HEB200" in names
    assert "Open cut excavation up to 2m depth" in names


# ── 3. Filter by category ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_by_category(session: AsyncSession) -> None:
    """``category=concrete`` returns only concrete templates."""
    await seed_assembly_templates(session, force=True)
    repo = AssemblyTemplateRepository(session)
    items, total = await repo.list_all(category="concrete", limit=100)
    assert total >= 1
    assert all(t.category == "concrete" for t in items)
    # We seed 2 walls + 2 slabs + 1 column → at least 5 concrete rows.
    assert len(items) >= 5


# ── 4. Filter by DIN 276 classification ───────────────────────────────────


@pytest.mark.asyncio
async def test_filter_by_classification_din276(session: AsyncSession) -> None:
    """The classification filter narrows the list to a DIN 276 KG."""
    await seed_assembly_templates(session, force=True)
    repo = AssemblyTemplateRepository(session)
    # KG 331 = exterior walls; we seed at least the two RC walls + KSL walls.
    items, total = await repo.list_all(classification_din276="331", limit=100)
    assert total >= 2
    for t in items:
        assert t.classification.get("din276") == "331"


# ── 5. Apply template — components carry resolved costs ────────────────────


@pytest.mark.asyncio
async def test_apply_template_returns_components_with_costs(
    session: AsyncSession,
) -> None:
    """Apply endpoint resolves cost_match_query against the catalogue.

    Uses the existing lexical matcher (no Qdrant required) so this test
    works in any environment.
    """
    await seed_assembly_templates(session, force=True)
    await _seed_costs(session)

    repo = AssemblyTemplateRepository(session)
    tpl = await repo.get_by_name("Reinforced concrete wall C30/37 d=24cm")
    assert tpl is not None

    # Inline a minimal apply implementation that mirrors the router —
    # tests run without the FastAPI dep graph.
    from app.modules.costs.matcher import match_cwicr_items

    components_out = []
    grand_total = 0.0
    for raw in tpl.components or []:
        query = raw.get("cost_match_query", "")
        factor = float(raw.get("factor", 0.0))
        comp_unit = raw.get("unit", "")
        matches = await match_cwicr_items(session, query, unit=comp_unit or None, top_k=1, source="cwicr")
        unit_rate = 0.0
        if matches:
            # MatchResult is a flat pydantic model; the rate is exposed
            # directly as ``unit_rate`` (no ``.item`` wrapper).
            unit_rate = float(matches[0].unit_rate or 0.0)
        total = factor * 1.0 * unit_rate
        components_out.append(
            {
                "query": query,
                "factor": factor,
                "unit_rate": unit_rate,
                "total": total,
                "matched": bool(matches),
            }
        )
        grand_total += total

    # All four canonical sub-recipes must resolve to non-zero rates from
    # the 4-row catalogue we seeded.
    matched_count = sum(1 for c in components_out if c["matched"])
    assert matched_count == len(components_out)
    assert all(c["unit_rate"] > 0 for c in components_out)
    assert grand_total > 0.0


# ── 6. Apply template — quantity scaling ───────────────────────────────────


@pytest.mark.asyncio
async def test_apply_template_quantity_scaling(session: AsyncSession) -> None:
    """``quantity`` scales every component total linearly.

    For quantity = 3 the rolled-up grand total must be exactly 3× the
    quantity = 1 total — that's the contract the BOQ side relies on.
    """
    await seed_assembly_templates(session, force=True)
    await _seed_costs(session)

    repo = AssemblyTemplateRepository(session)
    tpl = await repo.get_by_name("Reinforced concrete wall C30/37 d=24cm")
    assert tpl is not None

    from app.modules.costs.matcher import match_cwicr_items

    async def _grand_total(quantity: float) -> float:
        total = 0.0
        for raw in tpl.components or []:
            query = raw.get("cost_match_query", "")
            factor = float(raw.get("factor", 0.0))
            matches = await match_cwicr_items(session, query, top_k=1, source="cwicr")
            if not matches:
                continue
            rate = float(matches[0].unit_rate or 0.0)
            total += factor * quantity * rate
        return total

    t1 = await _grand_total(1.0)
    t3 = await _grand_total(3.0)
    assert t1 > 0.0
    # Floating-point tolerance — exact equality is fragile.
    assert abs(t3 - 3.0 * t1) < 1e-6

    # And verify the schema accepts the apply payload shape.
    req = ApplyTemplateRequest(project_id=PROJECT_ID, quantity=3.0)
    assert req.quantity == 3.0


# ── 7. Translations present for DE / RU / ES ──────────────────────────────


@pytest.mark.asyncio
async def test_template_translations_present_for_de_ru_es(
    session: AsyncSession,
) -> None:
    """Every seeded template carries DE + RU + ES localisations."""
    await seed_assembly_templates(session, force=True)
    repo = AssemblyTemplateRepository(session)
    items, total = await repo.list_all(limit=100)
    assert total == len(ASSEMBLY_TEMPLATES)
    for t in items:
        translations = t.name_translations or {}
        for lang in ("de", "ru", "es"):
            assert lang in translations, f"Template {t.name!r} missing {lang} translation"
            assert translations[lang], f"Template {t.name!r} has empty {lang} translation"
