# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Write flows over HTTP for plant_register, site_logistics, staffing and stakeholders.

Each test drives one module end to end on a demo project of the eleven-areas pack:
create, update, move through the state machine, try a transition the machine does not
allow, read the module's validation, and delete where the module allows it. Rows are
created new (codes prefixed ``QA``); seeded rows are only read, and used as templates
for catalogue codes a new row must carry.

A test collects every deviation and fails once with the request and response of each,
so one refused call does not hide the next. A deviation is a status outside the one the
flow expects, any 5xx, or a state that is not the one the transition names.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from typing import Any

import pytest
import pytest_asyncio

from tests.pg.elf_qa_fixtures import World, boot_world

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.environ.get("OE_API_SMOKE", "") != "1", reason="full-boot lane: set OE_API_SMOKE=1"),
]

PLANT = "/api/v1/plant-register/projects"
LOGISTICS = "/api/v1/site-logistics/projects"
STAFFING = "/api/v1/staffing/projects"
STAKEHOLDERS = "/api/v1/stakeholders/projects"


@pytest_asyncio.fixture(scope="module")
async def world(pg_async_url, tmp_path_factory):
    async for w in boot_world(pg_async_url, str(tmp_path_factory.mktemp("elf_qa_flows_d"))):
        yield w


class Flow:
    """Calls with a shared record of everything that deviated from the flow's expectation."""

    def __init__(self, world: World, project_id: uuid.UUID) -> None:
        self.world = world
        self.pid = str(project_id)
        self.problems: list[str] = []

    async def call(
        self,
        method: str,
        url: str,
        *,
        who: str = "admin",
        expect: tuple[int, ...] = (200,),
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """One request. ``expect`` may hold the string-free codes, or ``(4,)`` for any 4xx refusal."""
        resp = await self.world.client.request(method, url, json=json, params=params, headers=self.world.headers(who))
        ok = (resp.status_code in expect) or (expect == (4,) and 400 <= resp.status_code < 500)
        if not ok:
            self.problems.append(
                f"{who} {method} {url.replace(self.pid, '{pid}')} body={json} -> {resp.status_code} "
                f"(wanted {expect}): {resp.text[:300]}"
            )
        return resp

    def body(self, resp: Any) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def state(self, resp: Any, want: str, what: str, key: str = "status") -> None:
        got = self.body(resp).get(key, self.body(resp).get("state"))
        if resp.status_code < 300 and got is not None and got != want:
            self.problems.append(f"{what}: state is {got!r}, wanted {want!r}")

    def items(self, resp: Any) -> list[dict[str, Any]]:
        data = self.body(resp).get("items")
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    def finish(self, title: str) -> None:
        assert not self.problems, f"{title}: {len(self.problems)} deviation(s)\n" + "\n".join(
            f"- {p}" for p in self.problems
        )


def _flow(world: World) -> Flow:
    return Flow(world, world.projects["residential-regensburg"])


def _tag() -> str:
    return uuid.uuid4().hex[:6]


# ── plant_register ──────────────────────────────────────────────────────────


async def test_plant_register_item_lifecycle(world: World) -> None:
    f = _flow(world)
    base = f"{PLANT}/{f.pid}"
    code = f"QA-PL-{_tag()}"
    r = await f.call(
        "POST",
        f"{base}/items",
        expect=(201,),
        json={
            "code": code,
            "title": "QA transformer",
            "component_class_code": "power_transformer",
            "quantity": "1",
            "unit": "pcs",
        },
    )
    item = f.body(r).get("id")
    assert item, f"item not created: {r.status_code} {r.text[:300]}"
    f.state(r, "identified", "created item")
    got = await f.call("GET", f"{base}/items/{item}")
    f.state(got, "identified", "item read back")
    await f.call("PATCH", f"{base}/items/{item}", json={"description": "Edited by the QA flow"})
    again = await f.call("GET", f"{base}/items/{item}")
    if f.body(again).get("description") != "Edited by the QA flow":
        f.problems.append("PATCH item: description was not stored")

    moved = await f.call("POST", f"{base}/items/{item}/transition", json={"target": "specified"})
    f.state(moved, "specified", "item after transition to specified")
    # The machine moves by hand to a few states only; commissioned is read from the Cx system.
    await f.call("POST", f"{base}/items/{item}/transition", expect=(4,), json={"target": "commissioned"})
    await f.call("POST", f"{base}/items/{item}/transition", expect=(4,), json={"target": "no_such_state"})

    # Validation and readiness answer for the new item, and the register lists it.
    val = await f.call("GET", f"{base}/validation")
    if "items" not in f.body(val):
        f.problems.append("validation answer has no items list")
    await f.call("GET", f"{base}/readiness")
    listed = await f.call("GET", f"{base}/items", params={"limit": 200})
    if code not in {i.get("code") for i in f.items(listed)}:
        f.problems.append("the new item is not in the item list")

    cancelled = await f.call("POST", f"{base}/items/{item}/transition", json={"target": "cancelled"})
    f.state(cancelled, "cancelled", "item after cancel")
    await f.call("POST", f"{base}/items/{item}/transition", expect=(4,), json={"target": "specified"})
    await f.call("PATCH", f"{base}/items/{item}", expect=(4,), json={"title": "Edit after cancel"})
    f.finish("plant_register item lifecycle")


async def test_plant_register_spares_it_services_and_decision_paper(world: World) -> None:
    f = _flow(world)
    base = f"{PLANT}/{f.pid}"
    r = await f.call(
        "POST",
        f"{base}/items",
        expect=(201,),
        json={
            "code": f"QA-PL-{_tag()}",
            "title": "QA pump",
            "component_class_code": "power_transformer",
            "quantity": "2",
            "unit": "pcs",
        },
    )
    item = f.body(r).get("id")
    assert item, f"item not created: {r.status_code} {r.text[:300]}"

    # Spare parts: create, walk the machine, refuse a skipped step, delete an unused one.
    sp = await f.call(
        "POST",
        f"{base}/items/{item}/spares",
        expect=(201,),
        json={"category": "commissioning_spares", "description": "QA spare", "quantity": "2", "unit": "pcs"},
    )
    spare = f.body(sp).get("id")
    f.state(sp, "required", "created spare")
    if spare:
        up = await f.call("PATCH", f"{base}/items/{item}/spares/{spare}", json={"description": "QA spare, edited"})
        if f.body(up).get("description") != "QA spare, edited":
            f.problems.append("PATCH spare: description was not stored")
        t = await f.call("POST", f"{base}/items/{item}/spares/{spare}/transition", json={"target": "specified"})
        f.state(t, "specified", "spare after specified")
        await f.call(
            "POST", f"{base}/items/{item}/spares/{spare}/transition", expect=(4,), json={"target": "handed_over"}
        )
        t = await f.call("POST", f"{base}/items/{item}/spares/{spare}/transition", json={"target": "delivered"})
        f.state(t, "delivered", "spare after delivered")
        t = await f.call("POST", f"{base}/items/{item}/spares/{spare}/transition", json={"target": "handed_over"})
        f.state(t, "handed_over", "spare after handed_over")
        await f.call("PATCH", f"{base}/items/{item}/spares/{spare}", expect=(4,), json={"description": "closed"})
    sp2 = await f.call(
        "POST",
        f"{base}/items/{item}/spares",
        expect=(201,),
        json={"category": "special_tools", "description": "QA tool", "quantity": "1", "unit": "pcs"},
    )
    if f.body(sp2).get("id"):
        await f.call("DELETE", f"{base}/items/{item}/spares/{f.body(sp2)['id']}", expect=(204,))
    await f.call(
        "POST",
        f"{base}/items/{item}/spares",
        expect=(4,),
        json={"category": "no_such_category", "description": "x", "quantity": "1"},
    )

    # IT services: planned -> provisioned -> retired, a retired one is frozen.
    it = await f.call("POST", f"{base}/it-services", expect=(201,), json={"kind": "telecom", "description": "QA line"})
    service = f.body(it).get("id")
    f.state(it, "planned", "created IT service")
    if service:
        t = await f.call("POST", f"{base}/it-services/{service}/transition", json={"target": "provisioned"})
        f.state(t, "provisioned", "IT service after provisioned")
        await f.call("POST", f"{base}/it-services/{service}/transition", expect=(4,), json={"target": "planned"})
        t = await f.call("POST", f"{base}/it-services/{service}/transition", json={"target": "retired"})
        f.state(t, "retired", "IT service after retired")
        await f.call("PATCH", f"{base}/it-services/{service}", expect=(4,), json={"description": "after retire"})
    it2 = await f.call("POST", f"{base}/it-services", expect=(201,), json={"kind": "cctv", "description": "QA camera"})
    if f.body(it2).get("id"):
        await f.call("DELETE", f"{base}/it-services/{f.body(it2)['id']}", expect=(204,))
    await f.call("POST", f"{base}/it-services", expect=(4,), json={"kind": "no_such_kind"})

    # Decision paper: one open paper at a time, withdraw returns it to draft.
    paper_body = {
        "question": "Which supplier?",
        "options": [
            {"code": "a", "title": "Supplier A", "scores": {"cost": "3"}},
            {"code": "b", "title": "Supplier B", "scores": {"cost": "4"}},
        ],
        "criteria": [{"code": "cost", "title": "Cost", "weight": "1"}],
        "recommendation": "b",
        "rationale": "Cheaper.",
    }
    pr = await f.call("POST", f"{base}/items/{item}/decision-paper", expect=(201,), json=paper_body)
    paper = f.body(pr).get("id")
    f.state(pr, "draft", "created paper")
    if paper:
        await f.call("POST", f"{base}/items/{item}/decision-paper", expect=(4,), json=paper_body)
        await f.call("PATCH", f"{base}/items/{item}/decision-paper/{paper}", json={"rationale": "Cheaper, edited."})
        bad = {"recommendation": "zzz"}
        await f.call("PATCH", f"{base}/items/{item}/decision-paper/{paper}", expect=(4,), json=bad)
        sub = await f.call("POST", f"{base}/items/{item}/decision-paper/{paper}/submit", expect=(200, 422, 409))
        if sub.status_code == 200:
            f.state(sub, "submitted", "paper after submit")
            wd = await f.call("POST", f"{base}/items/{item}/decision-paper/{paper}/withdraw")
            f.state(wd, "draft", "paper after withdraw")
        else:
            print(f"[elf-qa] paper submit refused {sub.status_code}: {sub.text[:200]}")  # noqa: T201
    f.finish("plant_register spares, IT services and decision paper")


# ── site_logistics ──────────────────────────────────────────────────────────


async def test_site_logistics_stage_and_transport_lifecycle(world: World) -> None:
    f = _flow(world)
    base = f"{LOGISTICS}/{f.pid}"
    today = date.today()

    stage = await f.call(
        "POST",
        f"{base}/stages",
        expect=(201,),
        json={
            "code": f"qa_stage_{_tag()}",
            "title": "QA stage",
            "from_date": today.isoformat(),
            "to_date": (today + timedelta(days=30)).isoformat(),
        },
    )
    stage_id = f.body(stage).get("id")
    assert stage_id, f"stage not created: {stage.status_code} {stage.text[:300]}"
    f.state(stage, "planned", "created stage", key="state")
    await f.call("PATCH", f"{base}/stages/{stage_id}", json={"title": "QA stage, edited"})
    await f.call("POST", f"{base}/stages/{stage_id}/transition", expect=(4,), json={"target": "closed"})
    t = await f.call("POST", f"{base}/stages/{stage_id}/transition", json={"target": "active"})
    f.state(t, "active", "stage after active", key="state")
    t = await f.call("POST", f"{base}/stages/{stage_id}/transition", json={"target": "closed"})
    f.state(t, "closed", "stage after closed", key="state")
    await f.call("POST", f"{base}/stages/{stage_id}/transition", expect=(4,), json={"target": "active"})
    spare_stage = await f.call("POST", f"{base}/stages", expect=(201,), json={"code": f"qa_s_{_tag()}", "title": "QA"})
    if f.body(spare_stage).get("id"):
        await f.call("DELETE", f"{base}/stages/{f.body(spare_stage)['id']}", expect=(204,))

    # A transport takes its kind and load class from a seeded one, so the catalogue accepts it.
    seeded = (await f.call("GET", f"{base}/transports", params={"limit": 50})).json().get("items", [])
    template = next((t for t in seeded if t.get("transport_kind")), {})
    start = today + timedelta(days=14)
    body: dict[str, Any] = {
        "direction": "inbound",
        "title": "QA delivery",
        "carrier_name": "QA Haulage",
        "origin": "Plant",
        "destination": "Site",
        "planned_window_start": f"{start.isoformat()}T08:00:00+00:00",
        "planned_window_end": f"{start.isoformat()}T10:00:00+00:00",
        "gross_weight_t": "12.50",
    }
    if template.get("transport_kind"):
        body["transport_kind"] = template["transport_kind"]
    tr = await f.call("POST", f"{base}/transports", expect=(201,), json=body)
    transport = f.body(tr).get("id")
    if transport:
        f.state(tr, "planned", "created transport", key="state")
        await f.call("PATCH", f"{base}/transports/{transport}", json={"route_notes": "Via the north gate"})
        await f.call("POST", f"{base}/transports/{transport}/transition", expect=(4,), json={"target": "arrived"})
        t = await f.call("POST", f"{base}/transports/{transport}/transition", json={"target": "cancelled"})
        f.state(t, "cancelled", "transport after cancel", key="state")
        await f.call("POST", f"{base}/transports/{transport}/transition", expect=(4,), json={"target": "scheduled"})
        await f.call("DELETE", f"{base}/transports/{transport}", expect=(204, 409))

    # Permit: draft -> applied -> granted -> expired.
    permit_template = next(iter((await f.call("GET", f"{base}/permits")).json().get("items", [])), {})
    permit_body: dict[str, Any] = {"authority": "QA authority", "reference": f"QA-{_tag()}"}
    if permit_template.get("permit_kind"):
        permit_body["permit_kind"] = permit_template["permit_kind"]
    pm = await f.call("POST", f"{base}/permits", expect=(201,), json=permit_body)
    permit = f.body(pm).get("id")
    if permit:
        f.state(pm, "draft", "created permit", key="state")
        await f.call("POST", f"{base}/permits/{permit}/transition", expect=(4,), json={"target": "granted"})
        t = await f.call(
            "PATCH", f"{base}/permits/{permit}", json={"applied_on": today.isoformat(), "authority": "QA authority 2"}
        )
        t = await f.call("POST", f"{base}/permits/{permit}/transition", json={"target": "applied"})
        f.state(t, "applied", "permit after applied", key="state")
        t = await f.call("POST", f"{base}/permits/{permit}/transition", json={"target": "refused"})
        f.state(t, "refused", "permit after refused", key="state")
        await f.call("POST", f"{base}/permits/{permit}/transition", expect=(4,), json={"target": "granted"})

    # Neighbour complaint: received -> acknowledged -> action_taken -> closed.
    issues = (await f.call("GET", f"{base}/neighbour-issues")).json().get("items", [])
    issue_body: dict[str, Any] = {"description": "QA noise complaint", "reported_on": today.isoformat()}
    kind = next((i.get("kind") for i in issues if i.get("kind")), None)
    if kind:
        issue_body["kind"] = kind
    iss = await f.call("POST", f"{base}/neighbour-issues", expect=(201,), json=issue_body)
    issue = f.body(iss).get("id")
    if issue:
        f.state(iss, "received", "created complaint", key="state")
        await f.call("POST", f"{base}/neighbour-issues/{issue}/transition", expect=(4,), json={"target": "closed"})
        for step in ("acknowledged", "action_taken", "closed"):
            if step == "action_taken":
                await f.call("PATCH", f"{base}/neighbour-issues/{issue}", json={"response": "Hours agreed"})
            t = await f.call("POST", f"{base}/neighbour-issues/{issue}/transition", json={"target": step})
            f.state(t, step, f"complaint after {step}", key="state")
        await f.call("POST", f"{base}/neighbour-issues/{issue}/transition", expect=(4,), json={"target": "received"})

    # Validation and readiness answer, and the sweep does not fail.
    await f.call("GET", f"{base}/readiness")
    val = await f.call("POST", f"{base}/validate")
    if val.status_code == 200 and not isinstance(f.body(val), dict):
        f.problems.append("validate answered something that is not an object")
    f.finish("site_logistics stage, transport, permit and complaint lifecycle")


async def test_site_logistics_media_and_customs_lifecycle(world: World) -> None:
    f = _flow(world)
    base = f"{LOGISTICS}/{f.pid}"
    today = date.today()

    media_items = (await f.call("GET", f"{base}/media")).json().get("items", [])
    media_template = next((m for m in media_items if m.get("media_kind") or m.get("kind")), {})
    media_body: dict[str, Any] = {"title": "QA connection", "phase": "construction"}
    for key in ("media_kind", "kind"):
        if media_template.get(key):
            media_body[key] = media_template[key]
    md = await f.call("POST", f"{base}/media", expect=(201, 422), json=media_body)
    media = f.body(md).get("id")
    if media:
        await f.call("POST", f"{base}/media/{media}/transition", expect=(4,), json={"target": "connected"})
        t = await f.call("POST", f"{base}/media/{media}/transition", json={"target": "requested"})
        f.state(t, "requested", "media after requested", key="state")
        t = await f.call("POST", f"{base}/media/{media}/transition", json={"target": "identified"})
        f.state(t, "identified", "media back to identified", key="state")
        await f.call("DELETE", f"{base}/media/{media}", expect=(204,))
    else:
        print(f"[elf-qa] media create refused {md.status_code}: {md.text[:200]}")  # noqa: T201

    cu = await f.call(
        "POST",
        f"{base}/customs",
        expect=(201, 422),
        json={"direction": "import", "declarant_party": "buyer"},
    )
    case = f.body(cu).get("id")
    if case:
        f.state(cu, "open", "created customs case", key="state")
        await f.call("POST", f"{base}/customs/{case}/transition", expect=(4,), json={"target": "cleared"})
        await f.call("POST", f"{base}/customs/{case}/transition", expect=(4,), json={"target": "declared"})
        await f.call("DELETE", f"{base}/customs/{case}", expect=(204, 409))
    else:
        print(f"[elf-qa] customs create refused {cu.status_code}: {cu.text[:200]}")  # noqa: T201
    assert today
    f.finish("site_logistics media and customs lifecycle")


# ── staffing ────────────────────────────────────────────────────────────────


async def test_staffing_plan_and_position_lifecycle(world: World) -> None:
    f = _flow(world)
    base = f"{STAFFING}/{f.pid}"

    plan = await f.call("GET", f"{base}/plan")
    plan_status = f.body(plan).get("status")

    # The organisation of a custom position is a code of the pinned catalogue, not free text.
    pinned = f.body(await f.call("GET", f"{base}/catalogue"))
    org_codes = [o.get("code") for o in pinned.get("organisations") or [] if isinstance(o, dict) and o.get("code")]
    created = await f.call(
        "POST",
        f"{base}/positions",
        expect=(201,),
        json={
            "role_code": "custom",
            "custom_label": f"QA position {_tag()}",
            "organisation": org_codes[0] if org_codes else "contractor",
            "phase": "execution",
        },
    )
    position = f.body(created).get("id")
    if not position:
        # A catalogue without the custom role: take one it does have.
        roles = (await f.call("GET", f"{base}/catalogue")).json()
        codes = [r.get("code") for r in (roles.get("roles") or []) if isinstance(r, dict)]
        if codes:
            created = await f.call(
                "POST", f"{base}/positions", expect=(201,), json={"role_code": codes[0], "phase": "execution"}
            )
            position = f.body(created).get("id")
    assert position, f"position not created: {created.status_code} {created.text[:300]}"
    f.state(created, "open", "created position")

    await f.call("PATCH", f"{base}/positions/{position}", json={"notes": "Edited by the QA flow"})
    for step in ("recruiting", "open", "on_hold", "open"):
        t = await f.call("POST", f"{base}/positions/{position}/status", json={"status": step})
        f.state(t, step, f"position after {step}")
    # filled is derived, never set; a state that does not exist is refused too.
    await f.call("POST", f"{base}/positions/{position}/status", expect=(4,), json={"status": "filled"})
    await f.call("POST", f"{base}/positions/{position}/status", expect=(4,), json={"status": "no_such_state"})
    await f.call("PATCH", f"{base}/positions/{position}", expect=(4,), json={"headcount": 0})

    # Findings: the plan's own check and the module validation both answer.
    findings = await f.call("GET", f"{base}/plan/findings")
    if "items" not in f.body(findings):
        f.problems.append("plan findings answer has no items list")
    val = await f.call("GET", f"{base}/validation")
    if "items" not in f.body(val):
        f.problems.append("validation answer has no items list")

    # Submit, refuse a second submit, approve by the second user, or return.
    sub = await f.call("POST", f"{base}/plan/submit", expect=(200, 409, 422))
    if sub.status_code == 200:
        f.state(sub, "in_review", "plan after submit")
        await f.call("POST", f"{base}/plan/submit", expect=(4,))
        own = await f.call("POST", f"{base}/plan/approve", expect=(4,))
        other = await f.call("POST", f"{base}/plan/approve", who="manager2", expect=(200, 403, 409, 422))
        if other.status_code == 200:
            f.state(other, "binding", "plan after approval by the second user")
            if own.status_code < 300:
                f.problems.append("the submitter approved their own plan")
        else:
            # With gates in use the gate decision approves; the plan goes back to the author.
            ret = await f.call("POST", f"{base}/plan/return")
            f.state(ret, "draft", "plan after return")
    else:
        print(f"[elf-qa] plan submit refused {sub.status_code} (plan was {plan_status}): {sub.text[:200]}")  # noqa: T201

    await f.call("DELETE", f"{base}/positions/{position}", expect=(204, 409, 422))
    f.finish("staffing plan and position lifecycle")


async def test_staffing_personnel_file_lifecycle(world: World) -> None:
    f = _flow(world)
    base = f"{STAFFING}/{f.pid}"
    # The personnel file belongs to a roster member; use the first person the project has.
    positions = (await f.call("GET", f"{base}/positions")).json().get("items", [])
    member = next(
        (
            fill.get("roster_member_id")
            for p in positions
            for fill in p.get("fills", [])
            if fill.get("roster_member_id")
        ),
        None,
    )
    if member is None:
        pytest.skip("the demo project has no roster member to open a personnel file for")
    created = await f.call(
        "POST",
        f"{base}/personnel-files",
        expect=(201, 409),
        json={"roster_member_id": member, "employment_basis": "employee", "lawful_basis": "contract"},
    )
    file_id = f.body(created).get("id")
    if file_id:
        await f.call("PATCH", f"{base}/personnel-files/{file_id}", json={"employer_organisation": "QA GmbH"})
        trip = await f.call(
            "POST",
            f"{base}/personnel-files/{file_id}/travel",
            expect=(201,),
            json={"kind": "flight", "depart_date": date.today().isoformat(), "from_place": "A", "to_place": "B"},
        )
        travel = f.body(trip).get("id")
        if travel:
            t = await f.call(
                "POST", f"{base}/personnel-files/{file_id}/travel/{travel}/status", json={"status": "booked"}
            )
            f.state(t, "booked", "travel after booked")
            await f.call(
                "POST", f"{base}/personnel-files/{file_id}/travel/{travel}/status", expect=(4,), json={"status": "x"}
            )
        leave = await f.call(
            "POST",
            f"{base}/personnel-files/{file_id}/leave",
            expect=(201,),
            json={
                "leave_type": "annual",
                "from_date": (date.today() + timedelta(days=60)).isoformat(),
                "to_date": (date.today() + timedelta(days=64)).isoformat(),
            },
        )
        leave_id = f.body(leave).get("id")
        if leave_id:
            f.state(leave, "requested", "created leave")
            t = await f.call(
                "POST", f"{base}/personnel-files/{file_id}/leave/{leave_id}/status", json={"status": "approved"}
            )
            f.state(t, "approved", "leave after approval")
    f.finish("staffing personnel file lifecycle")


# ── stakeholders ────────────────────────────────────────────────────────────


async def test_stakeholders_register_assessment_and_plan(world: World) -> None:
    f = _flow(world)
    base = f"{STAKEHOLDERS}/{f.pid}"
    seeded = f.items(await f.call("GET", f"{base}/stakeholders", params={"limit": 200}))
    assert seeded, "the demo project has no stakeholders to take a category from"
    category = seeded[0]["category"]

    code = f"QA-{_tag()}"
    sh = await f.call(
        "POST",
        f"{base}/stakeholders",
        expect=(201,),
        json={"code": code, "display_name": "QA Stakeholder", "category": category, "interests": "Noise"},
    )
    sid = f.body(sh).get("id")
    assert sid, f"stakeholder not created: {sh.status_code} {sh.text[:300]}"
    f.state(sh, "active", "created stakeholder")
    await f.call(
        "POST",
        f"{base}/stakeholders",
        expect=(409, 422),
        json={"code": code, "display_name": "Dup", "category": category},
    )
    await f.call("POST", f"{base}/stakeholders", expect=(4,), json={"display_name": "No category"})
    await f.call(
        "POST", f"{base}/stakeholders", expect=(4,), json={"display_name": "Bad", "category": "no_such_category"}
    )
    up = await f.call("PATCH", f"{base}/stakeholders/{sid}", json={"concerns": "Dust", "status": "dormant"})
    f.state(up, "dormant", "stakeholder after update")

    # An assessment copies the shape of a seeded one, so the pinned method accepts it.
    template = None
    for s in seeded:
        rows = f.items(await f.call("GET", f"{base}/stakeholders/{s['id']}/assessments"))
        if rows:
            template = rows[0]
            break
    if template and template.get("scores"):
        ass = await f.call(
            "POST",
            f"{base}/stakeholders/{sid}/assessments",
            expect=(201,),
            json={"method_code": template.get("method_code"), "scores": template["scores"], "rationale": "QA"},
        )
        got = f.items(await f.call("GET", f"{base}/stakeholders/{sid}/assessments"))
        if ass.status_code == 201 and not got:
            f.problems.append("the assessment is not in the history")
    await f.call("POST", f"{base}/stakeholders/{sid}/assessments", expect=(4,), json={"scores": {"no_such_axis": 99}})

    # Engagement plan item: planned -> active -> paused -> completed, no way back from completed.
    plans = f.items(await f.call("GET", f"{base}/plan-items"))
    seed_plan = next((p for p in plans if p.get("format_code") or p.get("channel")), {})
    plan_body: dict[str, Any] = {"title": "QA engagement", "purpose": "Inform", "key_message": "Works start"}
    for key in ("participation_level", "channel", "format_code"):
        if seed_plan.get(key):
            plan_body[key] = seed_plan[key]
    plan_body["audience_stakeholder_ids"] = [sid]
    # An item needs a start date (with a frequency) or a trigger; a one-off a week out is the plain case.
    plan_body["starts_on"] = (date.today() + timedelta(days=7)).isoformat()
    pi = await f.call("POST", f"{base}/plan-items", expect=(201,), json=plan_body)
    item = f.body(pi).get("id")
    if item:
        f.state(pi, "planned", "created plan item")
        await f.call("PATCH", f"{base}/plan-items/{item}", expect=(4,), json={"status": "completed"})
        for step in ("active", "paused", "active", "completed"):
            t = await f.call("PATCH", f"{base}/plan-items/{item}", json={"status": step})
            f.state(t, step, f"plan item after {step}")
        await f.call("PATCH", f"{base}/plan-items/{item}", expect=(4,), json={"status": "active"})
    spare = await f.call("POST", f"{base}/plan-items", expect=(201,), json=plan_body)
    if f.body(spare).get("id"):
        await f.call("DELETE", f"{base}/plan-items/{f.body(spare)['id']}", expect=(204,))

    val = await f.call("GET", f"{base}/validation")
    if "items" not in f.body(val):
        f.problems.append("validation answer has no items list")
    await f.call("GET", f"{base}/readiness")

    await f.call("DELETE", f"{base}/stakeholders/{sid}", expect=(200, 204))
    f.finish("stakeholders register, assessment and plan")


async def test_stakeholders_commitment_lifecycle_with_a_second_verifier(world: World) -> None:
    f = _flow(world)
    base = f"{STAKEHOLDERS}/{f.pid}"
    me = (await world.client.get("/api/v1/users/me/", headers=world.admin)).json()["id"]
    seeded = f.items(await f.call("GET", f"{base}/stakeholders", params={"limit": 50}))
    assert seeded, "no seeded stakeholder to attach a commitment to"
    commitments = f.items(await f.call("GET", f"{base}/commitments"))
    category = next((c.get("category") for c in commitments if c.get("category")), None)

    body: dict[str, Any] = {
        "stakeholder_ids": [seeded[0]["id"]],
        "source_kind": "manual",
        "text": f"QA commitment {_tag()}",
        "owner_user_id": me,
        "due_date": (date.today() + timedelta(days=30)).isoformat(),
        "verification": "Site visit",
    }
    if category:
        body["category"] = category
    cm = await f.call("POST", f"{base}/commitments", expect=(201,), json=body)
    cid = f.body(cm).get("id")
    assert cid, f"commitment not created: {cm.status_code} {cm.text[:300]}"
    f.state(cm, "proposed", "created commitment")
    await f.call("PATCH", f"{base}/commitments/{cid}", json={"verification": "Site visit and photo"})

    # Skipping steps, withdrawing and breaching without a reason are refused.
    for target in ("verified", "fulfilled", "in_progress"):
        await f.call("POST", f"{base}/commitments/{cid}/transition", expect=(4,), json={"target": target})
    await f.call("POST", f"{base}/commitments/{cid}/transition", expect=(4,), json={"target": "withdrawn"})
    await f.call("POST", f"{base}/commitments/{cid}/transition", expect=(4,), json={"target": "breached"})

    # Agreeing is a mandate decision: the decider confirms it or the route starts; both are not a 5xx.
    agreed = await f.call(
        "POST", f"{base}/commitments/{cid}/transition", expect=(200, 403, 409, 422), json={"target": "agreed"}
    )
    if agreed.status_code != 200:
        print(f"[elf-qa] agreeing refused {agreed.status_code}: {agreed.text[:200]}")  # noqa: T201
        f.finish("stakeholders commitment lifecycle (refused at agreed)")
        return
    now = (await f.call("GET", f"{base}/commitments/{cid}")).json()
    if now.get("status") != "agreed":
        # An approval route was started: the state waits for the decider.
        print(f"[elf-qa] commitment is {now.get('status')} pending {now.get('pending_target')}")  # noqa: T201
        f.finish("stakeholders commitment lifecycle (pending approval)")
        return
    for step in ("in_progress", "fulfilled"):
        t = await f.call("POST", f"{base}/commitments/{cid}/transition", json={"target": step})
        f.state(t, step, f"commitment after {step}")
    # The owner does not verify their own commitment; the loop must be closed.
    await f.call("POST", f"{base}/commitments/{cid}/transition", expect=(4,), json={"target": "verified"})
    closed = {"target": "verified", "loop_not_required_rationale": "Internal matter, nobody to inform"}
    await f.call("POST", f"{base}/commitments/{cid}/transition", expect=(4,), json=closed)
    done = await f.call("POST", f"{base}/commitments/{cid}/transition", who="manager2", expect=(200, 403), json=closed)
    if done.status_code == 200:
        f.state(done, "verified", "commitment verified by the second user")
        await f.call("POST", f"{base}/commitments/{cid}/transition", expect=(4,), json={"target": "in_progress"})
    f.finish("stakeholders commitment lifecycle")
