# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Export: the columns the sheet has, in its established order, with the
awkward text surviving the round trip and a formula never surviving it."""

from __future__ import annotations

import csv
import io

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import day, make_project, make_user, raise_request, seeded
from tests.modules.work_requests.conftest import API_BASE, API_MANAGER

EXPECTED_HEADER = [
    "Reference",
    "Department",
    "Request types",
    "Title",
    "Job number",
    "Client",
    "Raised by",
    "Raised on",
    "Assignees",
    "Responsible",
    "Stage",
    "Status",
    "Ball in court",
    "Due date",
    "Info required by",
    "Quoted hours",
    "Logged hours",
    "Hours to complete",
    "Hours at completion",
    "Deviation",
    "Hourly rate",
    "Cost at completion",
    "Checklist",
    "Last activity",
]


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


def _read(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))


@pytest.mark.asyncio
async def test_the_columns_match_the_intake_sheet_order(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    proj = await make_project(session, owner=pm)
    dept = (await seeded(session))["workshop"]
    await service.update_department(session, dept, {"hourly_rate": "150"})
    await service.update_request_type(
        session,
        dept,
        "switchboard",
        {"checklist": [{"key": "fat", "label": "FAT booked"}, {"key": "qa", "label": "QA"}]},
    )
    req = await raise_request(
        session,
        project=proj,
        user=pm,
        quoted_hours=40,
        due_date=day(7),
        info_required_by=day(2),
        assignee_ids=[str(fitter.id)],
        responsible_user_id=str(fitter.id),
    )
    await service.log_hours(session, req, day=day(0), hours=6, user_id=str(pm.id), can_manage=True)
    await service.update_request(session, req, {"hours_to_complete": 30}, user_id=str(pm.id), can_manage=True)
    await service.set_checklist_item(session, req, "fat", True, user_id=str(pm.id), can_manage=False)

    out = await service.export_requests(session, fmt="csv", department="workshop", project_ids=None, project_id=proj.id)
    rows = _read(out["content"])
    assert rows[0] == EXPECTED_HEADER
    assert len(rows) == 2 and out["rows"] == 1

    line = dict(zip(EXPECTED_HEADER, rows[1], strict=True))
    assert line["Reference"] == req.reference
    assert line["Department"] == "Workshop"
    assert line["Request types"] == "Switchboard"
    assert line["Title"] == "MSB-01 main switchboard"
    assert line["Job number"] == "25406"
    assert line["Client"] == "Acme Holdings"
    assert line["Raised by"] == "PM Example"
    assert line["Assignees"] == "Fitter Example"
    assert line["Responsible"] == "Fitter Example"
    assert line["Stage"] == "Requested"
    assert line["Status"] == "submitted"
    assert line["Ball in court"] == "department"
    assert line["Due date"] == day(7)
    assert line["Info required by"] == day(2)
    assert line["Quoted hours"] == "40.00"
    assert line["Logged hours"] == "6.00"
    assert line["Hours to complete"] == "30.00"
    assert line["Hours at completion"] == "36.00"
    assert line["Deviation"] == "-4.00"
    assert line["Hourly rate"] == "150.00"
    assert line["Cost at completion"] == "5400.00"
    assert line["Checklist"] == "1/2"
    assert line["Last activity"].startswith(str(req.updated_at)[:10])


@pytest.mark.asyncio
async def test_awkward_text_survives_and_a_formula_does_not(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    nasty = 'MSB-01, "the big one"\nlevel 2'
    req = await raise_request(session, project=proj, user=pm, title=nasty)
    await service.update_request(
        session, req, {"cost_centres": {"workshop": "=cmd|calc"}}, user_id=str(pm.id), can_manage=True
    )

    out = await service.export_requests(session, fmt="csv", project_ids=None, project_id=proj.id)
    rows = _read(out["content"])
    # The title is single-lined on the way in, so the newline is a space -
    # the comma and the quotes are what the writer has to survive.
    assert rows[1][EXPECTED_HEADER.index("Title")] == 'MSB-01, "the big one" level 2'
    assert len(rows) == 2, "an embedded comma never becomes a second row"

    assert service._formula_safe("=SUM(A1:A9)") == "'=SUM(A1:A9)"
    assert service._formula_safe("@import") == "'@import"
    assert service._formula_safe("-4.00") == "-4.00", "a negative number is a number, not a formula"
    assert service._formula_safe("+61 2 9000 0000") == "'+61 2 9000 0000"


@pytest.mark.asyncio
async def test_templates_and_filters_are_honoured(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    live = await raise_request(session, project=proj, user=pm, title="MSB-01 main switchboard")
    tmpl = await raise_request(session, project=proj, user=pm, title="Standard switchboard")
    await service.update_request(session, tmpl, {"is_template": True}, user_id=str(pm.id), can_manage=True)
    await raise_request(
        session, project=proj, user=pm, department="drafting", request_type="drafting_only", title="GA for MSB-01"
    )

    everything = _read((await service.export_requests(session, project_ids=None, project_id=proj.id))["content"])
    assert sorted(r[0] for r in everything[1:]) == sorted([live.reference, "WR-DRF-000001"])

    workshop = await service.export_requests(session, department="workshop", project_ids=None, project_id=proj.id)
    rows = _read(workshop["content"])
    assert [r[0] for r in rows[1:]] == [live.reference]
    assert workshop["filename"] == f"work-requests-workshop-{service._today().isoformat()}.csv"

    templates = await service.export_requests(session, project_ids=None, project_id=proj.id, is_template=True)
    assert [r[0] for r in _read(templates["content"])[1:]] == [tmpl.reference]


@pytest.mark.asyncio
async def test_the_filename_names_the_department_or_all(session: AsyncSession) -> None:
    await seeded(session)
    today = service._today().isoformat()
    assert service.export_filename(None, "csv") == f"work-requests-all-{today}.csv"
    assert service.export_filename("workshop", "xlsx") == f"work-requests-workshop-{today}.xlsx"
    assert service.export_filename("../etc/passwd", "csv") == f"work-requests-etc-passwd-{today}.csv"


@pytest.mark.asyncio
async def test_xlsx_is_a_real_workbook(session: AsyncSession) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    req = await raise_request(session, project=proj, user=pm)

    out = await service.export_requests(session, fmt="xlsx", project_ids=None, project_id=proj.id)
    assert out["format"] == "xlsx" and out["note"] == ""
    assert out["filename"].endswith(".xlsx")
    assert out["media_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    book = openpyxl.load_workbook(io.BytesIO(out["content"]))
    sheet = book["Work requests"]
    assert [c.value for c in sheet[1]] == EXPECTED_HEADER
    assert sheet.cell(row=2, column=1).value == req.reference


@pytest.mark.asyncio
async def test_an_unknown_format_is_refused(session: AsyncSession) -> None:
    await seeded(session)
    with pytest.raises(service.WorkRequestError, match="Unknown export format"):
        await service.export_requests(session, fmt="pdf", project_ids=None)


@pytest.mark.asyncio
async def test_export_over_http(api) -> None:
    client, pid, state = api
    state["payload"] = dict(API_MANAGER)
    made = await client.post(
        f"{API_BASE}/requests",
        json={"project_id": pid, "department": "workshop", "request_type": "switchboard", "title": "MSB-01"},
    )
    assert made.status_code == 201

    r = await client.get(f"{API_BASE}/requests/export", params={"project_id": pid, "department": "workshop"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["x-export-rows"] == "1"
    assert 'filename="work-requests-workshop-' in r.headers["content-disposition"]
    rows = _read(r.content)
    assert rows[0] == EXPECTED_HEADER and rows[1][0] == "WR-WKS-000001"

    x = await client.get(f"{API_BASE}/requests/export", params={"project_id": pid, "format": "xlsx"})
    assert x.status_code == 200
    assert x.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert x.headers["content-disposition"].endswith('.xlsx"')

    bad = await client.get(f"{API_BASE}/requests/export", params={"project_id": pid, "format": "pdf"})
    assert bad.status_code == 400 and "Unknown export format" in bad.json()["detail"]
