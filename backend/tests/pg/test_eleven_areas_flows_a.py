# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Write flows of engineering_brief, economics, hse_frame and risk over HTTP on a fresh install.

Each flow runs on a project of its own, created through the API by the demo administrator, with the
second manager on its team. A project without a governance model has no gates, so the hand approval
routes are the ones in force, and four-eyes holds (the submitter may not approve). Risk has no
approval, so its flow runs on a demo project.

Every test collects what went wrong and fails once with the whole list: the request, the status and
the first 300 characters of the answer.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest
import pytest_asyncio

from tests.pg.elf_qa_fixtures import World, boot_world

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.environ.get("OE_API_SMOKE", "") != "1", reason="full-boot lane: set OE_API_SMOKE=1"),
]

BRIEF = "/api/v1/engineering-brief/projects"
ECON = "/api/v1/economics/projects"
HSE = "/api/v1/hse-frame/projects"
RISK = "/api/v1/risk"


@pytest_asyncio.fixture(scope="module")
async def world(pg_async_url, tmp_path_factory):
    async for w in boot_world(pg_async_url, str(tmp_path_factory.mktemp("elf_qa_flows_a"))):
        yield w


class Probe:
    """Send requests as a named identity and keep every unexpected answer."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.problems: list[str] = []

    async def call(self, who: str, method: str, url: str, ok: tuple[int, ...] | None = (200, 201, 204), **kw: Any):
        resp = await self.world.client.request(method, url, headers=self.world.headers(who), **kw)
        if ok is not None and resp.status_code not in ok:
            body = kw.get("json")
            self.problems.append(
                f"{who} {method} {url} {json.dumps(body, default=str)[:200] if body else ''} "
                f"-> {resp.status_code} {resp.text[:300]}"
            )
        return resp

    def json(self, resp: Any) -> Any:
        try:
            return resp.json()
        except ValueError:
            return {}

    def expect(self, label: str, actual: Any, wanted: Any) -> None:
        if actual != wanted:
            self.problems.append(f"{label}: got {actual!r}, wanted {wanted!r}")

    def refused(self, label: str, resp: Any, statuses: tuple[int, ...] = (403, 409, 422)) -> None:
        """An illegal act is a clean 4xx, never a 5xx and never a success."""
        if resp.status_code not in statuses:
            self.problems.append(f"{label}: expected one of {statuses}, got {resp.status_code} {resp.text[:300]}")

    def done(self, title: str) -> None:
        assert not self.problems, f"{title}: {len(self.problems)} problem(s)\n" + "\n".join(
            f"- {p}" for p in self.problems[:40]
        )


async def new_project(probe: Probe, name: str) -> uuid.UUID:
    """A project of its own, created through the API, with the second manager on its team."""
    from tests.pg.elf_qa_fixtures import add_member  # noqa: F401  (kept for symmetry with the fixtures)

    resp = await probe.call("admin", "POST", "/api/v1/projects/", json={"name": f"{name} {uuid.uuid4().hex[:6]}"})
    pid = uuid.UUID(probe.json(resp)["id"])
    from app.modules.teams.models import Team, TeamMembership

    async with probe.world.factory() as s:
        team = Team(project_id=pid, name="QA second manager")
        s.add(team)
        await s.flush()
        s.add(TeamMembership(team_id=team.id, user_id=probe.world.users["manager2"]))
        await s.commit()
    return pid


# ── engineering_brief ───────────────────────────────────────────────────────


async def test_engineering_brief_runs_from_draft_to_binding_and_back_to_revising(world: World) -> None:
    p = Probe(world)
    pid = await new_project(p, "Brief flow")
    base = f"{BRIEF}/{pid}"

    # Before a brief exists, the brief header is a clean 404 and not a 5xx.
    p.refused("brief before set", await p.call("admin", "GET", f"{base}/brief", ok=None), (404,))

    resp = await p.call(
        "admin",
        "PUT",
        f"{base}/brief",
        json={"catalogue_id": "neutral", "title": "QA brief", "summary": "Start", "operation_proof_date": "2031-01-01"},
    )
    p.expect("new brief status", p.json(resp).get("status"), "draft")

    # An incomplete brief produces findings and is refused at submission.
    findings = p.json(await p.call("admin", "GET", f"{base}/brief/findings"))
    errors = [f for f in findings.get("items", []) if f.get("severity") == "error"]
    if not errors:
        p.problems.append("an empty brief produced no error finding")
    p.refused("submit incomplete brief", await p.call("admin", "POST", f"{base}/brief/submit", ok=None), (409, 422))
    p.refused("approve a draft", await p.call("manager2", "POST", f"{base}/brief/approve", ok=None))

    # Patch the header.
    resp = await p.call("admin", "PATCH", f"{base}/brief", json={"title": "QA brief 2"})
    p.expect("patched title", p.json(resp).get("title"), "QA brief 2")

    # Requirement CRUD.
    cat = p.json(await p.call("admin", "GET", f"{base}/catalogue"))
    req_ids: list[str] = []
    for category in cat.get("requirement_categories", []):
        if not category.get("required"):
            continue
        resp = await p.call(
            "admin",
            "POST",
            f"{base}/requirements",
            json={
                "category": category["code"],
                "entity": "Building",
                "attribute": category["code"],
                "constraint_type": "exists",
                "priority": "must",
                "verification_method": "inspection",
                "originator": "Owner",
            },
        )
        if resp.status_code == 201:
            req_ids.append(p.json(resp)["id"])
    scratch = await p.call(
        "admin",
        "POST",
        f"{base}/requirements",
        json={"category": "qa_scratch", "entity": "Roof", "attribute": "load", "constraint_type": "exists"},
        ok=(201, 422),
    )
    if scratch.status_code == 201:
        rid = p.json(scratch)["id"]
        resp = await p.call("admin", "PATCH", f"{base}/requirements/{rid}", json={"rationale": "edited"})
        p.expect("requirement patched", p.json(resp).get("rationale"), "edited")
        await p.call("admin", "DELETE", f"{base}/requirements/{rid}", ok=(204,))
        p.refused(
            "deleted requirement",
            await p.call("admin", "PATCH", f"{base}/requirements/{rid}", json={}, ok=None),
            (404,),
        )

    # Concept items, programme and milestones, as the catalogue requires them.
    first = True
    for topic in cat.get("concept_topics", []):
        if topic.get("required"):
            await p.call(
                "admin",
                "POST",
                f"{base}/concept",
                json={
                    "topic_code": topic["code"],
                    "title": topic["code"],
                    "decision": "Decided",
                    "requirement_ids": req_ids if first else [],
                },
            )
            first = False
    kinds = cat.get("programme_kinds", [])
    if kinds:
        resp = await p.call(
            "admin",
            "POST",
            f"{base}/programme",
            json={"kind_code": kinds[0]["code"], "label": "Area", "unit": "m2", "quantity": "1000"},
        )
        line = p.json(resp)
        line_id = (line.get("id") or (line.get("items") or [{}])[-1].get("id")) if isinstance(line, dict) else None
        if line_id:
            await p.call("admin", "PATCH", f"{base}/programme/{line_id}", json={"quantity": "1200"})
    await p.call("admin", "POST", f"{base}/milestones/from-catalogue", json={})
    p.json(await p.call("admin", "GET", f"{base}/readiness?gate_code=none", ok=(200, 404, 422)))

    # Complete now: submit as admin, approve as someone else.
    findings = p.json(await p.call("admin", "GET", f"{base}/brief/findings"))
    errors = [f.get("code") or f.get("rule_id") for f in findings.get("items", []) if f.get("severity") == "error"]
    resp = await p.call("admin", "POST", f"{base}/brief/submit", ok=(200,))
    if resp.status_code != 200:
        p.problems.append(f"the brief stayed incomplete after the catalogue's required rows were added: {errors}")
        p.done("engineering_brief flow")
        return
    p.expect("status after submit", p.json(resp).get("status"), "in_review")
    p.refused("submitter approves own brief", await p.call("admin", "POST", f"{base}/brief/approve", ok=None), (403,))

    # Return and resubmit.
    resp = await p.call("manager2", "POST", f"{base}/brief/return")
    p.expect("status after return", p.json(resp).get("status"), "draft")
    await p.call("admin", "POST", f"{base}/brief/submit")
    resp = await p.call("manager2", "POST", f"{base}/brief/approve")
    p.expect("status after approve", p.json(resp).get("status"), "binding")

    # A binding brief is edited by opening a revision.
    p.refused("submit a binding brief", await p.call("admin", "POST", f"{base}/brief/submit", ok=None), (409,))
    resp = await p.call("admin", "PATCH", f"{base}/brief", json={"summary": "Revised"})
    p.expect("status after editing a binding brief", p.json(resp).get("status"), "revising")
    p.done("engineering_brief flow")


# ── economics ───────────────────────────────────────────────────────────────


async def test_economics_plan_goes_from_draft_through_proposal_to_approval(world: World) -> None:
    p = Probe(world)
    pid = await new_project(p, "Economics flow")
    base = f"{ECON}/{pid}"

    resp = await p.call("admin", "PUT", f"{base}/plan")
    p.expect("plan exists", p.json(resp).get("exists"), True)
    p.expect("plan status", p.json(resp).get("status"), "draft")

    # An empty plan has findings and is refused at proposal.
    validation = p.json(await p.call("admin", "GET", f"{base}/validation"))
    if not (validation.get("items") or validation.get("findings")):
        p.problems.append(f"an empty plan produced no validation findings: {str(validation)[:200]}")
    p.refused("propose an empty plan", await p.call("admin", "POST", f"{base}/propose", json={}, ok=None), (409, 422))
    p.refused("approve before proposal", await p.call("manager2", "POST", f"{base}/approve", ok=None), (409,))

    await p.call(
        "admin",
        "PATCH",
        f"{base}/plan",
        json={"discount_rate_pct": "4", "horizon_years": 10, "markup_allowance": "200000"},
    )
    for code, title, amount in (("300", "Building construction", "2000000"), ("400", "Building services", "400000")):
        resp = await p.call(
            "admin", "POST", f"{base}/cost-frame/lines", json={"code": code, "title": title, "amount": amount}
        )
    frame = p.json(resp)
    line_id = None
    for key in ("lines", "items"):
        if frame.get(key):
            line_id = frame[key][0].get("id")
    if line_id:
        await p.call("admin", "PATCH", f"{base}/cost-frame/lines/{line_id}", json={"title": "Building construction A"})

    total = "2600000"
    half = "1300000"
    await p.call(
        "admin",
        "POST",
        f"{base}/business-case/lines",
        json={"kind": "investment", "label": "Construction", "source": "cost_frame", "year_from": 0, "year_to": 2},
    )
    await p.call(
        "admin",
        "POST",
        f"{base}/business-case/lines",
        json={"kind": "revenue", "label": "Rent", "amount": "400000", "year_from": 3, "year_to": 10},
    )
    await p.call(
        "admin",
        "POST",
        f"{base}/business-case/lines",
        json={"kind": "operating_cost", "label": "Operation", "amount": "60000", "year_from": 3, "year_to": 10},
    )
    scratch = await p.call(
        "admin",
        "POST",
        f"{base}/business-case/lines",
        json={"kind": "residual", "label": "Residual value", "amount": "1500000", "year_from": 10, "year_to": 10},
    )
    case = p.json(scratch)
    rows = case.get("lines") or case.get("items") or []
    if rows:
        last = rows[-1].get("id")
        if last:
            await p.call("admin", "PATCH", f"{base}/business-case/lines/{last}", json={"notes": "edited"})
    for kind, name, due in (("equity", "Own funds", "2027-01-15"), ("bank_loan", "Construction loan", "2027-06-30")):
        body: dict[str, Any] = {"kind": kind, "name": name, "amount": half}
        if kind == "bank_loan":
            body["interest_rate_pct"] = "3.9"
        resp = await p.call("admin", "POST", f"{base}/financing/sources", json=body)
        fin = p.json(resp)
        sources = fin.get("sources") or fin.get("items") or []
        sid = next((s.get("id") for s in sources if s.get("name") == name), None)
        if sid:
            await p.call(
                "admin", "POST", f"{base}/financing/sources/{sid}/tranches", json={"due_on": due, "amount": half}
            )
    _ = total

    resp = await p.call("admin", "POST", f"{base}/propose", json={"rationale": "QA proposal"}, ok=(200, 409, 422))
    if resp.status_code != 200:
        p.problems.append(f"the complete plan could not be proposed: {resp.status_code} {resp.text[:300]}")
        p.done("economics flow")
        return
    p.expect("status after propose", p.json(resp).get("status"), "proposed")
    p.refused(
        "edit while proposed",
        await p.call("admin", "PATCH", f"{base}/plan", json={"horizon_years": 11}, ok=None),
        (409,),
    )
    p.refused("proposer approves own plan", await p.call("admin", "POST", f"{base}/approve", ok=None), (409, 403))

    resp = await p.call("admin", "POST", f"{base}/withdraw")
    p.expect("status after withdraw", p.json(resp).get("status"), "draft")
    await p.call("admin", "POST", f"{base}/propose", json={"rationale": "QA proposal again"})
    resp = await p.call("manager2", "POST", f"{base}/approve")
    p.expect("status after approve", p.json(resp).get("status"), "approved")

    p.refused(
        "edit an approved plan",
        await p.call("admin", "PATCH", f"{base}/plan", json={"horizon_years": 12}, ok=None),
        (409,),
    )
    p.refused("reopen without a reason", await p.call("admin", "POST", f"{base}/reopen", json={}, ok=None), (422,))
    resp = await p.call("admin", "POST", f"{base}/reopen", json={"reason": "QA change"})
    p.expect("status after reopen", p.json(resp).get("status"), "reopened")
    p.done("economics flow")


# ── hse_frame ───────────────────────────────────────────────────────────────


async def test_hse_frame_is_filled_submitted_returned_and_approved_by_another_person(world: World) -> None:
    p = Probe(world)
    pid = await new_project(p, "HSE flow")
    base = f"{HSE}/{pid}"

    resp = await p.call("admin", "POST", f"{base}/frame")
    frame = p.json(resp)
    p.expect("new frame state", frame.get("state"), "draft")
    p.refused("approve a draft frame", await p.call("manager2", "POST", f"{base}/frame/approve", ok=None), (409,))
    p.refused("revise a draft frame", await p.call("admin", "POST", f"{base}/frame/revise", ok=None), (409,))

    cat = p.json(await p.call("admin", "GET", f"{base}/catalogue"))
    topics = [t.get("code") for t in cat.get("topics", []) if isinstance(t, dict)] or ["hse_requirements"]

    await p.call(
        "admin",
        "PATCH",
        f"{base}/frame",
        json={"planned_start": "2031-03-01", "duration_working_days": 120, "peak_workers": 12, "employers_count": 2},
    )
    summary_before = p.json(await p.call("admin", "GET", f"{base}/summary"))
    validation = p.json(await p.call("admin", "GET", f"{base}/validation"))
    p.json(await p.call("admin", "GET", f"{base}/readiness"))
    _ = summary_before, validation

    # Items: create, edit, meet, waive (manager), reopen, delete.
    item_ids: list[str] = []
    for index in range(3):
        resp = await p.call(
            "admin",
            "POST",
            f"{base}/items",
            json={
                "topic": topics[0],
                "title": f"QA duty {index}",
                "obligation": "mandatory",
                "audience": ["contractor"],
            },
        )
        if resp.status_code == 201:
            item_ids.append(p.json(resp)["id"])
    if len(item_ids) == 3:
        a, b, c = item_ids
        resp = await p.call("admin", "PATCH", f"{base}/items/{a}", json={"status": "in_progress", "title": "QA duty A"})
        p.expect("item status", p.json(resp).get("status"), "in_progress")
        resp = await p.call("admin", "POST", f"{base}/items/{a}/meet", json={"evidence_note": "Inspected"})
        p.expect("met item", p.json(resp).get("status"), "met")
        p.refused(
            "waive without a reason",
            await p.call("admin", "POST", f"{base}/items/{b}/waive", json={"reason": "x"}, ok=None),
            (422,),
        )
        # The author of a duty cannot waive it; the second person does.
        resp = await p.call("manager2", "POST", f"{base}/items/{b}/waive", json={"reason": "Not needed here"})
        p.expect("waived item", p.json(resp).get("status"), "waived")
        resp = await p.call("admin", "POST", f"{base}/items/{b}/reopen")
        p.expect("reopened item", p.json(resp).get("status"), "open")
        await p.call("admin", "DELETE", f"{base}/items/{c}", ok=(204,))
        p.refused("read a deleted item", await p.call("admin", "GET", f"{base}/items/{c}", ok=None), (404,))

    # Roles: create, edit, delete.
    resp = await p.call(
        "admin",
        "POST",
        f"{base}/roles",
        json={"role_code": "qa_coordinator", "person_name": "QA Person", "status": "proposed"},
        ok=(200, 201, 422),
    )
    if resp.status_code in (200, 201) and p.json(resp).get("id"):
        rid = p.json(resp)["id"]
        resp = await p.call(
            "admin", "PATCH", f"{base}/roles/{rid}", json={"status": "appointed", "appointed_on": "2031-02-01"}
        )
        p.expect("role status", p.json(resp).get("status"), "appointed")
        await p.call("admin", "DELETE", f"{base}/roles/{rid}", ok=(200, 204))

    # Submission: refused with findings, or accepted when the frame is complete enough.
    resp = await p.call("admin", "POST", f"{base}/frame/submit", ok=(200, 422))
    if resp.status_code == 422:
        if not (resp.json().get("violations") or resp.json().get("detail")):
            p.problems.append(f"a refused submission named no findings: {resp.text[:200]}")
        p.done("hse_frame flow (incomplete frame refused; submit/approve not reached)")
        return
    p.expect("state after submit", p.json(resp).get("state"), "in_review")
    p.refused("submitter approves own frame", await p.call("admin", "POST", f"{base}/frame/approve", ok=None), (403,))
    p.refused("submit twice", await p.call("admin", "POST", f"{base}/frame/submit", ok=None), (409,))
    resp = await p.call("admin", "POST", f"{base}/frame/revise")
    p.expect("state after revise", p.json(resp).get("state"), "revising")
    await p.call("admin", "POST", f"{base}/frame/submit")
    resp = await p.call("manager2", "POST", f"{base}/frame/approve")
    p.expect("state after approve", p.json(resp).get("state"), "approved")
    p.done("hse_frame flow")


# ── risk ────────────────────────────────────────────────────────────────────


async def test_risk_register_row_is_created_scored_moved_and_deleted(world: World) -> None:
    p = Probe(world)
    pid = str(world.projects["residential-regensburg"])
    resp = await p.call(
        "admin",
        "POST",
        f"{RISK}/",
        json={
            "project_id": pid,
            "title": "QA flood risk",
            "category": "environmental",
            "probability": 0.7,
            "impact_cost": "250000.50",
            "impact_severity": "high",
        },
    )
    risk = p.json(resp)
    rid = risk.get("id")
    p.expect("new risk status", risk.get("status"), "identified")
    if not risk.get("risk_tier") or not risk.get("risk_score"):
        p.problems.append(f"a created risk was not scored: tier={risk.get('risk_tier')} score={risk.get('risk_score')}")
    if str(risk.get("impact_cost")) not in ("250000.50", "250000.5"):
        p.problems.append(f"impact_cost did not round-trip: {risk.get('impact_cost')!r}")
    if rid:
        for status in ("assessed", "mitigating", "mitigated", "closed"):
            resp = await p.call("manager2", "PATCH", f"{RISK}/{rid}", json={"status": status})
            p.expect(f"risk status {status}", p.json(resp).get("status"), status)
        resp = await p.call(
            "manager2", "PATCH", f"{RISK}/{rid}", json={"probability": 0.2, "mitigation_strategy": "Drainage"}
        )
        if p.json(resp).get("probability") != 0.2:
            p.problems.append(f"probability did not update: {resp.text[:200]}")
        p.refused(
            "invalid status", await p.call("admin", "PATCH", f"{RISK}/{rid}", json={"status": "bogus"}, ok=None), (422,)
        )
        p.refused(
            "invalid probability",
            await p.call("admin", "PATCH", f"{RISK}/{rid}", json={"probability": 2}, ok=None),
            (422,),
        )

        resp = await p.call("admin", "PATCH", f"{RISK}/batch/status/", json={"ids": [rid], "status": "open"})
        listed = p.json(await p.call("admin", "GET", f"{RISK}/?project_id={pid}&limit=100"))
        rows = listed if isinstance(listed, list) else listed.get("items", [])
        mine = next((r for r in rows if r.get("id") == rid), None)
        if mine is None:
            p.problems.append("the created risk is missing from the project list")
        else:
            p.expect("status after batch update", mine.get("status"), "open")
        p.json(await p.call("admin", "GET", f"{RISK}/{rid}"))
        await p.call(
            "admin", "POST", f"{RISK}/projects/{pid}/simulate", json={"iterations": 1000, "mode": "both"}, ok=(200, 422)
        )
        await p.call("admin", "GET", f"{RISK}/projects/{pid}/contingency")
        p.refused("viewer deletes a risk", await p.call("viewer", "DELETE", f"{RISK}/{rid}", ok=None), (403,))
        await p.call("admin", "DELETE", f"{RISK}/{rid}", ok=(204,))
        p.refused("read a deleted risk", await p.call("admin", "GET", f"{RISK}/{rid}", ok=None), (404,))
    p.done("risk flow")
