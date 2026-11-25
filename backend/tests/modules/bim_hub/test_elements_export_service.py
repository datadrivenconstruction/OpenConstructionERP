"""Element export through the service on PostgreSQL: filters in SQL, streamed CSV/JSON, capped XLSX, safe cells."""

from __future__ import annotations

import csv
import io
import json
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from openpyxl import load_workbook

from app.modules.bim_hub import service as svc_mod
from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.bim_hub.service import BIMHubService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def model():
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(id=uuid.uuid4(), email=f"x-{uuid.uuid4().hex[:6]}@test.io", hashed_password="x", full_name="X")
        s.add(owner)
        await s.flush()
        project = Project(id=uuid.uuid4(), name="P", owner_id=owner.id, currency="EUR")
        s.add(project)
        await s.flush()
        m = BIMModel(id=uuid.uuid4(), project_id=project.id, name="M", discipline="arch", version="1", status="ready")
        s.add(m)
        await s.flush()
        rows = [
            ("w1", "Walls", "L1", "=HYPERLINK(x)", {"Material": "+cmd"}),
            ("w2", "Walls", "L2", "Wall", {"Mark": "@SUM(A1)"}),
            ("s1", "Slabs", "L1", "\tTab", {"Fire": "-1+1"}),
        ]
        for sid, etype, storey, name, props in rows:
            s.add(
                BIMElement(
                    id=uuid.uuid4(),
                    model_id=m.id,
                    stable_id=sid,
                    element_type=etype,
                    storey=storey,
                    name=name,
                    properties=props,
                    quantities={"area_m2": 2.5},
                )
            )
        await s.commit()
        yield s, m.id


async def test_csv_filters_in_sql_and_neutralises_every_formula_lead(model):
    s, mid = model
    out, media, name = await BIMHubService(s).export_elements(mid, "csv", filters={"element_type": "Walls"})
    rows = list(csv.DictReader(io.StringIO(out.read().decode("utf-8-sig"))))
    assert media.startswith("text/csv") and name == "Elements_M.csv"
    assert [r["element_id"] for r in rows] == ["w1", "w2"]
    assert rows[0]["name"] == "'=HYPERLINK(x)" and rows[0]["prop:Material"] == "'+cmd"
    assert rows[1]["prop:Mark"] == "'@SUM(A1)"
    assert "prop:Fire" not in rows[0]  # the slab's key is not in the walls' columns


async def test_json_streams_the_filtered_rows(model):
    s, mid = model
    out, _, _ = await BIMHubService(s).export_elements(mid, "json", filters={"storey": ["L1"]})
    payload = json.loads(out.read())
    assert payload["count"] == 2 and {e["element_id"] for e in payload["elements"]} == {"w1", "s1"}


async def test_xlsx_cells_are_safe_and_the_row_count_is_capped(model, monkeypatch):
    s, mid = model
    out, _, _ = await BIMHubService(s).export_elements(mid, "xlsx")
    ws = load_workbook(io.BytesIO(out.read())).active
    values = {c.value for row in ws.iter_rows(min_row=2) for c in row}
    assert {"'\tTab", "'-1+1", "'=HYPERLINK(x)"} <= values
    monkeypatch.setattr(svc_mod, "XLSX_EXPORT_MAX_ROWS", 2)
    with pytest.raises(HTTPException) as exc:
        await BIMHubService(s).export_elements(mid, "xlsx")
    assert exc.value.status_code == 413
    assert exc.value.detail["code"] == "export_too_large_for_xlsx" and exc.value.detail["params"] == {
        "rows": 3,
        "max": 2,
    }
