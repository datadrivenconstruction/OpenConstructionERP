# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Behaviour tests for the streaming partner-pack activation.

These prove the Modules-page "Activate pack" path (``full_install_stream``)
actually installs the pack's bundled work catalog AND its embedded resource
database, surfaces both counts as live progress events, and stays idempotent
when the same pack is activated a second time.

The real CWICR loader reads regional Parquet files and a third-party embedding
model that are not present in CI, so the heavy steps are replaced with a fake
loader that writes ``CostItem`` rows (each carrying a ``components`` resource
breakdown) into a per-test PostgreSQL DB using the *same* idempotency contract
as the production loader: a region already holding rows imports nothing on the
second pass. That isolates exactly the wiring this feature adds - the
orchestrator calling the loader, summing resource components, and reporting
catalog + resource counts step by step.

The fixture hands out a sessionmaker bound to a throwaway PostgreSQL database
(cloned from a schema-loaded template by ``tests._pg.isolated_engine``). The
orchestrator opens its own sessions from that same factory and the fake loader
commits rows that the test then verifies through separate sessions, so the
fixture needs real cross-connection commit visibility rather than a
savepoint-rolled-back shared session.
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
from app.modules.costs.models import CostItem
from tests._pg import isolated_engine

# A pack that bundles one resolvable region. ``cwicr-de-berlin`` resolves to the
# live ``DE_BERLIN`` db_id via the §5.1 resolver, so this exercises the real
# slug -> db_id path without depending on which reference packs are installed.
_PACK_SLUG = "test-stream-pack"
_REGION_SLUG = "cwicr-de-berlin"
_RESOLVED_DB_ID = "DE_BERLIN"

# How many work items / resource components per item the fake loader writes.
_FAKE_ITEMS = 5
_RESOURCES_PER_ITEM = 3
_EXPECTED_RESOURCES = _FAKE_ITEMS * _RESOURCES_PER_ITEM


@pytest_asyncio.fixture
async def session_factory():
    """A sessionmaker over a fresh per-test PostgreSQL DB with the full schema.

    The throwaway database is cloned from the schema-loaded template (which
    already carries the ``CostItem`` table), so no ``create_all`` is needed.
    """
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _make_manifest() -> PartnerPackManifest:
    return PartnerPackManifest(
        slug=_PACK_SLUG,
        partner_name="Stream Test Partner",
        default_locale="de",
        default_currency="EUR",
        cwicr_regions=[_REGION_SLUG],
    )


def _fake_loader_factory(session_factory: async_sessionmaker[AsyncSession]):
    """Build a stand-in for ``load_cwicr_region`` with real idempotency.

    First call for a region inserts ``_FAKE_ITEMS`` CostItem rows, each with
    ``_RESOURCES_PER_ITEM`` resource components, and reports the resource total
    via ``resource_components`` (exactly like the production
    ``_process_and_insert_cwicr`` return). A subsequent call sees the rows
    already present and imports nothing, matching the live loader's
    "already loaded, skipping" branch.
    """

    async def _fake_load_cwicr_region(db_id: str, _session: AsyncSession) -> dict[str, Any]:
        async with session_factory() as s:
            existing = (
                await s.execute(select(func.count()).select_from(CostItem).where(CostItem.region == db_id))
            ).scalar_one()
            if existing > 0:
                return {
                    "imported": 0,
                    "skipped": existing,
                    "region": db_id,
                    "total_items": existing,
                    "resource_components": 0,
                    "status": "already_loaded",
                }
            components = [
                {
                    "name": f"res-{j}",
                    "code": f"R{j}",
                    "unit": "h",
                    "quantity": 1.0,
                    "unit_rate": 10.0,
                    "cost": 10.0,
                    "type": "labor",
                }
                for j in range(_RESOURCES_PER_ITEM)
            ]
            for i in range(_FAKE_ITEMS):
                s.add(
                    CostItem(
                        id=uuid.uuid4(),
                        code=f"{db_id}-{i:03d}",
                        description=f"Work item {i}",
                        unit="m3",
                        rate="100.00",
                        currency="EUR",
                        source="cwicr",
                        components=list(components),
                        is_active=True,
                        region=db_id,
                    )
                )
            await s.commit()
            return {
                "imported": _FAKE_ITEMS,
                "skipped": 0,
                "total_rows": _FAKE_ITEMS * _RESOURCES_PER_ITEM,
                "unique_items": _FAKE_ITEMS,
                "resource_components": _EXPECTED_RESOURCES,
                "database": db_id,
            }

    return _fake_load_cwicr_region


def _patch_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    demos_installed: list[str],
) -> None:
    """Patch the lazily-imported collaborators the stream orchestrator uses."""
    # The pack manifest the orchestrator resolves for slug lookups.
    monkeypatch.setattr(
        "app.core.partner_pack.discovery.get_pack_by_slug",
        lambda slug: _make_manifest() if slug == _PACK_SLUG else None,
    )

    # Step 1 (apply_pack) -> succeed without touching modules/branding/state.
    async def _fake_apply(*_a: Any, **_k: Any) -> fi.StepResult:
        return fi.StepResult(step="apply_pack", status="ok", detail={"modules_enabled": 0})

    monkeypatch.setattr(fi, "_step_apply_pack", _fake_apply)
    # Step 3 (cost_db + resources) -> our idempotent fake loader + test DB.
    monkeypatch.setattr(
        "app.modules.costs.router.load_cwicr_region",
        _fake_loader_factory(session_factory),
    )
    monkeypatch.setattr("app.database.async_session_factory", session_factory)

    # Step 4 (vector_db) -> graceful "vector backend unavailable" (skipped).
    async def _fake_vectorize(*_a: Any, **_k: Any):
        from fastapi.responses import JSONResponse

        return JSONResponse(content={"message": "vector backend unavailable"}, status_code=503)

    monkeypatch.setattr("app.modules.costs.router.vectorize_region", _fake_vectorize)

    # Step 5 (demos) -> install the requested ids without real templates. The
    # one-click installer tags each demo with the active pack's slug so the
    # workspace can scope to it, so the fake accepts (and records) partner_pack.
    async def _fake_install_demo(
        _session: AsyncSession, demo_id: str, *, partner_pack: str | None = None
    ) -> dict[str, Any]:
        assert partner_pack == _PACK_SLUG, f"demo not tagged with the pack slug: {partner_pack!r}"
        return {"project_id": str(uuid.uuid4()), "project_name": demo_id, "already_installed": False}

    monkeypatch.setattr("app.core.demo_projects.install_demo_project", _fake_install_demo)
    monkeypatch.setattr(fi, "_demo_install_list", lambda _slug, count: demos_installed[:count])


def _parse_events(frames: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """Parse raw SSE frames into ``(event_name, payload)`` tuples."""
    out: list[tuple[str, dict[str, Any]]] = []
    for frame in frames:
        event = ""
        data = ""
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if event:
            out.append((event, json.loads(data) if data else {}))
    return out


async def _run_stream(req: FullInstallRequest) -> list[tuple[str, dict[str, Any]]]:
    frames = [frame async for frame in full_install_stream(req)]
    return _parse_events(frames)


@pytest.mark.asyncio
async def test_stream_installs_catalog_and_resources(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Activating a pack writes work items + their resource breakdown and reports both."""
    _patch_orchestrator(monkeypatch, session_factory, demos_installed=["demo-de-1"])

    events = await _run_stream(
        FullInstallRequest(slug=_PACK_SLUG, set_locale=True, install_cost_db=True, vectorize=True, demo_count=1)
    )
    by_event = [e for e, _ in events]

    # The stream opens with ``start`` and closes with ``done``.
    assert by_event[0] == "start"
    assert by_event[-1] == "done"

    # The announced step list contains both the work-catalog and resources rows.
    start_payload = events[0][1]
    announced = [s["step"] for s in start_payload["steps"]]
    assert "cost_db" in announced
    assert "resources" in announced
    assert start_payload["total"] == len(announced)

    # Each announced step gets exactly one step_start and one step_done.
    step_starts = [p["step"] for e, p in events if e == "step_start"]
    step_dones = {p["step"]: p for e, p in events if e == "step_done"}
    assert sorted(step_starts) == sorted(announced)
    assert set(step_dones) == set(announced)

    # cost_db reports the imported work-item count + the embedded resource total.
    cost = step_dones["cost_db"]
    assert cost["status"] == "ok"
    assert cost["detail"]["items"] == _FAKE_ITEMS
    assert cost["detail"]["resources"] == _EXPECTED_RESOURCES

    # The dedicated resources row mirrors the same resource total.
    res = step_dones["resources"]
    assert res["status"] == "ok"
    assert res["detail"]["resources"] == _EXPECTED_RESOURCES

    # vector_db degrades to skipped (no embedding backend) but never errors out.
    assert step_dones["vector_db"]["status"] == "skipped"

    # The rows are actually in the relational store.
    async with session_factory() as s:
        item_count = (
            await s.execute(select(func.count()).select_from(CostItem).where(CostItem.region == _RESOLVED_DB_ID))
        ).scalar_one()
        rows = (await s.execute(select(CostItem).where(CostItem.region == _RESOLVED_DB_ID))).scalars().all()
    assert item_count == _FAKE_ITEMS
    total_components = sum(len(r.components or []) for r in rows)
    assert total_components == _EXPECTED_RESOURCES

    # apply_pack ok + at least one demo installed => overall ok.
    done_payload = events[-1][1]
    assert done_payload["ok"] is True


@pytest.mark.asyncio
async def test_stream_is_idempotent_on_second_activation(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A second activation imports no new rows (no duplicates) and still completes."""
    _patch_orchestrator(monkeypatch, session_factory, demos_installed=["demo-de-1"])
    req = FullInstallRequest(slug=_PACK_SLUG, set_locale=True, install_cost_db=True, vectorize=True, demo_count=1)

    first = await _run_stream(req)
    second = await _run_stream(req)

    async def _count() -> int:
        async with session_factory() as s:
            return (
                await s.execute(select(func.count()).select_from(CostItem).where(CostItem.region == _RESOLVED_DB_ID))
            ).scalar_one()

    # Exactly one population's worth of rows after running twice.
    assert await _count() == _FAKE_ITEMS

    first_cost = next(p for e, p in first if e == "step_done" and p["step"] == "cost_db")
    second_cost = next(p for e, p in second if e == "step_done" and p["step"] == "cost_db")
    # First run imports the catalogue; second sees it already loaded (0 new rows
    # but still reports the present total, so the step stays "ok").
    assert first_cost["detail"]["items"] == _FAKE_ITEMS
    assert second_cost["detail"]["items"] == _FAKE_ITEMS
    assert second_cost["status"] == "ok"
    # Both runs still drive the bar to completion.
    assert first[-1][0] == "done"
    assert second[-1][0] == "done"


@pytest.mark.asyncio
async def test_stream_ok_when_demos_opted_out(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Opting out of demos (demo_count=0) still reports ok when nothing errored.

    The Modules dialog lets the admin uncheck the sample project; a skipped
    demos step (no error) must not flip the whole activation to "partial".
    """
    _patch_orchestrator(monkeypatch, session_factory, demos_installed=["demo-de-1"])
    events = await _run_stream(
        FullInstallRequest(slug=_PACK_SLUG, set_locale=True, install_cost_db=True, vectorize=True, demo_count=0)
    )
    step_dones = {p["step"]: p for e, p in events if e == "step_done"}
    # cost_db + resources still ran (they don't depend on demos).
    assert step_dones["cost_db"]["status"] == "ok"
    assert step_dones["resources"]["detail"]["resources"] == _EXPECTED_RESOURCES
    # demos skipped (count 0), no error anywhere -> overall ok.
    assert step_dones["demos"]["status"] == "skipped"
    assert events[-1][1]["ok"] is True


@pytest.mark.asyncio
async def test_stream_threads_confirm_disables_into_apply(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The dialog's "hide modules" opt-in reaches the apply step over the stream."""
    seen: dict[str, bool] = {}

    async def _spy_apply(_slug: str, _app: Any, _actor: Any, *, confirm_disables: bool = False) -> fi.StepResult:
        seen["confirm_disables"] = confirm_disables
        return fi.StepResult(step="apply_pack", status="ok", detail={})

    monkeypatch.setattr(
        "app.core.partner_pack.discovery.get_pack_by_slug",
        lambda slug: PartnerPackManifest(slug=_PACK_SLUG, partner_name="P"),
    )
    monkeypatch.setattr(fi, "_step_apply_pack", _spy_apply)
    monkeypatch.setattr("app.database.async_session_factory", session_factory)
    monkeypatch.setattr(fi, "_demo_install_list", lambda _slug, _count: [])

    await _run_stream(
        FullInstallRequest(
            slug=_PACK_SLUG,
            set_locale=False,
            install_cost_db=False,
            vectorize=False,
            confirm_disables=True,
            demo_count=0,
        )
    )
    assert seen.get("confirm_disables") is True


@pytest.mark.asyncio
async def test_stream_skips_resources_when_pack_has_no_regions(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A pack with no cwicr_regions reports cost_db + resources as skipped, not error."""
    monkeypatch.setattr(
        "app.core.partner_pack.discovery.get_pack_by_slug",
        lambda slug: PartnerPackManifest(slug=_PACK_SLUG, partner_name="No Data Pack"),
    )

    async def _fake_apply(*_a: Any, **_k: Any) -> fi.StepResult:
        return fi.StepResult(step="apply_pack", status="ok", detail={})

    monkeypatch.setattr(fi, "_step_apply_pack", _fake_apply)
    monkeypatch.setattr("app.database.async_session_factory", session_factory)
    monkeypatch.setattr(fi, "_demo_install_list", lambda _slug, _count: [])

    events = await _run_stream(
        FullInstallRequest(slug=_PACK_SLUG, set_locale=True, install_cost_db=True, vectorize=True, demo_count=0)
    )
    step_dones = {p["step"]: p for e, p in events if e == "step_done"}
    assert step_dones["cost_db"]["status"] == "skipped"
    assert step_dones["resources"]["status"] == "skipped"
    assert step_dones["resources"]["detail"]["resources"] == 0
    # No catalogue rows were written.
    async with session_factory() as s:
        count = (await s.execute(select(func.count()).select_from(CostItem))).scalar_one()
    assert count == 0
    assert events[-1][0] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "batch"])
async def test_a_cost_base_that_fails_to_load_is_an_error_not_a_skip(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    stream: bool,
) -> None:
    """A region whose import raises must fail the step, and with it the install.

    ``skipped`` means the pack asked for nothing this step can do, which is
    what a pack without ``cwicr_regions`` gets and what the dialog greys out.
    A download that timed out or an import that raised is the opposite: the
    pack asked for a cost base and did not get one. Reporting that as
    ``skipped`` let the whole install finish with ``ok: true`` and an empty
    cost database behind it.
    """
    _patch_orchestrator(monkeypatch, session_factory, demos_installed=[])

    async def _broken_loader(db_id: str, _session: AsyncSession) -> dict[str, Any]:
        raise RuntimeError(f"download of {db_id} timed out")

    monkeypatch.setattr("app.modules.costs.router.load_cwicr_region", _broken_loader)

    if stream:
        result, loaded, _resources = await fi._step_cost_db_detailed(_PACK_SLUG)
    else:
        result, loaded = await fi._step_cost_db(_PACK_SLUG)
    assert loaded == []
    assert result.status == "error", result
    assert result.detail["errors"][0]["db_id"] == _RESOLVED_DB_ID

    if stream:
        events = await _run_stream(
            FullInstallRequest(slug=_PACK_SLUG, set_locale=True, install_cost_db=True, vectorize=False, demo_count=0)
        )
        assert events[-1][0] == "done"
        assert events[-1][1]["ok"] is False, events[-1][1]
