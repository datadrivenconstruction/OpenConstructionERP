# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Spreadsheet schedule import over HTTP: preview, commit, replace, template.

What is pinned here:

* preview writes nothing and reports duplicates of earlier imports;
* commit re-reads the file, refuses bytes that differ from the preview, refuses
  a second import of the same bytes unless ``allow_duplicate``, writes the
  schedule in one go and runs CPM and the schedule quality pack after it;
* replacing works on an untouched draft and is refused, each with its own code,
  for a non-draft, a baselined schedule, recorded progress and work orders;
* another tenant gets 404 whichever id it supplies;
* an unconfirmed day/month order is a 422 until the order is given;
* a sheet's ``client_visible`` column is only a suggestion the preview returns;
  the commit makes visible exactly the refs the person confirmed;
* durations are counted on the project's own week (a Gulf project's
  Sunday-to-Thursday);
* the downloadable template in every language reads back without an error;
* each activity keeps its sheet row in ``metadata.import_row`` through CPM;
* the interchange document import keeps every activity hidden whatever the
  document says, since nobody confirmed its visibility.

The routes are reached through the schedule module's own mount, not a test one.
"""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

PREFIX = "/api/v1/schedule/schedule/import/spreadsheet"

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.schedule import models as _schedule_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # No test mount: every request below goes through the schedule module's
        # own include. ``app.routes`` cannot be asked, it holds included routers
        # unflattened.
        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _editor(client: AsyncClient, tenant: str) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"{tenant}-{uuid.uuid4().hex[:8]}@schedule-tabular.io"
    password = f"ScheduleTabular{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="editor", is_active=True))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _project(client: AsyncClient, headers: dict[str, str], *, region: str = "DACH") -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": f"Tabular {uuid.uuid4().hex[:6]}", "currency": "EUR", "region": region},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def tenants(http_client):
    a = await _editor(http_client, "a")
    b = await _editor(http_client, "b")
    return {"a": a, "b": b, "b_project": await _project(http_client, b)}


def _csv(rows: list[list[Any]]) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue().encode("utf-8")


#: Five activities, an outline, a lead, a milestone and one client-visible row.
PLAN = _csv(
    [
        ["ID", "Name", "WBS", "Start", "Finish", "Duration", "Predecessors", "Client Visible"],
        ["A10", "Shell and core", "1", "", "", "", "", "no"],
        ["A20", "Excavation", "1.1", "2026-05-04", "2026-05-08", "5", "", "no"],
        ["A30", "Foundations", "1.2", "2026-05-11", "2026-05-15", "5", "A20FS", "no"],
        ["A40", "Ground slab", "1.3", "2026-05-13", "2026-05-19", "5", "A30FF-2d", ""],
        ["A50", "Foundations accepted", "1.4", "2026-05-19", "2026-05-19", "0", "A40", "yes"],
    ]
)


async def _preview(client, headers, project_id, data, filename="plan.csv", **form) -> Any:
    return await client.post(
        f"{PREFIX}/preview/",
        data={"project_id": project_id, **form},
        files={"file": (filename, data, "text/csv")},
        headers=headers,
    )


async def _commit(client, headers, project_id, data, sha=None, filename="plan.csv", **form) -> Any:
    if sha is None:
        first = await _preview(
            client, headers, project_id, data, filename, **{k: v for k, v in form.items() if k == "date_order"}
        )
        assert first.status_code == 200, first.text
        sha = first.json()["sha256"]
    return await client.post(
        f"{PREFIX}/commit/",
        data={"project_id": project_id, "expected_sha256": sha, **form},
        files={"file": (filename, data, "text/csv")},
        headers=headers,
    )


async def _schedule_count(project_id: str) -> int:
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.schedule.models import Schedule

    async with async_session_factory() as s:
        return int(
            (
                await s.execute(
                    select(func.count()).select_from(Schedule).where(Schedule.project_id == uuid.UUID(project_id))
                )
            ).scalar_one()
        )


async def _activities(schedule_id: str) -> dict[str, Any]:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.schedule.models import Activity

    async with async_session_factory() as s:
        rows = (await s.execute(select(Activity).where(Activity.schedule_id == uuid.UUID(schedule_id)))).scalars().all()
        return {
            a.activity_code: {
                "id": a.id,
                "parent_id": a.parent_id,
                "start": a.start_date,
                "end": a.end_date,
                "duration": a.duration_days,
                "type": a.activity_type,
                "client_visible": a.client_visible,
                "cpm": (a.metadata_ or {}).get("cpm"),
                "import_row": (a.metadata_ or {}).get("import_row"),
            }
            for a in rows
        }


# ── Preview ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_reads_the_file_and_writes_nothing(http_client, tenants):
    project_id = await _project(http_client, tenants["a"])
    before = await _schedule_count(project_id)
    resp = await _preview(http_client, tenants["a"], project_id, PLAN)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_errors"] is False, body["issues"]
    assert body["activity_count"] == 5
    assert body["relationship_count"] == 3
    assert body["mapping"]["predecessors"] == 6
    assert body["duplicate_of"] == []
    assert len(body["sha256"]) == 64
    assert await _schedule_count(project_id) == before


@pytest.mark.asyncio
async def test_preview_over_the_size_limit_is_413(http_client, tenants):
    from app.modules.schedule.tabular_import import MAX_FILE_BYTES

    project_id = tenants["b_project"]
    resp = await _preview(http_client, tenants["b"], project_id, b"Name\n" + b"x" * MAX_FILE_BYTES)
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "file_too_large"


# ── Commit ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_commit_writes_the_schedule_then_runs_cpm_and_validation(http_client, tenants):
    project_id = await _project(http_client, tenants["a"])
    resp = await _commit(http_client, tenants["a"], project_id, PLAN, filename="Oak Lane.csv")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["activity_count"], body["relationship_count"], body["replaced"]) == (5, 3, False)
    assert body["schedule_name"] == "Oak Lane"
    assert body["critical_count"] >= 1
    assert body["validation"]["rule_sets"] == ["schedule_quality"]
    for finding in body["validation"]["findings"]:
        if finding["element_ref"] in {"A10", "A20", "A30", "A40", "A50"}:
            assert finding["row"] in range(2, 7)

    acts = await _activities(body["schedule_id"])
    assert (acts["A20"]["start"], acts["A20"]["end"], acts["A20"]["duration"]) == ("2026-05-04", "2026-05-08", 5)
    assert acts["A20"]["parent_id"] == acts["A10"]["id"]
    assert acts["A50"]["type"] == "milestone"
    assert all(a["cpm"] is not None for a in acts.values())
    # CPM writes its own metadata key and leaves the sheet row beside it.
    assert {code: a["import_row"] for code, a in acts.items()} == {"A10": 2, "A20": 3, "A30": 4, "A40": 5, "A50": 6}

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.schedule.models import ScheduleRelationship

    async with async_session_factory() as s:
        lag = (
            await s.execute(
                select(ScheduleRelationship.lag_days, ScheduleRelationship.relationship_type).where(
                    ScheduleRelationship.successor_id == acts["A40"]["id"]
                )
            )
        ).one()
    assert tuple(lag) == (-2, "FF")


@pytest.mark.asyncio
async def test_a_sheet_yes_is_a_suggestion_and_stays_hidden_unconfirmed(http_client, tenants):
    project_id = await _project(http_client, tenants["a"])
    preview = await _preview(http_client, tenants["a"], project_id, PLAN)
    body = preview.json()
    assert body["client_visible_suggested"] == ["A50"]
    assert not any(a["client_visible"] for a in body["document"]["activities"])

    resp = await _commit(http_client, tenants["a"], project_id, PLAN)
    assert resp.status_code == 201, resp.text
    acts = await _activities(resp.json()["schedule_id"])
    assert not any(a["client_visible"] for a in acts.values())


@pytest.mark.asyncio
async def test_only_the_confirmed_refs_become_client_visible(http_client, tenants):
    project_id = await _project(http_client, tenants["a"])
    # The person keeps the suggested milestone and adds a row the sheet left at "no".
    resp = await _commit(http_client, tenants["a"], project_id, PLAN, client_visible_refs='["A20", "A50"]')
    assert resp.status_code == 201, resp.text
    acts = await _activities(resp.json()["schedule_id"])
    assert {code for code, a in acts.items() if a["client_visible"]} == {"A20", "A50"}

    no_column = _csv([["ID", "Name", "Duration"], ["M1", "Handover", "0"], ["T1", "Snagging", "3"]])
    resp = await _commit(http_client, tenants["a"], project_id, no_column, client_visible_refs='["M1"]')
    assert resp.status_code == 201, resp.text
    acts = await _activities(resp.json()["schedule_id"])
    assert {code for code, a in acts.items() if a["client_visible"]} == {"M1"}


@pytest.mark.asyncio
async def test_the_interchange_import_never_trusts_a_documents_visibility(http_client, tenants):
    project_id = await _project(http_client, tenants["a"])
    preview = await _preview(http_client, tenants["a"], project_id, PLAN)
    document = preview.json()["document"]
    for activity in document["activities"]:
        activity["client_visible"] = True
    resp = await http_client.post(
        "/api/v1/schedule/schedules/import",
        json={"project_id": project_id, "document": document},
        headers=tenants["a"],
    )
    assert resp.status_code == 201, resp.text
    acts = await _activities(resp.json()["schedule_id"])
    assert len(acts) == 5
    assert not any(a["client_visible"] for a in acts.values())


@pytest.mark.asyncio
async def test_a_confirmed_ref_outside_the_file_or_a_malformed_list_is_refused(http_client, tenants):
    project_id = await _project(http_client, tenants["a"])
    before = await _schedule_count(project_id)
    resp = await _commit(http_client, tenants["a"], project_id, PLAN, client_visible_refs='["A50", "Z99"]')
    assert resp.status_code == 422
    assert resp.json()["detail"] == {
        "code": "client_visible_unknown_ref",
        "message": "Some activities confirmed as client-visible are not in the file",
        "refs": ["Z99"],
    }
    for bad in ('{"A50": true}', "A50", "[true]"):
        resp = await _commit(http_client, tenants["a"], project_id, PLAN, client_visible_refs=bad)
        assert resp.status_code == 422, bad
        assert resp.json()["detail"]["code"] == "client_visible_refs_invalid"
    assert await _schedule_count(project_id) == before


@pytest.mark.asyncio
async def test_commit_refuses_bytes_other_than_the_previewed_ones(http_client, tenants):
    project_id = tenants["b_project"]
    resp = await _commit(http_client, tenants["b"], project_id, PLAN, sha="0" * 64)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "preview_mismatch"


@pytest.mark.asyncio
async def test_second_import_of_the_same_file_is_409_unless_allowed(http_client, tenants):
    project_id = await _project(http_client, tenants["a"])
    first = await _commit(http_client, tenants["a"], project_id, PLAN)
    assert first.status_code == 201, first.text

    again = await _preview(http_client, tenants["a"], project_id, PLAN)
    assert again.json()["duplicate_of"] == [first.json()["schedule_id"]]

    second = await _commit(http_client, tenants["a"], project_id, PLAN)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate_import"
    assert second.json()["detail"]["schedule_ids"] == [first.json()["schedule_id"]]

    allowed = await _commit(http_client, tenants["a"], project_id, PLAN, allow_duplicate="true")
    assert allowed.status_code == 201, allowed.text


@pytest.mark.asyncio
async def test_unconfirmed_date_order_is_422_until_given(http_client, tenants):
    project_id = await _project(http_client, tenants["a"])
    ambiguous = _csv(
        [
            ["Nr.", "Vorgangsname", "Dauer", "Anfang", "Ende"],
            ["10", "Baustelleneinrichtung", "5", "04.05.2026", "08.05.2026"],
            ["20", "Erdarbeiten", "2", "11.05.2026", "12.05.2026"],
        ]
    )
    preview = await _preview(http_client, tenants["a"], project_id, ambiguous)
    issue = next(i for i in preview.json()["issues"] if i["code"] == "date_order_unconfirmed")
    assert issue["params"]["suggested"] == "dmy"

    refused = await _commit(http_client, tenants["a"], project_id, ambiguous, sha=preview.json()["sha256"])
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["code"] == "import_has_errors"
    assert "date_order_unconfirmed" in {i["code"] for i in detail["issues"]}

    accepted = await _commit(http_client, tenants["a"], project_id, ambiguous, date_order="dmy")
    assert accepted.status_code == 201, accepted.text
    acts = await _activities(accepted.json()["schedule_id"])
    assert acts["20"]["start"] == "2026-05-11"


@pytest.mark.asyncio
async def test_durations_are_counted_on_the_projects_own_week(http_client, tenants):
    # 2026-05-03 is a Sunday: five working days to Thursday on a Gulf week,
    # four on the default Monday-to-Friday week.
    plan = _csv([["Name", "Start", "Finish", "Duration"], ["Pour", "2026-05-03", "2026-05-07", "5"]])
    gulf = await _project(http_client, tenants["a"], region="QA")
    resp = await _preview(http_client, tenants["a"], gulf, plan)
    assert "duration_mismatch" not in {i["code"] for i in resp.json()["issues"]}

    standard = await _project(http_client, tenants["a"])
    resp = await _preview(http_client, tenants["a"], standard, plan)
    assert "duration_mismatch" in {i["code"] for i in resp.json()["issues"]}


# ── Replace ────────────────────────────────────────────────────────────────


REPLACEMENT = _csv(
    [["ID", "Name", "Duration", "Predecessors"], ["R1", "Survey", "2", ""], ["R2", "Setting out", "1", "R1"]]
)


async def _draft(client, headers) -> tuple[str, str]:
    project_id = await _project(client, headers)
    resp = await _commit(client, headers, project_id, PLAN)
    assert resp.status_code == 201, resp.text
    return project_id, resp.json()["schedule_id"]


@pytest.mark.asyncio
async def test_replace_swaps_the_contents_of_an_untouched_draft(http_client, tenants):
    project_id, schedule_id = await _draft(http_client, tenants["a"])
    resp = await _commit(
        http_client, tenants["a"], project_id, REPLACEMENT, target="replace", schedule_id=schedule_id, name="Rev B"
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["schedule_id"], body["replaced"], body["schedule_name"]) == (schedule_id, True, "Rev B")
    acts = await _activities(schedule_id)
    assert set(acts) == {"R1", "R2"}
    assert await _schedule_count(project_id) == 1


async def _set(model_update) -> None:
    from app.database import async_session_factory

    async with async_session_factory() as s:
        await model_update(s)
        await s.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("history", ["not_draft", "has_baseline", "has_progress", "has_work_orders"])
async def test_replace_is_refused_when_the_schedule_has_history(http_client, tenants, history):
    from sqlalchemy import update

    from app.modules.schedule.models import Activity, Schedule, ScheduleBaseline, WorkOrder

    project_id, schedule_id = await _draft(http_client, tenants["a"])
    sid = uuid.UUID(schedule_id)
    acts = await _activities(schedule_id)

    async def _apply(s):
        if history == "not_draft":
            await s.execute(update(Schedule).where(Schedule.id == sid).values(status="active"))
        elif history == "has_baseline":
            s.add(
                ScheduleBaseline(
                    schedule_id=sid,
                    project_id=uuid.UUID(project_id),
                    name="Contract",
                    baseline_date="2026-05-01",
                    snapshot_data={},
                )
            )
        elif history == "has_progress":
            await s.execute(update(Activity).where(Activity.id == acts["A20"]["id"]).values(progress_pct="40"))
        else:
            s.add(WorkOrder(activity_id=acts["A20"]["id"], code="WO-1"))

    await _set(_apply)
    resp = await _commit(http_client, tenants["a"], project_id, REPLACEMENT, target="replace", schedule_id=schedule_id)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == f"replace_{history}"
    assert set(await _activities(schedule_id)) == {"A10", "A20", "A30", "A40", "A50"}


# ── Tenancy ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_another_tenant_gets_404_whichever_id_it_supplies(http_client, tenants):
    project_id, schedule_id = await _draft(http_client, tenants["a"])
    b = tenants["b"]

    assert (await _preview(http_client, b, project_id, REPLACEMENT)).status_code == 404
    sha = (await _preview(http_client, b, tenants["b_project"], REPLACEMENT)).json()["sha256"]
    into_a = await _commit(http_client, b, project_id, REPLACEMENT, sha=sha)
    assert into_a.status_code == 404
    # B's own project with A's schedule id: the schedule is not in that project.
    across = await _commit(
        http_client, b, tenants["b_project"], REPLACEMENT, sha=sha, target="replace", schedule_id=schedule_id
    )
    assert across.status_code == 404
    assert set(await _activities(schedule_id)) == {"A10", "A20", "A30", "A40", "A50"}


# ── Template ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", ["en", "de", "es", "fr", "ru", "pt", "it", "nl", "pl", "tr"])
@pytest.mark.parametrize("file_format", ["csv", "xlsx"])
async def test_template_reads_back_cleanly(http_client, tenants, lang, file_format):
    resp = await http_client.get(
        f"{PREFIX}/template/", params={"lang": lang, "format": file_format}, headers=tenants["b"]
    )
    assert resp.status_code == 200, resp.text
    assert f"schedule_import_template_{lang}.{file_format}" in resp.headers["content-disposition"]
    preview = await _preview(http_client, tenants["b"], tenants["b_project"], resp.content, filename=f"t.{file_format}")
    body = preview.json()
    assert body["has_errors"] is False, body["issues"]
    assert len(body["mapping"]) == 13
    assert body["activity_count"] == 4
    assert body["relationship_count"] == 2


@pytest.mark.asyncio
async def test_template_falls_back_to_english_for_an_unknown_language(http_client, tenants):
    resp = await http_client.get(f"{PREFIX}/template/", params={"lang": "xx", "format": "csv"}, headers=tenants["b"])
    assert resp.status_code == 200
    assert resp.content.decode("utf-8-sig").startswith("ID,Name,WBS")
