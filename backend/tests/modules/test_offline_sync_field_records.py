# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Offline sync on diary, diary entry, punch item and inspection​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Optimistic concurrency (If-Match / body version), ``client_op_id`` idempotent
create, the merge endpoint with its audit trail and event, and the demo seed.
The router handlers are called directly with a real PostgreSQL session; project
access is stubbed because the tests run without FK parents.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.offline_merge import OfflineMergeRequest
from app.core.validation.rules import register_builtin_rules
from app.modules.daily_diary import router as diary_router
from app.modules.daily_diary.schemas import (
    DailyDiaryCreate,
    DailyDiaryUpdate,
    DiaryEntryCreate,
    DiaryEntryUpdate,
)
from app.modules.daily_diary.service import DailyDiaryService
from app.modules.inspections import router as insp_router
from app.modules.inspections.schemas import InspectionCreate, InspectionUpdate
from app.modules.inspections.service import InspectionService
from app.modules.punchlist import router as punch_router
from app.modules.punchlist.schemas import PunchItemCreate, PunchItemUpdate
from app.modules.punchlist.service import PunchListService
from tests._pg import transactional_session

USER = str(uuid.uuid4())


async def _allow(*_a: Any, **_k: Any) -> None:
    return None


@pytest.fixture(autouse=True)
def _open_project_access(monkeypatch: pytest.MonkeyPatch) -> None:
    register_builtin_rules()
    for mod in (diary_router, punch_router, insp_router):
        monkeypatch.setattr(mod, "verify_project_access", _allow)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


class _Diary:
    name, text, event = "diary", "notes", "daily_diary.offline_merge_resolved"

    def __init__(self, s: AsyncSession) -> None:
        self.s, self.svc, self.pid = s, DailyDiaryService(s), uuid.uuid4()

    def _create_data(self, op: str | None) -> DailyDiaryCreate:
        return DailyDiaryCreate(
            project_id=self.pid, diary_date=datetime.now(UTC).date().isoformat(), notes="base", client_op_id=op
        )

    async def create(self, op: str | None = None, resp: Response | None = None) -> Any:
        out = await diary_router.create_diary(
            self._create_data(op), self.s, resp or Response(), user_id=USER, _perm=None, service=self.svc
        )
        return out

    async def update(self, oid: uuid.UUID, text: str, if_match: str | None = None, version: int | None = None) -> Any:
        return await diary_router.update_diary(
            oid, DailyDiaryUpdate(notes=text, version=version), self.s, USER, if_match, None, self.svc
        )

    async def merge(self, oid: uuid.UUID, body: OfflineMergeRequest) -> Any:
        return await diary_router.merge_diary(oid, body, self.s, USER, None, self.svc)

    async def audit(self, oid: uuid.UUID) -> Any:
        return await diary_router.diary_merge_audit(oid, self.s, USER, None, self.svc)

    async def count(self) -> int:
        _, total = await self.svc.list_diaries(self.pid)
        return total


class _Entry(_Diary):
    name, text, event = "entry", "description", "daily_diary.offline_merge_resolved"

    async def _diary_id(self) -> uuid.UUID:
        if not hasattr(self, "_did"):
            self._did = (await self.svc.create_diary(self._create_data(None))).id
        return self._did

    async def create(self, op: str | None = None, resp: Response | None = None) -> Any:
        data = DiaryEntryCreate(
            diary_id=await self._diary_id(),
            entry_type="general",
            entry_time=datetime.now(UTC),
            title="t",
            description="base",
            client_op_id=op,
        )
        return await diary_router.create_entry(
            data, self.s, resp or Response(), user_id=USER, _perm=None, service=self.svc
        )

    async def update(self, oid: uuid.UUID, text: str, if_match: str | None = None, version: int | None = None) -> Any:
        return await diary_router.update_entry(
            oid, DiaryEntryUpdate(description=text, version=version), self.s, USER, if_match, None, self.svc
        )

    async def merge(self, oid: uuid.UUID, body: OfflineMergeRequest) -> Any:
        return await diary_router.merge_entry(oid, body, self.s, USER, None, self.svc)

    async def audit(self, oid: uuid.UUID) -> Any:
        return await diary_router.entry_merge_audit(oid, self.s, USER, None, self.svc)

    async def count(self) -> int:
        return len(await self.svc.list_entries(await self._diary_id()))


class _Punch(_Diary):
    name, text, event = "punch", "description", "punchlist.offline_merge_resolved"

    def __init__(self, s: AsyncSession) -> None:
        super().__init__(s)
        self.svc = PunchListService(s)

    async def create(self, op: str | None = None, resp: Response | None = None) -> Any:
        data = PunchItemCreate(project_id=self.pid, title="t", description="base", client_op_id=op)
        return await punch_router.create_item(data, USER, self.s, resp or Response(), _perm=None, service=self.svc)

    async def update(self, oid: uuid.UUID, text: str, if_match: str | None = None, version: int | None = None) -> Any:
        return await punch_router.update_item(
            oid, PunchItemUpdate(description=text, version=version), self.s, USER, if_match, None, self.svc
        )

    async def merge(self, oid: uuid.UUID, body: OfflineMergeRequest) -> Any:
        return await punch_router.merge_item(oid, body, self.s, USER, None, self.svc)

    async def audit(self, oid: uuid.UUID) -> Any:
        return await punch_router.item_merge_audit(oid, self.s, USER, None, self.svc)

    async def count(self) -> int:
        _, total = await self.svc.list_items(self.pid)
        return total


class _Inspection(_Diary):
    name, text, event = "inspection", "description", "inspections.offline_merge_resolved"

    def __init__(self, s: AsyncSession) -> None:
        super().__init__(s)
        self.svc = InspectionService(s)

    async def create(self, op: str | None = None, resp: Response | None = None) -> Any:
        data = InspectionCreate(
            project_id=self.pid, inspection_type="general", title="t", description="base", client_op_id=op
        )
        return await insp_router.create_inspection(data, USER, self.s, resp or Response(), _perm=None, service=self.svc)

    async def update(self, oid: uuid.UUID, text: str, if_match: str | None = None, version: int | None = None) -> Any:
        return await insp_router.update_inspection(
            oid, InspectionUpdate(description=text, version=version), self.s, USER, if_match, None, self.svc
        )

    async def merge(self, oid: uuid.UUID, body: OfflineMergeRequest) -> Any:
        return await insp_router.merge_inspection(oid, body, self.s, USER, None, self.svc)

    async def audit(self, oid: uuid.UUID) -> Any:
        return await insp_router.inspection_merge_audit(oid, self.s, USER, None, self.svc)

    async def count(self) -> int:
        _, total = await self.svc.list_inspections(self.pid)
        return total


ADAPTERS = [_Diary, _Entry, _Punch, _Inspection]


@pytest.fixture(params=ADAPTERS, ids=lambda c: c.name)
def ad(request: pytest.FixtureRequest, session: AsyncSession) -> _Diary:
    return request.param(session)


def _req(ad: _Diary, **kw: Any) -> OfflineMergeRequest:
    return OfflineMergeRequest(**kw)


async def test_new_row_starts_at_version_one(ad: _Diary) -> None:
    assert (await ad.create()).version == 1


async def test_stale_if_match_is_409_with_the_current_row(ad: _Diary) -> None:
    row = await ad.create()
    await ad.update(row.id, "server edit")  # no precondition: still bumps
    with pytest.raises(HTTPException) as exc:
        await ad.update(row.id, "late edit", if_match='"1"')
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["code"] == "version_conflict"
    assert detail["current_version"] == 2
    assert detail["current"]["version"] == 2
    assert detail["current"][ad.text] == "server edit"
    assert isinstance(detail["message"], str)


async def test_stale_body_version_is_409(ad: _Diary) -> None:
    row = await ad.create()
    await ad.update(row.id, "server edit")
    with pytest.raises(HTTPException) as exc:
        await ad.update(row.id, "late edit", version=1)
    assert exc.value.status_code == 409


async def test_good_version_bumps(ad: _Diary) -> None:
    row = await ad.create()
    out = await ad.update(row.id, "edit", if_match='W/"1"')
    assert out.version == 2
    assert getattr(out, ad.text) == "edit"
    out = await ad.update(row.id, "edit 2", version=2)
    assert out.version == 3


async def test_update_without_precondition_still_works_and_bumps(ad: _Diary) -> None:
    row = await ad.create()
    assert (await ad.update(row.id, "a")).version == 2
    assert (await ad.update(row.id, "b")).version == 3


async def test_same_client_op_id_creates_one_row(ad: _Diary) -> None:
    first_resp, second_resp = Response(), Response()
    first = await ad.create("dev1-op-0001", first_resp)
    second = await ad.create("dev1-op-0001", second_resp)
    assert second.id == first.id
    assert second_resp.status_code == 200
    assert await ad.count() == 1
    other = await ad.create("dev1-op-0002") if ad.name not in ("diary",) else None
    if other is not None:
        assert other.id != first.id


async def test_merge_applies_audits_and_publishes(ad: _Diary) -> None:
    seen: list[dict[str, Any]] = []

    async def _on(event: Any) -> None:
        seen.append(event.data if hasattr(event, "data") else event)

    event_bus.subscribe(ad.event, _on)
    try:
        row = await ad.create()
        await ad.update(row.id, "server edit")  # version 2
        body = _req(
            ad,
            base_version=1,
            against_version=2,
            fields={ad.text: "merged by hand"},
            resolutions={ad.text: "manual"},
            device_id="tablet-7",
        )
        out = await ad.merge(row.id, body)
        assert out.version == 3
        assert out.item[ad.text] == "merged by hand"
        assert out.item["version"] == 3
        assert [(m.field, m.side) for m in out.merged] == [(ad.text, "manual")]

        audit = await ad.audit(row.id)
        assert len(audit) == 1
        assert audit[0].field == ad.text
        assert audit[0].side == "manual"
        assert audit[0].old_value == "server edit"
        assert audit[0].new_value == "merged by hand"
        assert audit[0].device_id == "tablet-7"
        assert audit[0].actor_id == USER

        import asyncio

        await asyncio.sleep(0)
        assert seen, "offline_merge_resolved was not published"
        payload = seen[-1]
        assert payload["entity_id"] == str(row.id)
        assert payload["version"] == 3
        assert payload["device_id"] == "tablet-7"
    finally:
        event_bus.unsubscribe(ad.event, _on)


async def test_merge_theirs_keeps_the_server_value(ad: _Diary) -> None:
    row = await ad.create()
    await ad.update(row.id, "server edit")
    body = _req(ad, base_version=1, against_version=2, fields={ad.text: "mine"}, resolutions={ad.text: "theirs"})
    out = await ad.merge(row.id, body)
    assert out.item[ad.text] == "server edit"
    assert out.version == 3


async def test_merge_with_an_unresolved_conflict_is_422(ad: _Diary) -> None:
    row = await ad.create()
    await ad.update(row.id, "server edit")
    body = _req(ad, base_version=1, against_version=2, fields={ad.text: "mine"})
    with pytest.raises(HTTPException) as exc:
        await ad.merge(row.id, body)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "merge_incomplete"
    assert exc.value.detail["conflicts"] == [ad.text]
    assert exc.value.detail["errors"][0]["rule_id"] == "offline_sync.merge_complete"
    assert await ad.audit(row.id) == []


async def test_merge_against_a_stale_version_is_409(ad: _Diary) -> None:
    row = await ad.create()
    await ad.update(row.id, "server edit")
    await ad.update(row.id, "server edit 2")  # version 3
    body = _req(ad, base_version=1, against_version=2, fields={ad.text: "x"}, resolutions={ad.text: "manual"})
    with pytest.raises(HTTPException) as exc:
        await ad.merge(row.id, body)
    assert exc.value.status_code == 409
    assert exc.value.detail["current_version"] == 3


async def test_merge_rejects_unknown_fields(ad: _Diary) -> None:
    row = await ad.create()
    body = _req(ad, base_version=1, against_version=1, fields={"status": "closed"})
    with pytest.raises(HTTPException) as exc:
        await ad.merge(row.id, body)
    assert exc.value.status_code == 422


async def test_merge_without_server_change_needs_no_resolution(ad: _Diary) -> None:
    row = await ad.create()
    body = _req(ad, base_version=1, against_version=1, fields={ad.text: "plain edit"})
    out = await ad.merge(row.id, body)
    assert out.version == 2
    assert out.merged[0].side == "mine"


async def test_demo_seed_is_idempotent_and_shows_a_resolved_conflict(session: AsyncSession) -> None:
    from app.core.offline_merge import list_merge_audit
    from app.modules.daily_diary.offline_demo import seed_offline_conflict_demo
    from app.modules.punchlist.models import PunchItem

    pid = uuid.uuid4()
    first = await seed_offline_conflict_demo(session, pid)
    again = await seed_offline_conflict_demo(session, pid)
    assert first == again
    conflict = await session.get(PunchItem, uuid.UUID(first["conflict_punch_id"]))
    assert conflict is not None
    assert conflict.version == 3
    assert conflict.metadata_["captured_offline"] is True
    audit = await list_merge_audit(session, "punchlist_item", conflict.id)
    assert len(audit) == 1
    assert audit[0].side == "manual"
