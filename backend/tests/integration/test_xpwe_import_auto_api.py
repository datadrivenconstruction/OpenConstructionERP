# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""End-to-end XPWE (Italian estimating XML) import through ``POST /import/auto/``.

The unit suite pins the parser and the shaper; this one pins what lands in the
database through the real ASGI app:

* the stored tree, by ordinal and parent, is the category tree of the file,
  with an item whose section's sub-sections come first still under its own
  section (the ``import_section`` signal, not "the last section");
* the quantities are the measured ones, the measurement sheet survives JSONB,
  and the safety item and the source pass ``PositionCreate``;
* the notes come back in the response;
* an estimating program's own project file is refused in the reader's language.

Run:
    cd backend
    OE_TEST_DB=pg python -m pytest tests/integration/test_xpwe_import_auto_api.py -v
"""

from __future__ import annotations

import os
import time
import tracemalloc
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Eager-import the model namespaces this suite touches so Base.metadata sees a
# coherent table set when create_all runs (mirrors the BOQ authz baseline).
import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.teams.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from tests.fixtures import xpwe_builder as fx

# The small bill with item 4 moved under Piano terra / Murature / Ala nord, so
# section 1.2 holds its own item 2 (1.2.1) AND a sub-section (1.2.2, with item
# 4), in the order the editor keeps a section in. Item 5, filed under no
# category, comes after section 2's sub-tree: "the last section" would put it
# under 2.1, and only its own empty ``import_section`` keeps it at the top.
_CONTENT = fx.replaced(
    "<IDSpCat>2</IDSpCat><IDCat>2</IDCat><IDSbCat>0</IDSbCat>",
    "<IDSpCat>1</IDSpCat><IDCat>2</IDCat><IDSbCat>1</IDSbCat>",
)

# Ordinal -> its parent's ordinal ("" for top level), sections and items alike.
_TREE = {
    "1": "",
    "1.1": "1",
    "1.1.1": "1.1",
    "1.2": "1",
    "1.2.1": "1.2",
    "1.2.2": "1.2",
    "1.2.2.1": "1.2.2",
    "2": "",
    "2.1": "2",
    "2.1.1": "2.1",
    "3": "",
}
_SECTIONS = 6


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module and create all tables."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()

    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def auth_headers(http_client) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"xpwe-import-{uuid.uuid4().hex[:8]}@import-auto.io"
    password = f"XpweImport{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "XPWE Import"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.status_code} {reg.text}"
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role="admin"))
        await s.commit()
    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, f"login failed: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def boq_id(http_client, auth_headers) -> str:
    project = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Computo {uuid.uuid4().hex[:6]}",
            "description": "XPWE /import/auto/ end-to-end",
            "region": "IT",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert project.status_code == 201, f"create project failed: {project.text}"
    boq = await http_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project.json()["id"], "name": "Computo metrico", "description": "import target"},
        headers=auth_headers,
    )
    assert boq.status_code == 201, f"create BOQ failed: {boq.text}"
    return boq.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def imported(http_client, auth_headers, boq_id) -> tuple[dict, list[dict]]:
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/auto/",
        files={"file": ("computo.xpwe", _CONTENT, "application/xml")},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"import/auto failed: {resp.status_code} {resp.text[:500]}"
    stored = await http_client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth_headers)
    assert stored.status_code == 200, stored.text[:300]
    return resp.json(), stored.json()["positions"]


@pytest.mark.asyncio
async def test_the_bill_lands_through_the_native_reader(imported) -> None:
    body, _positions = imported
    assert body["method"] == "native"
    assert body["format_id"] == "xpwe"
    assert body["errors"] == [], body["errors"]
    assert body["created"] == _SECTIONS + 5
    assert body["metadata"]["measurement_rows"] == 8
    assert {w["code"] for w in body["warnings"]} >= {"xpwe_see_item_flattened"}


@pytest.mark.asyncio
async def test_the_stored_tree_is_the_files_category_tree(imported) -> None:
    _body, positions = imported
    by_id = {p["id"]: p for p in positions}
    parent_ordinal = {p["ordinal"]: (by_id[p["parent_id"]]["ordinal"] if p.get("parent_id") else "") for p in positions}
    assert parent_ordinal == _TREE
    items = {
        p["metadata"]["xpwe_vc_id"]: p["ordinal"] for p in positions if (p.get("metadata") or {}).get("xpwe_vc_id")
    }
    assert items == {"1": "1.1.1", "2": "1.2.1", "4": "1.2.2.1", "3": "2.1.1", "5": "3"}


@pytest.mark.asyncio
async def test_quantities_are_the_measured_ones_and_the_sheet_survives(imported) -> None:
    _body, positions = imported
    items = {p["metadata"]["xpwe_vc_id"]: p for p in positions if (p.get("metadata") or {}).get("xpwe_vc_id")}
    quantities = {vc: Decimal(str(p["quantity"])) for vc, p in items.items()}
    assert quantities == {
        "1": Decimal("49.11"),
        "2": Decimal("12"),
        "3": Decimal("1"),
        "4": Decimal("24"),
        "5": Decimal("10"),
    }
    sheet = items["1"]["metadata"]["measurement"]
    assert sheet["source"] == "xpwe"
    assert len(sheet["lines"]) >= 3
    assert any(line.get("sign") == "-" for line in sheet["lines"])
    assert Decimal(str(items["1"]["unit_rate"])) == Decimal("13.63")
    assert items["1"]["unit"] == "m2"


@pytest.mark.asyncio
async def test_every_stored_sheet_reconciles_with_its_position(http_client, auth_headers, imported) -> None:
    """What the measurement drawer reports on open: a clean import matches its own sheets."""
    _body, positions = imported
    measured = [p for p in positions if ((p.get("metadata") or {}).get("measurement") or {}).get("lines")]
    assert measured
    for position in measured:
        resp = await http_client.get(f"/api/v1/boq/positions/{position['id']}/measurement/", headers=auth_headers)
        assert resp.status_code == 200, resp.text[:300]
        reconciliation = resp.json()["reconciliation"]
        assert reconciliation["matches"], (position["ordinal"], reconciliation)


@pytest.mark.asyncio
async def test_the_safety_item_and_the_source_pass_validation(imported) -> None:
    _body, positions = imported
    items = {p["metadata"]["xpwe_vc_id"]: p for p in positions if (p.get("metadata") or {}).get("xpwe_vc_id")}
    assert items["3"]["classification"].get("cost_type") == "sicurezza"
    assert items["3"]["metadata"]["safety_item"] is True
    assert {p["source"] for p in items.values()} == {"xpwe_import"}


@pytest.mark.asyncio
async def test_a_native_project_file_is_refused_in_the_readers_language(http_client, auth_headers, boq_id) -> None:
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/auto/",
        files={"file": ("progetto.dcf", b"\x00\x01binary project\x00", "application/octet-stream")},
        headers={**auth_headers, "Accept-Language": "de"},
    )
    assert resp.status_code == 400, resp.text[:300]
    detail = resp.json().get("detail")
    assert detail["code"] == "xpwe_not_xml", detail
    assert "XPWE" in detail["message"]
    assert "Export the estimate" not in detail["message"], f"refusal came back in English: {detail}"
    assert "Could not parse file as" not in str(detail), "the server still composes an English sentence around it"


async def _new_boq(http_client, auth_headers) -> str:
    project = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Scala {uuid.uuid4().hex[:6]}", "region": "IT", "currency": "EUR"},
        headers=auth_headers,
    )
    assert project.status_code == 201, project.text[:300]
    boq = await http_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project.json()["id"], "name": "Computo grande"},
        headers=auth_headers,
    )
    assert boq.status_code == 201, boq.text[:300]
    return boq.json()["id"]


@pytest.mark.asyncio
async def test_a_native_project_file_refused_in_the_background_reads_in_the_readers_language(
    http_client, auth_headers
) -> None:
    """The editor sends a program's own project file through the background job; the refusal stays translated."""
    boq = await _new_boq(http_client, auth_headers)
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq}/import/auto/?background=true",
        files={"file": ("progetto.dcf", b"\x00\x01binary project\x00", "application/octet-stream")},
        headers={**auth_headers, "Accept-Language": "de"},
    )
    if resp.status_code == 400:
        detail = str(resp.json().get("detail"))
    else:
        assert resp.status_code == 202, resp.text[:300]
        job = await _finished_job(http_client, auth_headers, boq, resp.json()["job_id"])
        assert job["status"] == "failed", job
        detail = job["error"] or ""
    assert "XPWE" in detail
    assert "Export the estimate" not in detail, f"refusal came back in English: {detail}"


async def _import(http_client, auth_headers, boq: str, content: bytes) -> dict:
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq}/import/auto/",
        files={"file": ("computo.xpwe", content, "application/xml")},
        headers=auth_headers,
        timeout=600,
    )
    assert resp.status_code == 200, resp.text[:500]
    return resp.json()


@pytest.mark.asyncio
async def test_the_statements_an_import_runs_do_not_grow_with_its_rows(http_client, auth_headers) -> None:
    """A bill is written in a bounded number of statements, not a dozen or so per row.

    One row at a time a position cost about 100 ms on a server, so a bill of
    a thousand rows outlived the proxy's timeout while the server went on
    writing, and the editor's retry wrote the bill a second time.
    """
    from sqlalchemy import event

    from app.database import engine

    async def statements_for(items: int) -> int:
        boq = await _new_boq(http_client, auth_headers)
        content = fx.measured_bill(items, categories=5)
        count = 0

        def _count(*_args: object) -> None:
            nonlocal count
            count += 1

        event.listen(engine.sync_engine, "before_cursor_execute", _count)
        try:
            body = await _import(http_client, auth_headers, boq, content)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _count)
        assert body["errors"] == [], body["errors"][:3]
        assert body["created"] == items + 5
        return count

    small = await statements_for(10)
    large = await statements_for(50)
    print(f"\nXPWE statements: 15 positions {small}, 55 positions {large}")
    # Forty more rows: one statement a row would already be forty.
    assert large - small < 20, (small, large)


@pytest.mark.asyncio
async def test_every_imported_row_reaches_the_search_index(http_client, auth_headers, monkeypatch) -> None:
    """Writing the rows together must not drop them from the search index the editor's "similar items" reads."""
    import asyncio

    from app.modules.boq import events as boq_events

    indexed: list[str] = []

    async def _one(_adapter: object, row: object, **_kwargs: object) -> bool:
        indexed.append(str(row.id))  # type: ignore[attr-defined]
        return True

    async def _many(_adapter: object, rows: list, **_kwargs: object) -> int:
        indexed.extend(str(row.id) for row in rows)
        return len(rows)

    monkeypatch.setattr(boq_events, "vector_index_one", _one)
    monkeypatch.setattr(boq_events, "vector_index_many", _many, raising=False)

    boq = await _new_boq(http_client, auth_headers)
    body = await _import(http_client, auth_headers, boq, fx.measured_bill(12, categories=3))
    assert body["created"] == 15
    stored = await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)
    ids = sorted(p["id"] for p in stored.json()["positions"])
    assert len(ids) == 15
    for _ in range(100):
        if set(ids) <= set(indexed):
            break
        await asyncio.sleep(0.1)
    assert sorted(i for i in indexed if i in set(ids)) == ids


@pytest.mark.asyncio
async def test_every_imported_row_gets_its_own_reference_code(imported) -> None:
    """The code a row is reused by: present on every row, never shared within the bill."""
    _body, positions = imported
    codes = [p.get("reference_code") for p in positions]
    assert all(codes), codes
    assert len(set(codes)) == len(codes)


@pytest.mark.asyncio
async def test_a_row_repeating_an_earlier_one_is_flagged_against_it(http_client, auth_headers) -> None:
    """The duplicate-content warning a row added by hand gets, naming the first row and not the second."""
    content = (
        fx.measured_bill(2, categories=1)
        .replace(b"numero 2,", b"numero 1,")
        .replace(b"<DesRidotta>Voce 2<", b"<DesRidotta>Voce 1<")
        .replace(b"<Prezzo1>3.25<", b"<Prezzo1>2.25<")
    )
    assert content.count(b"numero 1,") == 2
    boq = await _new_boq(http_client, auth_headers)
    await _import(http_client, auth_headers, boq, content)
    stored = await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)
    items = {
        p["metadata"]["xpwe_vc_id"]: p
        for p in stored.json()["positions"]
        if (p.get("metadata") or {}).get("xpwe_vc_id")
    }
    assert not items["1"]["metadata"].get("boq_quality_warnings")
    warnings = items["2"]["metadata"].get("boq_quality_warnings") or []
    assert any(f"'{items['1']['ordinal']}'" in w for w in warnings), warnings


def _per_row(monkeypatch) -> None:
    """Make the import write its rows one at a time, the way it did before the batch."""
    from app.modules.boq import router as boq_router

    async def _decline(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(boq_router, "_create_in_document_order", _decline)


# What differs between two imports of one file by construction: identities,
# timestamps, the generated reference code, and the absolute sort position
# (the order among siblings is compared separately).
_VOLATILE = {"id", "boq_id", "parent_id", "created_at", "updated_at", "reference_code", "sort_order", "version"}


async def _stored_shape(http_client, auth_headers, boq: str) -> tuple[dict[str, dict], dict[str, list[str]]]:
    stored = await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)
    assert stored.status_code == 200, stored.text[:300]
    positions = stored.json()["positions"]
    by_id = {p["id"]: p for p in positions}
    rows: dict[str, dict] = {}
    siblings: dict[str, list[tuple[int, str]]] = {}
    for p in positions:
        parent = by_id[p["parent_id"]]["ordinal"] if p.get("parent_id") else ""
        row = {k: v for k, v in p.items() if k not in _VOLATILE}
        row["metadata"] = {k: v for k, v in (p.get("metadata") or {}).items() if k != "import_source"}
        row["parent"] = parent
        rows[p["ordinal"]] = row
        siblings.setdefault(parent, []).append((int(p.get("sort_order") or 0), p["ordinal"]))
    return rows, {parent: [o for _s, o in sorted(kids)] for parent, kids in siblings.items()}


def _report_shape(report: dict | None) -> object:
    """A validation report minus its identity and timing; results as (rule, passed, message), order-free."""
    if not isinstance(report, dict):
        return report
    shape = {k: v for k, v in report.items() if k not in {"id", "created_at", "duration_ms", "report_id", "target_id"}}
    shape["results"] = sorted(
        (str(r.get("rule_id")), bool(r.get("passed")), str(r.get("message"))) for r in report.get("results") or []
    )
    return shape


def _ordinal_key(ordinal: str) -> tuple[int, ...]:
    return tuple(int(part) for part in ordinal.split("."))


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["small", "repeated_row"])
async def test_the_batch_stores_what_one_row_at_a_time_stored(http_client, auth_headers, monkeypatch, variant) -> None:
    """The same file imported both ways lands as the same bill, row for row, and validates the same."""
    content = (
        _CONTENT
        if variant == "small"
        else fx.measured_bill(3, categories=2)
        .replace(b"numero 3,", b"numero 1,")
        .replace(b"<DesRidotta>Voce 3<", b"<DesRidotta>Voce 1<")
        .replace(b"<Prezzo1>4.25<", b"<Prezzo1>2.25<")
    )
    batch_boq = await _new_boq(http_client, auth_headers)
    batch = await _import(http_client, auth_headers, batch_boq, content)
    with monkeypatch.context() as patch:
        _per_row(patch)
        row_boq = await _new_boq(http_client, auth_headers)
        one_by_one = await _import(http_client, auth_headers, row_boq, content)

    assert batch["created"] == one_by_one["created"]
    assert batch["errors"] == one_by_one["errors"]
    batch_rows, batch_order = await _stored_shape(http_client, auth_headers, batch_boq)
    row_rows, row_order = await _stored_shape(http_client, auth_headers, row_boq)
    # Siblings in the order the file lists them, both ways. One row at a time
    # used to put a section's second sub-section before its first (the
    # anchoring that keeps a hand-added item above the sub-sections applied to
    # an imported section too).
    assert batch_order == {parent: sorted(kids, key=_ordinal_key) for parent, kids in batch_order.items()}
    assert row_order == batch_order
    assert batch_rows.keys() == row_rows.keys()
    for ordinal, row in row_rows.items():
        assert batch_rows[ordinal] == row, ordinal
    assert batch["validation_report"] is not None
    assert _report_shape(batch["validation_report"]) == _report_shape(one_by_one["validation_report"])


@pytest.mark.asyncio
async def test_a_batch_that_fails_part_way_is_written_row_by_row_instead(
    http_client, auth_headers, monkeypatch
) -> None:
    """A statement failing after some rows were flushed takes them back; nothing is lost or written twice."""
    from sqlalchemy.exc import OperationalError

    from app.modules.boq.service import BOQService

    flush = BOQService._flush_and_release

    async def _fail_after_flushing(self: BOQService, positions: list) -> list:
        await flush(self, positions)
        raise OperationalError("INSERT", {}, Exception("connection dropped"))

    monkeypatch.setattr(BOQService, "_flush_and_release", _fail_after_flushing)
    boq = await _new_boq(http_client, auth_headers)
    body = await _import(http_client, auth_headers, boq, fx.measured_bill(6, categories=2))
    assert body["errors"] == [], body["errors"][:3]
    assert body["created"] == 8
    stored = await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)
    ordinals = [p["ordinal"] for p in stored.json()["positions"]]
    assert len(ordinals) == 8 == len(set(ordinals))


async def _totals(http_client, auth_headers, boq: str) -> tuple[Decimal, Decimal, list[dict]]:
    """The bill's total as its own page shows it, as the bill list shows it, and its markup lines."""
    detail = await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)
    assert detail.status_code == 200, detail.text[:300]
    listed = await http_client.get(f"/api/v1/boq/boqs/?project_id={detail.json()['project_id']}", headers=auth_headers)
    assert listed.status_code == 200, listed.text[:300]
    (row,) = [b for b in listed.json() if b["id"] == boq]
    markups = await http_client.get(f"/api/v1/boq/boqs/{boq}/markups/", headers=auth_headers)
    assert markups.status_code == 200, markups.text[:300]
    return Decimal(str(detail.json()["grand_total"])), Decimal(str(row["grand_total"])), markups.json()["markups"]


@pytest.mark.asyncio
async def test_a_bill_with_deductions_totals_what_the_file_does(http_client, auth_headers) -> None:
    """Deduction lines carry no price, one markup line takes their amount off, the total is the file's."""
    boq = await _new_boq(http_client, auth_headers)
    body = await _import(http_client, auth_headers, boq, fx.deductions_bill())
    assert body["errors"] == [], body["errors"]
    (note,) = [w for w in body["warnings"] if w.get("code") == "xpwe_deductions_moved"]
    assert note["count"] == 2

    shown, listed, markups = await _totals(http_client, auth_headers, boq)
    assert shown == listed == Decimal("2418.27")
    (line,) = markups
    assert (line["name"], line["markup_type"]) == ("Detrazioni / minori lavori", "fixed")
    assert Decimal(str(line["fixed_amount"])) == Decimal("-236.30")

    stored = (await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)).json()["positions"]
    credit = next(p for p in stored if (p.get("metadata") or {}).get("xpwe_vc_id") == "6")
    assert credit["metadata"]["deduction"] is True
    assert Decimal(str(credit["total"])) == 0
    measured = next(p for p in stored if (p.get("metadata") or {}).get("xpwe_vc_id") == "5")
    sheet = await http_client.get(f"/api/v1/boq/positions/{measured['id']}/measurement/", headers=auth_headers)
    assert sheet.json()["reconciliation"]["matches"], sheet.json()["reconciliation"]


@pytest.mark.asyncio
async def test_importing_the_bill_again_keeps_one_deductions_line_that_matches_the_bill(
    http_client, auth_headers
) -> None:
    """The line is worked out again from the deduction lines the bill holds, never added a second time."""
    from sqlalchemy import delete

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    boq = await _new_boq(http_client, auth_headers)
    await _import(http_client, auth_headers, boq, fx.deductions_bill())
    async with async_session_factory() as s:
        await s.execute(delete(Position).where(Position.boq_id == uuid.UUID(boq)))
        await s.commit()
    again = await _import(http_client, auth_headers, boq, fx.deductions_bill())
    assert again["errors"] == [], again["errors"][:3]

    shown, listed, markups = await _totals(http_client, auth_headers, boq)
    assert shown == listed == Decimal("2418.27")
    assert len(markups) == 1
    assert Decimal(str(markups[0]["fixed_amount"])) == Decimal("-236.30")


_WORKS = Decimal("2654.57")  # the positive items of the deductions bill
_NET = Decimal("2418.27")  # works less the 236.30 of deductions, the file's own total


def _cents(value: Decimal) -> Decimal:
    from decimal import ROUND_HALF_UP

    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _apply(http_client, auth_headers, boq: str, region: str) -> None:
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq}/markups/apply-defaults/?region={region}", headers=auth_headers
    )
    assert resp.status_code in (200, 201), resp.text[:300]


@pytest.mark.asyncio
async def test_a_template_applied_after_the_import_keeps_the_deductions_first(http_client, auth_headers) -> None:
    """Applying the price-list template must not drop the deductions, and its percentages run on the net amount."""
    boq = await _new_boq(http_client, auth_headers)
    await _import(http_client, auth_headers, boq, fx.deductions_bill())
    await _apply(http_client, auth_headers, boq, "IT_PREZZARIO")

    shown, listed, markups = await _totals(http_client, auth_headers, boq)
    names = [m["name"] for m in sorted(markups, key=lambda m: m["sort_order"])]
    assert names == ["Detrazioni / minori lavori", "Oneri della sicurezza non soggetti a ribasso", "IVA"]
    safety = _NET * Decimal("0.025")
    iva = (_NET + safety) * Decimal("0.22")
    assert shown == listed == _cents(_NET + safety + iva)


@pytest.mark.asyncio
async def test_general_expenses_after_the_deductions_are_taken_on_the_net_amount(http_client, auth_headers) -> None:
    """The analysis template on a bill with deductions: spese generali and IVA see works less deductions."""
    boq = await _new_boq(http_client, auth_headers)
    await _import(http_client, auth_headers, boq, fx.deductions_bill())
    await _apply(http_client, auth_headers, boq, "IT")

    shown, listed, markups = await _totals(http_client, auth_headers, boq)
    by_name = {m["name"]: m for m in markups}
    ordered = [m["name"] for m in sorted(markups, key=lambda m: m["sort_order"])]
    assert ordered[0] == "Detrazioni / minori lavori"
    assert by_name["Spese generali"]["apply_to"] == "subtotal"
    sg = _NET * Decimal("0.15")
    utile = (_NET + sg) * Decimal("0.10")
    # A direct_cost line further down keeps its base; the markup panel points it out.
    assert by_name["Oneri della sicurezza non soggetti a ribasso"]["apply_to"] == "direct_cost"
    safety = _WORKS * Decimal("0.025")
    iva = (_NET + sg + utile + safety) * Decimal("0.22")
    assert shown == listed == _cents(_NET + sg + utile + safety + iva)


@pytest.mark.asyncio
async def test_an_import_puts_its_deductions_before_markups_already_on_the_bill(http_client, auth_headers) -> None:
    """A template chosen before the file is imported: the deductions still go first and IVA sees the net amount."""
    boq = await _new_boq(http_client, auth_headers)
    await _apply(http_client, auth_headers, boq, "IT_PREZZARIO")
    await _import(http_client, auth_headers, boq, fx.deductions_bill())

    shown, listed, markups = await _totals(http_client, auth_headers, boq)
    ordered = sorted(markups, key=lambda m: m["sort_order"])
    assert ordered[0]["name"] == "Detrazioni / minori lavori"
    assert ordered[1]["apply_to"] == "subtotal"
    safety = _NET * Decimal("0.025")
    iva = (_NET + safety) * Decimal("0.22")
    assert shown == listed == _cents(_NET + safety + iva)


@pytest.mark.asyncio
async def test_import_without_deductions_clears_the_old_import_deduction_amount(http_client, auth_headers) -> None:
    """Replacing all rows with a positive bill must not retain the previous credit."""
    from sqlalchemy import delete

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    boq = await _new_boq(http_client, auth_headers)
    await _import(http_client, auth_headers, boq, fx.deductions_bill())
    async with async_session_factory() as session:
        await session.execute(delete(Position).where(Position.boq_id == uuid.UUID(boq)))
        await session.commit()
    result = await _import(http_client, auth_headers, boq, fx.small_computo())
    assert result["errors"] == [], result["errors"][:3]
    shown, listed, markups = await _totals(http_client, auth_headers, boq)
    assert shown == listed
    deduction_lines = [line for line in markups if (line.get("metadata") or {}).get("role") == "import_deductions"]
    assert sum((Decimal(str(line["fixed_amount"])) for line in deduction_lines), Decimal(0)) == 0


async def _post_background(http_client, auth_headers, boq: str, content: bytes):
    return await http_client.post(
        f"/api/v1/boq/boqs/{boq}/import/auto/?background=true",
        files={"file": ("computo.xpwe", content, "application/xml")},
        headers=auth_headers,
        timeout=600,
    )


async def _finished_job(http_client, auth_headers, boq: str, job_id: str) -> dict:
    import asyncio

    for _ in range(600):
        resp = await http_client.get(f"/api/v1/boq/boqs/{boq}/import/jobs/{job_id}/", headers=auth_headers)
        assert resp.status_code == 200, resp.text[:300]
        job = resp.json()
        if job["status"] in ("success", "failed", "cancelled"):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError(f"import job {job_id} did not finish: {job}")


async def _row_count(http_client, auth_headers, boq: str) -> int:
    stored = await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)
    assert stored.status_code == 200, stored.text[:300]
    return len(stored.json()["positions"])


@pytest.mark.asyncio
async def test_a_background_import_posted_twice_writes_the_bill_once(http_client, auth_headers) -> None:
    """The editor's retry after it gave up waiting gets the first import back, not a second copy."""
    boq = await _new_boq(http_client, auth_headers)
    first = await _post_background(http_client, auth_headers, boq, _CONTENT)
    assert first.status_code == 202, first.text[:300]
    second = await _post_background(http_client, auth_headers, boq, _CONTENT)
    assert second.status_code == 202, second.text[:300]
    assert second.json()["job_id"] == first.json()["job_id"]

    job = await _finished_job(http_client, auth_headers, boq, first.json()["job_id"])
    assert job["status"] == "success", job
    assert job["progress_percent"] == 100
    result = job["result"]
    assert result["created"] == _SECTIONS + 5
    assert result["format_id"] == "xpwe"
    assert result["validation_report"] is not None
    assert await _row_count(http_client, auth_headers, boq) == _SECTIONS + 5


@pytest.mark.asyncio
async def test_a_file_imported_before_is_named_as_such_and_imports_again_only_when_asked(
    http_client, auth_headers
) -> None:
    """Posting a file again on purpose is not an automatic retry: the person is told, then decides."""
    boq = await _new_boq(http_client, auth_headers)
    first = (await _post_background(http_client, auth_headers, boq, _CONTENT)).json()
    done = await _finished_job(http_client, auth_headers, boq, first["job_id"])
    assert done["status"] == "success", done

    before = (await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)).json()["positions"]
    before_by_id = {p["id"]: p for p in before}
    again = await _post_background(http_client, auth_headers, boq, _CONTENT)
    assert again.status_code == 409, again.text[:300]
    detail = again.json()["detail"]
    assert detail["code"] == "import_already_done", detail
    assert detail["params"]["imported_at"], detail
    assert await _row_count(http_client, auth_headers, boq) == _SECTIONS + 5

    forced = await http_client.post(
        f"/api/v1/boq/boqs/{boq}/import/auto/?background=true&force=true",
        files={"file": ("computo.xpwe", _CONTENT, "application/xml")},
        headers=auth_headers,
        timeout=600,
    )
    assert forced.status_code == 202, forced.text[:300]
    assert forced.json()["job_id"] != first["job_id"]
    repeated = await _finished_job(http_client, auth_headers, boq, forced.json()["job_id"])
    assert repeated["status"] == "success"
    assert repeated["result"]["created"] == _SECTIONS + 5
    assert repeated["result"]["errors"] == []
    after = (await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)).json()["positions"]
    assert len(after) == 2 * (_SECTIONS + 5)
    for row in after:
        if row["id"] in before_by_id:
            assert row == before_by_id[row["id"]]
    added = [p for p in after if p["id"] not in before_by_id]
    by_id = {p["id"]: p for p in added}
    assert len({p["ordinal"] for p in after}) == len(after)
    for row in added:
        original = row["metadata"]["import_original_ordinal"]
        expected_parent = _TREE[original]
        parent = by_id.get(row["parent_id"])
        assert (parent["metadata"]["import_original_ordinal"] if parent else "") == expected_parent


def _uploads() -> set[str]:
    from app.core.storage import module_uploads_dir

    directory = module_uploads_dir("boq_imports")
    return {path.name for path in directory.iterdir()} if directory.is_dir() else set()


@pytest.mark.asyncio
async def test_the_upload_waits_in_the_upload_directory_and_is_gone_once_the_job_ends(
    http_client, auth_headers, monkeypatch
) -> None:
    from app.core import job_runner
    from app.modules.boq import import_jobs

    before = _uploads()
    seen: list[set[str]] = []
    real = import_jobs.run_boq_import_job

    async def _watching(job_run, payload):
        seen.append(_uploads() - before)
        return await real(job_run, payload)

    monkeypatch.setitem(job_runner._HANDLERS, import_jobs.JOB_KIND, _watching)
    boq = await _new_boq(http_client, auth_headers)
    ok = (await _post_background(http_client, auth_headers, boq, _CONTENT)).json()
    assert (await _finished_job(http_client, auth_headers, boq, ok["job_id"]))["status"] == "success"
    refused = await http_client.post(
        f"/api/v1/boq/boqs/{boq}/import/auto/?background=true",
        files={"file": ("rotto.xpwe", b"<PweDocumento><broken", "application/xml")},
        headers=auth_headers,
    )
    assert (await _finished_job(http_client, auth_headers, boq, refused.json()["job_id"]))["status"] == "failed"

    assert [len(names) for names in seen] == [1, 1], "each job reads its upload from the upload directory"
    assert _uploads() == before, "an upload outlived its job"


def test_uploads_a_crash_left_behind_are_swept_and_fresh_ones_kept(tmp_path, monkeypatch) -> None:
    import os
    import time

    from app.modules.boq import import_jobs

    monkeypatch.setattr(import_jobs, "_upload_dir", lambda: tmp_path)
    stale = tmp_path / f"{'a' * 32}.upload"
    fresh = tmp_path / f"{'b' * 32}.upload"
    foreign = tmp_path / "notes.txt"
    for path in (stale, fresh, foreign):
        path.write_bytes(b"x")
    old = time.time() - 2 * 3600
    os.utime(stale, (old, old))
    os.utime(foreign, (old, old))

    assert import_jobs.sweep_stale_uploads() == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted([fresh.name, foreign.name])


def test_the_sweep_runs_when_the_module_starts(monkeypatch) -> None:
    import asyncio

    from app.modules import boq
    from app.modules.boq import import_jobs

    calls: list[int] = []
    monkeypatch.setattr(import_jobs, "sweep_stale_uploads", lambda **_: calls.append(1) or 0)
    asyncio.run(boq.on_startup())
    assert calls == [1]


@pytest.mark.asyncio
async def test_the_same_file_imports_again_once_its_rows_are_gone(http_client, auth_headers) -> None:
    from sqlalchemy import delete

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    boq = await _new_boq(http_client, auth_headers)
    first = (await _post_background(http_client, auth_headers, boq, _CONTENT)).json()
    assert (await _finished_job(http_client, auth_headers, boq, first["job_id"]))["status"] == "success"
    async with async_session_factory() as s:
        await s.execute(delete(Position).where(Position.boq_id == uuid.UUID(boq)))
        await s.commit()

    again = await _post_background(http_client, auth_headers, boq, _CONTENT)
    assert again.status_code == 202, again.text[:300]
    assert again.json()["job_id"] != first["job_id"]
    assert (await _finished_job(http_client, auth_headers, boq, again.json()["job_id"]))["status"] == "success"
    assert await _row_count(http_client, auth_headers, boq) == _SECTIONS + 5


@pytest.mark.asyncio
async def test_a_failed_background_import_can_be_retried(http_client, auth_headers, monkeypatch) -> None:
    from app.modules.boq import router as boq_router

    real = boq_router._run_native_import
    calls = 0

    async def _fail_first(*args: object, **kwargs: object) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database went away")
        return await real(*args, **kwargs)

    monkeypatch.setattr(boq_router, "_run_native_import", _fail_first)
    boq = await _new_boq(http_client, auth_headers)
    first = (await _post_background(http_client, auth_headers, boq, _CONTENT)).json()
    failed = await _finished_job(http_client, auth_headers, boq, first["job_id"])
    assert failed["status"] == "failed"
    # An internal failure is not shown to the reader word for word.
    assert "database went away" not in str(failed)

    retry = await _post_background(http_client, auth_headers, boq, _CONTENT)
    assert retry.json()["job_id"] != first["job_id"]
    assert (await _finished_job(http_client, auth_headers, boq, retry.json()["job_id"]))["status"] == "success"
    assert await _row_count(http_client, auth_headers, boq) == _SECTIONS + 5


@pytest.mark.asyncio
async def test_a_file_the_reader_refuses_fails_the_job_with_the_reason(http_client, auth_headers) -> None:
    """The reason the synchronous route answers with a 400 reaches the reader through the job."""
    boq = await _new_boq(http_client, auth_headers)
    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq}/import/auto/?background=true",
        files={"file": ("progetto.xpwe", b"<PweDocumento><broken", "application/xml")},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text[:300]
    job = await _finished_job(http_client, auth_headers, boq, resp.json()["job_id"])
    assert job["status"] == "failed"
    assert job["error_code"] == "xpwe_not_well_formed", job
    assert set(job["error_params"]) == {"line", "column"}, job
    assert "XPWE" in (job["error"] or ""), job
    assert await _row_count(http_client, auth_headers, boq) == 0


@pytest.mark.asyncio
async def test_an_import_job_is_visible_only_through_its_own_bill_to_its_owner(http_client, auth_headers) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    boq = await _new_boq(http_client, auth_headers)
    job_id = (await _post_background(http_client, auth_headers, boq, _CONTENT)).json()["job_id"]
    await _finished_job(http_client, auth_headers, boq, job_id)

    other_boq = await _new_boq(http_client, auth_headers)
    resp = await http_client.get(f"/api/v1/boq/boqs/{other_boq}/import/jobs/{job_id}/", headers=auth_headers)
    assert resp.status_code == 404, resp.text[:300]
    resp = await http_client.get(f"/api/v1/boq/boqs/{boq}/import/jobs/{uuid.uuid4()}/", headers=auth_headers)
    assert resp.status_code == 404, resp.text[:300]

    email = f"xpwe-other-{uuid.uuid4().hex[:8]}@import-auto.io"
    password = f"XpweOther{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Other"}
    )
    assert reg.status_code in (200, 201), reg.text[:300]
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role="editor"))
        await s.commit()
    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    other = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = await http_client.get(f"/api/v1/boq/boqs/{boq}/import/jobs/{job_id}/", headers=other)
    assert resp.status_code in (403, 404), resp.text[:300]
    assert "result" not in resp.json()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_a_large_bill_imports_completely(http_client, auth_headers, monkeypatch) -> None:
    """The scale harness: wall time, and heap with ``XPWE_TRACE_HEAP=1`` (tracing slows the run).

    ``XPWE_SCALE_ITEMS`` sets the number of measured items (default 1000);
    ``XPWE_PER_ROW=1`` writes the rows one at a time, for comparison.
    """
    if os.environ.get("XPWE_PER_ROW") == "1":
        _per_row(monkeypatch)
    items = int(os.environ.get("XPWE_SCALE_ITEMS", "1000"))
    categories = 25
    content = fx.measured_bill(items, categories=categories)
    boq = await _new_boq(http_client, auth_headers)
    trace = os.environ.get("XPWE_TRACE_HEAP") == "1"
    if trace:
        tracemalloc.start()
    started = time.perf_counter()
    try:
        resp = await http_client.post(
            f"/api/v1/boq/boqs/{boq}/import/auto/",
            files={"file": ("grande.xpwe", content, "application/xml")},
            headers=auth_headers,
            timeout=1800,
        )
        elapsed = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1] if trace else 0
    finally:
        if trace:
            tracemalloc.stop()
    assert resp.status_code == 200, resp.text[:500]
    body = resp.json()
    print(
        f"\nXPWE scale: {items} items + {categories} sections, {len(content) / 2**20:.1f} MiB, "
        f"{elapsed:.1f} s, {1000 * elapsed / (items + categories):.1f} ms/position"
        + (f", heap peak {peak / 2**20:.0f} MiB" if trace else "")
    )
    assert body["errors"] == [], body["errors"][:3]
    assert body["created"] == items + categories


@pytest.mark.asyncio
async def test_all_rejected_rows_fail_background_job(http_client, auth_headers):
    boq = await _new_boq(http_client, auth_headers)
    # Synchronous import has no background hash entry. A new background job
    # collides with every stored ordinal and must fail, not report success.
    await _import(http_client, auth_headers, boq, _CONTENT)
    queued = await _post_background(http_client, auth_headers, boq, _CONTENT)
    assert queued.status_code == 202
    job = await _finished_job(http_client, auth_headers, boq, queued.json()["job_id"])
    assert job["status"] == "failed"
    assert "import_persistence_failed" in str(job)
    assert await _row_count(http_client, auth_headers, boq) == _SECTIONS + 5


@pytest.mark.asyncio
async def test_an_imported_computo_generates_a_schedule(http_client, auth_headers) -> None:
    """The Italian tester's path: import an XPWE computo, then Generate from BoQ.

    Their report was that generation "always errors". The bill here has the
    capitolo > categoria > sub-categoria depth, measurement sheets and an item
    filed under no category, as a real computo does.
    """
    boq = await _new_boq(http_client, auth_headers)
    await _import(http_client, auth_headers, boq, _CONTENT)
    stored = await http_client.get(f"/api/v1/boq/boqs/{boq}", headers=auth_headers)
    project_id = stored.json()["project_id"]
    schedule = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={"project_id": project_id, "name": "Cronoprogramma", "start_date": "2026-05-04"},
        headers=auth_headers,
    )
    assert schedule.status_code == 201, schedule.text[:300]
    sid = schedule.json()["id"]

    preview = await http_client.post(
        f"/api/v1/schedule/schedules/{sid}/generate-from-boq/preview/", json={"boq_id": boq}, headers=auth_headers
    )
    assert preview.status_code == 200, preview.text[:500]
    assert preview.json()["positions_scheduled"] == 5

    generated = await http_client.post(
        f"/api/v1/schedule/schedules/{sid}/generate-from-boq/", json={"boq_id": boq}, headers=auth_headers
    )
    assert generated.status_code in (200, 201), generated.text[:500]
    # Run again with replace, as a person fixing the bill and regenerating does.
    again = await http_client.post(
        f"/api/v1/schedule/schedules/{sid}/generate-from-boq/",
        json={"boq_id": boq, "replace": True},
        headers=auth_headers,
    )
    assert again.status_code in (200, 201), again.text[:500]
