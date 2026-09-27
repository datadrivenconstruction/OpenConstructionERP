# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quick-estimate deepening: server-side history + enriched BOQ creation.

Covers the two highest-value depth additions for the quick-estimate module:

1. ``AIService.list_estimates`` (backing ``GET /api/v1/ai/estimates/``) -
   paginated, user-scoped server-side history so estimate runs survive a
   reload / device switch (previously the history lived only in browser
   localStorage and was never wired into the page).

2. ``apply_enriched`` on ``AIService.create_boq_from_estimate`` (backing
   ``POST /api/v1/ai/estimate/{job_id}/create-boq/``) - when set, BOQ creation
   replaces each line's AI rate with the best *same-currency* CWICR match the
   user reviewed in the table, records the match code on the position, and
   never blends foreign-currency rates.

Plus the shared matcher and the history-summary builder.

These are exercised through the **service layer directly** against the
conftest-provisioned PostgreSQL cluster, seeding users / projects / jobs via
the ORM. That keeps the suite hermetic (no AI key, no Qdrant - the
deterministic text-keyword fallback inside ``_match_cost_items`` is the path
under test) and avoids the module-scoped ASGI HTTP-client fixture pattern,
which currently breaks on Windows + pytest-asyncio 1.3 + asyncpg (WinError
10038) under the only locally available interpreter.

Run:
    cd backend
    python -m pytest tests/modules/ai/test_quick_estimate_history_enrich.py -v
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio

# Eager-import the model namespaces the suite touches so Base.metadata sees a
# coherent table set when create_all runs.
import app.modules.ai.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.costs.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.teams.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401

# ── Schema bootstrap (no ASGI client needed) ───────────────────────────────


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def schema():
    """Create all ORM tables once for the module against the embedded cluster."""
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


# ── ORM seed helpers ────────────────────────────────────────────────────────


async def _seed_user() -> str:
    from app.database import async_session_factory
    from app.modules.users.models import User

    uid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            User(
                id=uid,
                email=f"qe-{uuid.uuid4().hex[:10]}@qe-deepen.io",
                full_name="QE Deepen",
                hashed_password="x",
                is_active=True,
                role="admin",
            )
        )
        await s.commit()
    return str(uid)


async def _seed_project(*, owner_id: str, currency: str = "EUR") -> uuid.UUID:
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            Project(
                id=pid,
                name=f"QeD-{uuid.uuid4().hex[:6]}",
                description="quick-estimate deepening test",
                owner_id=uuid.UUID(owner_id),
                currency=currency,
                region="DACH",
                classification_standard="din276",
                metadata_={},
                fx_rates=[],
            )
        )
        await s.commit()
    return pid


async def _seed_cost_item(
    *,
    description: str,
    unit: str = "m3",
    rate: str = "185.00",
    currency: str = "EUR",
    region: str | None = None,
) -> str:
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    code = f"QED-{uuid.uuid4().hex[:8].upper()}"
    async with async_session_factory() as s:
        s.add(
            CostItem(
                id=uuid.uuid4(),
                code=code,
                description=description,
                unit=unit,
                rate=rate,
                currency=currency,
                source="cwicr",
                classification={"din276": "330"},
                components=[],
                tags=[],
                region=region,
                is_active=True,
                metadata_={},
            )
        )
        await s.commit()
    return code


async def _seed_job(
    *,
    user_id: str,
    project_id: uuid.UUID | None,
    items: list[dict],
    status: str = "completed",
    input_text: str = "test estimate",
    tokens: int = 1200,
    cost_usd: float = 0.0024,
) -> uuid.UUID:
    """Insert a completed AIEstimateJob row directly (bypasses the LLM)."""
    from app.database import async_session_factory
    from app.modules.ai.models import AIEstimateJob

    jid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            AIEstimateJob(
                id=jid,
                user_id=uuid.UUID(user_id),
                project_id=project_id,
                input_type="text",
                input_text=input_text,
                status=status,
                result=items if status == "completed" else None,
                model_used="anthropic",
                tokens_used=tokens,
                duration_ms=950,
                cost_usd_estimate=cost_usd,
            )
        )
        await s.commit()
    return jid


def _item(desc: str, qty: float, rate: float, unit: str = "m3", currency: str = "EUR") -> dict:
    return {
        "ordinal": "01.01.0001",
        "description": desc,
        "unit": unit,
        "quantity": qty,
        "unit_rate": rate,
        "total": round(qty * rate, 2),
        "classification": {"din276": "330"},
        "category": "Concrete",
        "currency": currency,
    }


# ── 1. Pure: history summary builder ────────────────────────────────────────


def test_build_job_summary_recomputes_total_and_currency() -> None:
    """The summary must derive grand_total + currency from the line rows and
    expose token / cost telemetry without echoing the full item payload."""
    from app.modules.ai.service import _build_job_summary

    job = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=None,
        input_type="text",
        input_text="2000 m2 office",
        input_filename=None,
        status="completed",
        result=[_item("Concrete C30/37", 10, 185.0), _item("Rebar", 2, 1200.0)],
        model_used="anthropic",
        tokens_used=1500,
        cost_usd_estimate=0.0036,
        duration_ms=900,
        error_message=None,
        created_at=datetime.now(UTC),
    )
    summary = _build_job_summary(job)
    assert summary.items_count == 2
    assert summary.currency == "EUR"
    # 10*185 + 2*1200 = 1850 + 2400 = 4250.00
    assert summary.grand_total == Decimal("4250.00")
    assert summary.tokens_used == 1500
    assert summary.cost_usd_estimate == Decimal("0.0036")


def test_build_job_summary_handles_empty_result() -> None:
    from app.modules.ai.service import _build_job_summary

    job = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=None,
        input_type="text",
        input_text="x",
        input_filename=None,
        status="failed",
        result=None,
        model_used=None,
        tokens_used=0,
        cost_usd_estimate=0.0,
        duration_ms=0,
        error_message="boom",
        created_at=datetime.now(UTC),
    )
    summary = _build_job_summary(job)
    assert summary.items_count == 0
    assert summary.grand_total == Decimal("0.00")
    assert summary.currency == ""
    assert summary.status == "failed"


# ── 2. Shared matcher (text-keyword fallback, no vector) ────────────────────


@pytest.mark.asyncio(loop_scope="module")
async def test_match_cost_items_finds_by_keyword(schema) -> None:
    from app.database import async_session_factory
    from app.modules.ai.service import _match_cost_items

    code = await _seed_cost_item(description="Reinforced concrete wall C30/37 cast in place", rate="210.50")
    async with async_session_factory() as s:
        matches = await _match_cost_items(
            s,
            description="reinforced concrete wall",
            item_unit="m3",
            region="",
            limit=5,
        )
    codes = [m["code"] for m in matches]
    assert code in codes, f"expected seeded item {code} in matches {codes}"
    best = matches[0]
    assert best["score"] > 0
    assert float(best["rate"]) > 0


@pytest.mark.asyncio(loop_scope="module")
async def test_the_item_matching_every_keyword_is_found_behind_many_partial_ones(schema, monkeypatch) -> None:
    """The text fallback ranks before it caps, so the full match is not cut off.

    Twenty items share one keyword and are stored first; the one that carries
    all three is stored last. An unordered cap of 15 kept the first rows the
    scan met and never scored the full match.
    """
    import app.core.vector as vector
    from app.database import async_session_factory
    from app.modules.ai.service import _match_cost_items

    def _no_embedder(_texts):
        raise RuntimeError("no embedder in this test")

    monkeypatch.setattr(vector, "encode_texts", _no_embedder)
    token = f"zq{uuid.uuid4().hex[:10]}"
    first, second = f"alpha{uuid.uuid4().hex[:6]}", f"beta{uuid.uuid4().hex[:6]}"
    for _ in range(20):
        await _seed_cost_item(description=f"Partial {token} item", rate="10.00")
    full = await _seed_cost_item(description=f"Full {token} {first} {second} item", rate="99.00")

    async with async_session_factory() as s:
        matches = await _match_cost_items(
            s,
            description=f"{token} {first} {second}",
            item_unit="m3",
            region="",
            limit=5,
        )

    assert matches, "the text fallback found nothing"
    assert matches[0]["code"] == full, [m["code"] for m in matches]


@pytest.mark.asyncio(loop_scope="module")
async def test_match_cost_items_empty_for_no_keywords(schema) -> None:
    """A description with no usable keywords must return [] rather than raise."""
    from app.database import async_session_factory
    from app.modules.ai.service import _match_cost_items

    async with async_session_factory() as s:
        matches = await _match_cost_items(s, description="a", item_unit="", region="", limit=5)
    assert matches == []


# ── 3. list_estimates: pagination, ordering, scoping ────────────────────────


@pytest.mark.asyncio(loop_scope="module")
async def test_list_estimates_is_user_scoped_and_newest_first(schema) -> None:
    from app.database import async_session_factory
    from app.modules.ai.service import AIService

    ua = await _seed_user()
    ub = await _seed_user()
    j1 = await _seed_job(user_id=ua, project_id=None, items=[_item("Concrete", 5, 100)])
    j2 = await _seed_job(user_id=ua, project_id=None, items=[_item("Steel", 2, 500)])
    j3 = await _seed_job(user_id=ua, project_id=None, items=[_item("Brick", 8, 50)])
    await _seed_job(user_id=ub, project_id=None, items=[_item("Glass", 1, 999)])

    async with async_session_factory() as s:
        out = await AIService(s).list_estimates(ua, limit=50)

    ids = [str(it.id) for it in out.items]
    assert str(j1) in ids and str(j2) in ids and str(j3) in ids
    # User B's job must not leak.
    assert all(str(it.id) != "glass" for it in out.items)
    # Newest first: j3 inserted last -> precedes j1.
    assert ids.index(str(j3)) < ids.index(str(j1))
    # Telemetry computed per row.
    s2 = next(it for it in out.items if it.id == j2)
    assert s2.items_count == 1
    assert s2.currency == "EUR"
    assert s2.grand_total == Decimal("1000.00")  # 2 * 500
    assert out.total >= 3


@pytest.mark.asyncio(loop_scope="module")
async def test_list_estimates_pagination(schema) -> None:
    from app.database import async_session_factory
    from app.modules.ai.service import AIService

    uid = await _seed_user()
    for i in range(5):
        await _seed_job(user_id=uid, project_id=None, items=[_item(f"Item {i}", 1, 100 + i)])

    async with async_session_factory() as s:
        svc = AIService(s)
        page1 = await svc.list_estimates(uid, limit=2, offset=0)
        page2 = await svc.list_estimates(uid, limit=2, offset=2)

    assert len(page1.items) == 2
    assert page1.limit == 2
    ids1 = {it.id for it in page1.items}
    ids2 = {it.id for it in page2.items}
    assert ids1.isdisjoint(ids2)
    assert page1.total == 5


@pytest.mark.asyncio(loop_scope="module")
async def test_list_estimates_status_filter(schema) -> None:
    from app.database import async_session_factory
    from app.modules.ai.service import AIService

    uid = await _seed_user()
    await _seed_job(user_id=uid, project_id=None, items=[_item("ok", 1, 10)], status="completed")
    failed = await _seed_job(user_id=uid, project_id=None, items=[], status="failed")

    async with async_session_factory() as s:
        out = await AIService(s).list_estimates(uid, status_filter="failed", limit=50)

    ids = [it.id for it in out.items]
    assert failed in ids
    assert all(it.status == "failed" for it in out.items)


# ── 4. Enriched BOQ creation ────────────────────────────────────────────────


async def _fetch_positions(boq_id: str) -> list:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    async with async_session_factory() as s:
        rows = (await s.execute(select(Position).where(Position.boq_id == uuid.UUID(boq_id)))).scalars().all()
    return list(rows)


@pytest.mark.asyncio(loop_scope="module")
async def test_create_boq_applies_same_currency_cwicr_rate(schema) -> None:
    from app.database import async_session_factory
    from app.modules.ai.schemas import CreateBOQFromEstimateRequest
    from app.modules.ai.service import AIService

    uid = await _seed_user()
    code = await _seed_cost_item(
        description="Structural concrete slab grade C25 30",
        unit="m3",
        rate="222.00",
        currency="EUR",
    )
    project_id = await _seed_project(owner_id=uid, currency="EUR")
    job_id = await _seed_job(
        user_id=uid,
        project_id=project_id,
        items=[_item("structural concrete slab grade", 10, 999.0, currency="EUR")],
    )

    async with async_session_factory() as s:
        result = await AIService(s).create_boq_from_estimate(
            uid,
            job_id,
            CreateBOQFromEstimateRequest(
                project_id=project_id,
                boq_name="Enriched Estimate",
                apply_enriched=True,
                region="",
            ),
        )
        await s.commit()

    assert result["positions_created"] == 1
    assert result["positions_enriched"] == 1
    # 10 * 222.00 = 2220.00 (the CWICR rate, NOT 10*999).
    assert Decimal(str(result["grand_total"])) == Decimal("2220.00")

    positions = await _fetch_positions(result["boq_id"])
    assert len(positions) == 1
    pos = positions[0]
    assert pos.source == "ai_estimate_cwicr"
    assert pos.classification.get("cwicr") == code
    assert pos.metadata_["cwicr_match"]["applied"] is True
    assert float(pos.unit_rate) == 222.0


@pytest.mark.asyncio(loop_scope="module")
async def test_create_boq_does_not_blend_foreign_currency(schema) -> None:
    from app.database import async_session_factory
    from app.modules.ai.schemas import CreateBOQFromEstimateRequest
    from app.modules.ai.service import AIService

    uid = await _seed_user()
    await _seed_cost_item(
        description="Curtain wall aluminium glazing premium",
        unit="m2",
        rate="333.00",
        currency="USD",
    )
    project_id = await _seed_project(owner_id=uid, currency="EUR")
    job_id = await _seed_job(
        user_id=uid,
        project_id=project_id,
        items=[_item("curtain wall aluminium glazing", 4, 500.0, unit="m2", currency="EUR")],
    )

    async with async_session_factory() as s:
        result = await AIService(s).create_boq_from_estimate(
            uid,
            job_id,
            CreateBOQFromEstimateRequest(
                project_id=project_id,
                boq_name="FX-safe Estimate",
                apply_enriched=True,
            ),
        )
        await s.commit()

    # No enrichment applied (currency mismatch) -> keep AI rate 4*500 = 2000.
    assert result["positions_enriched"] == 0
    assert Decimal(str(result["grand_total"])) == Decimal("2000.00")

    positions = await _fetch_positions(result["boq_id"])
    assert len(positions) == 1
    pos = positions[0]
    assert pos.source == "ai_estimate"
    assert float(pos.unit_rate) == 500.0
    match_meta = pos.metadata_.get("cwicr_match")
    if match_meta is not None:
        assert match_meta["applied"] is False


@pytest.mark.asyncio(loop_scope="module")
async def test_create_boq_without_enrich_keeps_ai_rates(schema) -> None:
    from app.database import async_session_factory
    from app.modules.ai.schemas import CreateBOQFromEstimateRequest
    from app.modules.ai.service import AIService

    uid = await _seed_user()
    await _seed_cost_item(description="Plaster internal walls smooth finish", rate="45.00", currency="EUR")
    project_id = await _seed_project(owner_id=uid, currency="EUR")
    job_id = await _seed_job(
        user_id=uid,
        project_id=project_id,
        items=[_item("plaster internal walls", 100, 60.0, unit="m2", currency="EUR")],
    )

    async with async_session_factory() as s:
        result = await AIService(s).create_boq_from_estimate(
            uid,
            job_id,
            CreateBOQFromEstimateRequest(project_id=project_id, boq_name="Raw Estimate"),
        )
        await s.commit()

    assert result.get("positions_enriched", 0) == 0
    # AI rate preserved: 100 * 60 = 6000.
    assert Decimal(str(result["grand_total"])) == Decimal("6000.00")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
