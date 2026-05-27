# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for dashboard rollup service (module ``oe_dashboard``).

Coverage:
* Each built-in widget kind produces expected aggregate from fixture data.
* Empty-state (zero projects) → zeroes / None, never crash.
* Permission-filtered scope (user sees only own projects).
* ``compute_rollup`` dispatcher — unknown widget id silently skipped.
* ``WidgetConfigItem`` schema validation — 422-path is exercised.
"""

from __future__ import annotations

import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base

if TYPE_CHECKING:
    from app.modules.projects.models import Project

# ── Model registration (must precede create_all) ───────────────────────────


def _register_models() -> None:
    import app.modules.boq.models  # noqa: F401
    import app.modules.changeorders.models  # noqa: F401
    import app.modules.daily_diary.models  # noqa: F401
    import app.modules.finance.models  # noqa: F401
    import app.modules.procurement.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.safety.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    import app.modules.validation.models  # noqa: F401


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    """Per-test isolated SQLite DB with all required tables."""
    tmp_db = Path(tempfile.mkdtemp()) / "rollup_unit.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


async def _make_user(session: AsyncSession, *, role: str = "member") -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    user = User(
        id=uid,
        email=f"u-{uid.hex[:6]}@test.io",
        hashed_password="x",
        full_name="Test User",
        role=role,
    )
    session.add(user)
    await session.flush()
    return uid


async def _make_project(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    name: str = "Test Project",
    status: str = "active",
) -> Project:
    from app.modules.projects.models import Project

    p = Project(
        id=uuid.uuid4(),
        name=name,
        owner_id=owner_id,
        status=status,
        currency="EUR",
    )
    session.add(p)
    await session.flush()
    return p


# ── Empty-state tests ──────────────────────────────────────────────────────


class TestEmptyState:
    """All compute_* functions must return sensible zero-state, never crash."""

    @pytest.mark.asyncio
    async def test_boq_summary_no_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_boq_summary

        result = await compute_boq_summary(session, [])
        assert result["total_boqs"] == 0
        assert result["active_boqs"] == 0
        assert result["total_value_eur"] == "0.00"
        assert result["position_count"] == 0
        assert result["last_boq"] is None
        assert result["by_project"] == []

    @pytest.mark.asyncio
    async def test_validation_score_no_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_validation_score

        result = await compute_validation_score(session, [])
        assert result["avg"] is None
        assert result["passed"] == 0
        assert result["by_project"] == []

    @pytest.mark.asyncio
    async def test_hse_scorecard_no_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_hse_scorecard

        result = await compute_hse_scorecard(session, [])
        assert result["total"] == 0
        assert result["days_since_last"] is None

    @pytest.mark.asyncio
    async def test_budget_variance_no_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_budget_variance

        result = await compute_budget_variance(session, [])
        assert result["over_budget_count"] == 0
        assert result["top_over"] == []

    @pytest.mark.asyncio
    async def test_procurement_no_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_procurement_pipeline

        result = await compute_procurement_pipeline(session, [])
        assert result["rfqs_pending"] == 0
        assert result["pos_issued"] == 0

    @pytest.mark.asyncio
    async def test_change_orders_no_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_change_orders

        result = await compute_change_orders(session, [])
        # empty list → no rows → open_count = 0
        assert result["open_count"] == 0
        assert result["total_impact"] == "0.00"

    @pytest.mark.asyncio
    async def test_risk_top_no_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_risk_top

        result = await compute_risk_top(session, [])
        assert result["top"] == []

    @pytest.mark.asyncio
    async def test_schedule_critical_no_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_schedule_critical

        result = await compute_schedule_critical(session, [])
        assert result["top"] == []
        assert result["total_schedules"] == 0

    @pytest.mark.asyncio
    async def test_weather_site_no_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_weather_site

        result = await compute_weather_site(session, [])
        assert result["project_id"] is None
        assert result["temperature_c"] is None


# ── Aggregate-value tests ─────────────────────────────────────────────────


class TestBOQSummaryAggregate:
    """compute_boq_summary sums correctly from fixture data."""

    @pytest.mark.asyncio
    async def test_total_value_two_boqs(self, session: AsyncSession) -> None:
        from app.modules.boq.models import BOQ, Position
        from app.modules.dashboard.service import compute_boq_summary

        uid = await _make_user(session)
        project = await _make_project(session, uid)

        boq1 = BOQ(id=uuid.uuid4(), project_id=project.id, name="BOQ-A", status="draft")
        boq2 = BOQ(id=uuid.uuid4(), project_id=project.id, name="BOQ-B", status="draft")
        session.add_all([boq1, boq2])
        await session.flush()

        # boq1: 2 positions totalling 1 000 EUR
        session.add(
            Position(
                boq_id=boq1.id,
                ordinal="01",
                description="Item A",
                unit="m2",
                quantity="10",
                unit_rate="50",
                total="500",
            )
        )
        session.add(
            Position(
                boq_id=boq1.id,
                ordinal="02",
                description="Item B",
                unit="m2",
                quantity="10",
                unit_rate="50",
                total="500",
            )
        )
        # boq2: 1 position, 250 EUR, zero quantity → missing_qty flag
        session.add(
            Position(
                boq_id=boq2.id,
                ordinal="01",
                description="Item C",
                unit="m3",
                quantity="0",
                unit_rate="250",
                total="0",
            )
        )
        await session.commit()

        result = await compute_boq_summary(session, [project])

        assert result["total_boqs"] == 2
        assert result["position_count"] == 3
        assert Decimal(result["total_value_eur"]) == Decimal("1000.00")
        assert result["positions_missing_quantity"] == 1
        assert result["last_boq"] is not None
        assert len(result["by_project"]) == 1

    @pytest.mark.asyncio
    async def test_active_boq_count_excludes_archived(self, session: AsyncSession) -> None:
        from app.modules.boq.models import BOQ
        from app.modules.dashboard.service import compute_boq_summary

        uid = await _make_user(session)
        project = await _make_project(session, uid)

        session.add(BOQ(id=uuid.uuid4(), project_id=project.id, name="Draft", status="draft"))
        session.add(BOQ(id=uuid.uuid4(), project_id=project.id, name="Archived", status="archived"))
        session.add(BOQ(id=uuid.uuid4(), project_id=project.id, name="Closed", status="closed"))
        await session.commit()

        result = await compute_boq_summary(session, [project])
        assert result["total_boqs"] == 3
        assert result["active_boqs"] == 1  # only "draft" survives


class TestValidationScoreAggregate:
    """compute_validation_score returns average of latest-per-project scores."""

    @pytest.mark.asyncio
    async def test_average_score(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_validation_score
        from app.modules.validation.models import ValidationReport

        uid = await _make_user(session)
        p1 = await _make_project(session, uid, name="P1")
        p2 = await _make_project(session, uid, name="P2")

        session.add(
            ValidationReport(
                id=uuid.uuid4(),
                project_id=p1.id,
                target_type="boq",
                target_id=str(uuid.uuid4()),
                rule_set="boq_quality",
                status="passed",
                score="0.9",
            )
        )
        session.add(
            ValidationReport(
                id=uuid.uuid4(),
                project_id=p2.id,
                target_type="boq",
                target_id=str(uuid.uuid4()),
                rule_set="boq_quality",
                status="warnings",
                score="0.7",
            )
        )
        await session.commit()

        result = await compute_validation_score(session, [p1, p2])
        assert result["avg"] == pytest.approx(0.8, abs=0.01)
        assert result["passed"] == 1
        assert result["warnings"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_no_reports_avg_none(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_validation_score

        uid = await _make_user(session)
        project = await _make_project(session, uid)
        result = await compute_validation_score(session, [project])
        assert result["avg"] is None


class TestHSEScorecardAggregate:
    """compute_hse_scorecard counts incidents correctly."""

    @pytest.mark.asyncio
    async def test_near_miss_and_recordable(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_hse_scorecard
        from app.modules.safety.models import SafetyIncident

        uid = await _make_user(session)
        project = await _make_project(session, uid)

        session.add(
            SafetyIncident(
                id=uuid.uuid4(),
                project_id=project.id,
                incident_number="INC-001",
                incident_date="2026-05-10",
                incident_type="near_miss",
                title="Near miss event",
                description="Scaffolding near miss",
                severity="minor",
                osha_recordable=False,
            )
        )
        session.add(
            SafetyIncident(
                id=uuid.uuid4(),
                project_id=project.id,
                incident_number="INC-002",
                incident_date="2026-05-15",
                incident_type="incident",
                title="Recordable incident",
                description="Worker injured",
                severity="major",
                osha_recordable=True,
            )
        )
        await session.commit()

        result = await compute_hse_scorecard(session, [project])
        assert result["total"] == 2
        assert result["near_miss"] == 1
        assert result["recordables"] >= 1  # osha_recordable=True


# ── Permission-filtering tests ─────────────────────────────────────────────


class TestPermissionFiltering:
    """accessible_projects filters by owner — IDOR-safe boundary."""

    @pytest.mark.asyncio
    async def test_regular_user_sees_only_own_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import accessible_projects

        uid_a = await _make_user(session)
        uid_b = await _make_user(session)

        p_a = await _make_project(session, uid_a, name="Alice-Project")
        _p_b = await _make_project(session, uid_b, name="Bob-Project")
        await session.commit()

        projects = await accessible_projects(session, str(uid_a))
        ids = {p.id for p in projects}
        assert p_a.id in ids
        assert _p_b.id not in ids

    @pytest.mark.asyncio
    async def test_admin_sees_all_projects(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import accessible_projects

        admin_id = await _make_user(session, role="admin")
        uid_b = await _make_user(session)

        p1 = await _make_project(session, admin_id, name="Admin-Proj")
        p2 = await _make_project(session, uid_b, name="Other-Proj")
        await session.commit()

        projects = await accessible_projects(session, str(admin_id))
        ids = {p.id for p in projects}
        assert p1.id in ids
        assert p2.id in ids

    @pytest.mark.asyncio
    async def test_archived_project_excluded(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import accessible_projects

        admin_id = await _make_user(session, role="admin")
        _p_archived = await _make_project(session, admin_id, name="Old", status="archived")
        p_active = await _make_project(session, admin_id, name="Active", status="active")
        await session.commit()

        projects = await accessible_projects(session, str(admin_id))
        ids = {p.id for p in projects}
        assert p_active.id in ids
        assert _p_archived.id not in ids

    @pytest.mark.asyncio
    async def test_requested_ids_outside_scope_dropped(self, session: AsyncSession) -> None:
        """Requesting another user's project ID → silently dropped (IDOR-safe)."""
        from app.modules.dashboard.service import accessible_projects

        uid_a = await _make_user(session)
        uid_b = await _make_user(session)

        _p_a = await _make_project(session, uid_a, name="A-Proj")
        p_b = await _make_project(session, uid_b, name="B-Proj")
        await session.commit()

        # uid_a requests p_b's ID — must be dropped silently.
        projects = await accessible_projects(
            session,
            str(uid_a),
            requested_ids=[p_b.id],
        )
        assert projects == []


# ── Dispatcher tests ───────────────────────────────────────────────────────


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_unknown_widget_silently_skipped(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_rollup

        uid = await _make_user(session)
        project = await _make_project(session, uid)
        await session.commit()

        result = await compute_rollup(
            session,
            [project],
            ["boq_summary", "this_does_not_exist"],
        )
        assert "boq_summary" in result
        assert "this_does_not_exist" not in result

    @pytest.mark.asyncio
    async def test_single_widget_only(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_rollup

        uid = await _make_user(session)
        project = await _make_project(session, uid)
        await session.commit()

        result = await compute_rollup(session, [project], ["risk_top"])
        assert set(result.keys()) == {"risk_top"}

    @pytest.mark.asyncio
    async def test_empty_widget_list_returns_empty(self, session: AsyncSession) -> None:
        from app.modules.dashboard.service import compute_rollup

        uid = await _make_user(session)
        project = await _make_project(session, uid)
        await session.commit()

        result = await compute_rollup(session, [project], [])
        assert result == {}


# ── Widget config schema validation ───────────────────────────────────────


class TestWidgetConfigValidation:
    """WidgetConfigItem validates widget config — 422 path in Pydantic."""

    def test_valid_config_accepted(self) -> None:
        from app.modules.dashboard.schemas import WidgetConfigItem

        item = WidgetConfigItem(
            widget_id="boq_summary",
            config={"show_last_boq": True, "max_by_project": 5},
        )
        assert item.widget_id == "boq_summary"
        assert item.config["max_by_project"] == 5

    def test_unknown_widget_id_rejected(self) -> None:
        from pydantic import ValidationError

        from app.modules.dashboard.schemas import WidgetConfigItem

        with pytest.raises(ValidationError, match="Unknown widget_id"):
            WidgetConfigItem(widget_id="totally_fake", config={})

    def test_unknown_config_key_rejected(self) -> None:
        from pydantic import ValidationError

        from app.modules.dashboard.schemas import WidgetConfigItem

        with pytest.raises(ValidationError, match="Unknown config key"):
            WidgetConfigItem(
                widget_id="boq_summary",
                config={"evil_key": True},
            )

    def test_wrong_value_type_rejected(self) -> None:
        from pydantic import ValidationError

        from app.modules.dashboard.schemas import WidgetConfigItem

        with pytest.raises(ValidationError, match="must be bool"):
            WidgetConfigItem(
                widget_id="boq_summary",
                config={"show_last_boq": "yes"},  # str instead of bool
            )

    def test_int_out_of_bounds_rejected(self) -> None:
        from pydantic import ValidationError

        from app.modules.dashboard.schemas import WidgetConfigItem

        with pytest.raises(ValidationError, match="between 1 and 500"):
            WidgetConfigItem(
                widget_id="boq_summary",
                config={"max_by_project": 9999},
            )

    def test_float_out_of_bounds_rejected(self) -> None:
        from pydantic import ValidationError

        from app.modules.dashboard.schemas import WidgetConfigItem

        with pytest.raises(ValidationError, match="between 0"):
            WidgetConfigItem(
                widget_id="validation_score",
                config={"target_score": 1.5},
            )

    def test_empty_config_always_valid(self) -> None:
        from app.modules.dashboard.schemas import WidgetConfigItem

        for widget_id in [
            "boq_summary",
            "validation_score",
            "clash_health",
            "schedule_critical",
            "risk_top",
            "hse_scorecard",
            "procurement_pipeline",
            "budget_variance",
            "change_orders",
            "weather_site",
        ]:
            item = WidgetConfigItem(widget_id=widget_id, config={})
            assert item.widget_id == widget_id

    def test_rollup_request_bad_config_raises_validation_error(self) -> None:
        from pydantic import ValidationError

        from app.modules.dashboard.schemas import RollupRequest

        with pytest.raises(ValidationError):
            RollupRequest(
                widget_configs=[
                    {"widget_id": "boq_summary", "config": {"evil": True}},
                ],
            )
