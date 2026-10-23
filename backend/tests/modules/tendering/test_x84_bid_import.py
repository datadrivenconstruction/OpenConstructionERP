# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A priced GAEB X84 bid return lands in the bid comparison, checked line by line.

Run:
    cd backend
    python -m pytest tests/modules/tendering/test_x84_bid_import.py -q
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _x84(items: list[tuple[str, str, str, str, str]], *, dp: str = "84", currency: str = "EUR") -> bytes:
    """Build an X84 with one section ``01``; items are (rno, qty, unit, up, text)."""
    rows = "".join(
        f'<Item RNoPart="{rno}"><Qty>{qty}</Qty><QU>{unit}</QU><UP>{up}</UP>'
        f"<Description><CompleteText><OutlineText><OutlTxt><TextOutlTxt><p><span>{text}</span></p>"
        f"</TextOutlTxt></OutlTxt></OutlineText></CompleteText></Description></Item>"
        for rno, qty, unit, up, text in items
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA{dp}/3.3"><GAEBInfo><Version>3.3</Version></GAEBInfo>'
        f"<Award><DP>{dp}</DP><AwardInfo><Cur>{currency}</Cur></AwardInfo><BoQ><BoQInfo>"
        "<BoQBkdn><Type>BoQLevel</Type><Length>2</Length><Num>Yes</Num></BoQBkdn>"
        "<BoQBkdn><Type>Item</Type><Length>3</Length><Num>Yes</Num></BoQBkdn></BoQInfo>"
        f'<BoQBody><BoQCtgy RNoPart="01"><LblTx><p><span>Earthworks</span></p></LblTx>'
        f"<BoQBody><Itemlist>{rows}</Itemlist></BoQBody></BoQCtgy></BoQBody></BoQ></Award></GAEB>"
    )
    return xml.encode()


GOOD = [
    ("001", "120.5", "m3", "21.40", "Excavate trench"),
    ("002", "80", "m3", "9.95", "Backfill and compact"),
]


# ── Pure matching ─────────────────────────────────────────────────────────────


def _pos(ordinal: str, unit: str, quantity: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), ordinal=ordinal, unit=unit, quantity=quantity, metadata_={})


def _row(ordinal: str, unit: str, quantity: float, up: str) -> SimpleNamespace:
    return SimpleNamespace(
        is_section=False,
        description="x",
        ordinal=ordinal,
        unit=unit,
        quantity=quantity,
        unit_rate=float(up),
        metadata={"gaeb_ordinal": ordinal, "gaeb_up": up},
    )


def test_ordinals_match_without_leading_zeros() -> None:
    from app.modules.tendering.x84_import import normalise_ordinal

    assert normalise_ordinal("01.0010") == normalise_ordinal("1.10") == "1.10"


def test_lines_report_every_deviation() -> None:
    from app.modules.tendering.x84_import import check_lines

    a, b, c = _pos("01.001", "m3", "120.5"), _pos("01.002", "m3", "80"), _pos("01.003", "t", "15")
    priceable = {str(p.id): p for p in (a, b, c)}
    rows = [
        _row("1.1", "m3", 120.5, "21.40"),
        _row("01.002", "m2", 80, "9.95"),
        _row("01.009", "m3", 1, "5"),
        _row("01.003", "t", 16, "3"),
    ]
    checks, prices, missing = check_lines(rows, priceable)
    assert [c.issues for c in checks] == [[], ["unit_mismatch"], ["unknown_position"], ["quantity_changed"]]
    assert prices == {str(a.id): pytest.approx(prices[str(a.id)])}
    assert str(prices[str(a.id)]) == "21.40"
    assert missing == []


# ── Routes ────────────────────────────────────────────────────────────────────


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
async def setup(client: AsyncClient) -> dict:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.boq.models import Position
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    email, password = f"x84-{tag}@test.io", f"X84Import{tag}9"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"X84 {tag}", "role": "admin"},
    )
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    project = await client.post(
        "/api/v1/projects/", json={"name": "X84 tests", "currency": "EUR", "locale": "de"}, headers=headers
    )
    project_id = project.json()["id"]
    boq = await client.post("/api/v1/boq/boqs/", json={"project_id": project_id, "name": "Bill"}, headers=headers)
    boq_id = boq.json()["id"]
    section = uuid.uuid4()
    async with async_session_factory() as session:
        session.add(
            Position(
                id=section,
                boq_id=uuid.UUID(boq_id),
                ordinal="01",
                description="Earthworks",
                unit="",
                quantity="0",
                unit_rate="0",
                total="0",
                sort_order=0,
                metadata_={},
            )
        )
        for i, (ordinal, desc, unit, qty) in enumerate(
            [("01.001", "Excavate trench", "m3", "120.5"), ("01.002", "Backfill and compact", "m3", "80")]
        ):
            session.add(
                Position(
                    id=uuid.uuid4(),
                    boq_id=uuid.UUID(boq_id),
                    parent_id=section,
                    ordinal=ordinal,
                    description=desc,
                    unit=unit,
                    quantity=qty,
                    unit_rate="1",
                    total=qty,
                    sort_order=i + 1,
                    metadata_={},
                )
            )
        await session.commit()
    package = await client.post(
        "/api/v1/tendering/packages/from-boq/",
        json={
            "project_id": project_id,
            "boq_id": boq_id,
            "section_ids": [str(section)],
            "package_name": "Earthworks",
            "deadline": (datetime.now(UTC) + timedelta(days=14)).strftime("%Y-%m-%d"),
        },
        headers=headers,
    )
    assert package.status_code == 201, package.text
    return {"headers": headers, "package_id": package.json()["id"]}


async def test_preview_accepts_a_matching_x84(client: AsyncClient, setup: dict) -> None:
    url = f"/api/v1/tendering/packages/{setup['package_id']}/bids/import-x84/preview/"
    r = await client.post(url, files={"file": ("bid.x84", _x84(GOOD))}, headers=setup["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocking"] is False, body
    assert body["priced"] == 2
    assert body["total_amount"] == "3374.70"
    assert len(body["sha256"]) == 64


async def test_changed_quantity_or_x83_blocks_the_import(client: AsyncClient, setup: dict) -> None:
    base = f"/api/v1/tendering/packages/{setup['package_id']}/bids/import-x84/"
    changed = _x84([("001", "100", "m3", "21.40", "Excavate trench"), GOOD[1]])
    r = await client.post(base + "preview/", files={"file": ("bid.x84", changed)}, headers=setup["headers"])
    assert r.json()["blocking"] is True
    assert r.json()["lines"][0]["issues"] == ["quantity_changed"]

    r = await client.post(base + "preview/", files={"file": ("bid.x83", _x84(GOOD, dp="83"))}, headers=setup["headers"])
    assert "not_x84" in r.json()["file_issues"]

    r = await client.post(
        base, files={"file": ("bid.x84", changed)}, data={"company_name": "Muster"}, headers=setup["headers"]
    )
    assert r.status_code == 422


async def test_import_writes_a_bid_the_comparison_reads(client: AsyncClient, setup: dict) -> None:
    pid = setup["package_id"]
    r = await client.post(
        f"/api/v1/tendering/packages/{pid}/bids/import-x84/",
        files={"file": ("bid.x84", _x84(GOOD))},
        data={"company_name": "Musterbau GmbH", "contact_email": "bid@musterbau.test"},
        headers=setup["headers"],
    )
    assert r.status_code == 201, r.text
    bid = r.json()
    assert bid["total_amount"] in ("3374.70", "3374.7")
    assert bid["status"] == "submitted"
    assert {str(li["unit_rate"]) for li in bid["line_items"]} == {"21.40", "9.95"}

    comparison = await client.get(f"/api/v1/tendering/packages/{pid}/comparison/", headers=setup["headers"])
    assert comparison.status_code == 200, comparison.text
    assert "Musterbau GmbH" in comparison.text
