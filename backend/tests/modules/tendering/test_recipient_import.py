# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bulk tender recipients from a CSV/XLSX file: parsing, row checks, preview, confirm.

Run:
    cd backend
    python -m pytest -q -x --no-header tests/modules/tendering/test_recipient_import.py
"""

from __future__ import annotations

import io
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.modules.tendering.recipient_import import (
    RecipientFileError,
    check_rows,
    parse_recipient_file,
)

HEADER = "Company,Contact name,Email,Trade,VAT ID\n"


def _csv(*lines: str) -> bytes:
    return (HEADER + "\n".join(lines) + "\n").encode()


# ── Pure parsing and checks ───────────────────────────────────────────────────


def test_checks_flag_bad_email_file_duplicate_and_already_invited():
    rows = parse_recipient_file(
        "r.csv",
        _csv(
            "Alpha,Ann,ann@alpha.io,Concrete,DE1",
            "Beta,Bob,not-an-email,Steel,",
            "Alpha again,Ann,ANN@alpha.io,Concrete,",
            "Gamma,Gus,gus@gamma.io,Roofing,",
            ",Hal,hal@x.io,Paint,",
        ),
    )
    check_rows(rows, {"Gus@Gamma.io"})
    assert [r.issues for r in rows] == [
        [],
        ["email_invalid"],
        ["duplicate_in_file"],
        ["already_invited"],
        ["company_missing"],
    ]
    assert rows[0].line == 2


def test_semicolon_csv_and_header_aliases():
    rows = parse_recipient_file("r.csv", b"Firm;E-Mail;Name\nAlpha;a@alpha.io;Ann\n")
    assert (rows[0].company, rows[0].email, rows[0].contact_name) == ("Alpha", "a@alpha.io", "Ann")


def test_xlsx_is_read():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["company", "contact name", "email", "trade", "vat id"])
    ws.append(["Alpha", "Ann", "ann@alpha.io", "Concrete", "DE1"])
    buf = io.BytesIO()
    wb.save(buf)
    rows = parse_recipient_file("r.xlsx", buf.getvalue())
    assert rows[0].trade == "Concrete" and rows[0].vat_id == "DE1"


@pytest.mark.parametrize(
    ("name", "content", "code"),
    [
        ("r.pdf", b"x", "unsupported_type"),
        ("r.csv", b"", "empty_file"),
        ("r.csv", b"foo,bar\n1,2\n", "missing_columns"),
        ("r.xlsx", b"not a workbook", "unreadable_file"),
    ],
)
def test_unreadable_files_are_refused_with_a_code(name, content, code):
    with pytest.raises(RecipientFileError, match=code):
        parse_recipient_file(name, content)


@pytest.mark.asyncio
async def test_rule_is_registered_and_reports_each_bad_row():
    from app.core.validation.engine import validation_engine
    from app.modules.tendering.recipient_import import RECIPIENT_IMPORT_RULE_SET, register_recipient_import_rules

    register_recipient_import_rules()
    report = await validation_engine.validate(
        data={
            "rows": [
                {"line": 2, "company": "A", "email": "a@a.io"},
                {"line": 3, "company": "B", "email": "bad"},
            ],
            "existing_emails": [],
        },
        rule_sets=[RECIPIENT_IMPORT_RULE_SET],
        target_type="tender_recipient_import",
        target_id="t",
    )
    failed = [r for r in report.results if not r.passed]
    assert [r.details["line"] for r in failed] == [3]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def client():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def staff(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    email = f"recimport-{tag}@test.io"
    password = f"RecImport{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Rec Import {tag}", "role": "admin"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def package_id(client: AsyncClient, staff: dict[str, str]) -> str:
    project = await client.post(
        "/api/v1/projects/", json={"name": "Recipient import", "currency": "EUR"}, headers=staff
    )
    assert project.status_code in (200, 201), project.text
    pkg = await client.post(
        "/api/v1/tendering/packages/",
        json={"project_id": project.json()["id"], "name": "Import package"},
        headers=staff,
    )
    assert pkg.status_code == 201, pkg.text
    return pkg.json()["id"]


def _upload(content: bytes, name: str = "r.csv") -> dict:
    return {"file": (name, content, "text/csv")}


@pytest.mark.asyncio
async def test_preview_stores_nothing_and_confirm_adds_valid_rows_through_the_contact_bridge(
    client: AsyncClient, staff: dict[str, str], package_id: str
):
    tag = uuid.uuid4().hex[:6]
    known = f"known-{tag}@firm.io"
    fresh = f"fresh-{tag}@firm.io"
    # An existing tenant contact with its own company name that the import must not overwrite.
    made = await client.post(
        "/api/v1/contacts/",
        json={"contact_type": "subcontractor", "company_name": "Original Name", "primary_email": known},
        headers=staff,
    )
    assert made.status_code in (200, 201), made.text
    existing_contact_id = made.json()["id"]

    body = _csv(
        f"Known Co,Kim,{known},Steel,",
        f"Fresh Co,Fay,{fresh},Concrete,DE123",
        "Broken Co,Bo,broken,Paint,",
        f"Fresh twin,Fay,{fresh.upper()},Concrete,",
    )
    base = f"/api/v1/tendering/packages/{package_id}/recipients"
    prev = await client.post(f"{base}/import/preview/", files=_upload(body), headers=staff)
    assert prev.status_code == 200, prev.text
    data = prev.json()
    assert (data["total"], data["valid"]) == (4, 2)
    assert data["rows"][2]["issues"] == ["email_invalid"]
    assert data["rows"][3]["issues"] == ["duplicate_in_file"]
    assert (await client.get(f"{base}/", headers=staff)).json() == []

    done = await client.post(f"{base}/import/", files=_upload(body), headers=staff)
    assert done.status_code == 201, done.text
    out = done.json()
    assert len(out["added"]) == 2 and len(out["skipped"]) == 2
    assert (out["contacts_linked"], out["contacts_created"]) == (1, 1)
    by_email = {a["email"]: a for a in out["added"]}
    assert by_email[known]["contact_id"] == existing_contact_id
    assert by_email[fresh]["contact_id"] not in (None, existing_contact_id)

    linked = await client.get(f"/api/v1/contacts/{existing_contact_id}", headers=staff)
    assert linked.json()["company_name"] == "Original Name"
    created = await client.get(f"/api/v1/contacts/{by_email[fresh]['contact_id']}", headers=staff)
    assert created.json()["company_name"] == "Fresh Co"

    # A second upload of the same file invites nobody twice.
    again = await client.post(f"{base}/import/", files=_upload(body), headers=staff)
    assert again.json()["added"] == []
    assert len((await client.get(f"{base}/", headers=staff)).json()) == 2


@pytest.mark.asyncio
async def test_a_bad_file_is_a_422_with_a_code(client: AsyncClient, staff: dict[str, str], package_id: str):
    resp = await client.post(
        f"/api/v1/tendering/packages/{package_id}/recipients/import/preview/",
        files=_upload(b"foo,bar\n1,2\n"),
        headers=staff,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "missing_columns"
