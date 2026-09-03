# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Raised in error: delete it, or withdraw it.

There was no way to remove a register item at all, so junk raised by
mistake was permanent and six test items had to be deleted straight out
of the database. The rail that replaces that:

    something nobody outside has seen  ->  DELETE, and it is gone
    something that has already gone out ->  WITHDRAW, and it stays on
                                            the record, plainly marked

and the reference is never given back either way. A supplier holding
REG-RFQ-25406-0005 must never receive a different package under the same
number, so the counter does not roll back when the newest item is
deleted - pinned by ``test_the_counter_never_rolls_back``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.dependencies import (  # noqa: E402
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.contacts.models import Contact  # noqa: E402
from app.modules.projects.models import Project  # noqa: E402
from app.modules.register_workflow.router import router as rw_router  # noqa: E402
from app.modules.users.models import User  # noqa: E402
from tests._pg import isolated_engine

USER_ID = "00000000-0000-0000-0000-0000000000d5"
API = "/api/v1/register-workflow"

#: A reason a person can still read in six weeks - the bar gate overrides
#: are held to, and the one withdraw reuses.
GOOD_REASON = "Client cancelled the switchboard package before it was priced."

RFQ_FIELDS = {
    "Package": "Cable ladder",
    "Delivery to": "12 Site Rd",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2026-09-30",
}


@pytest_asyncio.fixture
async def ctx():
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = User(
                id=uuid.UUID(USER_ID),
                email=f"dw-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Delete Withdraw",
                role="admin",
            )
            s.add(user)
            await s.flush()
            project = Project(
                name=f"DW {uuid.uuid4().hex[:6]}",
                owner_id=user.id,
                currency="AUD",
                project_code="25406",
            )
            s.add(project)
            supplier = Contact(
                contact_type="supplier",
                company_name="Acme Electrical",
                first_name="Alex",
                last_name="Example",
                primary_email="alex@acme.example",
            )
            s.add(supplier)
            await s.commit()
            project_id, supplier_id = str(project.id), str(supplier.id)

        app = FastAPI()
        app.include_router(rw_router, prefix=API)
        # WHO IS CALLING, mutable per test. The delete rail is two-sided -
        # the raiser with `update`, anybody else with `delete` - so the
        # tests have to be able to stop being an admin.
        caller = {"sub": USER_ID, "role": "admin", "permissions": ["*"]}
        app.dependency_overrides[get_current_user_id] = lambda: caller["sub"]
        app.dependency_overrides[get_current_user_payload] = lambda: dict(caller)

        async def _session_override():
            async with maker() as s:
                yield s

        app.dependency_overrides[get_session] = _session_override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client, project_id, supplier_id, maker, caller


async def _raise(client, project_id: str, kind: str = "rfq", **over) -> dict:
    body = {
        "project_id": project_id,
        "kind": kind,
        "title": over.pop("title", "MSB-01"),
        "fields": dict(RFQ_FIELDS, **over.pop("fields", {})),
        "recipient_contact_ids": over.pop("recipients", []),
    }
    body.update(over)
    r = await client.post(f"{API}/items", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _withdraw(client, item_id: str, reason: str = GOOD_REASON):
    return await client.post(f"{API}/items/{item_id}/withdraw", json={"reason": reason})


# ── Delete: only what nobody has seen ────────────────────────────────────


@pytest.mark.asyncio
async def test_a_fresh_item_can_be_deleted(ctx) -> None:
    client, pid, _sid, _maker, _caller = ctx
    item = await _raise(client, pid)
    r = await client.delete(f"{API}/items/{item['id']}")
    assert r.status_code == 204, r.text
    assert (await client.get(f"{API}/items/{item['id']}")).status_code == 404
    rows = (await client.get(f"{API}/items", params={"project_id": pid})).json()["items"]
    assert all(x["id"] != item["id"] for x in rows)


@pytest.mark.asyncio
async def test_deleting_takes_the_native_record_with_it(ctx) -> None:
    """A raise publishes an RFQ on the RFQ register too.

    Leaving that behind was the other half of the "deleted straight from
    the database" problem: the register row vanished and a junk RFQ
    nobody asked for stayed on the procurement screen for ever.
    """
    from app.modules.rfq_bidding.models import RFQ

    client, pid, _sid, maker, _caller = ctx
    item = await _raise(client, pid)
    native_id = uuid.UUID(item["linked_entity_id"])
    async with maker() as s:
        assert await s.get(RFQ, native_id) is not None

    assert (await client.delete(f"{API}/items/{item['id']}")).status_code == 204
    async with maker() as s:
        assert await s.get(RFQ, native_id) is None


@pytest.mark.asyncio
async def test_delete_is_refused_once_it_has_been_emailed(ctx) -> None:
    """A supplier holds it now. That is a record, not a mistake."""
    client, pid, sid, maker, _caller = ctx
    item = await _raise(client, pid, recipients=[sid])
    logged = await client.post(
        f"{API}/items/{item['id']}/log-sent",
        json={"contact_id": sid, "contact_name": "Acme Electrical", "sent_on": ""},
    )
    assert logged.status_code == 200, logged.text

    r = await client.delete(f"{API}/items/{item['id']}")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    # It says WHAT stops it, and what to do instead - never a bare "no".
    assert "emailed to 1 supplier" in detail["error"]
    assert "withdraw it instead" in detail["error"]
    assert any("emailed" in reason for reason in detail["reasons"])
    # And it is still there.
    assert (await client.get(f"{API}/items/{item['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_delete_is_refused_once_a_quote_is_recorded(ctx) -> None:
    client, pid, sid, maker, _caller = ctx
    item = await _raise(client, pid, recipients=[sid])
    quoted = await client.post(
        f"{API}/items/{item['id']}/quotes",
        json={"bidder_contact_id": sid, "amount": "9350", "quote_number": "100042"},
    )
    assert quoted.status_code == 200, quoted.text

    r = await client.delete(f"{API}/items/{item['id']}")
    assert r.status_code == 409, r.text
    assert "1 quote" in r.json()["detail"]["error"]


@pytest.mark.asyncio
async def test_delete_is_refused_once_a_reply_is_on_file(ctx) -> None:
    client, pid, sid, maker, _caller = ctx
    item = await _raise(client, pid, recipients=[sid])
    logged = await client.post(
        f"{API}/items/{item['id']}/log-reply",
        json={
            "contact_id": sid,
            "subject": "Re: MSB-01",
            "body": "We will price this today.",
            "received_on": "2026-09-01",
        },
    )
    assert logged.status_code == 200, logged.text

    r = await client.delete(f"{API}/items/{item['id']}")
    assert r.status_code == 409, r.text
    assert "on file" in r.json()["detail"]["error"]


@pytest.mark.asyncio
async def test_delete_is_refused_when_something_was_raised_from_it(ctx) -> None:
    """Erasing the parent leaves the child's provenance pointing at air."""
    client, pid, _sid, _maker, _caller = ctx
    parent = await _raise(client, pid, kind="rfi", title="Ceiling height", fields={"Question": "Ceiling height?"})
    child = await _raise(client, pid, raised_from_id=parent["id"])

    r = await client.delete(f"{API}/items/{parent['id']}")
    assert r.status_code == 409, r.text
    assert child["reference"] in r.json()["detail"]["error"]


# ── Delete: whose mistake is it to erase ─────────────────────────────────
#
# Two-sided on purpose. A cleanup you have to ask a manager for is the
# "just delete it out of the database for me" problem again, so the
# person who RAISED it may erase their own unseen mistake with ordinary
# update rights. Anybody else needs the manager-level permission the
# module already declares, because erasing a colleague's item is not a
# correction, it is a decision about somebody else's work.


async def _someone_else_raised_it(maker, item_id: str) -> None:
    """Re-stamp ``created_by`` - what a colleague's item looks like."""
    from app.modules.register_workflow.models import RegisterItem

    async with maker() as s:
        row = await s.get(RegisterItem, uuid.UUID(item_id))
        row.created_by = str(uuid.uuid4())
        await s.commit()


@pytest.mark.asyncio
async def test_the_person_who_raised_it_can_delete_their_own_mistake(ctx) -> None:
    client, pid, _sid, _maker, caller = ctx
    item = await _raise(client, pid)

    # An ordinary editor, with nothing but update rights - not an admin.
    caller.update(role="editor", permissions=["register_workflow.update"])
    r = await client.delete(f"{API}/items/{item['id']}")
    assert r.status_code == 204, r.text
    assert (await client.get(f"{API}/items/{item['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_another_editor_cannot_delete_somebody_elses_item(ctx) -> None:
    client, pid, _sid, maker, caller = ctx
    item = await _raise(client, pid)
    await _someone_else_raised_it(maker, item["id"])

    caller.update(role="editor", permissions=["register_workflow.update"])
    r = await client.delete(f"{API}/items/{item['id']}")
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    # Same shape as the 409, so one renderer in the UI covers either.
    assert detail["error"] == (
        f"{item['reference']} was raised by another person - only a manager can delete it. You can withdraw it instead."
    )
    assert any("raised by somebody else" in reason for reason in detail["reasons"])
    assert (await client.get(f"{API}/items/{item['id']}")).status_code == 200

    # And the way out that the message points at is genuinely open.
    assert (await _withdraw(client, item["id"])).status_code == 200


@pytest.mark.asyncio
async def test_a_manager_can_delete_somebody_elses_item(ctx) -> None:
    client, pid, _sid, maker, caller = ctx
    item = await _raise(client, pid)
    await _someone_else_raised_it(maker, item["id"])

    # The manager-level permission the module has always declared, used
    # at last. Not admin - the role's own registry entry is what carries.
    caller.update(role="manager", permissions=["register_workflow.update"])
    r = await client.delete(f"{API}/items/{item['id']}")
    assert r.status_code == 204, r.text
    assert (await client.get(f"{API}/items/{item['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_the_record_rail_beats_every_permission(ctx) -> None:
    """A manager cannot erase an issued item either - it is withdrawn.

    The permission decides WHOSE mistakes you may clean up. It never
    decides whether a record of something that happened can be erased.
    """
    client, pid, sid, maker, caller = ctx
    item = await _raise(client, pid, recipients=[sid])
    await _someone_else_raised_it(maker, item["id"])
    sent = await client.post(
        f"{API}/items/{item['id']}/log-sent",
        json={"contact_id": sid, "contact_name": "Acme Electrical", "sent_on": ""},
    )
    assert sent.status_code == 200, sent.text

    for role in ("manager", "admin"):
        caller.update(role=role, permissions=["register_workflow.update", "register_workflow.delete"])
        r = await client.delete(f"{API}/items/{item['id']}")
        # The RECORD refusal, not the permission one - 409, and it names
        # the send rather than the raiser.
        assert r.status_code == 409, (role, r.text)
        assert "emailed to 1 supplier" in r.json()["detail"]["error"]
        assert "raised by another person" not in r.text
    assert (await client.get(f"{API}/items/{item['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_the_counter_never_rolls_back(ctx) -> None:
    """THE ONE THING A DELETE MUST NOT GIVE BACK.

    Re-issuing a deleted item's number would put two different packages
    under one reference in two different inboxes - which is the whole
    reason the series moved off MAX+1 in the first place.
    """
    client, pid, _sid, _maker, _caller = ctx
    first = await _raise(client, pid)
    second = await _raise(client, pid)
    assert (await client.delete(f"{API}/items/{second['id']}")).status_code == 204

    third = await _raise(client, pid)
    assert third["reference"] != second["reference"]
    assert third["reference"] != first["reference"]
    # NEXT, not the gap: 0001, 0002 deleted, 0003.
    tail = lambda ref: int(ref.rsplit("-", 1)[-1])  # noqa: E731
    assert tail(third["reference"]) == tail(second["reference"]) + 1


# ── Withdraw: still on the record, plainly marked ────────────────────────


@pytest.mark.asyncio
async def test_withdraw_needs_a_reason_somebody_can_read_later(ctx) -> None:
    client, pid, _sid, _maker, _caller = ctx
    item = await _raise(client, pid)
    for junk in ("", "n/a", "no", "-", "wrong"):
        r = await _withdraw(client, item["id"], junk)
        assert r.status_code in (409, 422), (junk, r.status_code, r.text)
        assert (await client.get(f"{API}/items/{item['id']}")).json()["status"] == "open"

    r = await _withdraw(client, item["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "withdrawn"
    assert body["withdrawn_reason"] == GOOD_REASON
    assert body["withdrawn_at"] and body["withdrawn_by"] == USER_ID
    # The audit line lands in the step trail, where the rest of the
    # item's history already lives.
    withdrawn_step = [s for s in body["steps"] if s["name"] == "Withdrawn"]
    assert len(withdrawn_step) == 1
    assert withdrawn_step[0]["state"] == "done"
    assert withdrawn_step[0]["override_reason"] == GOOD_REASON


@pytest.mark.asyncio
async def test_a_withdrawn_item_leaves_the_open_views_but_not_the_record(ctx) -> None:
    client, pid, sid, maker, _caller = ctx
    item = await _raise(client, pid, recipients=[sid], fields={"Quotes due": "2020-01-01"})
    assert (await _withdraw(client, item["id"])).status_code == 200

    open_rows = (await client.get(f"{API}/items", params={"project_id": pid, "status": "open"})).json()["items"]
    assert all(x["id"] != item["id"] for x in open_rows)

    # It is in the closed view, carrying its reason, so nobody has to open
    # it to find out what happened - or raise it again.
    closed_rows = (await client.get(f"{API}/items", params={"project_id": pid, "status": "closed"})).json()["items"]
    mine = next((x for x in closed_rows if x["id"] == item["id"]), None)
    assert mine is not None
    assert mine["status"] == "withdrawn" and mine["withdrawn_reason"] == GOOD_REASON
    # And the filter names it directly.
    only = (await client.get(f"{API}/items", params={"project_id": pid, "status": "withdrawn"})).json()["items"]
    assert [x["id"] for x in only] == [item["id"]]

    # Out of the counts and off the overdue clock, though it is long past
    # its quotes-due date.
    assert mine["is_overdue"] is False
    summary = (await client.get(f"{API}/summary", params={"project_id": pid})).json()
    assert summary["rfq"]["open"] == 0
    assert summary["rfq"]["with_them"] == 0
    assert summary["rfq"]["withdrawn"] == 1
    assert summary["rfq"]["overdue"] == 0


@pytest.mark.asyncio
async def test_a_withdrawn_item_is_out_of_the_sweep_and_the_tracking(ctx) -> None:
    client, pid, sid, maker, _caller = ctx
    item = await _raise(client, pid, recipients=[sid], fields={"Quotes due": "2020-01-01"})

    # A SECOND, LIVE ITEM. The sweep remembers what it announced today,
    # so "0 published after the withdrawal" would pass on the dedupe
    # alone - the live one proves the sweep still had something to say
    # and deliberately left the withdrawn one out of it.
    live = await _raise(client, pid, title="MSB-02", recipients=[sid], fields={"Quotes due": "2020-01-01"})
    for target in (item, live):
        sent = await client.post(
            f"{API}/items/{target['id']}/log-sent",
            json={"contact_id": sid, "contact_name": "Acme Electrical", "sent_on": "2020-01-01"},
        )
        assert sent.status_code == 200, sent.text

    assert (await _withdraw(client, item["id"])).status_code == 200

    swept = (await client.post(f"{API}/deadline-sweep", params={"project_id": pid})).json()
    announced = " ".join(swept["detail"])
    assert live["reference"] in announced
    assert item["reference"] not in announced

    tracking = (await client.get(f"{API}/tracking", params={"project_id": pid})).json()
    outstanding = [row["reference"] for row in tracking["outstanding"]]
    assert live["reference"] in outstanding
    assert item["reference"] not in outstanding


@pytest.mark.asyncio
async def test_a_withdrawn_item_refuses_every_further_move(ctx) -> None:
    """Withdrawn that could still be emailed or awarded is just a label."""
    client, pid, sid, maker, _caller = ctx
    item = await _raise(client, pid, recipients=[sid])
    assert (await _withdraw(client, item["id"])).status_code == 200
    iid = item["id"]

    refusals = [
        await client.post(f"{API}/items/{iid}/email/eml", json={"contact_id": sid}),
        await client.post(
            f"{API}/items/{iid}/log-sent",
            json={"contact_id": sid, "contact_name": "Acme Electrical", "sent_on": ""},
        ),
        await client.post(
            f"{API}/items/{iid}/log-reply",
            json={"contact_id": sid, "subject": "Re", "body": "x", "received_on": ""},
        ),
        await client.post(f"{API}/items/{iid}/quotes", json={"bidder_contact_id": sid, "amount": "9350"}),
        await client.post(
            f"{API}/items/{iid}/award-confirmation/eml",
            json={"contact_id": sid, "po_number": "PO-1"},
        ),
        await client.patch(f"{API}/items/{iid}", json={"title": "Renamed"}),
        await client.post(f"{API}/items/{iid}/steps", json={"name": "Chase", "step_type": "step"}),
    ]
    for r in refusals:
        assert r.status_code == 409, (r.request.url, r.status_code, r.text)
        assert "withdrawn" in r.text.lower() and "Reopen it" in r.text

    # The stage moves too - the open step is still there and stays put.
    fresh = (await client.get(f"{API}/items/{iid}")).json()
    step = next(s for s in fresh["steps"] if s["state"] == "open")
    ticked = await client.post(f"{API}/steps/{step['id']}/complete", json={})
    assert ticked.status_code == 409 and "withdrawn" in ticked.text.lower()
    assert (await client.get(f"{API}/items/{iid}")).json()["status"] == "withdrawn"


@pytest.mark.asyncio
async def test_a_withdrawn_item_can_be_reopened_with_a_reason(ctx) -> None:
    client, pid, sid, maker, _caller = ctx
    item = await _raise(client, pid, recipients=[sid])
    assert (await _withdraw(client, item["id"])).status_code == 200

    junk = await client.post(f"{API}/items/{item['id']}/reopen", json={"reason": "n/a"})
    assert junk.status_code == 409
    assert (await client.get(f"{API}/items/{item['id']}")).json()["status"] == "withdrawn"

    r = await client.post(
        f"{API}/items/{item['id']}/reopen",
        json={"reason": "Client reinstated the package on 3 September."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "open"
    assert body["withdrawn_reason"] == "" and body["withdrawn_at"] is None
    # Both moves stay on the trail - the history is not rewritten.
    names = [s["name"] for s in body["steps"]]
    assert "Withdrawn" in names and "Reopened" in names
    # And it works again.
    assert (await client.patch(f"{API}/items/{item['id']}", json={"title": "MSB-01a"})).status_code == 200


@pytest.mark.asyncio
async def test_withdrawing_twice_is_refused(ctx) -> None:
    client, pid, _sid, _maker, _caller = ctx
    item = await _raise(client, pid)
    assert (await _withdraw(client, item["id"])).status_code == 200
    again = await _withdraw(client, item["id"], "Second thoughts about the same package.")
    assert again.status_code == 409 and "already withdrawn" in again.text
