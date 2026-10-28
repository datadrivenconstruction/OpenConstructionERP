"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit + service tests for the Asset Operations module.

Two layers:
  * Pure functions (lifecycle health, discovery scoring) - no DB.
  * Service layer against the shared PostgreSQL unit DB with per-test
    transaction isolation (same fixture style as
    ``test_bim_asset_register.py``).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets import discovery as disc
from app.modules.assets import lifecycle as lc
from app.modules.assets.service import AssetOpsService
from app.modules.bim_hub.models import BIMElement, BIMModel
from tests._pg import transactional_session

TODAY = date(2026, 6, 6)


# ── Pure: lifecycle health ────────────────────────────────────────────────────


class TestComputeHealth:
    def test_warranty_expired(self):
        h = lc.compute_health({"warranty_until": "2020-01-01"}, today=TODAY)
        assert h.warranty_status == lc.WARRANTY_EXPIRED
        assert h.days_to_warranty_expiry is not None and h.days_to_warranty_expiry < 0
        assert "warranty_expired" in h.issues
        assert h.attention_score >= 40

    def test_warranty_expiring_within_lead(self):
        h = lc.compute_health({"warranty_until": "2026-07-15"}, today=TODAY, warranty_lead_days=90)
        assert h.warranty_status == lc.WARRANTY_EXPIRING
        assert 0 <= (h.days_to_warranty_expiry or -1) <= 90

    def test_warranty_ok_far_future(self):
        h = lc.compute_health({"warranty_until": "2030-01-01"}, today=TODAY)
        assert h.warranty_status == lc.WARRANTY_OK
        assert h.attention_score == 0

    def test_warranty_unknown_when_missing(self):
        h = lc.compute_health({}, today=TODAY)
        assert h.warranty_status == lc.WARRANTY_UNKNOWN
        assert h.maintenance_status == lc.MAINT_UNKNOWN

    def test_age_from_installation_date(self):
        h = lc.compute_health({"installation_date": "2016-06-06"}, today=TODAY)
        assert h.age_years == pytest.approx(10.0, abs=0.1)

    def test_maintenance_overdue_from_interval_and_install(self):
        # Installed 2 years ago, 180-day interval, never serviced -> overdue.
        h = lc.compute_health(
            {"installation_date": "2024-01-01", "maintenance_interval_days": "180"},
            today=TODAY,
        )
        assert h.maintenance_status == lc.MAINT_OVERDUE
        assert h.next_maintenance_due is not None

    def test_maintenance_uses_latest_service_log_entry(self):
        h = lc.compute_health(
            {
                "maintenance_interval_days": "365",
                "service_log": [
                    {"date": "2026-05-01", "note": "annual"},
                    {"date": "2025-01-01", "note": "older"},
                ],
            },
            today=TODAY,
        )
        # Last service 2026-05-01 + 365d -> well in the future -> ok.
        assert h.maintenance_status == lc.MAINT_OK
        assert h.last_serviced == "2026-05-01"
        assert h.service_log_count == 2

    def test_decommissioned_zeroes_attention(self):
        h = lc.compute_health(
            {
                "warranty_until": "2020-01-01",
                "operational_status": "decommissioned",
            },
            today=TODAY,
        )
        assert h.attention_score == 0

    def test_unparseable_dates_are_unknown_not_raise(self):
        h = lc.compute_health({"warranty_until": "not-a-date", "installation_date": ""}, today=TODAY)
        assert h.warranty_status == lc.WARRANTY_UNKNOWN
        assert h.age_days is None


# ── Pure: discovery scoring ───────────────────────────────────────────────────


class TestDiscovery:
    def test_mechanical_equipment_is_candidate(self):
        cs = disc.score_candidate(
            element_type="Mechanical Equipment",
            properties={"category": "Mechanical Equipment", "manufacturer": "Siemens"},
        )
        assert cs.is_candidate
        assert cs.score >= 35

    def test_wall_is_rejected(self):
        cs = disc.score_candidate(element_type="Walls", properties={"category": "Walls"})
        assert not cs.is_candidate
        assert cs.score == 0

    def test_already_tracked_never_candidate(self):
        cs = disc.score_candidate(element_type="Pump", properties={"manufacturer": "X"}, already_tracked=True)
        assert not cs.is_candidate

    def test_geometry_overrides_property_signal(self):
        # A wall with a stray manufacturer prop is still geometry.
        cs = disc.score_candidate(element_type="Basic Wall", properties={"category": "Walls", "manufacturer": "X"})
        assert not cs.is_candidate

    def test_both_spellings_of_specialty_equipment_score_the_same(self):
        # specialty is American, speciality British, both correct, and authoring
        # templates ship both. The variant scored zero with nothing logged, so a
        # whole category of equipment was simply absent from the register.
        american = disc.score_candidate(
            element_type="Specialty Equipment", properties={"category": "Specialty Equipment"}
        )
        british = disc.score_candidate(
            element_type="Speciality Equipment", properties={"category": "Speciality Equipment"}
        )
        assert british.is_candidate
        assert british.score == american.score
        assert british.reasons == american.reasons

    def test_a_geometry_word_in_the_family_name_never_zeroes_a_real_category(self):
        # A family name says where plant is MOUNTED, not what it is. Real models
        # ship "Floor Mounted Pump", "Wall Hung Boiler" and "Rooftop AHU", and
        # matching the geometry negatives against the family name rejected all
        # of them before the positive category was ever read. Asserted over the
        # whole negative vocabulary, because each word fails the same silent way.
        for word in disc._GEOMETRY_CATEGORY_HINTS:
            cs = disc.score_candidate(
                element_type="Mechanical Equipment",
                properties={"category": "Mechanical Equipment", "family": f"{word} mounted pump"},
            )
            assert cs.is_candidate, f"{word!r} in the family name zeroed mechanical equipment"
            assert cs.score >= 35

    def test_a_geometry_word_in_the_category_still_rejects(self):
        # Narrowing where the negatives look must not cost them their job.
        for category in ("Walls", "Floors", "Structural Framing", "Generic Models"):
            cs = disc.score_candidate(element_type=category, properties={"category": category})
            assert not cs.is_candidate, f"{category!r} was accepted as an asset"
            assert cs.score == 0

    def test_extract_suggested_asset_info_maps_keys(self):
        out = disc.extract_suggested_asset_info({"Manufacturer": "Grundfos", "Type Name": "CR-5", "Mark": "P-12"})
        assert out == {"manufacturer": "Grundfos", "model": "CR-5", "asset_tag": "P-12"}


# ── Service layer ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _seed(session: AsyncSession, project_id, **overrides) -> BIMElement:
    model = BIMModel(
        project_id=project_id,
        name=overrides.pop("model_name", "Mechanical.rvt"),
        status="ready",
    )
    session.add(model)
    await session.flush()
    el = BIMElement(
        model_id=model.id,
        stable_id=overrides.pop("stable_id", f"el-{uuid.uuid4().hex[:6]}"),
        element_type=overrides.pop("element_type", "Pump"),
        name=overrides.pop("name", "Pump A"),
        properties=overrides.pop("properties", {}),
        asset_info=overrides.pop("asset_info", {}),
        is_tracked_asset=overrides.pop("is_tracked_asset", False),
        **overrides,
    )
    session.add(el)
    await session.flush()
    await session.refresh(el)
    return el


class _OwnedProject:
    """Small holder for a seeded (user, project) pair used by write-path tests."""

    __slots__ = ("project_id", "user_id")

    def __init__(self, project_id, user_id):
        self.project_id = project_id
        self.user_id = user_id


async def _seed_owned_project(session: AsyncSession) -> _OwnedProject:
    """Seed a real user and a project they own; return both ids.

    The asset write paths call ``verify_project_access``, which only passes for
    the project owner (or an admin / team member). Tests that exercise a write
    must therefore have a real project row with a matching owner.
    """
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(email=f"asset-owner-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x")
    session.add(user)
    await session.flush()

    project = Project(name="Asset Ops Test", owner_id=user.id)
    session.add(project)
    await session.flush()

    return _OwnedProject(project_id=project.id, user_id=user.id)


class TestAssetOpsService:
    @pytest.mark.asyncio
    async def test_list_enriches_with_health_and_sorts_by_attention(self, session):
        pid = uuid.uuid4()
        await _seed(
            session,
            pid,
            stable_id="ok-asset",
            asset_info={"warranty_until": "2030-01-01", "operational_status": "operational"},
            is_tracked_asset=True,
        )
        await _seed(
            session,
            pid,
            stable_id="bad-asset",
            asset_info={"warranty_until": "2020-01-01"},
            is_tracked_asset=True,
        )
        svc = AssetOpsService(session)
        resp = await svc.list_assets(pid, sort="attention")
        assert resp.total == 2
        # Worst (expired warranty) first.
        assert resp.items[0].stable_id == "bad-asset"
        assert resp.items[0].health.warranty_status == lc.WARRANTY_EXPIRED

    @pytest.mark.asyncio
    async def test_warranty_status_filter_is_computed(self, session):
        pid = uuid.uuid4()
        await _seed(
            session,
            pid,
            stable_id="exp",
            asset_info={"warranty_until": "2020-01-01"},
            is_tracked_asset=True,
        )
        await _seed(
            session,
            pid,
            stable_id="fine",
            asset_info={"warranty_until": "2030-01-01"},
            is_tracked_asset=True,
        )
        svc = AssetOpsService(session)
        resp = await svc.list_assets(pid, warranty_status="expired")
        assert resp.total == 1
        assert resp.items[0].stable_id == "exp"

    @pytest.mark.asyncio
    async def test_needs_attention_filter_total_matches_portfolio_count(self, session):
        """The KPI figure and the rows behind it must be the same number.

        The tile count comes from the portfolio roll-up, computed over every
        asset in the project. The list is paginated, so if the two were
        computed separately a user could click a tile reading three and be
        shown a different number of rows with nothing to explain the gap.
        Asserting ``total`` against ``needs_attention`` is what pins them
        together; ``limit=1`` is deliberate, so a page smaller than the match
        set cannot disguise a disagreement.
        """
        pid = uuid.uuid4()
        # Two need attention (expired warranty, overdue maintenance), one does
        # not, and one is decommissioned - which scores zero however bad its
        # warranty looks, so it must not be counted or listed.
        await _seed(
            session, pid, stable_id="expired", asset_info={"warranty_until": "2020-01-01"}, is_tracked_asset=True
        )
        await _seed(
            session,
            pid,
            stable_id="overdue",
            asset_info={"installation_date": "2024-01-01", "maintenance_interval_days": "180"},
            is_tracked_asset=True,
        )
        await _seed(
            session,
            pid,
            stable_id="healthy",
            asset_info={"warranty_until": "2031-01-01", "operational_status": "operational"},
            is_tracked_asset=True,
        )
        await _seed(
            session,
            pid,
            stable_id="retired",
            asset_info={"warranty_until": "2019-01-01", "operational_status": "decommissioned"},
            is_tracked_asset=True,
        )

        svc = AssetOpsService(session)
        summary = await svc.portfolio_summary(pid)
        filtered = await svc.list_assets(pid, needs_attention=True, limit=1)

        assert summary.needs_attention == 2
        assert filtered.total == summary.needs_attention
        # Paginated down to one row, but still reporting the full match count.
        assert len(filtered.items) == 1
        assert filtered.total == 2

        everything = await svc.list_assets(pid, needs_attention=True, limit=100)
        assert {r.stable_id for r in everything.items} == {"expired", "overdue"}

    @pytest.mark.asyncio
    async def test_needs_attention_filter_off_by_default(self, session):
        """Absent the flag the list is unfiltered, so existing callers are unaffected."""
        pid = uuid.uuid4()
        await _seed(
            session, pid, stable_id="expired", asset_info={"warranty_until": "2020-01-01"}, is_tracked_asset=True
        )
        await _seed(
            session, pid, stable_id="healthy", asset_info={"warranty_until": "2031-01-01"}, is_tracked_asset=True
        )

        svc = AssetOpsService(session)
        assert (await svc.list_assets(pid)).total == 2

    @pytest.mark.asyncio
    async def test_portfolio_summary_counts(self, session):
        pid = uuid.uuid4()
        await _seed(session, pid, asset_info={"warranty_until": "2020-01-01"}, is_tracked_asset=True)
        await _seed(
            session,
            pid,
            asset_info={
                "warranty_until": (date.today() + timedelta(days=30)).isoformat(),
                "operational_status": "operational",
            },
            is_tracked_asset=True,
        )
        await _seed(
            session,
            pid,
            asset_info={"warranty_until": "2031-01-01", "operational_status": "operational"},
            is_tracked_asset=True,
        )
        svc = AssetOpsService(session)
        s = await svc.portfolio_summary(pid)
        assert s.total_assets == 3
        assert s.warranties_expired == 1
        assert s.warranties_expiring_soon == 1
        assert s.needs_attention >= 2
        assert s.by_operational_status.get("operational") == 2

    @pytest.mark.asyncio
    async def test_discover_finds_mechanical_skips_walls_and_tracked(self, session):
        pid = uuid.uuid4()
        await _seed(
            session,
            pid,
            stable_id="ahu",
            element_type="Mechanical Equipment",
            properties={"category": "Mechanical Equipment", "manufacturer": "Trane"},
            is_tracked_asset=False,
        )
        await _seed(
            session,
            pid,
            stable_id="wall",
            element_type="Walls",
            properties={"category": "Walls"},
            is_tracked_asset=False,
        )
        await _seed(
            session,
            pid,
            stable_id="already",
            element_type="Pump",
            properties={"category": "Mechanical Equipment"},
            is_tracked_asset=True,
        )
        svc = AssetOpsService(session)
        resp = await svc.discover_candidates(pid)
        ids = {c.stable_id for c in resp.items}
        assert "ahu" in ids
        assert "wall" not in ids
        assert "already" not in ids
        assert resp.already_tracked == 1
        # Suggested asset_info lifted from properties.
        ahu = next(c for c in resp.items if c.stable_id == "ahu")
        assert ahu.suggested_asset_info.get("manufacturer") == "Trane"

    @pytest.mark.asyncio
    async def test_warranty_alerts_scan_without_dispatch(self, session):
        pid = uuid.uuid4()
        await _seed(session, pid, asset_info={"warranty_until": "2020-01-01"}, is_tracked_asset=True)
        await _seed(session, pid, asset_info={"warranty_until": "2031-01-01"}, is_tracked_asset=True)
        svc = AssetOpsService(session)
        resp = await svc.warranty_alerts(pid, lead_days=90, dispatch=False)
        assert resp.total == 1
        assert resp.dispatched is False
        assert resp.items[0].status == lc.WARRANTY_EXPIRED

    @pytest.mark.asyncio
    async def test_append_service_log_persists_and_recomputes(self, session):
        # append_service_log enforces project access (IDOR defence), so the
        # element's parent project must exist and the caller must own it. Seed
        # a real owner + project and pass that owner as the actor.
        owner_id = await _seed_owned_project(session)
        pid = owner_id.project_id
        el = await _seed(
            session,
            pid,
            asset_info={"maintenance_interval_days": "180", "installation_date": "2024-01-01"},
            is_tracked_asset=True,
        )
        svc = AssetOpsService(session)
        resp = await svc.append_service_log(
            el.id,
            entry={"date": "2026-06-01", "note": "Replaced bearing", "kind": "repair"},
            actor_user_id=str(owner_id.user_id),
        )
        assert len(resp.service_log) == 1
        assert resp.service_log[0]["note"] == "Replaced bearing"
        # last_serviced kept in sync and maintenance recomputed off it.
        assert resp.health.last_serviced == "2026-06-01"
        # 2026-06-01 + 180d is in the future relative to "today" at test
        # time only if run before ~Nov 2026; assert the value is set instead.
        assert resp.health.next_maintenance_due is not None

    @pytest.mark.asyncio
    async def test_append_service_log_missing_asset_404(self, session):
        from fastapi import HTTPException

        svc = AssetOpsService(session)
        with pytest.raises(HTTPException) as exc:
            await svc.append_service_log(uuid.uuid4(), entry={"date": "2026-06-01", "note": "x"})
        assert exc.value.status_code == 404
