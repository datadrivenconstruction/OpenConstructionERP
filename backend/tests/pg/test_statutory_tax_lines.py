# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The statutory tax lines of a payment document, through the real routes.

Three things here can only be shown on PostgreSQL.

The unique keys. One set of lines per source document and one line per kind is
what makes a save idempotent, and it is the database that holds that, not the
service: two requests can both find nothing and both insert.

The amounts. They are ``NUMERIC(18, 4)`` so a three-decimal currency keeps its
last digit, and PostgreSQL pads every value it returns to the column scale. A
dinar amount has to leave the API with three decimals and a yen amount with
none, as the strings they came in as, and a held figure has to leave as
``null``. None of that is visible on a backend that stores decimals as text.

The project boundary. The source document is named by an id from another
module, so nothing but the stored ``project_id`` says whose it is. Every route
is asked twice by somebody from another project: once naming a project they
cannot reach, once naming their own. Both answers must be the 404 the rest of
the platform gives. Whose document an id is, the owning module says: it
registers a resolver per source kind, and every route asks it before it reads
or writes. Here a stand-in resolver answers that every document belongs to the
owner's project, except where a test says otherwise. A kind nobody registered
for, a document its owner does not know, and a document of another project
all get the same 404, and none of them leaves a row behind.

Every rate row is synthetic and injected through the router's row source, so a
correction to a shipped rate cannot break a test in this file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.payment_taxes import RateRow

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/tax-withholding/statutory"
NOT_FOUND = "Statutory tax lines not found"


def _row(**changes) -> RateRow:
    base = RateRow(
        country_code="XX",
        kind="vat_withholding",
        code="W1",
        labels={"en": "Synthetic work"},
        base="vat",
        rate_pct=None,
        numerator=3,
        denominator=10,
        threshold_amount=None,
        threshold_currency="",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        legal_reference="Synthetic Act art. 1",
        source_url="https://example.invalid/act/1",
        read_date="2026-01-01",
        review_status="confirmed",
    )
    return replace(base, **changes)


ROWS: tuple[RateRow, ...] = (
    _row(conditions={"en": "Synthetic condition"}),
    _row(code="W2", numerator=7, review_status="unconfirmed"),
    _row(kind="income_withholding", code="I1", base="net", rate_pct=Decimal("4"), numerator=None, denominator=None),
    _row(kind="stamp_duty", code="S1", base="net", rate_pct=Decimal("0.25"), numerator=None, denominator=None),
)


@dataclass
class World:
    """Two projects with two owners, and a client that can speak as either."""

    session: object
    app: FastAPI
    owner_id: uuid.UUID
    project_id: uuid.UUID
    outsider_id: uuid.UUID
    outsider_project_id: uuid.UUID
    acting: dict
    #: Documents that belong somewhere other than the owner's project:
    #: ``None`` for a document the owning module does not know.
    owned_elsewhere: dict

    def act_as(self, user_id: uuid.UUID, role: str = "manager") -> None:
        self.acting.clear()
        self.acting.update({"sub": str(user_id), "role": role})

    def client(self) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")


@pytest_asyncio.fixture
async def world(pg_session):
    from app.dependencies import get_current_user_payload, get_session
    from app.modules.projects.models import Project
    from app.modules.tax_withholding import router as tax_router
    from app.modules.tax_withholding import source_owners
    from app.modules.tax_withholding.permissions import register_tax_withholding_permissions
    from app.modules.tax_withholding.service import STATUTORY_SOURCE_KINDS
    from app.modules.tax_withholding.validators import register_tax_withholding_rules
    from app.modules.users.models import User

    register_tax_withholding_permissions()
    register_tax_withholding_rules()

    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"stat-owner-{tag}@reference.example", hashed_password="x", full_name="Owner")
    outsider = User(email=f"stat-outsider-{tag}@reference.example", hashed_password="x", full_name="Outsider")
    pg_session.add_all([owner, outsider])
    await pg_session.flush()
    project = Project(name=f"Statutory {tag}", owner_id=owner.id)
    other = Project(name=f"Elsewhere {tag}", owner_id=outsider.id)
    pg_session.add_all([project, other])
    await pg_session.flush()

    app = FastAPI()
    app.include_router(tax_router.router, prefix="/api/v1/tax-withholding")
    acting: dict = {"sub": str(owner.id), "role": "manager"}

    async def current_session():
        yield pg_session

    app.dependency_overrides[get_session] = current_session
    app.dependency_overrides[get_current_user_payload] = lambda: dict(acting)
    app.dependency_overrides[tax_router.statutory_row_source] = lambda: lambda country: ROWS

    # Stand in for the modules that own the source documents.
    owned_elsewhere: dict = {}
    registered_before = dict(source_owners._resolvers)
    for kind in STATUTORY_SOURCE_KINDS:
        source_owners.register_source_owner(
            kind, lambda _session, source_id: owned_elsewhere.get(source_id, project.id)
        )
    try:
        yield World(
            session=pg_session,
            app=app,
            owner_id=owner.id,
            project_id=project.id,
            outsider_id=outsider.id,
            outsider_project_id=other.id,
            acting=acting,
            owned_elsewhere=owned_elsewhere,
        )
    finally:
        source_owners._resolvers.clear()
        source_owners._resolvers.update(registered_before)


def _body(world: World, **changes) -> dict:
    body = {
        "project_id": str(world.project_id),
        "direction": "borne_by_us",
        "source_reference": "PC-007",
        "country_code": "XX",
        "currency_code": "EUR",
        "document_date": "2026-03-10",
        "net_amount": "100000.00",
        "vat_rate_pct": "20",
        "vat_withholding": {"state": "selected", "code": "W1"},
        "income_withholding": {"state": "selected", "code": "I1"},
        "stamp_duty": {"state": "not_applicable", "reason": "Private contract, no taxable paper"},
    }
    body.update(changes)
    return body


def _figures(payload: dict) -> dict[str, dict]:
    return {figure["kind"]: figure for figure in payload["figures"]}


async def _stored_rows(session, source_id: uuid.UUID) -> tuple[int, int]:
    from app.modules.tax_withholding.models import StatutoryTaxCalc, StatutoryTaxLine

    headers = await session.scalar(
        select(func.count()).select_from(StatutoryTaxCalc).where(StatutoryTaxCalc.source_id == source_id)
    )
    lines = await session.scalar(
        select(func.count()).select_from(StatutoryTaxLine).where(StatutoryTaxLine.source_id == source_id)
    )
    return int(headers or 0), int(lines or 0)


# ── The tables ───────────────────────────────────────────────────────────────


async def test_both_tables_exist_with_their_unique_keys(pg_session) -> None:
    found = (
        await pg_session.execute(
            text(
                "SELECT c.conname, t.relname FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE c.contype = 'u' AND t.relname LIKE 'oe_tax_withholding_statutory_%'"
            )
        )
    ).all()
    assert {(name, table) for name, table in found} == {
        ("uq_tax_wh_stat_calc_source", "oe_tax_withholding_statutory_calc"),
        ("uq_tax_wh_stat_line_source_kind", "oe_tax_withholding_statutory_line"),
    }


async def test_amount_columns_keep_four_decimals_and_allow_null(pg_session) -> None:
    columns = (
        await pg_session.execute(
            text(
                "SELECT column_name, numeric_precision, numeric_scale, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name = 'oe_tax_withholding_statutory_line' "
                "AND column_name IN ('tax_amount', 'base_amount', 'override_amount')"
            )
        )
    ).all()
    assert len(columns) == 3
    for name, precision, scale, nullable, default in columns:
        assert (precision, scale) == (18, 4), name
        assert nullable == "YES", name
        # A default of zero would be the fallback this table must not have.
        assert default is None, name


async def test_the_database_refuses_a_second_line_of_one_kind(world: World) -> None:
    from app.modules.tax_withholding.models import StatutoryTaxLine

    source_id = uuid.uuid4()
    async with world.client() as client:
        saved = await client.put(f"{BASE}/progress_claim/{source_id}", json=_body(world))
    assert saved.status_code == 200, saved.text

    duplicate = StatutoryTaxLine(
        calc_id=uuid.UUID(saved.json()["id"]),
        project_id=world.project_id,
        source_kind="progress_claim",
        source_id=source_id,
        kind="vat_withheld",
        calc_status="held",
        currency_code="EUR",
    )

    async def insert_in_a_savepoint() -> None:
        # A savepoint, so the refused insert does not take the test's
        # transaction down with it.
        async with world.session.begin_nested():
            world.session.add(duplicate)
            await world.session.flush()

    with pytest.raises(IntegrityError):
        await insert_in_a_savepoint()


# ── Saving ───────────────────────────────────────────────────────────────────


async def test_saving_twice_is_one_document(world: World) -> None:
    source_id = uuid.uuid4()
    async with world.client() as client:
        first = await client.put(f"{BASE}/progress_claim/{source_id}", json=_body(world))
        second = await client.put(f"{BASE}/progress_claim/{source_id}", json=_body(world))
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["figures"] == first.json()["figures"]
    assert await _stored_rows(world.session, source_id) == (1, 5)


async def test_two_source_kinds_with_one_id_do_not_collide(world: World) -> None:
    shared = uuid.uuid4()
    async with world.client() as client:
        claim = await client.put(f"{BASE}/progress_claim/{shared}", json=_body(world))
        invoice = await client.put(
            f"{BASE}/invoice/{shared}",
            json=_body(world, net_amount="500.00", direction="withheld_by_us"),
        )
        read_claim = await client.get(f"{BASE}/progress_claim/{shared}", params={"project_id": str(world.project_id)})
    assert claim.status_code == 200, claim.text
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["id"] != claim.json()["id"]
    assert await _stored_rows(world.session, shared) == (2, 10)
    # The invoice saved afterwards did not touch the claim's figures.
    assert _figures(read_claim.json())["vat_computed"]["amount"] == "20000.00"
    assert _figures(invoice.json())["vat_computed"]["amount"] == "100.00"
    assert invoice.json()["direction"] == "withheld_by_us"


async def test_an_unknown_source_kind_is_not_a_route(world: World) -> None:
    async with world.client() as client:
        response = await client.put(f"{BASE}/purchase_order/{uuid.uuid4()}", json=_body(world))
    assert response.status_code == 422


async def test_the_vat_rate_must_be_stated_even_when_it_is_unknown(world: World) -> None:
    source_id = uuid.uuid4()
    missing = _body(world)
    del missing["vat_rate_pct"]
    async with world.client() as client:
        refused = await client.put(f"{BASE}/progress_claim/{source_id}", json=missing)
        unknown = await client.put(f"{BASE}/progress_claim/{source_id}", json=_body(world, vat_rate_pct=None))
    assert refused.status_code == 422
    assert unknown.status_code == 200, unknown.text
    figures = _figures(unknown.json())
    # Unknown is held with no amount. It is never a VAT-free document.
    for kind in ("vat_computed", "vat_withheld", "vat_payable"):
        assert figures[kind]["status"] == "held", kind
        assert figures[kind]["amount"] is None, kind
    assert figures["vat_computed"]["reason_key"] == "vat_rate_unknown"
    assert unknown.json()["inputs"]["vat_rate_pct"] is None
    assert unknown.json()["complete"] is False


# ── Decimal exactness ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("currency", "net", "computed", "withheld", "payable"),
    [
        ("EUR", "100000.00", "20000.00", "6000.00", "14000.00"),
        ("KWD", "1000.555", "200.111", "60.033", "140.078"),
        ("JPY", "100005", "20001", "6000", "14001"),
    ],
)
async def test_amounts_go_in_and_come_out_as_the_same_strings(
    world: World, currency, net, computed, withheld, payable
) -> None:
    source_id = uuid.uuid4()
    body = _body(world, currency_code=currency, net_amount=net, income_withholding={"state": "unset"})
    async with world.client() as client:
        saved = await client.put(f"{BASE}/progress_claim/{source_id}", json=body)
        world.session.expire_all()
        read = await client.get(f"{BASE}/progress_claim/{source_id}", params={"project_id": str(world.project_id)})
    assert saved.status_code == 200, saved.text
    assert read.status_code == 200, read.text
    for payload in (saved.json(), read.json()):
        figures = _figures(payload)
        assert payload["inputs"]["net_amount"] == net
        assert figures["vat_computed"]["amount"] == computed
        assert figures["vat_computed"]["base"] == net
        assert figures["vat_withheld"]["amount"] == withheld
        assert figures["vat_payable"]["amount"] == payable
        assert (figures["vat_withheld"]["numerator"], figures["vat_withheld"]["denominator"]) == (3, 10)
        # Held and not applicable travel as null, never as "0".
        assert figures["income_withheld"]["status"] == "held"
        assert figures["income_withheld"]["amount"] is None
        assert figures["stamp_duty"]["status"] == "not_applicable"
        assert figures["stamp_duty"]["amount"] is None


async def test_an_amount_finer_than_its_currency_is_refused_not_rounded(world: World) -> None:
    source_id = uuid.uuid4()
    async with world.client() as client:
        response = await client.put(
            f"{BASE}/progress_claim/{source_id}", json=_body(world, currency_code="JPY", net_amount="100005.5")
        )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "amount_finer_than_currency"
    assert await _stored_rows(world.session, source_id) == (0, 0)


async def test_stamp_duty_waits_for_its_own_base(world: World) -> None:
    """The stamp duty base is not the VAT base, and it is asked for, not assumed."""
    source_id = uuid.uuid4()
    url = f"{BASE}/progress_claim/{source_id}"
    selected = {"state": "selected", "code": "S1"}
    async with world.client() as client:
        waiting = await client.put(url, json=_body(world, stamp_duty=selected))
        stated = await client.put(
            url,
            json=_body(
                world,
                stamp_duty=selected,
                stamp_duty_base="80000.00",
                work_value_incl_vat="750000.00",
                work_value_note="Value of the main contract",
            ),
        )
        world.session.expire_all()
        read = await client.get(url, params={"project_id": str(world.project_id)})
        as_net = await client.put(url, json=_body(world, stamp_duty=selected, stamp_duty_base_same_as_net=True))
        both = await client.put(
            url, json=_body(world, stamp_duty=selected, stamp_duty_base="1.00", stamp_duty_base_same_as_net=True)
        )
    assert waiting.status_code == 200, waiting.text
    held = _figures(waiting.json())["stamp_duty"]
    assert (held["status"], held["amount"], held["reason_key"]) == ("held", None, "stamp_duty_base_unknown")
    assert waiting.json()["inputs"]["stamp_duty_base"] is None

    assert stated.status_code == 200, stated.text
    for payload in (stated.json(), read.json()):
        figure = _figures(payload)["stamp_duty"]
        assert (figure["status"], figure["base"], figure["amount"]) == ("value", "80000.00", "200.00")
        assert _figures(payload)["vat_computed"]["base"] == "100000.00"
        assert payload["inputs"]["stamp_duty_base"] == "80000.00"
        assert payload["inputs"]["work_value_incl_vat"] == "750000.00"
        assert payload["inputs"]["work_value_note"] == "Value of the main contract"

    assert as_net.status_code == 200, as_net.text
    assert _figures(as_net.json())["stamp_duty"]["base"] == "100000.00"
    assert _figures(as_net.json())["stamp_duty"]["amount"] == "250.00"
    assert both.status_code == 422


async def test_preview_computes_and_stores_nothing(world: World) -> None:
    body = _body(world)
    for key in ("project_id", "direction", "source_reference"):
        del body[key]
    before = await world.session.scalar(text("SELECT count(*) FROM oe_tax_withholding_statutory_calc"))
    async with world.client() as client:
        response = await client.post(f"{BASE}/preview", json=body)
    assert response.status_code == 200, response.text
    assert _figures(response.json())["vat_withheld"]["amount"] == "6000.00"
    assert response.json()["complete"] is True
    assert await world.session.scalar(text("SELECT count(*) FROM oe_tax_withholding_statutory_calc")) == before


async def test_the_category_picker_lists_the_injected_rows(world: World) -> None:
    async with world.client() as client:
        listed = await client.get(
            f"{BASE}/categories", params={"country": "XX", "kind": "vat_withholding", "on": "2026-03-10"}
        )
        undated = await client.get(f"{BASE}/categories", params={"country": "XX"})
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert (page["total"], page["offset"], page["limit"]) == (2, 0, 200)
    assert [(row["code"], row["numerator"], row["denominator"], row["review_status"]) for row in page["items"]] == [
        ("W1", 3, 10, "confirmed"),
        ("W2", 7, 10, "unconfirmed"),
    ]
    first = page["items"][0]
    assert first["legal_reference"] == "Synthetic Act art. 1"
    assert first["source_url"] == "https://example.invalid/act/1"
    assert first["conditions"] == {"en": "Synthetic condition"}
    assert first["rate_pct"] is None
    # No date, no picker: the rows on offer depend on the document's date.
    assert undated.status_code == 422


# ── Override, confirm, reopen ────────────────────────────────────────────────


async def test_the_whole_life_of_one_document(world: World) -> None:
    source_id = uuid.uuid4()
    url = f"{BASE}/progress_claim/{source_id}"
    project = str(world.project_id)
    async with world.client() as client:
        saved = await client.put(url, json=_body(world, vat_withholding={"state": "selected", "code": "W2"}))
        assert saved.status_code == 200, saved.text
        assert saved.json()["uses_unconfirmed_rates"] is True
        assert _figures(saved.json())["vat_withheld"]["amount"] == "14000.00"

        overridden = await client.post(
            f"{url}/override",
            json={"project_id": project, "kind": "vat_withheld", "amount": "13999.99", "reason": "Agreed figure"},
        )
        assert overridden.status_code == 200, overridden.text
        figures = _figures(overridden.json())
        assert figures["vat_withheld"]["overridden"] is True
        assert figures["vat_withheld"]["amount"] == "13999.99"
        assert figures["vat_withheld"]["override_reason"] == "Agreed figure"
        assert figures["vat_withheld"]["overridden_by"] == str(world.owner_id)
        assert figures["vat_payable"]["amount"] == "6000.01"

        unacknowledged = await client.post(f"{url}/confirm", json={"project_id": project})
        assert unacknowledged.status_code == 422, unacknowledged.text
        assert unacknowledged.json()["detail"]["code"] == "statutory_unconfirmed_rates"

        confirmed = await client.post(
            f"{url}/confirm", json={"project_id": project, "acknowledge_unconfirmed_rates": True}
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "confirmed"
        assert confirmed.json()["confirmed_by"] == str(world.owner_id)
        assert confirmed.json()["unconfirmed_rates_acknowledged_by"] == str(world.owner_id)
        assert confirmed.json()["unconfirmed_rates_acknowledged_at"] is not None

        frozen = await client.put(url, json=_body(world, net_amount="1.00"))
        assert frozen.status_code == 409, frozen.text
        assert frozen.json()["detail"]["code"] == "statutory_confirmed"
        still = await client.get(url, params={"project_id": project})
        assert _figures(still.json())["vat_withheld"]["amount"] == "13999.99"

        reopened = await client.post(f"{url}/reopen", json={"project_id": project, "reason": "Net corrected"})
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["status"] == "draft"
        assert reopened.json()["confirmed_by"] is None
        assert reopened.json()["reopen_reason"] == "Net corrected"

        cleared = await client.delete(f"{url}/override/vat_withheld", params={"project_id": project})
        assert cleared.status_code == 200, cleared.text
        assert _figures(cleared.json())["vat_withheld"]["overridden"] is False
        assert _figures(cleared.json())["vat_withheld"]["amount"] == "14000.00"

        voided = await client.post(f"{url}/void", json={"project_id": project, "reason": "Claim withdrawn"})
        assert voided.status_code == 200, voided.text
        assert voided.json()["status"] == "void"

    audited = (
        (
            await world.session.execute(
                text(
                    "SELECT action FROM oe_core_audit_log "
                    "WHERE entity_type = 'tax_withholding_statutory' AND entity_id = :id ORDER BY created_at, action"
                ),
                {"id": saved.json()["id"]},
            )
        )
        .scalars()
        .all()
    )
    assert sorted(audited) == ["confirm", "reopen", "void"]


async def test_a_held_figure_cannot_be_confirmed(world: World) -> None:
    source_id = uuid.uuid4()
    url = f"{BASE}/progress_claim/{source_id}"
    async with world.client() as client:
        await client.put(url, json=_body(world, income_withholding={"state": "unset"}))
        response = await client.post(
            f"{url}/confirm", json={"project_id": str(world.project_id), "acknowledge_unconfirmed_rates": True}
        )
        read = await client.get(url, params={"project_id": str(world.project_id)})
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "statutory_held"
    assert detail["details"]["held"] == ["income_withheld"]
    assert "tax_withholding.statutory_line_held" in {finding["rule_id"] for finding in detail["findings"]}
    assert read.json()["status"] == "draft"


# ── Who may do what ──────────────────────────────────────────────────────────


async def test_view_edit_and_confirm_are_three_permissions(world: World) -> None:
    source_id = uuid.uuid4()
    url = f"{BASE}/progress_claim/{source_id}"
    project = str(world.project_id)
    async with world.client() as client:
        world.act_as(world.owner_id, "viewer")
        assert (await client.put(url, json=_body(world))).status_code == 403

        world.act_as(world.owner_id, "editor")
        assert (await client.put(url, json=_body(world))).status_code == 200
        assert (await client.post(f"{url}/confirm", json={"project_id": project})).status_code == 403
        assert (await client.post(f"{url}/void", json={"project_id": project, "reason": "x"})).status_code == 403

        world.act_as(world.owner_id, "viewer")
        assert (await client.get(url, params={"project_id": project})).status_code == 200

        world.act_as(world.owner_id, "manager")
        assert (await client.post(f"{url}/confirm", json={"project_id": project})).status_code == 200
        assert (await client.post(f"{url}/reopen", json={"project_id": project, "reason": "x"})).status_code == 200


def _calls(world: World, url: str, project: str) -> list[tuple[str, str, dict]]:
    """Every route that touches a stored document, as ``(method, url, kwargs)``."""
    return [
        ("GET", url, {"params": {"project_id": project}}),
        ("PUT", url, {"json": {**_body(world), "project_id": project}}),
        (
            "POST",
            f"{url}/override",
            {"json": {"project_id": project, "kind": "vat_withheld", "amount": "1.00", "reason": "x"}},
        ),
        ("DELETE", f"{url}/override/vat_withheld", {"params": {"project_id": project}}),
        ("POST", f"{url}/confirm", {"json": {"project_id": project}}),
        ("POST", f"{url}/reopen", {"json": {"project_id": project, "reason": "x"}}),
        ("POST", f"{url}/void", {"json": {"project_id": project, "reason": "x"}}),
    ]


async def test_another_projects_user_cannot_reach_a_document_on_any_route(world: World) -> None:
    source_id = uuid.uuid4()
    url = f"{BASE}/progress_claim/{source_id}"
    async with world.client() as client:
        saved = await client.put(url, json=_body(world))
        assert saved.status_code == 200, saved.text
        world.act_as(world.outsider_id, "manager")

        # Naming the project the document really belongs to: the caller cannot
        # reach it, and gets the same 404 as for a project that does not exist.
        for method, target, kwargs in _calls(world, url, str(world.project_id)):
            response = await client.request(method, target, **kwargs)
            assert response.status_code == 404, (method, target, response.text)
            assert response.json()["detail"] == "Project not found", (method, target)

        # Naming a project of their own: the document is filed elsewhere, and
        # the answer is the one for a document with nothing stored.
        for method, target, kwargs in _calls(world, url, str(world.outsider_project_id)):
            response = await client.request(method, target, **kwargs)
            assert response.status_code == 404, (method, target, response.text)
            assert response.json()["detail"] == NOT_FOUND, (method, target)

        nothing_stored = await client.get(
            f"{BASE}/progress_claim/{uuid.uuid4()}", params={"project_id": str(world.outsider_project_id)}
        )
        assert nothing_stored.status_code == 404
        assert nothing_stored.json()["detail"] == NOT_FOUND

        world.act_as(world.owner_id, "manager")
        untouched = await client.get(url, params={"project_id": str(world.project_id)})
    assert untouched.status_code == 200, untouched.text
    assert untouched.json()["status"] == "draft"
    assert untouched.json()["project_id"] == str(world.project_id)
    assert untouched.json()["figures"] == saved.json()["figures"]
    assert await _stored_rows(world.session, source_id) == (1, 5)


async def test_a_document_cannot_be_claimed_under_a_project_it_does_not_belong_to(world: World) -> None:
    """The hole this guard closes: an id nobody had filed yet could be taken by any project."""
    source_id = uuid.uuid4()
    url = f"{BASE}/progress_claim/{source_id}"
    world.act_as(world.outsider_id, "manager")
    async with world.client() as client:
        # The outsider may write to their own project, and names it. The
        # document belongs to the other one, so nothing is created.
        claimed = await client.put(url, json=_body(world, project_id=str(world.outsider_project_id)))
        assert claimed.status_code == 404, claimed.text
        assert claimed.json()["detail"] == NOT_FOUND
        assert await _stored_rows(world.session, source_id) == (0, 0)

        # So the real owner still finds nothing stored, and can file the set.
        world.act_as(world.owner_id, "manager")
        saved = await client.put(url, json=_body(world))
    assert saved.status_code == 200, saved.text
    assert saved.json()["project_id"] == str(world.project_id)
    assert await _stored_rows(world.session, source_id) == (1, 5)


async def test_a_document_its_owner_does_not_know_is_refused_on_every_route(world: World) -> None:
    source_id = uuid.uuid4()
    world.owned_elsewhere[source_id] = None
    url = f"{BASE}/progress_claim/{source_id}"
    async with world.client() as client:
        for method, target, kwargs in _calls(world, url, str(world.project_id)):
            response = await client.request(method, target, **kwargs)
            assert response.status_code == 404, (method, target, response.text)
            assert response.json()["detail"] == NOT_FOUND, (method, target)
    assert await _stored_rows(world.session, source_id) == (0, 0)


async def test_a_source_kind_nobody_owns_is_refused_on_every_route(world: World) -> None:
    """Fail closed: where the owning module is not installed there is no such document."""
    from app.modules.tax_withholding import source_owners

    source_owners.unregister_source_owner("invoice")
    source_id = uuid.uuid4()
    url = f"{BASE}/invoice/{source_id}"
    async with world.client() as client:
        for method, target, kwargs in _calls(world, url, str(world.project_id)):
            response = await client.request(method, target, **kwargs)
            assert response.status_code == 404, (method, target, response.text)
            assert response.json()["detail"] == NOT_FOUND, (method, target)
    assert await _stored_rows(world.session, source_id) == (0, 0)


async def test_a_set_stored_before_its_document_changed_hands_is_unreachable(world: World) -> None:
    """The stored ``project_id`` alone is not trusted either: the owner is asked on every read."""
    source_id = uuid.uuid4()
    url = f"{BASE}/progress_claim/{source_id}"
    async with world.client() as client:
        saved = await client.put(url, json=_body(world))
        assert saved.status_code == 200, saved.text
        # The owning module now says the document belongs elsewhere.
        world.owned_elsewhere[source_id] = world.outsider_project_id
        for method, target, kwargs in _calls(world, url, str(world.project_id)):
            response = await client.request(method, target, **kwargs)
            assert response.status_code == 404, (method, target, response.text)
            assert response.json()["detail"] == NOT_FOUND, (method, target)
