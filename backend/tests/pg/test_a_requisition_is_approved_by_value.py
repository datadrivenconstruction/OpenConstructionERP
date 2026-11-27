# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Requisition approval routed on value, over HTTP against PostgreSQL.

The world of ``test_a_requisition_is_approved_and_ordered_once``: concrete
71.4 m3 at 95.50 EUR (6 818.70 EUR) and an unpriced rebar line. The project
sets ``5 000 EUR -> [manager]`` and ``50 000 EUR -> [second manager]``.

What is pinned here:

* the bands are saved, read back with names, and refused when they overlap;
* a 6 818.70 EUR requisition goes to the manager only, who is shown as added
  by the 5 000 band, and the second manager may not decide it;
* withdrawn, it shows only the approvers someone chose; resubmitted at
  60 000 EUR it goes to both, lowest band first;
* a line priced in another currency blocks submission, and an unpriced line is
  flagged as counting zero;
* bands switched off restore the one-step approval;
* a band may name a role: any project manager but the requester decides it,
  and a role that cannot approve requisitions is refused.
"""

from __future__ import annotations

import pytest

from tests.pg.test_a_requisition_is_approved_and_ordered_once import (  # noqa: F401 - the fixture is used by name
    REQ,
    World,
    _body,
    client_as,
    world,
)
from tests.pg.test_requisition_orders_approvals_and_feed import _member_manager

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _set_bands(w: World, bands: list[dict], currency: str = "EUR"):
    async with client_as(w, w.manager, "manager") as c:
        return await c.put(
            f"{REQ}/settings",
            params={"project_id": str(w.project_id)},
            json={"approval_bands": {"currency": currency, "bands": bands}},
        )


async def test_value_bands_pick_the_approvers_at_submission(world: World) -> None:
    second = await _member_manager(world)
    overlapping = await _set_bands(
        world,
        [
            {"from_amount": "5000", "approvers": [str(world.manager)]},
            {"from_amount": "9000", "approvers": [str(world.manager)]},
        ],
    )
    assert overlapping.status_code == 422
    saved = await _set_bands(
        world,
        [
            {"from_amount": "50000", "approvers": [str(second)]},
            {"from_amount": "5000", "approvers": [str(world.manager)]},
        ],
    )
    assert saved.status_code == 200, saved.text
    bands = saved.json()["approval_bands"]
    assert bands["currency"] == "EUR"
    assert [b["from_amount"] for b in bands["bands"]] == ["5000", "50000"], "stored lowest band first"
    assert bands["bands"][0]["approvers"][0]["name"] == "Req manager"

    async with client_as(world, world.editor, "editor") as c:
        created = await c.post(f"{REQ}/", json={**_body(world), "approval_chain": []})
        rid = created.json()["id"]
        validated = (await c.get(f"{REQ}/{rid}/validate")).json()
        submitted = await c.post(f"{REQ}/{rid}/submit")
    unpriced = [r for r in validated["results"] if r["rule_id"] == "procurement.requisition_unpriced_under_bands"]
    assert [r["passed"] for r in unpriced] == [False], "the rebar line has no price"
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert [(s["user_id"], s["band_from"]) for s in body["approval_chain"]] == [(str(world.manager), "5000")]

    async with client_as(world, second, "manager") as c:
        out_of_band = await c.post(f"{REQ}/{rid}/approve", json={})
    assert out_of_band.status_code == 403

    async with client_as(world, world.editor, "editor") as c:
        withdrawn = (await c.post(f"{REQ}/{rid}/withdraw")).json()
        assert withdrawn["approval_chain"] == []
        concrete = withdrawn["items"][0]
        items = [
            {
                **{k: concrete[k] for k in ("description", "unit", "currency_code")},
                "quantity_requested": "600",
                "unit_cost": "100",
            }
        ]
        edited = await c.patch(f"{REQ}/{rid}", json={"items": items})
        assert edited.status_code == 200, edited.text
        resubmitted = await c.post(f"{REQ}/{rid}/submit")
    assert resubmitted.status_code == 200, resubmitted.text
    assert [(s["user_id"], s["band_from"]) for s in resubmitted.json()["approval_chain"]] == [
        (str(world.manager), "5000"),
        (str(second), "50000"),
    ]


async def test_a_line_in_another_currency_blocks_and_bands_off_restore_one_step(world: World) -> None:
    saved = await _set_bands(world, [{"from_amount": "5000", "approvers": [str(world.manager)]}], currency="USD")
    assert saved.status_code == 200, saved.text
    async with client_as(world, world.editor, "editor") as c:
        created = await c.post(f"{REQ}/", json={**_body(world), "approval_chain": []})
        refused = await c.post(f"{REQ}/{created.json()['id']}/submit")
    assert refused.status_code == 422
    assert "procurement.requisition_value_band_currency" in refused.text

    off = await _set_bands(world, [])
    assert off.status_code == 200 and off.json()["approval_bands"] is None
    async with client_as(world, world.editor, "editor") as c:
        submitted = await c.post(f"{REQ}/{created.json()['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["approval_chain"] == []


async def test_a_role_band_is_decided_by_any_holder_of_the_role(world: World) -> None:
    second = await _member_manager(world)
    refused = await _set_bands(world, [{"from_amount": "5000", "roles": ["viewer"]}])
    assert refused.status_code == 422, "a viewer cannot approve requisitions"
    saved = await _set_bands(world, [{"from_amount": "5000", "roles": ["manager"]}])
    assert saved.status_code == 200, saved.text
    assert saved.json()["approval_bands"]["bands"][0]["roles"] == ["manager"]

    async with client_as(world, world.editor, "editor") as c:
        created = await c.post(f"{REQ}/", json={**_body(world), "approval_chain": []})
        rid = created.json()["id"]
        submitted = await c.post(f"{REQ}/{rid}/submit")
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert [(s["user_id"], s["role"], s["band_from"]) for s in body["approval_chain"]] == [
        ("role:manager", "manager", "5000")
    ]
    assert body["next_approver_id"] is None
    assert body["next_approver_role"] == "manager"
    assert (body["approval_chain"][0]["can_decide"], body["approval_chain"][0]["decide_reason"]) == (
        False,
        "own_submission",
    ), "the submitter sees why the step is not theirs"

    async with client_as(world, second, "manager") as c:
        seen = (await c.get(f"{REQ}/{rid}")).json()
        assert seen["approval_chain"][0]["can_decide"] is True
        approved = await c.post(f"{REQ}/{rid}/approve", json={})
    assert approved.status_code == 200, approved.text
    out = approved.json()
    assert out["status"] == "approved"
    assert out["approval_chain"][0]["state"] == "approved"
    assert out["approval_chain"][0]["name"], "the step names the manager who decided it"
