# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Round-5 carbon module audit — IDOR, race, bulk-insert, allowlist tests.

This complements the existing ``test_carbon.py`` pure-math coverage with
the security + correctness guarantees added in the Round-5 sweep:

* **IDOR — project-access enforcement.** A user who is NOT the owner of
  the project that owns an inventory must not be able to read / mutate
  any child entity (inventory, embodied entry, scope-1/2/3 entry,
  target, report). Verified by calling the service-level helpers that
  the router uses to resolve ``project_id`` — those raise / return a
  project_id the test asserts against. The router-level
  ``verify_project_access`` is the existing well-tested gate; here we
  cover the carbon-side glue that feeds it the right project_id.

* **EPD race-condition handling.** Two concurrent ``create_epd`` calls
  on the same external ``epd_id`` must produce one 409, not a 500. We
  monkey-patch the repo's ``create`` to raise ``IntegrityError`` after
  the pre-flight returns no row, simulating the race.

* **Bulk-embodied stage allowlist.** A bad stage in any element of the
  bulk payload rejects the whole batch with 400 — no half-commits.

* **Stage filter allowlist on list endpoint.** Arbitrary stage strings
  reject with 400 (was: silent empty-list scan).

* **Decimal-exact rollup with negative D-stage credits.** Module D
  (beyond system boundary) carries negative GWP credits; the rollup
  must treat them as Decimal (not float) and must NOT add them into
  the cradle-to-grave total (per ``compute_inventory_totals``).

Per ``feedback_test_isolation.md`` we use a temp SQLite file set up
BEFORE app imports so the test never touches dev/prod DB.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-carbon-idor-"))
_TMP_DB = _TMP_DIR / "carbon_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base  # noqa: E402
from app.modules.carbon.repository import (  # noqa: E402
    EmbodiedEntryRepository,
)
from app.modules.carbon.schemas import (  # noqa: E402
    CarbonInventoryCreate,
    CarbonTargetCreate,
    EmbodiedCarbonEntryCreate,
    EPDRecordCreate,
    Scope1EntryCreate,
    SustainabilityReportCreate,
)
from app.modules.carbon.service import (  # noqa: E402
    CarbonService,
    compute_inventory_totals,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


async def _make_owner(session: AsyncSession) -> uuid.UUID:
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:8]}@test.local",
        hashed_password="x",
        full_name="Test",
        role="editor",
    )
    session.add(user)
    await session.flush()
    return user.id


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Spin up a fresh in-memory SQLite engine with carbon + project tables."""
    import app.modules.carbon.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    session = Session()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def _setup_two_projects(session: AsyncSession) -> dict[str, Any]:
    """Two unrelated projects owned by two different users.

    Returns dict with: project_a, project_b, owner_a, owner_b, service.
    """
    from app.modules.projects.models import Project

    owner_a = await _make_owner(session)
    owner_b = await _make_owner(session)
    proj_a = Project(id=uuid.uuid4(), name="A", owner_id=owner_a)
    proj_b = Project(id=uuid.uuid4(), name="B", owner_id=owner_b)
    session.add_all([proj_a, proj_b])
    await session.flush()
    return {
        "project_a": proj_a,
        "project_b": proj_b,
        "owner_a": owner_a,
        "owner_b": owner_b,
        "service": CarbonService(session),
    }


# ── IDOR: inventory → project_id resolution ────────────────────────────────


@pytest.mark.asyncio
async def test_get_inventory_project_id_returns_correct_owner(
    db_session: AsyncSession,
) -> None:
    """The helper that feeds verify_project_access must return the OWNING project.

    If this ever returned the wrong project_id we'd silently allow cross-tenant
    writes — the test pins the contract.
    """
    ctx = await _setup_two_projects(db_session)
    inv_a = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="A inv"),
        user_id=None,
    )
    pid = await ctx["service"].get_inventory_project_id(inv_a.id)
    assert pid == ctx["project_a"].id, "helper must return the inventory's project_id"


@pytest.mark.asyncio
async def test_get_inventory_project_id_missing_raises_404(
    db_session: AsyncSession,
) -> None:
    """Unknown inventory UUID must 404 (not leak existence cross-tenant)."""
    service = CarbonService(db_session)
    with pytest.raises(HTTPException) as exc:
        await service.get_inventory_project_id(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_embodied_project_id_resolves_through_inventory(
    db_session: AsyncSession,
) -> None:
    """Embodied-entry IDOR gate: entry → inventory → project_id."""
    ctx = await _setup_two_projects(db_session)
    inv_a = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="A inv"),
        user_id=None,
    )
    entry = await ctx["service"].create_embodied_entry(
        EmbodiedCarbonEntryCreate(
            inventory_id=inv_a.id,
            description="x",
            quantity=Decimal("1"),
            unit="kg",
            factor_value_used=Decimal("0.1"),
            carbon_kg=Decimal("0.1"),
            stage="a1a3",
        ),
    )
    pid = await ctx["service"].get_embodied_project_id(entry.id)
    assert pid == ctx["project_a"].id


@pytest.mark.asyncio
async def test_get_scope1_project_id_resolves_through_inventory(
    db_session: AsyncSession,
) -> None:
    """Scope-1 IDOR gate: entry → inventory → project_id."""
    from datetime import date

    ctx = await _setup_two_projects(db_session)
    inv_a = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="A inv"),
        user_id=None,
    )
    entry = await ctx["service"].create_scope1(
        Scope1EntryCreate(
            inventory_id=inv_a.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            fuel_type="diesel",
            litres_or_m3=Decimal("100"),
            emission_factor_kg_co2e_per_unit=Decimal("2.68"),
        ),
    )
    pid = await ctx["service"].get_scope1_project_id(entry.id)
    assert pid == ctx["project_a"].id


@pytest.mark.asyncio
async def test_get_target_project_id_resolves(db_session: AsyncSession) -> None:
    ctx = await _setup_two_projects(db_session)
    target = await ctx["service"].create_target(
        CarbonTargetCreate(
            project_id=ctx["project_a"].id,
            name="50% by 2030",
            baseline_value=Decimal("1000"),
            target_value=Decimal("500"),
        ),
        user_id=None,
    )
    pid = await ctx["service"].get_target_project_id(target.id)
    assert pid == ctx["project_a"].id


@pytest.mark.asyncio
async def test_get_report_project_id_resolves(db_session: AsyncSession) -> None:
    from datetime import date

    ctx = await _setup_two_projects(db_session)
    report = await ctx["service"].create_report_record(
        SustainabilityReportCreate(
            project_id=ctx["project_a"].id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            framework="ghg_protocol",
        ),
        user_id=None,
    )
    pid = await ctx["service"].get_report_project_id(report.id)
    assert pid == ctx["project_a"].id


# ── EPD race-condition: pre-flight passes, IntegrityError on commit ───────


@pytest.mark.asyncio
async def test_create_epd_race_returns_409_not_500(
    db_session: AsyncSession,
) -> None:
    """Two concurrent ingests of the same epd_id: second one must 409, not 500.

    Simulates the race by stubbing the repo's ``create`` to raise
    IntegrityError AFTER the pre-flight uniqueness check has already
    returned ``None`` (the window between SELECT and INSERT).
    """
    service = CarbonService(db_session)
    # The pre-flight lookup returns None — emulate "no row yet" race condition.
    service.epd_repo.get_by_epd_id = AsyncMock(return_value=None)
    # The actual INSERT loses to a parallel writer.
    service.epd_repo.create = AsyncMock(
        side_effect=IntegrityError("INSERT", {}, Exception("UNIQUE")),
    )
    with pytest.raises(HTTPException) as exc:
        await service.create_epd(
            EPDRecordCreate(
                epd_id="EPD-RACE-001",
                source="custom",
                material_class="concrete",
                product_name="Test C30/37",
                gwp_a1a3=Decimal("0.13"),
            ),
        )
    assert exc.value.status_code == 409
    assert "already exists" in str(exc.value.detail)


# ── EPD ingest by identifier: indexed lookup, not full-table scan ─────────


@pytest.mark.asyncio
async def test_ingest_epd_by_identifier_uses_indexed_lookup(
    db_session: AsyncSession,
) -> None:
    """Re-ingesting the same identifier must call ``get_by_epd_id`` (indexed),
    not the unbounded ``list_filtered`` we used to walk."""
    service = CarbonService(db_session)
    # First ingest creates the row.
    first = await service.ingest_epd_by_identifier(
        identifier="oekobaudat:1.4.01.04",
        gwp_a1a3=Decimal("0.13"),
        product_name="C30/37",
        material_class="concrete",
    )
    assert first.epd_id == "oekobaudat:1.4.01.04"
    # Second ingest should update via indexed lookup. Spy on get_by_epd_id.
    spy = AsyncMock(wraps=service.epd_repo.get_by_epd_id)
    service.epd_repo.get_by_epd_id = spy
    second = await service.ingest_epd_by_identifier(
        identifier="oekobaudat:1.4.01.04",
        gwp_a1a3=Decimal("0.15"),
        product_name="C30/37",
        material_class="concrete",
    )
    spy.assert_called_once_with("oekobaudat:1.4.01.04")
    assert second.id == first.id
    assert Decimal(str(second.gwp_a1a3)) == Decimal("0.15")


# ── Bulk embodied: stage allowlist + atomic batch ─────────────────────────


@pytest.mark.asyncio
async def test_bulk_embodied_rejects_bad_stage_atomically(
    db_session: AsyncSession,
) -> None:
    """Bad stage in any element rejects the entire batch — no half-commit."""
    ctx = await _setup_two_projects(db_session)
    inv = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="bulk-test"),
        user_id=None,
    )
    good = EmbodiedCarbonEntryCreate(
        inventory_id=inv.id,
        description="ok",
        quantity=Decimal("1"),
        unit="kg",
        factor_value_used=Decimal("0.1"),
        carbon_kg=Decimal("0.1"),
        stage="a1a3",
    )
    # Build a bad entry by patching schema validation off — payload-level
    # validation already rejects via Pydantic, but the service layer must
    # also defend in depth because the bulk wrapper takes raw dicts in some
    # call paths (BOQ importer).
    bad_dict = good.model_dump()
    bad_dict["stage"] = "z9"  # not in EN_15978_STAGES
    bad = EmbodiedCarbonEntryCreate.model_construct(**bad_dict)
    with pytest.raises(HTTPException) as exc:
        await ctx["service"].bulk_create_embodied(inv.id, [good, bad])
    assert exc.value.status_code == 400
    # And nothing was persisted from the good entry either — atomic batch.
    rows = await EmbodiedEntryRepository(db_session).list_for_inventory(inv.id)
    assert rows == [], "atomic batch must not half-commit on a bad entry"


@pytest.mark.asyncio
async def test_bulk_embodied_empty_returns_zero(db_session: AsyncSession) -> None:
    """Empty bulk request is a no-op (was: silent zero write before)."""
    ctx = await _setup_two_projects(db_session)
    inv = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="empty"),
        user_id=None,
    )
    n = await ctx["service"].bulk_create_embodied(inv.id, [])
    assert n == 0


@pytest.mark.asyncio
async def test_bulk_embodied_persists_all_good_entries(
    db_session: AsyncSession,
) -> None:
    """Happy path: N entries → N rows, single flush."""
    ctx = await _setup_two_projects(db_session)
    inv = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="happy"),
        user_id=None,
    )
    payloads = [
        EmbodiedCarbonEntryCreate(
            inventory_id=inv.id,
            description=f"entry-{i}",
            quantity=Decimal(str(i)),
            unit="kg",
            factor_value_used=Decimal("0.1"),
            carbon_kg=Decimal(str(i)) * Decimal("0.1"),
            stage="a1a3",
        )
        for i in range(1, 6)
    ]
    n = await ctx["service"].bulk_create_embodied(inv.id, payloads)
    assert n == 5
    rows = await EmbodiedEntryRepository(db_session).list_for_inventory(inv.id)
    assert len(rows) == 5


# ── Stage filter allowlist on list endpoint ────────────────────────────────


@pytest.mark.asyncio
async def test_list_embodied_rejects_unknown_stage(
    db_session: AsyncSession,
) -> None:
    """Unknown stage string must 400, not silently return [] from a full scan."""
    ctx = await _setup_two_projects(db_session)
    inv = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="stage-test"),
        user_id=None,
    )
    with pytest.raises(HTTPException) as exc:
        await ctx["service"].list_embodied_entries(inv.id, stage="bogus")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_list_embodied_accepts_known_stage(
    db_session: AsyncSession,
) -> None:
    """Known EN 15978 stage passes through (granular codes like c2 too)."""
    ctx = await _setup_two_projects(db_session)
    inv = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="stage-test-ok"),
        user_id=None,
    )
    # Granular c2 normalises and is accepted (we still query by the original
    # column value — empty list back is fine, the point is no 400).
    rows, total = await ctx["service"].list_embodied_entries(inv.id, stage="c2")
    assert isinstance(rows, list)
    assert total == 0


# ── Decimal-exact rollup with negative module-D credits ───────────────────


def test_rollup_d_credits_negative_decimal_exact() -> None:
    """Module D carries negative credits; rollup keeps Decimal precision and
    must NOT add D into the cradle-to-grave total (D is "beyond system
    boundary"). The float-drift property we pin: 0.1 + 0.2 + 0.3 = 0.6 in
    Decimal, but in float you'd see 0.6000000000000001.
    """
    from types import SimpleNamespace

    inv_id = uuid.uuid4()
    # 0.1 + 0.2 + 0.3 sums exactly to 0.6 in Decimal — would drift in float.
    embodied = [
        SimpleNamespace(stage="a1a3", carbon_kg=Decimal("100")),
        SimpleNamespace(stage="d", carbon_kg=Decimal("-0.1")),
        SimpleNamespace(stage="d", carbon_kg=Decimal("-0.2")),
        SimpleNamespace(stage="d", carbon_kg=Decimal("-0.3")),
    ]
    totals = compute_inventory_totals(inv_id, embodied)
    # D credits sum to exactly -0.6, not -0.6000000000000001 drift.
    assert Decimal(totals["embodied_d"]) == Decimal("-0.6")
    # Total is cradle-to-grave (A1-A5 + B + C + operational + scope3),
    # D is excluded by design — total must be exactly 100.
    assert Decimal(totals["total"]) == Decimal("100")


# ── Auto-fill carbon_kg correctness (Fix 1) ──────────────────────────────


@pytest.mark.asyncio
async def test_create_embodied_entry_autofill_direct_multiply(
    db_session: AsyncSession,
) -> None:
    """Auto-fill carbon_kg = quantity × factor_value_used (direct multiply).

    Regression: the old code called compute_embodied_entry_carbon(qty, unit,
    factor, unit) — passing entry.unit for BOTH qty_unit and factor_unit.
    When the factor is declared per-kg but the entry unit is m3, the identity
    branch fires and returns qty (m3) × factor instead of the correct result.
    The fix: auto-fill multiplies directly without any unit conversion so
    callers own the normalisation step (as they do in assign_boq_position_carbon).
    """
    ctx = await _setup_two_projects(db_session)
    inv = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="autofill-test"),
        user_id=None,
    )
    # Pass carbon_kg=0 so the auto-fill path triggers.
    entry = await ctx["service"].create_embodied_entry(
        EmbodiedCarbonEntryCreate(
            inventory_id=inv.id,
            description="auto",
            quantity=Decimal("10"),
            unit="m3",
            factor_value_used=Decimal("0.13"),
            carbon_kg=Decimal("0"),
            stage="a1a3",
        ),
    )
    # 10 × 0.13 = 1.3 exactly (no float drift).
    assert Decimal(str(entry.carbon_kg)) == Decimal("1.3"), (
        f"auto-fill produced wrong carbon_kg: {entry.carbon_kg}"
    )


# ── EPD source allowlist includes epd_international (Fix 2) ──────────────


def test_epd_record_create_accepts_epd_international_source() -> None:
    """EPDRecordCreate must accept source='epd_international' after the fix.

    Before the fix the pattern was ^(oekobaudat|ice|ec3|custom)$ which would
    reject the epd_international source returned by parse_epd_identifier for
    environdec/EPD-Norge URLs — silently unusable API surface.
    """
    from app.modules.carbon.schemas import EPDRecordCreate

    rec = EPDRecordCreate(
        epd_id="epd_international:EPD-TEST-001",
        source="epd_international",
        material_class="concrete",
        product_name="Test product",
        gwp_a1a3=Decimal("0.15"),
    )
    assert rec.source == "epd_international"


# ── Permission registry orphan check ──────────────────────────────────────


def test_carbon_read_permission_registered() -> None:
    """carbon.read is defined in the permission registry even though it's
    not yet on every GET — it's needed for grid-factor lookup + future
    read-gating. Pin its presence so a refactor doesn't drop it silently.
    """
    from app.core.permissions import permission_registry
    from app.modules.carbon import permissions as carbon_perms

    carbon_perms.register_carbon_permissions()
    perms = permission_registry.list_modules().get("carbon", [])
    assert "carbon.read" in perms


# ── Structured-log emission on inventory finalize ─────────────────────────


@pytest.mark.asyncio
async def test_finalize_inventory_emits_structured_log(
    db_session: AsyncSession,
) -> None:
    """Finalize must log a structured carbon.inventory.finalized line with
    the project_id, totals, and status — auditable carbon footprint freeze
    is a high-trust event per Round-5.
    """
    ctx = await _setup_two_projects(db_session)
    inv = await ctx["service"].create_inventory(
        CarbonInventoryCreate(project_id=ctx["project_a"].id, name="freeze-me"),
        user_id=None,
    )
    with (
        patch(
            "app.modules.carbon.service.event_bus.publish_detached",
        ),
        patch("app.modules.carbon.service.logger") as log_mock,
    ):
        await ctx["service"].finalize_inventory(inv.id, status_value="baseline")
    # The info-level structured log MUST be the carbon.inventory.finalized
    # event with project_id+inventory_id+total_kg_co2e fields.
    info_calls = [c for c in log_mock.info.call_args_list]
    assert any(
        c.args[0] == "carbon.inventory.finalized"
        and "project_id" in c.kwargs.get("extra", {})
        and "total_kg_co2e" in c.kwargs.get("extra", {})
        for c in info_calls
    ), f"expected structured finalize log, got: {info_calls}"
