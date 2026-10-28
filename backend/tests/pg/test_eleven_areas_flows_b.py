# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Write flows of delivery_model, design_management, permits and transmittals over HTTP.

Each test creates NEW rows on a demo project of the eleven-areas-framework install, drives
them through their lifecycle (create, update, transition, approve with a second user, return,
delete), reads every result back and records what it did not expect. A test fails once at the
end with the whole list: method, URL, body, status and the start of the answer.

Where a status is not a fixed fact of the state machine (a gate may own the decision, a
catalogue may not carry a code) the step is *soft*: anything below 500 passes and the step
only supplies ids for the steps after it.
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

DM = "/api/v1/delivery-model"
DES = "/api/v1/design-management"
PER = "/api/v1/permits"
TRA = "/api/v1/transmittals"
APR = "/api/v1/approval-routes"


@pytest_asyncio.fixture(scope="module")
async def world(pg_async_url, tmp_path_factory):
    async for w in boot_world(pg_async_url, str(tmp_path_factory.mktemp("elf_qa_flows_b"))):
        yield w


class Flow:
    """One flow: a project, a list of problems and a request helper that fills it."""

    def __init__(self, world: World, demo_id: str = "residential-regensburg") -> None:
        self.w = world
        self.pid = str(world.projects[demo_id])
        self.problems: list[str] = []

    async def go(
        self,
        who: str,
        method: str,
        url: str,
        body: Any = None,
        *,
        ok: tuple[int, ...] = (200,),
        soft: bool = False,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        resp = await self.w.client.request(method, url, json=body, params=params, headers=self.w.headers(who))
        try:
            data = resp.json() if resp.content else None
        except ValueError:
            data = None
        good = resp.status_code < 500 if soft else resp.status_code in ok
        if not good:
            self.problems.append(
                f"{method} {url.replace(self.pid, '{pid}')} as {who} body={json.dumps(body, default=str)[:200]} "
                f"-> {resp.status_code} (wanted {'<500' if soft else ok}): {resp.text[:300]}"
            )
        return resp.status_code, data

    def expect(self, label: str, actual: Any, wanted: Any) -> None:
        if actual != wanted:
            self.problems.append(f"{label}: got {actual!r}, wanted {wanted!r}")

    def done(self, title: str) -> None:
        assert not self.problems, f"{title}: {len(self.problems)} problem(s)\n" + "\n".join(
            f"- {p}" for p in self.problems[:60]
        )


def _rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("items", "results", "data"):
            if isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
    return []


def _tag() -> str:
    return uuid.uuid4().hex[:6].upper()


# ── delivery_model ──────────────────────────────────────────────────────────


@pytest.mark.timeout(900)
async def test_delivery_model_options_packages_ofi_and_decision(world: World) -> None:
    f = Flow(world)
    base = f"{DM}/projects/{f.pid}"

    # Options: add, patch, read back, delete.
    option_id = None
    for code in ("cm_at_risk", "design_build", "design_bid_build_single", "design_bid_build"):
        status, data = await f.go("admin", "POST", f"{base}/options", {"form_code": code}, ok=(201, 409, 422))
        if status == 201 and data:
            option_id = data.get("id")
            break
    if option_id:
        await f.go("admin", "PATCH", f"{base}/options/{option_id}", {"notes": "QA note"})
        _, listing = await f.go("admin", "GET", f"{base}/options")
        mine = next((o for o in _rows(listing) if o.get("id") == option_id), None)
        f.expect("option notes after patch", (mine or {}).get("notes"), "QA note")
        await f.go("admin", "POST", f"{base}/scores/prefill", None, soft=True)
        # A viewer-proof illegal call: an unknown form code is refused, not a 500.
        await f.go("admin", "POST", f"{base}/options", {"form_code": "no_such_form"}, ok=(404, 409, 422))
    else:
        # The demo seed may already hold these forms; then an existing option stands in.
        _, listing = await f.go("admin", "GET", f"{base}/options")
        if not _rows(listing):
            f.problems.append("no delivery form could be added and the project has no option")

    # Packages: create, patch, status, illegal status, delete.
    code = f"QA-{_tag()}"
    status, pkg = await f.go(
        "admin",
        "POST",
        f"{base}/packages",
        {"code": code, "title": "QA package", "kind": "construction", "builds": True},
        ok=(201,),
    )
    pkg_id = (pkg or {}).get("id")
    if pkg_id:
        _, patched = await f.go("admin", "PATCH", f"{base}/packages/{pkg_id}", {"title": "QA package renamed"})
        f.expect("package title after patch", (patched or {}).get("title"), "QA package renamed")
        await f.go("admin", "POST", f"{base}/packages/{pkg_id}/status", {"status": "bogus"}, ok=(422,))
        await f.go("admin", "POST", f"{base}/packages/{pkg_id}/status", {"status": "closed"}, soft=True)
        await f.go("admin", "DELETE", f"{base}/packages/{pkg_id}", ok=(204, 409))
    await f.go(
        "admin", "POST", f"{base}/packages", {"code": "bad code", "title": "x", "kind": "construction"}, ok=(422,)
    )

    # Owner furnished items: create, route, status, delete.
    status, ofi = await f.go(
        "admin",
        "POST",
        f"{base}/ofi",
        {"code": f"OFI-{_tag()}", "description": "QA lift", "item_kind": "equipment"},
        ok=(201,),
    )
    ofi_id = (ofi or {}).get("id")
    if ofi_id:
        await f.go("admin", "PATCH", f"{base}/ofi/{ofi_id}", {"description": "QA lift 2"})
        await f.go("admin", "PUT", f"{base}/ofi/{ofi_id}/route", {"procurement_route": "none_yet"}, soft=True)
        await f.go("admin", "POST", f"{base}/ofi/{ofi_id}/status", {"status": "ordered"}, soft=True)
        await f.go("admin", "POST", f"{base}/ofi/{ofi_id}/status", {"status": "bogus"}, ok=(422,))
        await f.go("admin", "DELETE", f"{base}/ofi/{ofi_id}", ok=(204, 409))

    # Decision: propose as the admin, the hand approval is the second user's (or the gate's) to make.
    if option_id:
        status, _ = await f.go(
            "admin",
            "POST",
            f"{base}/decision",
            {"option_id": option_id, "rationale": "QA: single point of responsibility."},
            soft=True,
        )
        if status == 201:
            _, cur = await f.go("admin", "GET", f"{base}/decision")
            f.expect("decision state after propose", (cur or {}).get("state") or (cur or {}).get("status"), "proposed")
            await f.go("admin", "POST", f"{base}/decision/approve", None, ok=(200, 409))
            await f.go("manager2", "POST", f"{base}/decision/approve", None, ok=(200, 409))
            await f.go("admin", "POST", f"{base}/decision/withdraw", None, soft=True)
    # Findings: readiness and validation answer, with a page of findings.
    _, ready = await f.go("admin", "GET", f"{base}/readiness")
    f.expect("readiness is an object", isinstance(ready, dict), True)
    _, val = await f.go("admin", "GET", f"{base}/validation")
    if not _rows(val):
        f.problems.append("validation returned no findings at all for a project with open items")
    f.done("delivery_model")


# ── design_management ───────────────────────────────────────────────────────


@pytest.mark.timeout(900)
async def test_design_management_role_deliverable_review_and_approval_point(world: World) -> None:
    f = Flow(world)
    base = f"{DES}/projects/{f.pid}"
    tag = _tag()

    # Role: create, patch, read back, delete.
    _, role = await f.go(
        "admin",
        "POST",
        f"{base}/roles",
        {"code": f"QA{tag}", "title": "QA discipline designer", "party_kind": "discipline_designer"},
        ok=(201, 409),
    )
    role_id = (role or {}).get("id")
    if role_id:
        _, patched = await f.go("admin", "PATCH", f"{base}/roles/{role_id}", {"title": "QA designer renamed"})
        f.expect("role title after patch", (patched or {}).get("title"), "QA designer renamed")
        await f.go("admin", "PATCH", f"{base}/roles/{role_id}", {"state": "appointed"}, soft=True)
        await f.go("admin", "PATCH", f"{base}/roles/{role_id}", {"party_kind": "not_a_kind"}, ok=(422,))
    await f.go("admin", "POST", f"{base}/roles", {"title": "no code and no kind"}, ok=(422,))

    # Deliverable: create, patch, delete.
    _, dl = await f.go(
        "admin",
        "POST",
        f"{base}/deliverables",
        {"code": f"QD{tag}", "title": "QA deliverable", "planned_count": 2, "role_id": role_id},
        soft=True,
    )
    dl_id = (dl or {}).get("id")
    if dl_id:
        await f.go("admin", "PATCH", f"{base}/deliverables/{dl_id}", {"planned_count": 3}, soft=True)
        await f.go("admin", "DELETE", f"{base}/deliverables/{dl_id}", ok=(204, 409))
    if role_id:
        await f.go("admin", "DELETE", f"{base}/roles/{role_id}", ok=(204, 409))

    # Review: create, open, comment, answer, conclude; an unknown target is refused.
    _, rev = await f.go("admin", "POST", f"{base}/reviews", {"code": f"QR{tag}", "title": "QA review"}, soft=True)
    rev_id = (rev or {}).get("id")
    if rev_id:
        await f.go("admin", "POST", f"{base}/reviews/{rev_id}/transition", {"target": "nonsense"}, ok=(409, 422))
        await f.go("admin", "POST", f"{base}/reviews/{rev_id}/transition", {"target": "open"}, soft=True)
        _, com = await f.go(
            "admin", "POST", f"{base}/reviews/{rev_id}/comments", {"text": "QA comment", "severity": "minor"}, soft=True
        )
        com_id = (com or {}).get("id")
        if com_id:
            await f.go(
                "manager2",
                "POST",
                f"{base}/comments/{com_id}/transition",
                {"target": "answered", "answer": "ok"},
                soft=True,
            )
        await f.go("admin", "POST", f"{base}/reviews/{rev_id}/conclude", {"outcome": "accepted"}, soft=True)

    # Approval point: submitted to a route whose only step is the second manager.
    ap_status, ap = await f.go(
        "admin",
        "POST",
        f"{base}/approval-points",
        {"code": f"QAP{tag}", "title": "QA owner approval", "kind": "owner_approval"},
        ok=(201,),
    )
    ap_id = (ap or {}).get("id")
    route_status, route = await f.go(
        "admin",
        "POST",
        f"{APR}/routes",
        {
            "project_id": f.pid,
            "name": f"QA design route {tag}",
            "target_kind": "design_approval_point",
            "steps": [{"ordinal": 1, "approver_user_id": str(world.users["manager2"]), "mode": "any"}],
        },
        ok=(201,),
    )
    route_id = (route or {}).get("id")
    if ap_id and route_id:
        await f.go("admin", "PATCH", f"{base}/setup", {"approval_route_id": route_id}, soft=True)
        sub_status, sub = await f.go("admin", "POST", f"{base}/approval-points/{ap_id}/submit", None, soft=True)
        if sub_status == 200:
            f.expect("approval point state after submit", (sub or {}).get("state"), "in_review")
            # Not twice.
            await f.go("admin", "POST", f"{base}/approval-points/{ap_id}/submit", None, ok=(409, 422))
            instance = (sub or {}).get("approval_instance_id")
            if instance:
                _, inst = await f.go("admin", "GET", f"{APR}/instances/{instance}")
                step_id = ((inst or {}).get("step_states") or [{}])[0].get("step_id")
                if step_id:
                    # The submitter is not the approver; the second manager is.
                    await f.go(
                        "admin",
                        "POST",
                        f"{APR}/instances/{instance}/decide",
                        {"step_id": step_id, "decision": "approved"},
                        ok=(403, 409, 422),
                    )
                    await f.go(
                        "manager2",
                        "POST",
                        f"{APR}/instances/{instance}/decide",
                        {"step_id": step_id, "decision": "approved"},
                    )
                    _, aps = await f.go("admin", "GET", f"{base}/approval-points")
                    mine = next((a for a in _rows(aps) if a.get("id") == ap_id), None)
                    f.expect("approval point state after approval", (mine or {}).get("state"), "approved")
                    await f.go("admin", "POST", f"{base}/approval-points/{ap_id}/reopen", None, ok=(409,))
        elif sub_status == 422:
            f.problems.append("approval point submit answered 422 although a route was pinned on the setup")

    _, val = await f.go("admin", "GET", f"{base}/validation")
    f.expect("design validation answers an object", isinstance(val, dict), True)
    _, ready = await f.go("admin", "GET", f"{base}/readiness")
    f.expect("design readiness answers an object", isinstance(ready, dict), True)
    f.done("design_management")


# ── permits ─────────────────────────────────────────────────────────────────


@pytest.mark.timeout(900)
async def test_permits_application_lifecycle_and_permit_transitions(world: World) -> None:
    f = Flow(world)
    base = f"{PER}/projects/{f.pid}"

    _, reqs = await f.go("admin", "GET", f"{base}/requirements")
    requirement = next((r for r in _rows(reqs) if r.get("id")), None)
    if requirement is None:
        f.problems.append("the demo project has no permit requirement to apply for")
        f.done("permits")
        return
    req_id = requirement["id"]

    await f.go("admin", "PATCH", f"{base}/requirements/{req_id}", {"applicant_rationale": "QA rationale"}, soft=True)
    await f.go("admin", "PATCH", f"{base}/requirements/{req_id}", {"applicant_role": "not_a_role"}, ok=(422,))

    status, app = await f.go(
        "admin",
        "POST",
        f"{base}/applications",
        {"requirement_id": req_id, "kind": "new", "authority_name": "QA authority"},
        soft=True,
    )
    app_id = (app or {}).get("id") if status == 201 else None
    if app_id:
        await f.go("admin", "PATCH", f"{base}/applications/{app_id}", {"authority_reference": "QA-1"})
        # A jump to a state the lifecycle does not offer from draft is refused, not a 500.
        await f.go(
            "admin", "POST", f"{base}/applications/{app_id}/transition", {"target": "validated"}, ok=(403, 409, 422)
        )
        await f.go("admin", "POST", f"{base}/applications/{app_id}/transition", {"target": "nonsense"}, ok=(422,))
        for target in ("preparing", "internal_review", "submitted"):
            await f.go(
                "admin",
                "POST",
                f"{base}/applications/{app_id}/transition",
                {"target": target, "on_date": "2026-09-01"},
                soft=True,
            )
        _, detail = await f.go("admin", "GET", f"{base}/applications/{app_id}")
        f.expect("application detail is an object", isinstance(detail, dict), True)
        await f.go(
            "admin",
            "POST",
            f"{base}/applications/{app_id}/clock-events",
            {"kind": "stop", "at": "2026-09-05", "reason": "QA"},
            soft=True,
        )
        await f.go(
            "manager2",
            "POST",
            f"{base}/applications/{app_id}/decision",
            {
                "outcome": "granted_with_conditions",
                "decision_date": "2026-09-20",
                "conditions": [{"number": "QA-1", "text": "Report to the authority.", "kind": "obligation"}],
            },
            soft=True,
        )
        _, conds = await f.go("admin", "GET", f"{base}/conditions")
        mine = next((c for c in _rows(conds) if c.get("number") == "QA-1"), None)
        if mine:
            cid = mine["id"]
            await f.go("admin", "PATCH", f"{base}/conditions/{cid}", {"text": "QA changed"}, soft=True)
            await f.go("admin", "POST", f"{base}/conditions/{cid}/discharge", {"mode": "not_triggered"}, soft=True)
    elif status == 201:
        f.problems.append("application created but no id in the answer")

    # A seeded permit moves out and back, and an unknown target is a 422.
    _, permits = await f.go("admin", "GET", f"{base}/permits")
    permit = next((p for p in _rows(permits) if p.get("id") and p.get("state", p.get("status")) == "in_force"), None)
    if permit:
        pid = permit["id"]
        await f.go("admin", "POST", f"{base}/permits/{pid}/transition", {"target": "bogus"}, ok=(422,))
        await f.go(
            "admin", "POST", f"{base}/permits/{pid}/transition", {"target": "suspended", "reason": "QA"}, soft=True
        )
        await f.go(
            "admin", "POST", f"{base}/permits/{pid}/transition", {"target": "in_force", "reason": "QA"}, soft=True
        )

    for gate in ("start", "register"):
        _, ready = await f.go("admin", "GET", f"{base}/readiness", params={"gate": gate})
        f.expect(f"readiness {gate} is an object", isinstance(ready, dict), True)
    _, val = await f.go("admin", "GET", f"{base}/validation")
    f.expect("permit validation answers", val is not None, True)
    f.done("permits")


# ── transmittals ────────────────────────────────────────────────────────────


@pytest.mark.timeout(900)
async def test_transmittal_draft_issue_acknowledge_respond_and_delete(world: World) -> None:
    f = Flow(world, "school-ludwigsburg")
    body = {
        "project_id": f.pid,
        "subject": f"QA transmittal {_tag()}",
        "purpose_code": "for_review",
        "recipients": [{"recipient_name": "QA Recipient", "recipient_email": "qa@example.test"}],
        "items": [{"item_number": 1, "description": "QA drawing set"}],
    }
    # Bad purpose and a due date before the issue date are refused.
    await f.go("admin", "POST", f"{TRA}/", {**body, "purpose_code": "whatever"}, ok=(422,))
    await f.go(
        "admin",
        "POST",
        f"{TRA}/",
        {**body, "issued_date": "2026-09-10", "response_due_date": "2026-09-01"},
        ok=(422,),
    )

    _, empty = await f.go(
        "admin",
        "POST",
        f"{TRA}/",
        {"project_id": f.pid, "subject": "QA empty draft", "purpose_code": "for_record"},
        ok=(201,),
    )
    empty_id = (empty or {}).get("id")
    if empty_id:
        f.expect("new transmittal is a draft", empty.get("status"), "draft")
        # Nothing to send yet: refused with the reason, and still a draft afterwards.
        await f.go("admin", "POST", f"{TRA}/{empty_id}/issue/", None, ok=(422,))
        _, again = await f.go("admin", "GET", f"{TRA}/{empty_id}")
        f.expect("draft stays a draft after a refused issue", (again or {}).get("status"), "draft")
        await f.go("admin", "DELETE", f"{TRA}/{empty_id}", ok=(204,))
        await f.go("admin", "GET", f"{TRA}/{empty_id}", ok=(404,))

    _, tr = await f.go("admin", "POST", f"{TRA}/", body, ok=(201,))
    tid = (tr or {}).get("id")
    if tid:
        _, patched = await f.go("admin", "PATCH", f"{TRA}/{tid}", {"subject": "QA transmittal renamed"})
        f.expect("subject after patch", (patched or {}).get("subject"), "QA transmittal renamed")
        _, rec = await f.go(
            "admin",
            "POST",
            f"{TRA}/{tid}/recipients/",
            {"recipient_name": "Second QA", "action_required": "review"},
            ok=(201,),
        )
        extra = (rec or {}).get("id")
        if extra:
            await f.go("admin", "DELETE", f"{TRA}/{tid}/recipients/{extra}", ok=(204,))
        _, issued = await f.go("admin", "POST", f"{TRA}/{tid}/issue/", None)
        f.expect("status after issue", (issued or {}).get("status"), "issued")
        # Issued is locked: no edit, no delete, no second issue.
        await f.go("admin", "PATCH", f"{TRA}/{tid}", {"subject": "late edit"}, ok=(409, 422))
        await f.go("admin", "POST", f"{TRA}/{tid}/issue/", None, ok=(409,))
        await f.go("admin", "DELETE", f"{TRA}/{tid}", ok=(409, 422))
        _, full = await f.go("admin", "GET", f"{TRA}/{tid}")
        recipients = (full or {}).get("recipients") or []
        if recipients:
            rid = recipients[0]["id"]
            _, ack = await f.go("manager2", "POST", f"{TRA}/{tid}/recipients/{rid}/acknowledge/", {})
            f.expect("acknowledged_at set", bool((ack or {}).get("acknowledged_at")), True)
            _, resp = await f.go("manager2", "POST", f"{TRA}/{tid}/recipients/{rid}/respond/", {"response": "Noted."})
            f.expect("response stored", (resp or {}).get("response"), "Noted.")
            _, after = await f.go("admin", "GET", f"{TRA}/{tid}")
            f.expect("status after the only recipient responded", (after or {}).get("status"), "responded")
        else:
            f.problems.append("GET transmittal carries no recipients list")
        status, blob = await f.go(
            "admin", "GET", f"{TRA}/export/", params={"project_id": f.pid, "export_format": "pdf"}
        )
        f.expect("register export reachable", status, 200)
    f.done("transmittals")
