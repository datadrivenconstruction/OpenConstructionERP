# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The choices and the verdict of a streamed pack install.

The activation dialog offers the country's cost bases before it installs them,
lets the user untick one, loads the resource catalogue next to the work items,
retries a failed step on its own, and ends on a per-step summary. These tests
pin the backend half of each of those:

* ``describe_cost_bases`` names every declared region, loadable or not, so a
  pack whose regions have no published base says so instead of going quiet.
* ``cost_regions`` narrows what ``cost_db`` loads and ``detail.bases`` says
  why each region did or did not load.
* the ``catalog`` step imports a region's catalogue once and leaves a
  populated one alone.
* ``only_steps`` reruns just the failed step and its verdict does not hinge on
  an ``apply_pack`` it did not run.
* an unticked sample project installs nothing, even for a pack that pins its
  demos.

The heavy loaders are stubbed; the per-test PostgreSQL database is the same
cloned template the stream tests use.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.partner_pack import full_install as fi
from app.core.partner_pack.full_install import FullInstallRequest, full_install_stream
from app.core.partner_pack.manifest import PartnerPackManifest
from tests._pg import isolated_engine

_PACK_SLUG = "test-choices-pack"
# Berlin resolves to a published base, Munich deliberately to none (see the
# alias table in full_install), so one pack carries both cases.
_LOADABLE = "cwicr-de-berlin"
_LOADABLE_DB_ID = "DE_BERLIN"
_UNLOADABLE = "cwicr-de-munich"


@pytest_asyncio.fixture
async def session_factory():
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _manifest(regions: list[str], **extra: Any) -> PartnerPackManifest:
    return PartnerPackManifest(
        slug=_PACK_SLUG,
        partner_name="Choices Test Pack",
        default_locale="de",
        default_currency="EUR",
        cwicr_regions=regions,
        **extra,
    )


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    manifest: PartnerPackManifest,
    *,
    loads: list[str] | None = None,
    catalog_imports: list[str] | None = None,
) -> None:
    monkeypatch.setattr(
        "app.core.partner_pack.discovery.get_pack_by_slug",
        lambda slug: manifest if slug == _PACK_SLUG else None,
    )
    monkeypatch.setattr("app.database.async_session_factory", session_factory)

    async def _fake_apply(*_a: Any, **_k: Any) -> fi.StepResult:
        return fi.StepResult(step="apply_pack", status="ok", detail={"rule_sets": []})

    monkeypatch.setattr(fi, "_step_apply_pack", _fake_apply)

    async def _fake_load(db_id: str, _session: AsyncSession) -> dict[str, Any]:
        if loads is not None:
            loads.append(db_id)
        return {"imported": 7, "resource_components": 21, "database": db_id}

    monkeypatch.setattr("app.modules.costs.router.load_cwicr_region", _fake_load)

    async def _fake_catalog(session: AsyncSession, region: str) -> dict[str, Any]:
        from app.modules.catalog.models import CatalogResource

        if catalog_imports is not None:
            catalog_imports.append(region)
        for i in range(4):
            session.add(
                CatalogResource(
                    resource_code=f"{region}-{i}",
                    name=f"Resource {i}",
                    resource_type="material",
                    category="General",
                    unit="kg",
                    base_price="1.00",
                    currency="EUR",
                    source="github_import",
                    region=region,
                    specifications={},
                    metadata_={},
                )
            )
        await session.flush()
        return {"imported": 4, "skipped": 0, "region": region, "source": "test"}

    monkeypatch.setattr("app.modules.catalog.router.import_region_catalog", _fake_catalog)
    monkeypatch.setattr(fi, "_demo_install_list", lambda _slug, _count: [])


def _parse(frames: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for frame in frames:
        event, data = "", ""
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if event:
            out.append((event, json.loads(data) if data else {}))
    return out


async def _run(req: FullInstallRequest) -> list[tuple[str, dict[str, Any]]]:
    return _parse([frame async for frame in full_install_stream(req)])


def _dones(events: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    return {p["step"]: p for e, p in events if e == "step_done"}


# ── describe_cost_bases ─────────────────────────────────────────────────────


def test_describe_cost_bases_names_every_declared_region() -> None:
    """A region with no published base is listed as such, not dropped."""
    bases = fi.describe_cost_bases([_LOADABLE, _UNLOADABLE])

    assert [b["slug"] for b in bases] == [_LOADABLE, _UNLOADABLE]
    berlin, munich = bases
    assert berlin["loadable"] is True
    assert berlin["db_id"] == _LOADABLE_DB_ID
    assert isinstance(berlin["positions"], int) and berlin["positions"] > 0
    assert berlin["currency"] == "EUR"
    assert berlin["reason_code"] is None

    assert munich["loadable"] is False
    assert munich["db_id"] is None
    assert munich["reason_code"] == "no_published_base"


def test_describe_cost_bases_marks_a_second_slug_for_the_same_base() -> None:
    """Two slugs for one base: the first loads it, the second is not offered twice."""
    bases = fi.describe_cost_bases(["cwicr-eng-london", "cwicr-eng-gbp"])
    assert bases[0]["loadable"] is True
    assert bases[1]["loadable"] is False
    assert bases[1]["reason_code"] == "duplicate_base"


# ── cost_regions ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unticked_base_is_not_loaded_and_says_why(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    loads: list[str] = []
    _patch(monkeypatch, session_factory, _manifest([_LOADABLE, _UNLOADABLE]), loads=loads)

    events = await _run(FullInstallRequest(slug=_PACK_SLUG, vectorize=False, demo_count=0, cost_regions=[]))
    cost = _dones(events)["cost_db"]

    assert loads == []
    assert cost["status"] == "skipped"
    assert cost["detail"]["reason_code"] == "none_selected"
    assert {b["slug"]: b["reason_code"] for b in cost["detail"]["bases"]} == {
        _LOADABLE: "not_selected",
        _UNLOADABLE: "not_selected",
    }
    assert events[-1][1]["ok"] is True


@pytest.mark.asyncio
async def test_a_pack_with_nothing_loadable_says_so(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _patch(monkeypatch, session_factory, _manifest([_UNLOADABLE]))

    events = await _run(FullInstallRequest(slug=_PACK_SLUG, vectorize=False, demo_count=0))
    cost = _dones(events)["cost_db"]

    assert cost["status"] == "skipped"
    assert cost["detail"]["reason_code"] == "no_loadable_base"
    assert cost["detail"]["bases"] == [
        {"slug": _UNLOADABLE, "db_id": None, "status": "skipped", "reason_code": "no_published_base"}
    ]


@pytest.mark.asyncio
async def test_each_loaded_base_reports_its_own_counts(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _patch(monkeypatch, session_factory, _manifest([_LOADABLE, _UNLOADABLE]))

    events = await _run(FullInstallRequest(slug=_PACK_SLUG, vectorize=False, demo_count=0, cost_regions=[_LOADABLE]))
    bases = {b["slug"]: b for b in _dones(events)["cost_db"]["detail"]["bases"]}

    assert bases[_LOADABLE]["status"] == "ok"
    assert bases[_LOADABLE]["items"] == 7
    assert bases[_LOADABLE]["resources"] == 21
    assert bases[_UNLOADABLE]["reason_code"] == "not_selected"


# ── catalog ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_catalogue_loads_once_and_a_populated_one_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from app.modules.catalog.models import CatalogResource

    imports: list[str] = []
    _patch(monkeypatch, session_factory, _manifest([_LOADABLE]), catalog_imports=imports)
    req = FullInstallRequest(slug=_PACK_SLUG, vectorize=False, demo_count=0, install_catalog=True)

    first = _dones(await _run(req))
    second = _dones(await _run(req))

    assert imports == [_LOADABLE_DB_ID]
    assert first["catalog"]["status"] == "ok"
    assert first["catalog"]["detail"]["resources"] == 4
    assert second["catalog"]["status"] == "ok"
    assert second["catalog"]["detail"]["catalogs"][0]["already_loaded"] is True
    async with session_factory() as s:
        count = (
            await s.execute(
                select(func.count()).select_from(CatalogResource).where(CatalogResource.region == _LOADABLE_DB_ID)
            )
        ).scalar_one()
    assert count == 4


@pytest.mark.asyncio
async def test_the_catalogue_is_not_announced_unless_asked_for(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Callers that predate the step keep the step list they had."""
    _patch(monkeypatch, session_factory, _manifest([_LOADABLE]))

    events = await _run(FullInstallRequest(slug=_PACK_SLUG, vectorize=False, demo_count=0))

    assert "catalog" not in [s["step"] for s in events[0][1]["steps"]]


@pytest.mark.asyncio
async def test_a_failed_catalogue_fails_the_step(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _patch(monkeypatch, session_factory, _manifest([_LOADABLE]))

    async def _broken(_session: AsyncSession, region: str) -> dict[str, Any]:
        raise RuntimeError(f"catalogue for {region} could not be downloaded")

    monkeypatch.setattr("app.modules.catalog.router.import_region_catalog", _broken)

    events = await _run(FullInstallRequest(slug=_PACK_SLUG, vectorize=False, demo_count=0, install_catalog=True))
    catalog = _dones(events)["catalog"]

    assert catalog["status"] == "error"
    assert catalog["detail"]["catalogs"][0]["reason_code"] == "load_failed"
    assert events[-1][1]["ok"] is False


@pytest.mark.asyncio
async def test_a_base_repriced_into_another_market_gets_no_home_catalogue(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The home catalogue is in the home currency; the repriced items are not.

    A base priced into another market carries that market's currency on its
    work items. Its catalogue file is the home market's, so importing it would
    show one base in two currencies. The step skips it and says why.
    """
    from app.modules.catalog.models import CatalogResource
    from app.modules.costs.models import CostItem

    imports: list[str] = []
    _patch(monkeypatch, session_factory, _manifest([_LOADABLE]), catalog_imports=imports)
    async with session_factory() as s:
        for i in range(3):
            s.add(
                CostItem(
                    code=f"R-{i}",
                    description="Repriced work item",
                    unit="m3",
                    rate="10.00",
                    currency="USD",
                    region=_LOADABLE_DB_ID,
                )
            )
        await s.commit()

    events = await _run(FullInstallRequest(slug=_PACK_SLUG, vectorize=False, demo_count=0, install_catalog=True))
    catalog = _dones(events)["catalog"]

    assert imports == []
    assert catalog["status"] == "skipped"
    assert catalog["detail"]["reason_code"] == "repriced_market"
    entry = catalog["detail"]["catalogs"][0]
    assert entry["reason_code"] == "repriced_market"
    assert entry["currency"] == "USD"
    assert entry["catalog_currency"] == "EUR"
    async with session_factory() as s:
        count = (
            await s.execute(
                select(func.count()).select_from(CatalogResource).where(CatalogResource.region == _LOADABLE_DB_ID)
            )
        ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_a_base_in_its_home_currency_still_gets_its_catalogue(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from app.modules.costs.models import CostItem

    imports: list[str] = []
    _patch(monkeypatch, session_factory, _manifest([_LOADABLE]), catalog_imports=imports)
    async with session_factory() as s:
        s.add(
            CostItem(
                code="H-1",
                description="Home work item",
                unit="m3",
                rate="10.00",
                currency="EUR",
                region=_LOADABLE_DB_ID,
            )
        )
        await s.commit()

    events = await _run(FullInstallRequest(slug=_PACK_SLUG, vectorize=False, demo_count=0, install_catalog=True))

    assert imports == [_LOADABLE_DB_ID]
    assert _dones(events)["catalog"]["status"] == "ok"


# ── only_steps ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_retry_runs_only_the_failed_step_and_what_it_needs(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    applied: list[str] = []
    _patch(monkeypatch, session_factory, _manifest([_LOADABLE]))

    async def _spy_apply(*_a: Any, **_k: Any) -> fi.StepResult:
        applied.append("apply")
        return fi.StepResult(step="apply_pack", status="ok", detail={})

    monkeypatch.setattr(fi, "_step_apply_pack", _spy_apply)

    events = await _run(
        FullInstallRequest(
            slug=_PACK_SLUG,
            vectorize=False,
            demo_count=2,
            install_catalog=True,
            only_steps=["catalog"],
        )
    )

    assert [s["step"] for s in events[0][1]["steps"]] == ["cost_db", "resources", "catalog"]
    assert applied == []
    assert events[-1][1]["ok"] is True


def test_only_steps_rejects_an_unknown_step() -> None:
    with pytest.raises(ValueError, match="only_steps"):
        FullInstallRequest(slug=_PACK_SLUG, only_steps=["drop_everything"])  # type: ignore[list-item]


# ── demos ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unticked_sample_project_installs_nothing_even_when_pinned(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from app.core.demo_projects import DEMO_TEMPLATES

    pinned = next(iter(DEMO_TEMPLATES))
    installs: list[str] = []
    manifest = _manifest([], demo_template_ids=[pinned])
    _patch(monkeypatch, session_factory, manifest)

    async def _spy_install(_session: AsyncSession, demo_id: str, **_k: Any) -> dict[str, Any]:
        installs.append(demo_id)
        return {"project_id": str(uuid.uuid4())}

    monkeypatch.setattr("app.core.demo_projects.install_demo_project", _spy_install)

    result = await fi._step_demos(_PACK_SLUG, 0)

    assert installs == []
    assert result.status == "skipped"
    assert result.detail["reason_code"] == "not_requested"


# ── apply_pack ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_step_names_the_rule_sets_it_switched_on(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_apply_pack(slug: str, **_k: Any) -> dict[str, Any]:
        return {
            "effects": {"modules_enabled": ["a"], "modules_disabled": []},
            "plan": {"rule_sets_enabled": ["din276", "gaeb"]},
        }

    monkeypatch.setattr("app.core.partner_pack.apply.apply_pack", _fake_apply_pack)
    monkeypatch.setattr("app.core.partner_pack.state.load_applied_state", lambda: None)

    result = await fi._step_apply_pack(_PACK_SLUG, None, None)

    assert result.detail["rule_sets"] == ["din276", "gaeb"]
    assert result.detail["modules_enabled"] == 1
