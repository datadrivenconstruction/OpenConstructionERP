# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Write flows over HTTP on a fresh install: procurement concept, quality concept, commitment release, governance.

Each flow runs on a project created for it (owned by the demo administrator, with the second manager and the
viewer on its team) rather than on a seeded demo project, so a flow starts from a draft whatever the pack
demo left behind. The identities come from ``elf_qa_fixtures``: ``admin`` creates and submits, ``manager2``
approves or decides, ``viewer`` is refused.

A flow collects every unexpected answer (method, url, body, status, response excerpt) and fails once at the end.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.pg.elf_qa_fixtures import World, boot_world

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.environ.get("OE_API_SMOKE", "") != "1", reason="full-boot lane: set OE_API_SMOKE=1"),
]

PC = "/api/v1/procurement-concept"
QC = "/api/v1/quality-concept"
CR = "/api/v1/commitment-release"
PG = "/api/v1/project-governance"


@pytest_asyncio.fixture(scope="module")
async def world(pg_async_url, tmp_path_factory):
    async for w in boot_world(pg_async_url, str(tmp_path_factory.mktemp("elf_qa_flows_c"))):
        yield w


class Flow:
    """One flow's calls, and the problems found along the way."""

    def __init__(self, world: World, name: str) -> None:
        self.world = world
        self.name = name
        self.problems: list[str] = []

    async def call(self, who: str, method: str, url: str, body: Any = None, **kw: Any):
        resp = await self.world.client.request(
            method, url, json=body if body is not None else None, headers=self.world.headers(who), **kw
        )
        resp.flow_label = f"{who} {method} {url.split('/api/v1')[-1]} {body if body is not None else ''}"[:260]
        return resp

    def expect(self, resp: Any, statuses: tuple[int, ...], note: str = "") -> bool:
        if resp.status_code in statuses:
            return True
        self.problems.append(
            f"[{self.name}] {note} {resp.flow_label} -> {resp.status_code} (wanted {statuses}): {resp.text[:300]}"
        )
        return False

    def refused(self, resp: Any, note: str = "") -> None:
        """An illegal move is a 4xx, never a 2xx and never a 5xx."""
        if not (400 <= resp.status_code < 500):
            self.problems.append(f"[{self.name}] {note} {resp.flow_label} -> {resp.status_code}, wanted a 4xx refusal")

    def check(self, value: Any, wanted: Any, note: str) -> None:
        if value != wanted:
            self.problems.append(f"[{self.name}] {note}: got {value!r}, wanted {wanted!r}")

    def done(self) -> None:
        assert not self.problems, f"{self.name}: {len(self.problems)} problem(s)\n" + "\n".join(
            f"- {p}" for p in self.problems
        )


async def fresh_project(world: World) -> uuid.UUID:
    """A project owned by the demo administrator, with the second manager and the viewer on its team."""
    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership
    from app.modules.users.models import User

    pid = uuid.uuid4()
    async with world.factory() as s:
        owner = (await s.execute(select(User.id).where(User.email == "demo@openconstructionerp.com"))).scalar_one()
        s.add(
            Project(
                id=pid,
                name=f"QA flow {pid.hex[:6]}",
                currency="EUR",
                status="active",
                owner_id=owner,
                metadata_={},
                fx_rates=[{"code": "GBP", "rate": "1.20"}],
            )
        )
        await s.flush()
        team = Team(project_id=pid, name="QA flow team")
        s.add(team)
        await s.flush()
        for who in ("manager2", "viewer"):
            s.add(TeamMembership(team_id=team.id, user_id=world.users[who]))
        await s.commit()
    return pid


async def admin_id(world: World) -> uuid.UUID:
    from app.modules.users.models import User

    async with world.factory() as s:
        return (await s.execute(select(User.id).where(User.email == "demo@openconstructionerp.com"))).scalar_one()


def _items(resp: Any) -> list[dict[str, Any]]:
    try:
        body = resp.json()
    except ValueError:
        return []
    return body.get("items", []) if isinstance(body, dict) else body if isinstance(body, list) else []


# ── procurement concept ─────────────────────────────────────────────────────


async def test_procurement_concept_plan_and_packages(world: World) -> None:
    from sqlalchemy import insert

    from app.modules.procurement_concept import plan_source as plan

    f = Flow(world, "procurement packages")
    pid = await fresh_project(world)
    pkg = uuid.uuid4()
    async with world.factory() as s:
        await s.execute(
            insert(plan.PACKAGE_TABLE).values(
                id=pkg,
                project_id=pid,
                code="W1",
                title="W1 package",
                kind="construction",
                parent_id=None,
                scope="Scope of W1",
                wbs_ref="",
                boq_ref="",
                need_date=None,
                status="planned",
                sort_order=0,
            )
        )
        await s.commit()
    base = f"{PC}/projects/{pid}"

    r = await f.call("admin", "PUT", f"{base}/concept", {"vat_rate_pct": "19"})
    f.expect(r, (200,), "create concept")
    f.check(r.json().get("state") if r.status_code == 200 else None, "draft", "new concept state")

    # Validation produces findings for a concept with no estimated value on its package.
    r = await f.call("admin", "GET", f"{base}/findings")
    if f.expect(r, (200,), "findings"):
        f.check(bool(_items(r)), True, "an incomplete concept has findings")

    works = {"estimated_value": "900000", "currency": "EUR", "procedure_code": "open"}
    r = await f.call("admin", "PUT", f"{base}/packages/{pkg}", works)
    f.expect(r, (200,), "set package procedure")
    f.check(r.json().get("state") if r.status_code == 200 else None, "procedure_set", "package state after procedure")

    # Hold, an illegal second hold, resume back to where it was, then cancel and an illegal resume.
    r = await f.call("admin", "POST", f"{base}/packages/{pkg}/state", {"action": "hold", "reason": "QA"})
    f.expect(r, (200,), "hold")
    f.check(r.json().get("state") if r.status_code == 200 else None, "on_hold", "state after hold")
    f.refused(await f.call("admin", "POST", f"{base}/packages/{pkg}/state", {"action": "hold"}), "hold twice")
    r = await f.call("admin", "POST", f"{base}/packages/{pkg}/state", {"action": "resume"})
    f.expect(r, (200,), "resume")
    f.check(r.json().get("state") if r.status_code == 200 else None, "procedure_set", "state after resume")
    r = await f.call("admin", "POST", f"{base}/packages/{pkg}/state", {"action": "cancel", "reason": "QA"})
    f.expect(r, (200,), "cancel")
    f.check(r.json().get("state") if r.status_code == 200 else None, "cancelled", "state after cancel")
    f.refused(await f.call("admin", "POST", f"{base}/packages/{pkg}/state", {"action": "resume"}), "resume cancelled")

    # In-tender and awarded are read back from execution, never set by hand.
    f.refused(await f.call("admin", "POST", f"{base}/packages/{pkg}/state", {"action": "awarded"}), "set awarded")
    f.refused(await f.call("viewer", "PUT", f"{base}/packages/{pkg}", works), "viewer edits package")

    r = await f.call("admin", "GET", f"{base}/packages")
    if f.expect(r, (200,), "list packages"):
        row = next((i for i in _items(r) if i.get("contract_package", {}).get("code") == "W1"), None)
        f.check(row is not None and (row.get("award") or {}).get("state"), "cancelled", "listed package state")
    f.expect(await f.call("admin", "GET", f"{base}/validation"), (200,), "validation")
    f.done()


async def test_procurement_concept_submit_approve_return(world: World) -> None:
    f = Flow(world, "procurement concept")
    pid = await fresh_project(world)
    base = f"{PC}/projects/{pid}"
    f.expect(await f.call("admin", "PUT", f"{base}/concept", {"vat_rate_pct": "19"}), (200,), "create")
    r = await f.call("admin", "POST", f"{base}/concept/submit")
    ok = f.expect(r, (200,), "submit")
    if ok:
        f.check(r.json().get("state"), "in_review", "state after submit")
        f.refused(await f.call("admin", "POST", f"{base}/concept/submit"), "submit twice")
        # Approval states are never a target of a call.
        f.refused(await f.call("admin", "POST", f"{base}/concept/binding"), "set binding by name")
        r = await f.call("admin", "POST", f"{base}/concept/return")
        f.expect(r, (200,), "return")
        f.check(r.json().get("state") if r.status_code == 200 else None, "draft", "state after return")
        f.refused(await f.call("admin", "POST", f"{base}/concept/return"), "return a draft")
        f.expect(await f.call("admin", "POST", f"{base}/concept/submit"), (200,), "resubmit")
        # A project without gates: approval by hand. The submitter does not approve under four eyes.
        mine = await f.call("admin", "POST", f"{base}/concept/approve")
        if mine.status_code == 200:
            f.problems.append("[procurement concept] the submitter approved their own concept (four eyes not enforced)")
        else:
            f.refused(mine, "submitter approves")
        r = await f.call("manager2", "POST", f"{base}/concept/approve")
        # A blocking finding may legitimately stop the approval; a 5xx never.
        f.expect(r, (200, 409, 422), "second manager approves")
        if r.status_code == 200:
            f.check(r.json().get("state") in ("approved", "binding"), True, "state after hand approval")
            f.refused(await f.call("admin", "POST", f"{base}/concept/return"), "return an approved concept")
            reopened = await f.call("manager2", "POST", f"{base}/concept/reopen", {"reason": "QA reopen"})
            f.expect(reopened, (200, 409), "reopen")
    v = await f.call("viewer", "POST", f"{base}/concept/submit")
    f.check(v.status_code, 403, "viewer submit status")
    f.expect(await f.call("admin", "GET", f"{base}/readiness"), (200,), "readiness")
    f.done()


async def test_procurement_soundings_profiles_and_frameworks(world: World) -> None:
    f = Flow(world, "procurement registers")
    pid = await fresh_project(world)
    base = f"{PC}/projects/{pid}"
    f.expect(await f.call("admin", "PUT", f"{base}/concept", {"vat_rate_pct": "19"}), (200,), "create concept")

    r = await f.call("admin", "POST", f"{base}/market-soundings", {"trade": "Concrete", "held_on": "2026-09-01"})
    if f.expect(r, (201,), "create sounding"):
        sid = r.json()["id"]
        r = await f.call("admin", "PATCH", f"{base}/market-soundings/{sid}", {"capacity_signal": "tight"})
        f.expect(r, (200,), "patch sounding")
        f.check(r.json().get("capacity_signal") if r.status_code == 200 else None, "tight", "signal after patch")
        f.check(r.json().get("unmitigated") if r.status_code == 200 else None, True, "tight without mitigation")
        f.refused(await f.call("viewer", "DELETE", f"{base}/market-soundings/{sid}"), "viewer deletes sounding")
        f.expect(await f.call("admin", "DELETE", f"{base}/market-soundings/{sid}"), (204,), "delete sounding")
        f.refused(await f.call("admin", "PATCH", f"{base}/market-soundings/{sid}", {"trade": "x"}), "patch deleted")

    profile = {"name": "Works", "criteria": [{"code": "similar_projects", "weight": "100"}], "pass_mark": "50"}
    r = await f.call("admin", "POST", f"{base}/prequal-profiles", profile)
    if f.expect(r, (201,), "create profile"):
        prid = r.json()["id"]
        f.expect(
            await f.call("admin", "PUT", f"{base}/prequal-profiles/{prid}", {**profile, "pass_mark": "60"}),
            (200,),
            "update profile",
        )
        f.refused(
            await f.call("admin", "POST", f"{base}/prequal-profiles", {**profile, "pass_mark": "150"}),
            "pass mark over 100",
        )
        f.expect(await f.call("admin", "DELETE", f"{base}/prequal-profiles/{prid}"), (204,), "delete profile")

    fw = {
        "code": f"FW-{uuid.uuid4().hex[:5]}",
        "title": "Rebar",
        "package_kinds": ["supply"],
        "lots": [],
        "max_value": "500000",
        "currency": "EUR",
        "start_date": "2026-01-01",
        "end_date": "2028-12-31",
    }
    f.refused(await f.call("viewer", "POST", f"{PC}/frameworks", fw), "viewer creates framework")
    r = await f.call("admin", "POST", f"{PC}/frameworks", fw)
    if f.expect(r, (201,), "create framework"):
        fid = r.json()["id"]
        f.check(r.json().get("state"), "draft", "new framework state")
        f.refused(
            await f.call("admin", "POST", f"{PC}/frameworks/{fid}/state", {"target": "expired"}), "draft to expired"
        )
        r = await f.call("admin", "POST", f"{PC}/frameworks/{fid}/state", {"target": "active"})
        f.expect(r, (200,), "activate framework")
        f.check(r.json().get("state") if r.status_code == 200 else None, "active", "state after activate")
        f.expect(await f.call("admin", "PATCH", f"{PC}/frameworks/{fid}", {"title": "Rebar 2"}), (200,), "patch")
        r = await f.call("admin", "POST", f"{PC}/frameworks/{fid}/state", {"target": "terminated"})
        f.expect(r, (200,), "terminate framework")
        f.refused(
            await f.call("admin", "POST", f"{PC}/frameworks/{fid}/state", {"target": "active"}), "reactivate terminated"
        )
        f.expect(await f.call("admin", "GET", f"{PC}/frameworks/{fid}/ledger"), (200,), "ledger")
    f.refused(await f.call("admin", "POST", f"{PC}/frameworks", {**fw, "code": "FW-X", "currency": ""}), "no currency")
    f.done()


# ── quality concept ─────────────────────────────────────────────────────────


async def test_quality_concept_lifecycle(world: World) -> None:
    f = Flow(world, "quality concept")
    pid = await fresh_project(world)
    base = f"{QC}/projects/{pid}"

    v = await f.call("viewer", "POST", f"{base}/concept")
    f.check(v.status_code, 403, "viewer create concept status")

    r = await f.call("admin", "POST", f"{base}/concept")
    f.expect(r, (201,), "create concept")
    f.check(r.json().get("state") if r.status_code == 201 else None, "draft", "new concept state")
    f.refused(await f.call("admin", "POST", f"{base}/concept"), "second concept")

    r = await f.call(
        "admin",
        "PATCH",
        f"{base}/concept",
        {"packages": [{"ref": "P-01", "title": "Structure"}, {"ref": "P-02", "title": "Services"}]},
    )
    f.expect(r, (200,), "patch packages")
    r = await f.call("admin", "POST", f"{base}/standards", {"code": "EN 206", "package_refs": ["P-01"]})
    if f.expect(r, (201,), "create standard"):
        sid = r.json()["id"]
        f.expect(await f.call("admin", "PATCH", f"{base}/standards/{sid}", {"title": "Concrete"}), (200,), "patch std")
        r = await f.call("admin", "GET", f"{base}/standards")
        f.check(any(i.get("code") == "EN 206" for i in _items(r)), True, "standard listed")
        f.expect(await f.call("admin", "DELETE", f"{base}/standards/{sid}"), (204,), "delete standard")

    # The validation endpoint produces findings for a plan nobody finished.
    r = await f.call("admin", "GET", f"{base}/validation")
    if f.expect(r, (200,), "validation"):
        f.check(bool(_items(r)), True, "an unfinished concept has findings")
    f.expect(await f.call("admin", "GET", f"{base}/readiness"), (200,), "readiness")

    f.refused(await f.call("admin", "POST", f"{base}/concept/approve"), "approve a draft")
    f.refused(await f.call("admin", "POST", f"{base}/concept/return"), "return a draft")
    r = await f.call("admin", "POST", f"{base}/concept/submit")
    if r.status_code == 200:
        f.check(r.json().get("state"), "in_review", "state after submit")
        mine = await f.call("admin", "POST", f"{base}/concept/approve")
        if mine.status_code == 200:
            f.problems.append("[quality concept] the submitter approved their own concept (four eyes not enforced)")
        r = await f.call("admin", "POST", f"{base}/concept/return") if mine.status_code != 200 else None
        if r is not None:
            f.expect(r, (200,), "return")
            f.expect(await f.call("admin", "POST", f"{base}/concept/submit"), (200,), "resubmit")
        r = await f.call("manager2", "POST", f"{base}/concept/approve")
        f.expect(r, (200,), "second manager approves")
        if r.status_code == 200:
            f.check(r.json().get("state"), "binding", "state after hand approval")
            f.expect(await f.call("manager2", "POST", f"{base}/concept/reopen", {"rationale": "QA"}), (200,), "reopen")
    else:
        # An incomplete plan may not be submitted; the refusal names what is missing.
        f.expect(r, (409, 422), "submit an unfinished concept")
        f.check("concept_incomplete" in r.text, True, "submit refusal names concept_incomplete")
    f.done()


# ── commitment release ──────────────────────────────────────────────────────


async def test_commitment_release_request_decide_reject_withdraw(world: World) -> None:
    f = Flow(world, "commitment release")
    pid = await fresh_project(world)
    admin = await admin_id(world)
    base = f"{CR}/projects/{pid}"

    f.expect(await f.call("admin", "PUT", f"{base}/matrix", {"schedule_id": "neutral"}), (200,), "pin schedule")
    r = await f.call(
        "admin",
        "PUT",
        f"{base}/assignments",
        {
            "assignments": [
                {"project_role": "owner_pm", "user_id": str(world.users["manager2"])},
                {"project_role": "owner_sponsor", "user_id": str(admin)},
                {"project_role": "owner_board_member", "user_id": str(world.users["viewer"])},
            ]
        },
    )
    f.expect(r, (200,), "assign tiers")

    def item_body(code: str, amount: str = "10000") -> dict[str, Any]:
        return {
            "code": code,
            "title": f"Item {code}",
            "commitment_type": "design",
            "planned_source": "manual",
            "planned_manual_amount": amount,
            "currency": "EUR",
        }

    def status_of(resp: Any) -> Any:
        body = resp.json() if resp.status_code < 300 else {}
        return body.get("status") or body.get("state") or (body.get("item") or {}).get("status")

    # Create, update, hold and resume.
    r = await f.call("admin", "POST", f"{base}/items", item_body("QA-1"))
    if not f.expect(r, (201,), "create item"):
        f.done()
    iid = r.json()["id"]
    f.check(status_of(r), "planned", "new item status")
    f.refused(await f.call("admin", "POST", f"{base}/items", item_body("QA-1")), "duplicate item code")
    f.refused(
        await f.call("admin", "POST", f"{base}/items", {**item_body("QA-X"), "commitment_type": "nope"}), "bad type"
    )
    f.expect(await f.call("admin", "PATCH", f"{base}/items/{iid}", {"title": "Renamed"}), (200,), "patch item")
    r = await f.call("admin", "POST", f"{base}/items/{iid}/hold", {"hold": True, "reason": "QA"})
    f.expect(r, (200,), "hold item")
    f.check(status_of(r), "on_hold", "status after hold")
    f.refused(await f.call("admin", "POST", f"{base}/items/{iid}/releases", {"amount": "10000"}), "release on hold")
    r = await f.call("admin", "POST", f"{base}/items/{iid}/hold", {"hold": False})
    f.expect(r, (200,), "resume item")
    f.check(status_of(r), "planned", "status after resume")

    # Request a release; the requester cannot decide it; the tier holder can.
    r = await f.call("admin", "POST", f"{base}/items/{iid}/releases", {"amount": "10000"})
    if f.expect(r, (201,), "request release"):
        f.check(status_of(await f.call("admin", "GET", f"{base}/items/{iid}")), "release_requested", "item status")
        f.refused(await f.call("admin", "POST", f"{base}/items/{iid}/releases", {"amount": "10000"}), "second request")
        own = await f.call("admin", "POST", f"{base}/items/{iid}/releases/decide", {"decision": "approved"})
        f.check(own.status_code, 403, "requester decides own release")
        outsider = await f.call("outsider", "POST", f"{base}/items/{iid}/releases/decide", {"decision": "approved"})
        f.check(outsider.status_code in (403, 404), True, "outsider decides")
        f.refused(
            await f.call("manager2", "POST", f"{base}/items/{iid}/releases/decide", {"decision": "rejected"}),
            "reject without a comment",
        )
        r = await f.call("manager2", "POST", f"{base}/items/{iid}/releases/decide", {"decision": "approved"})
        f.expect(r, (200,), "tier holder approves")
        item = await f.call("admin", "GET", f"{base}/items/{iid}")
        f.check(status_of(item) in ("released", "partially_released"), True, "item status after approval")
        f.refused(
            await f.call("manager2", "POST", f"{base}/items/{iid}/releases/decide", {"decision": "approved"}),
            "decide with nothing pending",
        )
        f.expect(await f.call("admin", "GET", f"{base}/items/{iid}/releases"), (200,), "release history")

    # Rejection returns the item to planned; a withdrawn request does too.
    r = await f.call("admin", "POST", f"{base}/items", item_body("QA-2"))
    if f.expect(r, (201,), "create second item"):
        iid2 = r.json()["id"]
        f.expect(await f.call("admin", "POST", f"{base}/items/{iid2}/releases", {"amount": "5000"}), (201,), "request")
        r = await f.call(
            "manager2", "POST", f"{base}/items/{iid2}/releases/decide", {"decision": "rejected", "comment": "Not yet"}
        )
        f.expect(r, (200,), "reject with comment")
        f.check(status_of(await f.call("admin", "GET", f"{base}/items/{iid2}")), "planned", "status after rejection")
        f.expect(await f.call("admin", "POST", f"{base}/items/{iid2}/releases", {"amount": "5000"}), (201,), "again")
        f.expect(
            await f.call("admin", "POST", f"{base}/items/{iid2}/releases/withdraw", {"reason": "QA"}),
            (200,),
            "withdraw",
        )
        f.check(status_of(await f.call("admin", "GET", f"{base}/items/{iid2}")), "planned", "status after withdraw")
        f.refused(await f.call("admin", "POST", f"{base}/items/{iid2}/releases/withdraw", {}), "withdraw nothing")

    f.refused(await f.call("viewer", "POST", f"{base}/items", item_body("QA-V")), "viewer creates item")
    r = await f.call("admin", "GET", f"{base}/validation")
    f.expect(r, (200,), "validation")
    f.expect(await f.call("admin", "GET", f"{base}/exposure"), (200,), "exposure")
    f.done()


# ── project governance ──────────────────────────────────────────────────────


async def test_governance_model_areas_and_gate_refusals(world: World) -> None:
    f = Flow(world, "project governance")
    pid = await fresh_project(world)
    base = f"{PG}/projects/{pid}"

    f.refused(await f.call("admin", "GET", f"{base}/model"), "model before it is chosen")
    v = await f.call("viewer", "PUT", f"{base}/model", {"catalogue_id": "neutral"})
    f.check(v.status_code, 403, "viewer sets model")
    f.refused(await f.call("admin", "PUT", f"{base}/model", {"catalogue_id": "no_such_model"}), "unknown model")
    r = await f.call("admin", "PUT", f"{base}/model", {"catalogue_source": "shipped", "catalogue_id": "neutral"})
    f.expect(r, (201,), "set model")
    f.check(r.json().get("catalogue_id") if r.status_code == 201 else None, "neutral", "pinned model")
    f.check(bool(r.json().get("four_eyes")) if r.status_code == 201 else None, True, "four eyes default")

    r = await f.call("admin", "GET", f"{base}/areas")
    areas = _items(r) if f.expect(r, (200,), "list areas") else []
    f.check(bool(areas), True, "the model brings areas")
    if areas:
        aid = areas[0]["id"]
        r = await f.call("admin", "PATCH", f"{base}/areas/{aid}", {"owner_user_id": str(world.users["manager2"])})
        f.expect(r, (200,), "name an area owner")
        f.check(r.json().get("owner_user_id") if r.status_code == 200 else None, str(world.users["manager2"]), "owner")
        f.refused(await f.call("admin", "PATCH", f"{base}/areas/{uuid.uuid4()}", {"applicable": False}), "unknown area")
        f.check(
            (await f.call("viewer", "PATCH", f"{base}/areas/{aid}", {"applicable": False})).status_code,
            403,
            "viewer edits area",
        )

    r = await f.call("admin", "GET", f"{base}/gates")
    gates = _items(r) if f.expect(r, (200,), "list gates") else []
    f.check(bool(gates), True, "the model brings gates")
    if gates:
        gid = gates[0]["id"]
        # A gate nobody prepared is neither submitted nor decided.
        f.refused(await f.call("admin", "POST", f"{base}/gates/{gid}/submit"), "submit an unprepared gate")
        f.refused(
            await f.call("manager2", "POST", f"{base}/gates/{gid}/decide", {"outcome": "go", "rationale": "QA"}),
            "decide a gate that is not in review",
        )
        f.refused(await f.call("manager2", "POST", f"{base}/gates/{gid}/reopen", {"rationale": "QA"}), "reopen")
        r = await f.call("admin", "POST", f"{base}/gates/{gid}/prepare")
        f.expect(r, (200, 409, 422), "prepare a gate")
        f.expect(await f.call("admin", "GET", f"{base}/gates/{gid}"), (200,), "gate detail")
        f.expect(await f.call("admin", "GET", f"{base}/gates/{gid}/decisions"), (200,), "decisions")
        v = await f.call("viewer", "POST", f"{base}/gates/{gid}/prepare")
        f.check(v.status_code, 403, "viewer prepares gate")

    r = await f.call("admin", "GET", f"{base}/validation")
    if f.expect(r, (200,), "validation"):
        f.check(bool(_items(r)), True, "a model with no owners and no documents has findings")
    f.expect(await f.call("admin", "GET", f"{base}/documents"), (200,), "documents")
    f.expect(await f.call("admin", "GET", f"{base}/matrix"), (200,), "matrix")
    f.done()
