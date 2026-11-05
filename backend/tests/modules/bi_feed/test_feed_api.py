# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Feed endpoints on a real PostgreSQL session: bytes, tenant scope, key rules, paging, limits."""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from decimal import Decimal

import pyarrow.parquet as pq

from app.modules.bi_feed import service as feed_service
from tests.modules.bi_feed.conftest import (
    PREFIX,
    build_app,
    http_client,
    make_boq,
    make_invoice,
    make_key,
    make_position,
    make_project,
    make_user,
)


def _ids(n: int, base: int = 0x1000) -> list[uuid.UUID]:
    return [uuid.UUID(int=base + i) for i in range(n)]


async def _seed(session, owner, *, positions: int = 1, currency: str = "EUR", id_base: int = 0x1000):
    project = await make_project(session, owner.id, currency=currency)
    boq = await make_boq(session, project.id)
    for i, pid in enumerate(_ids(positions, id_base)):
        await make_position(session, boq.id, ordinal=f"{i + 1:02d}", position_id=pid)
    return project, boq


async def test_csv_golden_bytes_for_a_seeded_project(session) -> None:
    user = await make_user(session)
    project, boq = await _seed(session, user, positions=0)
    await make_position(
        session,
        boq.id,
        position_id=uuid.UUID(int=0x2000),
        description="=1+1",
        quantity="3.5",
        unit_rate="-12.50",
        total="-43.75",
    )
    async with http_client(build_app(session)) as client:
        response = await client.get(
            f"{PREFIX}/feeds/boq_positions.csv",
            params={"project_id": str(project.id)},
            headers={"X-Test-User": str(user.id)},
        )
    assert response.status_code == 200
    assert response.headers["x-total-count"] == "1"
    assert response.headers["content-type"].startswith("text/csv")
    body = response.content
    assert body.startswith(b"\xef\xbb\xbf")
    lines = body[3:].decode("utf-8").split("\r\n")
    assert lines[0] == (
        "id,project_id,boq_id,boq_name,ordinal,description,unit,quantity,unit_rate,total,currency,source,"
        "validation_status,created_at,updated_at"
    )
    assert lines[1] == (
        f"{uuid.UUID(int=0x2000)},{project.id},{boq.id},Main BOQ,01,'=1+1,m3,3.500000,-12.500000,-43.750000,EUR,"
        "manual,pending,2026-01-02T03:04:05Z,2026-01-02T03:04:05Z"
    )
    assert lines[2] == ""


async def test_parquet_round_trip_through_the_endpoint_is_exact(session) -> None:
    user = await make_user(session)
    project, _ = await _seed(session, user, positions=2)
    await make_invoice(
        session,
        project.id,
        amount_total=Decimal("1234567.89"),
        amount_subtotal=Decimal("1000000.00"),
        currency_code="CHF",
    )
    async with http_client(build_app(session)) as client:
        response = await client.get(f"{PREFIX}/feeds/invoices.parquet", headers={"X-Test-User": str(user.id)})
    assert response.status_code == 200
    rows = pq.read_table(io.BytesIO(response.content)).to_pylist()
    assert len(rows) == 1
    assert rows[0]["amount_total"] == Decimal("1234567.890000")
    assert rows[0]["currency"] == "CHF"
    assert rows[0]["direction"] == "payable"


async def test_json_preview_lists_columns_and_rows(session) -> None:
    user = await make_user(session)
    await _seed(session, user, positions=3)
    async with http_client(build_app(session)) as client:
        response = await client.get(
            f"{PREFIX}/feeds/boq_positions.json", params={"limit": 2}, headers={"X-Test-User": str(user.id)}
        )
    body = response.json()
    assert body["total"] == 3 and len(body["rows"]) == 2
    assert body["rows"][0]["quantity"] == "10.000000"
    assert response.headers["x-next-offset"] == "2"


async def test_feed_list_counts_only_what_the_caller_can_read(session) -> None:
    a, b = await make_user(session), await make_user(session)
    await _seed(session, a, positions=2)
    await _seed(session, b, positions=5, id_base=0x3000)
    async with http_client(build_app(session)) as client:
        response = await client.get(f"{PREFIX}/feeds", headers={"X-Test-User": str(a.id)})
    counts = {f["id"]: f["row_count"] for f in response.json()}
    assert counts["boq_positions"] == 2
    assert counts["projects"] == 1
    assert set(counts) == {"projects", "boq_positions", "invoices", "purchase_orders", "schedule_activities"}


# ── Tenant isolation ───────────────────────────────────────────────────────


async def test_a_key_never_sees_another_owners_rows(session) -> None:
    a, b = await make_user(session), await make_user(session)
    project_a, _ = await _seed(session, a, positions=2)
    project_b, _ = await _seed(session, b, positions=3, id_base=0x3000)
    await make_invoice(session, project_b.id)
    key_a = await make_key(session, a.id)
    async with http_client(build_app(session)) as client:
        mine = await client.get(f"{PREFIX}/feeds/boq_positions.json", headers={"X-API-Key": key_a})
        invoices = await client.get(f"{PREFIX}/feeds/invoices.json", headers={"X-API-Key": key_a})
        projects = await client.get(f"{PREFIX}/feeds/projects.json", headers={"X-API-Key": key_a})
        foreign = await client.get(
            f"{PREFIX}/feeds/boq_positions.json", params={"project_id": str(project_b.id)}, headers={"X-API-Key": key_a}
        )
        missing = await client.get(
            f"{PREFIX}/feeds/boq_positions.json", params={"project_id": str(uuid.uuid4())}, headers={"X-API-Key": key_a}
        )
    assert {r["project_id"] for r in mine.json()["rows"]} == {str(project_a.id)}
    assert mine.json()["total"] == 2
    assert invoices.json()["total"] == 0
    assert [r["id"] for r in projects.json()["rows"]] == [str(project_a.id)]
    assert foreign.status_code == 404 and missing.status_code == 404


# ── Keys ───────────────────────────────────────────────────────────────────


async def test_key_rules(session) -> None:
    user = await make_user(session)
    await _seed(session, user)
    cases = {
        "no_scope": (await make_key(session, user.id, permissions=["projects.read"]), 403),
        "undeclared": (await make_key(session, user.id, permissions=[]), 403),
        "ok": (await make_key(session, user.id), 200),
        "expired": (await make_key(session, user.id, expires_in=timedelta(days=-1)), 401),
        "inactive": (await make_key(session, user.id, active=False), 401),
        "unknown": ("oe_" + "0" * 32, 401),
    }
    async with http_client(build_app(session)) as client:
        for name, (secret, status) in cases.items():
            response = await client.get(f"{PREFIX}/feeds/projects.csv", headers={"X-API-Key": secret})
            assert response.status_code == status, name


async def test_a_key_of_an_inactive_owner_is_refused(session) -> None:
    user = await make_user(session)
    secret = await make_key(session, user.id)
    user.is_active = False
    await session.flush()
    async with http_client(build_app(session)) as client:
        response = await client.get(f"{PREFIX}/feeds/projects.csv", headers={"X-API-Key": secret})
    assert response.status_code == 401


# ── Paging ─────────────────────────────────────────────────────────────────


async def test_pages_follow_primary_key_order_without_repeats(session) -> None:
    user = await make_user(session)
    await _seed(session, user, positions=7)
    headers = {"X-Test-User": str(user.id)}
    seen: list[str] = []
    async with http_client(build_app(session)) as client:
        offset = 0
        while True:
            response = await client.get(
                f"{PREFIX}/feeds/boq_positions.json", params={"limit": 3, "offset": offset}, headers=headers
            )
            seen += [r["id"] for r in response.json()["rows"]]
            if "x-next-offset" not in response.headers:
                break
            offset = int(response.headers["x-next-offset"])
    assert seen == [str(i) for i in _ids(7)]


async def test_after_cursor_survives_a_concurrent_insert(session) -> None:
    user = await make_user(session)
    project, boq = await _seed(session, user, positions=7)
    headers = {"X-Test-User": str(user.id)}
    async with http_client(build_app(session)) as client:
        first = await client.get(f"{PREFIX}/feeds/boq_positions.json", params={"limit": 3}, headers=headers)
        # A row that sorts before everything already read lands between the two requests.
        await make_position(session, boq.id, ordinal="99", position_id=uuid.UUID(int=1))
        cursor = first.headers["x-next-after"]
        second = await client.get(
            f"{PREFIX}/feeds/boq_positions.json", params={"limit": 3, "after": cursor}, headers=headers
        )
        third = await client.get(
            f"{PREFIX}/feeds/boq_positions.json",
            params={"limit": 3, "after": second.headers["x-next-after"]},
            headers=headers,
        )
    pages = [r["id"] for resp in (first, second, third) for r in resp.json()["rows"]]
    assert pages == [str(i) for i in _ids(7)]  # no repeat, no gap among the rows that existed
    assert len(set(pages)) == len(pages)


async def test_updated_since_filters_on_the_update_stamp(session) -> None:
    user = await make_user(session)
    await _seed(session, user, positions=2)
    async with http_client(build_app(session)) as client:
        newer = await client.get(
            f"{PREFIX}/feeds/boq_positions.json",
            params={"updated_since": "2026-01-02T03:04:06Z"},
            headers={"X-Test-User": str(user.id)},
        )
        same = await client.get(
            f"{PREFIX}/feeds/boq_positions.json",
            params={"updated_since": "2026-01-02T03:04:05Z"},
            headers={"X-Test-User": str(user.id)},
        )
    assert newer.json()["total"] == 0
    assert same.json()["total"] == 2


# ── Limits and codes ───────────────────────────────────────────────────────


async def test_error_codes(session, monkeypatch) -> None:
    user = await make_user(session)
    await _seed(session, user, positions=3)
    headers = {"X-Test-User": str(user.id)}
    async with http_client(build_app(session)) as client:
        too_big = await client.get(f"{PREFIX}/feeds/boq_positions.csv", params={"limit": 50001}, headers=headers)
        junk = await client.get(f"{PREFIX}/feeds/boq_positions.csv", params={"$filter": "x"}, headers=headers)
        unknown = await client.get(f"{PREFIX}/feeds/users.csv", headers=headers)
        monkeypatch.setattr(feed_service, "MAX_UNPAGED_ROWS", 2)
        whole = await client.get(f"{PREFIX}/feeds/boq_positions.csv", headers=headers)
        paged = await client.get(f"{PREFIX}/feeds/boq_positions.csv", params={"limit": 2}, headers=headers)
    assert (too_big.status_code, too_big.json()["detail"]["code"]) == (400, "BI_FEED_LIMIT")
    assert (junk.status_code, junk.json()["detail"]["code"]) == (400, "BI_FEED_BAD_PARAM")
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "BI_FEED_UNKNOWN")
    assert (whole.status_code, whole.json()["detail"]["code"]) == (400, "BI_FEED_TOO_LARGE")
    assert paged.status_code == 200 and paged.headers["x-total-count"] == "3"


async def test_statement_timeout_is_armed_on_postgresql(session) -> None:
    from sqlalchemy import text

    from app.modules.bi_feed.service import BiFeedService

    await BiFeedService(session)._arm_timeout()
    assert (await session.execute(text("SHOW statement_timeout"))).scalar_one() == "15s"
