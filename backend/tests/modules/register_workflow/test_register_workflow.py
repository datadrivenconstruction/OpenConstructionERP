# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Register Workflow tests - every rail, each with the failure it prevents."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import service, templates
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, code: str = "24188") -> uuid.UUID:
    user = User(email=f"rw-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="RW", role="admin")
    session.add(user)
    await session.flush()
    proj = Project(name=f"RW {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="AUD", project_code=code)
    session.add(proj)
    await session.flush()
    return proj.id


RFQ_FIELDS = {
    "Package": "Switchboards",
    "Delivery to": "12 Site Rd, Wetherill Park",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2099-01-01",
}


# -- Templates ------------------------------------------------------------


def test_every_kind_has_a_spine_and_a_form() -> None:
    for kind in templates.KINDS:
        spec = templates.spec_for(kind)
        assert spec["flow"], f"{kind} has no workflow"
        assert spec["fields"], f"{kind} has no raise fields"
        # Every register except the internal toolbox talk ends in a decision.
        if kind != "toolbox":
            assert any(s["t"] == "route" for s in spec["flow"]), f"{kind} has no route"
        assert any(s["t"] == "gate" for s in spec["flow"]), f"{kind} has no gate"


def test_money_fields_are_marked_internal() -> None:
    # The money rail starts here: if a value field is not marked internal,
    # the email builder has no way to know to strip it.
    rfq = {f["label"]: f for f in templates.spec_for("rfq")["fields"]}
    assert rfq["Estimated value $"]["internal"] is True
    variation = {f["label"]: f for f in templates.spec_for("variation")["fields"]}
    for label in ("Cost $", "Sell $", "Margin"):
        assert variation[label]["internal"] is True


# -- Raising --------------------------------------------------------------


@pytest.mark.asyncio
async def test_raise_lays_the_spine_and_numbers_per_kind(session: AsyncSession) -> None:
    pid = await _project(session)
    a = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    b = await service.raise_item(session, project_id=pid, kind="rfq", title="Cable ladder", fields=RFQ_FIELDS)
    c = await service.raise_item(session, project_id=pid, kind="rfi", title="Grid clash", fields={})
    # REG-RFQ-24188-0001: house prefix, kind, JOB NUMBER, then a
    # per-job counter that never re-issues. The old RFQ-001 was MAX+1
    # within one project, so two jobs both held an RFI-004 and a forwarded
    # reply carrying only its reference could be filed against either. The
    # job number inside the reference is what makes per-job numbering safe.
    assert (a.reference, b.reference, c.reference) == (
        "REG-RFQ-24188-0001",
        "REG-RFQ-24188-0002",
        "REG-RFI-24188-0001",
    )
    assert len(a.steps) == len(templates.FLOWS["rfq"])
    assert a.due_date == "2099-01-01"  # taken from the kind's deadline field
    assert a.status == "open"


@pytest.mark.asyncio
async def test_rfq_refuses_without_the_delivery_block(session: AsyncSession) -> None:
    pid = await _project(session)
    with pytest.raises(service.WorkflowError) as exc:
        await service.raise_item(session, project_id=pid, kind="rfq", title="No block", fields={"Package": "x"})
    # A supplier cannot quote freight to nowhere - name every gap at once.
    for label in ("Delivery to", "Site contact", "Estimated value $"):
        assert label in str(exc.value)


# -- Stepping -------------------------------------------------------------


@pytest.mark.asyncio
async def test_steps_complete_in_order_only(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    with pytest.raises(service.WorkflowError) as exc:
        await service.complete_step(session, steps[2].id, user_id="u1")
    assert "earlier steps first" in str(exc.value)
    await service.complete_step(session, steps[0].id, user_id="u1")
    await service.complete_step(session, steps[1].id, user_id="u1")
    done = await service.complete_step(session, steps[2].id, user_id="u1")
    assert done.state == "done" and done.completed_by == "u1"


@pytest.mark.asyncio
async def test_undo_is_reverse_order_only(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    await service.complete_step(session, steps[0].id, user_id="u1")
    await service.complete_step(session, steps[1].id, user_id="u1")
    with pytest.raises(service.WorkflowError):
        await service.uncomplete_step(session, steps[0].id)
    await service.uncomplete_step(session, steps[1].id)
    reopened = await service.uncomplete_step(session, steps[0].id)
    assert reopened.state == "open" and reopened.completed_at is None


@pytest.mark.asyncio
async def test_a_gate_can_never_be_waived(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    gate = next(s for s in steps if s.step_type == "gate")
    with pytest.raises(service.WorkflowError) as exc:
        await service.mark_not_required(session, gate.id, user_id="u1")
    assert "hold point" in str(exc.value)


@pytest.mark.asyncio
async def test_a_plain_step_can_be_marked_not_required(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    marked = await service.mark_not_required(session, steps[0].id, user_id="u1")
    assert marked.state == "not_required"
    # And it no longer blocks the next step.
    await service.complete_step(session, steps[1].id, user_id="u1")


# -- The compare gate: blocked FIRST, then forceable ----------------------


@pytest.mark.asyncio
async def test_a_written_reason_forces_the_quote_gate_it_does_not_skip_it(
    session: AsyncSession,
) -> None:
    """The regression the hardening pass introduced.

    Taking the reason as permission meant the rule was never consulted at
    all: send an override on the FIRST call and a $9,900 package with no
    quotes on it ticked its compare gate clean. A reason is permission to
    pass a gate that actually refused, and nothing else.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    steps = sorted(item.steps, key=lambda s: s.position)
    gate = next(s for s in steps if "quotes compared" in s.name.lower())
    for s in steps:
        if s.position >= gate.position:
            break
        await service.complete_step(session, s.id, user_id="u1")

    # No reason: refused, and told it can be forced.
    with pytest.raises(service.GateBlocked) as exc:
        await service.complete_step(session, gate.id, user_id="u1")
    assert exc.value.detail["can_force"] is True

    # A reason is STILL checked against the rule - it does not bypass it.
    # Junk is refused before it can force anything.
    for junk in ("x", "n/a", "tbc", "no time"):
        with pytest.raises(service.GateBlocked) as exc:
            await service.complete_step(session, gate.id, user_id="u1", override_reason=junk)
        assert exc.value.detail.get("reason_rejected") is True
        assert gate.state == "open"

    # A real sentence forces it, and the file says so forever.
    reason = "Two suppliers declined in writing and the program cannot wait"
    await service.complete_step(session, gate.id, user_id="u1", override_reason=reason)
    assert gate.state == "done"
    assert gate.override_reason == reason


@pytest.mark.asyncio
async def test_a_gate_that_passes_clean_is_never_branded_as_forced(
    session: AsyncSession,
) -> None:
    """The other half of the same regression.

    Because the reason was taken instead of the check, a gate that would
    have passed on its own merits was permanently recorded as "passed
    below the rule" - a claim about the job that was simply untrue.
    """
    from app.modules.register_workflow import native

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    # $9,900 needs three written prices. Give it three.
    for n, amount in enumerate(("9350.00", "9720.00", "10100.00")):
        await native.record_bid(
            session,
            rfq_entity_id=item.linked_entity_id,
            bidder_contact_id=f"supplier-{n}",
            amount=amount,
        )
    steps = sorted(item.steps, key=lambda s: s.position)
    gate = next(s for s in steps if "quotes compared" in s.name.lower())
    for s in steps:
        if s.position >= gate.position:
            break
        await service.complete_step(session, s.id, user_id="u1")

    # A reason typed into the box before the gate was even asked must not
    # end up on the record when the gate had nothing to forgive.
    await service.complete_step(session, gate.id, user_id="u1", override_reason="Belt and braces, ignore me")
    assert gate.state == "done"
    assert gate.override_reason is None


def test_a_non_answer_is_not_a_reason() -> None:
    """The override exists so somebody in six weeks can read WHY. These
    are the ways of typing nothing, ported from the old app."""
    for junk in ("", "   ", "x", "N/A", "n/a.", "tbc", "-", "later", "unknown", "because"):
        assert service.gate_reason_bad(junk)
    for real in (
        "Two suppliers declined in writing",
        "Client instructed us to proceed on the single price",
    ):
        assert service.gate_reason_bad(real) == ""


# -- Routes ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_route_cannot_be_ticked_it_must_be_chosen(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="toolbox", title="T", fields={})
    # Toolbox has no route; use RFI's.
    rfi = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    route = next(s for s in rfi.steps if s.step_type == "route")
    with pytest.raises(service.WorkflowError) as exc:
        await service.complete_step(session, route.id, user_id="u1")
    assert "decision" in str(exc.value)
    assert item is not None


@pytest.mark.asyncio
async def test_choosing_a_branch_appends_that_path(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    for s in steps[:-1]:
        await service.complete_step(session, s.id, user_id="u1")
    route = steps[-1]
    before = len(item.steps)
    await service.take_route(session, route.id, "Change - raise a variation", user_id="u1")
    after = sorted(item.steps, key=lambda s: s.position)
    assert len(after) == before + 3
    assert route.chosen_branch == "Change - raise a variation"
    assert [s.name for s in after[-3:]] == [
        "Variation raised (link the VO no.)",
        "Client instruction in writing",
        "Closed out - carried by the VO",
    ]
    # The appended step that starts another register is marked as such, so
    # the UI can offer "raise it" instead of asking someone to retype.
    assert after[-3].raises_kind == "variation"


@pytest.mark.asyncio
async def test_undoing_a_decision_puts_the_options_back(session: AsyncSession) -> None:
    """A mis-clicked fork had no fix inside the app.

    The hardening pass refused to undo a route at all, reasoning the
    branch was already on the record. That turned one wrong click on a
    four-way fork into a permanent one. Undoing it now strips the wrong
    branch's still-open steps and clears the choice, so the picker renders
    its options again and the other path can be taken.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    for s in steps[:-1]:
        await service.complete_step(session, s.id, user_id="u1")
    route = steps[-1]
    spine = len(item.steps)

    await service.take_route(session, route.id, "Change - raise a variation", user_id="u1")
    assert len(item.steps) == spine + 3

    await service.uncomplete_step(session, route.id)
    # The decision is open again and says nothing about which way it went.
    assert route.state == "open"
    assert route.chosen_branch is None
    # The wrong branch's steps came off with it - left behind, a second
    # choice would have put BOTH paths on one item.
    assert len(item.steps) == spine
    assert "Variation raised (link the VO no.)" not in [s.name for s in item.steps]
    # Positions closed up, so the route is still last and pickable.
    assert [s.position for s in sorted(item.steps, key=lambda s: s.position)] == list(range(spine))

    # And the other path can now be taken.
    await service.take_route(session, route.id, "No change - action it", user_id="u1")
    assert route.chosen_branch == "No change - action it"
    assert "Variation raised (link the VO no.)" not in [s.name for s in item.steps]


@pytest.mark.asyncio
async def test_a_decision_cannot_be_undone_once_its_path_has_been_worked(
    session: AsyncSession,
) -> None:
    """Undo is still reverse-order only. Once a branch step is ticked, the
    work happened - taking the fork back would strip signed history."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    for s in steps[:-1]:
        await service.complete_step(session, s.id, user_id="u1")
    route = steps[-1]
    await service.take_route(session, route.id, "Change - raise a variation", user_id="u1")
    first_branch_step = sorted(item.steps, key=lambda s: s.position)[-3]
    await service.complete_step(session, first_branch_step.id, user_id="u1")

    with pytest.raises(service.WorkflowError, match="Undo the later steps first"):
        await service.uncomplete_step(session, route.id)
    assert route.chosen_branch == "Change - raise a variation"


@pytest.mark.asyncio
async def test_an_unknown_branch_is_refused(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    for s in steps[:-1]:
        await service.complete_step(session, s.id, user_id="u1")
    with pytest.raises(service.WorkflowError):
        await service.take_route(session, steps[-1].id, "Whatever I like", user_id="u1")


# -- Added actions --------------------------------------------------------


@pytest.mark.asyncio
async def test_next_action_slots_in_after_the_current_step(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    await service.complete_step(session, steps[0].id, user_id="u1")
    await service.add_step(session, item.id, name="Chased by phone")
    after = sorted(item.steps, key=lambda s: s.position)
    # It lands right after the work already done, not at the end.
    assert after[1].name == "Chased by phone"
    assert after[2].name == steps[1].name


# -- Status + payload -----------------------------------------------------


@pytest.mark.asyncio
async def test_item_closes_when_nothing_is_open(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="toolbox", title="Talk", fields={})
    for s in sorted(item.steps, key=lambda x: x.position):
        await service.complete_step(session, s.id, user_id="u1")
    assert item.status == "closed"
    assert service.item_payload(item)["current_step"] is None


@pytest.mark.asyncio
async def test_payload_reports_progress_overdue_and_ball_in_court(session: AsyncSession) -> None:
    pid = await _project(session)
    fields = dict(RFQ_FIELDS, **{"Quotes due": "2020-01-01"})
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Late one", fields=fields)
    p = service.item_payload(item)
    assert p["is_overdue"] is True and p["days_until_due"] < 0
    assert p["steps_done"] == 0 and p["steps_total"] == len(templates.FLOWS["rfq"])
    # First step is ours to do.
    assert p["ball_in_court"] == "us"


# -- Interlink ------------------------------------------------------------


@pytest.mark.asyncio
async def test_prefill_carries_the_reference_and_narrative(session: AsyncSession) -> None:
    pid = await _project(session)
    rfi = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Ceiling clash",
        fields={"Question": "Which drawing revision applies at grid C-D?"},
    )
    pre = await service.prefill_from(session, rfi.id, "variation")
    assert pre["raised_from_reference"] == "REG-RFI-24188-0001"
    assert pre["fields"]["Client instruction ref"] == "REG-RFI-24188-0001"
    assert pre["fields"]["Description of change"].startswith("From REG-RFI-24188-0001:")


@pytest.mark.asyncio
async def test_raising_from_a_step_closes_the_loop_both_ways(session: AsyncSession) -> None:
    pid = await _project(session)
    rfi = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(rfi.steps, key=lambda s: s.position)
    for s in steps[:-1]:
        await service.complete_step(session, s.id, user_id="u1")
    await service.take_route(session, steps[-1].id, "Change - raise a variation", user_id="u1")

    vo = await service.raise_item(
        session,
        project_id=pid,
        kind="variation",
        title="Extra ceiling works",
        fields={},
        raised_from_id=str(rfi.id),
    )
    assert vo.raised_from_id == str(rfi.id)
    raising = next(s for s in rfi.steps if s.raises_kind == "variation")
    # "You never type the VO number twice."
    assert raising.raised_reference == vo.reference


@pytest.mark.asyncio
async def test_summary_counts_per_kind(session: AsyncSession) -> None:
    pid = await _project(session)
    await service.raise_item(session, project_id=pid, kind="rfq", title="A", fields=RFQ_FIELDS)
    await service.raise_item(
        session, project_id=pid, kind="rfq", title="B", fields=dict(RFQ_FIELDS, **{"Quotes due": "2020-01-01"})
    )
    await service.raise_item(session, project_id=pid, kind="rfi", title="C", fields={})
    s = await service.summary(session, pid)
    assert s["rfq"]["total"] == 2 and s["rfq"]["open"] == 2 and s["rfq"]["overdue"] == 1
    assert s["rfi"]["total"] == 1
    assert s["delay"]["total"] == 0


# -- Native bridge: the item IS the platform's own record -----------------


@pytest.mark.asyncio
async def test_raising_an_rfq_creates_the_native_rfq(session: AsyncSession) -> None:
    """Not a parallel copy: the platform's RFQ register gets the row, so
    the quote gate, compare and award all act on real data."""
    from app.modules.rfq_bidding.models import RFQ

    pid = await _project(session)
    item = await service.raise_item(
        session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS, user_id=str(uuid.uuid4())
    )
    assert item.linked_entity_type == "rfq" and item.linked_entity_id

    rfq = await session.get(RFQ, uuid.UUID(item.linked_entity_id))
    assert rfq is not None
    assert rfq.project_id == pid
    assert rfq.submission_deadline == "2099-01-01"
    # The estimated value typed on the raise form is the number the quote
    # gate tiers off - it must land where the gate reads it.
    assert rfq.metadata_["estimated_value"] == "9900"
    assert rfq.metadata_["delivery"]["to"] == RFQ_FIELDS["Delivery to"]


@pytest.mark.asyncio
async def test_enriched_payload_carries_the_live_quote_gate(session: AsyncSession) -> None:
    from app.modules.register_workflow import native

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    payload = await service.item_payload_enriched(session, item)
    gate = payload["native"]["quote_gate"]
    # $9,900 package with nothing quoted yet: three prices required.
    assert gate["required"] == 3 and gate["counted"] == 0 and gate["passes"] is False

    await native.record_bid(session, rfq_entity_id=item.linked_entity_id, bidder_contact_id="alpha", amount="9350.00")
    payload = await service.item_payload_enriched(session, item)
    assert payload["native"]["quote_gate"]["counted"] == 1
    assert payload["native"]["bids"][0]["amount"] == "9350.00"


@pytest.mark.asyncio
async def test_a_typed_price_updates_rather_than_duplicates(session: AsyncSession) -> None:
    from app.modules.register_workflow import native

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    await native.record_bid(session, rfq_entity_id=item.linked_entity_id, bidder_contact_id="alpha", amount="9350")
    await native.record_bid(session, rfq_entity_id=item.linked_entity_id, bidder_contact_id="alpha", amount="9100")
    payload = await service.item_payload_enriched(session, item)
    # One supplier, one column - a corrected figure is not a second quote.
    assert len(payload["native"]["bids"]) == 1
    assert payload["native"]["bids"][0]["amount"] == "9100"
    assert payload["native"]["quote_gate"]["counted"] == 1


@pytest.mark.asyncio
async def test_raising_an_rfi_creates_the_native_rfi(session: AsyncSession) -> None:
    from app.modules.rfi.models import RFI

    pid = await _project(session)
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Ceiling grid clash",
        fields={
            "Question": "Which revision applies?",
            "Discipline": "Electrical",
            "Response required by": "2026-09-10",
        },
        user_id=str(uuid.uuid4()),
    )
    assert item.linked_entity_type == "rfi"
    rfi = await session.get(RFI, uuid.UUID(item.linked_entity_id))
    assert rfi is not None and rfi.question == "Which revision applies?"
    assert rfi.discipline == "Electrical"
    payload = await service.item_payload_enriched(session, item)
    assert payload["native"]["rfi_number"] == rfi.rfi_number


@pytest.mark.asyncio
async def test_workflow_only_kinds_have_no_native_record(session: AsyncSession) -> None:
    pid = await _project(session)
    for kind in ("delay", "toolbox"):
        item = await service.raise_item(session, project_id=pid, kind=kind, title=kind, fields={})
        assert item.linked_entity_type is None
        # And they still render - a workflow-only item is a first-class row.
        payload = await service.item_payload_enriched(session, item)
        assert payload["native"] == {}
        assert payload["steps_total"] > 0


# -- Item emails: preview-first, tailored, response boxes, send log -------


@pytest.mark.asyncio
async def test_item_email_is_tailored_with_notified_and_no_money(session: AsyncSession) -> None:
    from app.modules.contacts.models import Contact
    from app.modules.register_workflow import emailing

    pid = await _project(session)
    a = Contact(contact_type="supplier", company_name="Alpha Electrical", primary_email="alpha@example.com")
    b = Contact(contact_type="supplier", company_name="Beta Switchboards", primary_email="beta@example.com")
    session.add_all([a, b])
    await session.flush()

    fields = dict(
        RFQ_FIELDS, **{"Materials / scope required": "Item\tQty\tUnit\nLadder 450\t24\tlen\nBrackets\t96\tea"}
    )
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfq",
        title="Cable ladder",
        fields=fields,
        recipient_contact_ids=[str(a.id), str(b.id)],
    )

    built = await emailing.build_item_email(session, item, contact_id=str(a.id))
    # Tailored: addressed to Alpha alone, and the Notified block names
    # ONLY Alpha. This assertion used to demand BOTH companies appear -
    # written before the rail landed and never updated, so it was asking
    # for the exact defect test_one_supplier_is_never_shown_the_others
    # exists to prevent: handing each supplier its competitor list.
    assert built["to"] == ["alpha@example.com"]
    assert "Alpha Electrical" in built["html"]
    assert "Beta Switchboards" not in built["html"]
    assert {n["name"] for n in built["notified"]} == {"Alpha Electrical"}
    assert built["subject"].startswith("RFQ - ALPHA ELECTRICAL - REG-RFQ-")
    # The money rail: the estimated value NEVER appears in the email.
    assert "9900" not in built["html"]
    # Pasted Excel cells render as a real table with its header row.
    assert "Ladder 450" in built["html"] and "Materials / scope required" in built["html"]
    # RFQ carries no response box - it is not asking for a form back.
    assert "Your response" not in built["html"]


@pytest.mark.asyncio
async def test_rfi_email_carries_the_response_box(session: AsyncSession) -> None:
    from app.modules.register_workflow import emailing

    pid = await _project(session)
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Grid clash",
        fields={"Question": "Which revision applies?"},
    )
    built = await emailing.build_item_email(session, item)
    assert "Your response" in built["html"]
    assert "Answered by" in built["html"]
    assert "Please complete the box above and reply to this email." in built["html"]


@pytest.mark.asyncio
async def test_send_log_records_and_ticks_the_sent_step(session: AsyncSession) -> None:
    from app.modules.register_workflow import emailing

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="X", fields=RFQ_FIELDS)
    steps = sorted(item.steps, key=lambda s: s.position)
    # Walk to the "Sent to at least two suppliers" step.
    for s in steps:
        if "sent" in s.name.lower():
            break
        await service.complete_step(session, s.id, user_id="u1")
    sent_step = next(s for s in steps if "sent" in s.name.lower())
    assert sent_step.state == "open"

    await emailing.record_send(
        session, item, contact_id=None, contact_name="Alpha", subject="RFQ - X", channel="outlook", user_id="u1"
    )
    assert len(emailing.send_log(item)) == 1
    # Opening the draft IS doing the "Sent ..." step - it ticked itself.
    assert sent_step.state == "done"


@pytest.mark.asyncio
async def test_send_log_never_bypasses_the_order_rail(session: AsyncSession) -> None:
    from app.modules.register_workflow import emailing

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="X", fields=RFQ_FIELDS)
    sent_step = next(s for s in sorted(item.steps, key=lambda s: s.position) if "sent" in s.name.lower())
    # Nothing completed yet: "Sent ..." is NOT the current step, so the
    # send logs but the step stays open - the in-order rail holds.
    await emailing.record_send(
        session, item, contact_id=None, contact_name="Alpha", subject="RFQ - X", channel="eml", user_id="u1"
    )
    assert len(emailing.send_log(item)) == 1
    assert sent_step.state == "open"


# -- DEFECT: attachments must actually ride the email ---------------------


@pytest.mark.asyncio
async def test_attachments_ride_the_email_and_are_named(session: AsyncSession, tmp_path, monkeypatch) -> None:
    """The whole point of attaching a drawing is that the supplier gets it.

    The builder returned [] for months of my own making: the file sat on
    the record and never reached anyone.
    """
    from pathlib import Path

    from app.modules.register_workflow import emailing

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB", fields=RFQ_FIELDS)

    root = Path(tmp_path) / "att"
    monkeypatch.setattr(emailing, "ATTACH_ROOT", root)
    folder = root / str(item.id)
    folder.mkdir(parents=True)
    (folder / "drawing.pdf").write_bytes(b"%PDF-1.4 fake")
    (folder / "internal-note.txt").write_bytes(b"our own markup")

    item.fields = dict(
        item.fields,
        _attachments=[
            {"filename": "drawing.pdf", "size": 13, "email": True},
            {"filename": "internal-note.txt", "size": 14, "email": False},
            {"filename": "vanished.pdf", "size": 99, "email": True},
        ],
    )
    await session.flush()

    built = await emailing.build_item_email(session, item)
    # The ticked, existing file rides.
    assert built["attachments"] == [str(folder / "drawing.pdf")]
    assert built["attachment_names"] == ["drawing.pdf"]
    # The email NAMES it, so the reader knows to look.
    assert "drawing.pdf" in built["html"]
    # Un-ticked evidence stays on the record and out of the inbox.
    assert "internal-note.txt" not in built["html"]
    # A file that has gone missing is reported, never silently claimed.
    assert built["attachments_missing"] == ["vanished.pdf"]
    assert "vanished.pdf" not in built["html"]


@pytest.mark.asyncio
async def test_no_attachments_means_no_attached_section(session: AsyncSession) -> None:
    from app.modules.register_workflow import emailing

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB", fields=RFQ_FIELDS)
    built = await emailing.build_item_email(session, item)
    assert built["attachments"] == []
    assert "Attached documents" not in built["html"]


# -- DEFECT: the analyser's figures reach the compare panel ---------------


def test_supplier_matching_never_guesses() -> None:
    from app.modules.register_workflow.suggestions import match_supplier, tokens

    sups = [("a", "Mid Coast Fasteners"), ("b", "Northbank Electrical Pty Ltd")]
    # Whole name.
    assert match_supplier("Quote from Mid Coast Fasteners attached", sups) == "a"
    # A distinctive token carries it.
    assert match_supplier("pricing from northbank for the ladder", sups) == "b"
    # "Electrical"/"Pty"/"Ltd" carry no identity, so they must not match.
    assert tokens("Northbank Electrical Pty Ltd") == ["northbank"]
    # Two suppliers named in one message is unknowable - say nothing.
    assert match_supplier("forwarding Mid Coast Fasteners to Northbank Electrical", sups) is None
    # Nothing recognisable at all.
    assert match_supplier("please find attached", sups) is None


@pytest.mark.asyncio
async def test_suggestions_carry_evidence_and_bucket_the_unplaceable(session: AsyncSession) -> None:
    from app.modules.comms_intelligence import service as ci_service
    from app.modules.contacts.models import Contact
    from app.modules.correspondence.models import Correspondence
    from app.modules.correspondence.repository import CorrespondenceRepository
    from app.modules.register_workflow import suggestions

    pid = await _project(session)
    alpha = Contact(contact_type="supplier", company_name="Midcoast Fasteners", primary_email="a@x.com")
    beta = Contact(contact_type="supplier", company_name="Riverton Switchboards", primary_email="b@x.com")
    session.add_all([alpha, beta])
    await session.flush()

    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfq",
        title="Ladder package",
        fields=RFQ_FIELDS,
        recipient_contact_ids=[str(alpha.id), str(beta.id)],
    )

    async def _reply(subject: str, body: str) -> Correspondence:
        repo = CorrespondenceRepository(session)
        row = Correspondence(
            project_id=pid,
            reference_number=await repo.next_reference_number(pid),
            direction="incoming",
            subject=subject,
            correspondence_type="email",
            notes=body,
        )
        session.add(row)
        await session.flush()
        await ci_service.analyze_correspondence(session, str(row.id), use_ai=False)
        return row

    await _reply(
        f"Quote for {item.reference}",
        "Midcoast Fasteners here. Quote No: 5501. Total Ex 4,000.00 GST 400.00 Total 4,400.00. Lead time 3 weeks.",
    )
    await _reply(f"RE {item.reference} pricing", "Total Ex 9,000.00 GST 900.00 Total 9,900.00 — no name in the body")

    out = await suggestions.suggestions_for(session, item)
    mine = out["by_supplier"].get(str(alpha.id))
    assert mine is not None
    latest = mine["latest"]
    # The ex-GST figure, its basis, and the WORDS it was read from.
    assert latest["amount"] == "4000.00"
    assert latest["basis"] == "ex gst"
    assert "4,000.00" in latest["evidence"]
    assert latest["lead_time"] == "3 weeks"
    assert latest["quote_number"] == "5501"
    # The nameless reply is held, not guessed onto whoever was closest.
    assert len(out["unmatched"]) == 1
    assert out["unmatched"][0]["amount"] == "9000.00"


@pytest.mark.asyncio
async def test_a_question_never_becomes_a_suggestion(session: AsyncSession) -> None:
    from app.modules.comms_intelligence import service as ci_service
    from app.modules.contacts.models import Contact
    from app.modules.correspondence.models import Correspondence
    from app.modules.correspondence.repository import CorrespondenceRepository
    from app.modules.register_workflow import suggestions

    pid = await _project(session)
    c = Contact(contact_type="supplier", company_name="Midcoast Fasteners", primary_email="a@x.com")
    session.add(c)
    await session.flush()
    item = await service.raise_item(
        session, project_id=pid, kind="rfq", title="P", fields=RFQ_FIELDS, recipient_contact_ids=[str(c.id)]
    )
    repo = CorrespondenceRepository(session)
    row = Correspondence(
        project_id=pid,
        reference_number=await repo.next_reference_number(pid),
        direction="incoming",
        subject=f"RE {item.reference}",
        correspondence_type="email",
        notes="Midcoast Fasteners — can you confirm the bracket centres before we price it?",
    )
    session.add(row)
    await session.flush()
    await ci_service.analyze_correspondence(session, str(row.id), use_ai=False)

    out = await suggestions.suggestions_for(session, item)
    assert out["by_supplier"] == {} and out["unmatched"] == []


# -- Configurator, stats, documents ---------------------------------------


#: The RFI route, by name - gates and routes are matched by name, which
#: is exactly why they cannot be renamed through the configurator.
ROUTE_NAME = "Does the answer change scope, cost or program?"


@pytest.mark.asyncio
async def test_configure_never_touches_finished_history(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    await service.complete_step(session, steps[0].id, user_id="u1")
    await service.complete_step(session, steps[1].id, user_id="u1")
    done_names = [s.name for s in sorted(item.steps, key=lambda s: s.position) if s.state != "open"]

    await service.configure_steps(
        session,
        item.id,
        [
            {"name": "Chase the consultant", "type": "step"},
            {"name": "Reviewed before issue", "type": "gate", "owner": "PM"},
            # The route has to be carried through: tailoring the workflow
            # may reorder and re-own the work, but it cannot delete the
            # decision that records which way the item went.
            {"name": ROUTE_NAME, "type": "step"},
            {"name": "Closed out", "type": "step"},
        ],
    )
    after = sorted(item.steps, key=lambda s: s.position)
    # History intact, and still first.
    assert [s.name for s in after if s.state != "open"] == done_names
    # The remaining work is exactly what was asked for, in that order.
    assert [s.name for s in after if s.state == "open"] == [
        "Chase the consultant",
        "Reviewed before issue",
        ROUTE_NAME,
        "Closed out",
    ]
    assert next(s for s in after if s.name == "Reviewed before issue").step_type == "gate"
    # The route kept its type and its branches - it was not flattened to a
    # plain step by being listed as one.
    route = next(s for s in after if s.name == ROUTE_NAME)
    assert route.step_type == "route"
    assert route.branches


@pytest.mark.asyncio
async def test_configure_cannot_silently_delete_or_rename_a_gate_or_route(
    session: AsyncSession,
) -> None:
    """The sharpest hole the stress pass found.

    The compare gate is matched BY NAME, so renaming it through the
    workflow configurator left something that still rendered as a gate and
    still ticked - while the quote rule it existed to enforce was never
    consulted. Dropping it outright was the same trick with fewer steps.

    Both are still refused with no reason given, and a non-answer is not a
    reason - see the retire test below for the legitimate exit.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})

    with pytest.raises(service.WorkflowError, match="without a written reason"):
        await service.configure_steps(session, item.id, [{"name": "Just do the thing", "type": "step"}])
    # Renaming it is the same attack: the gate is gone by any other name.
    remaining = [s.name for s in sorted(item.steps, key=lambda s: s.position) if s.state == "open"]
    renamed = [{"name": ("Comparison complete" if n == ROUTE_NAME else n), "type": "step"} for n in remaining]
    with pytest.raises(service.WorkflowError, match="without a written reason"):
        await service.configure_steps(session, item.id, renamed)

    # "n/a" is a way of typing nothing, and so is a single character.
    with pytest.raises(service.WorkflowError, match="not a reason"):
        await service.configure_steps(
            session, item.id, [{"name": "Just do the thing", "type": "step"}], retire_reason="n/a"
        )
    with pytest.raises(service.WorkflowError, match="too short"):
        await service.configure_steps(
            session, item.id, [{"name": "Just do the thing", "type": "step"}], retire_reason="no time"
        )

    # And the item still has its route, untouched, after every refusal.
    assert any(s.step_type == "route" for s in item.steps)


@pytest.mark.asyncio
async def test_a_gate_that_does_not_apply_comes_off_the_workflow_on_the_record(
    session: AsyncSession,
) -> None:
    """The hardening pass left an inapplicable gate with no honest exit.

    Refusing removal outright meant the only way past a gate that does not
    apply to this job was to SIGN AN OVERRIDE - which then records that
    the rule was passed below its threshold, a thing that never happened.
    So it can be taken off, with a reason, and it is retired onto the
    record rather than deleted from it.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    gate = next(s for s in item.steps if s.step_type == "gate")
    reason = "Client issues this RFI direct - there is no internal review stage on this job"

    await service.configure_steps(
        session,
        item.id,
        [{"name": "Sent to the client / consultant", "type": "step"}],
        retire_reason=reason,
        user_id="u1",
    )

    # The hold point is still on the file, saying who took it off and why.
    kept = next(s for s in item.steps if s.name == gate.name)
    assert kept.step_type == "gate"
    assert kept.state == "not_required"
    assert reason in (kept.override_reason or "")
    assert kept.completed_by == "u1"
    # It does NOT read as a gate that was passed below its rule.
    assert "below" not in (kept.override_reason or "").lower()
    # And the remaining work is what was asked for.
    assert [s.name for s in sorted(item.steps, key=lambda s: s.position) if s.state == "open"] == [
        "Sent to the client / consultant"
    ]


@pytest.mark.asyncio
async def test_marking_a_gate_not_required_still_refuses_and_says_where_to_go(
    session: AsyncSession,
) -> None:
    """⊘ on a gate stays refused - a hold point you can wave away is not a
    hold point. The refusal now points at the exit that IS legitimate."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    gate = next(s for s in item.steps if s.step_type == "gate")
    with pytest.raises(service.WorkflowError) as exc:
        await service.mark_not_required(session, gate.id, user_id="u1")
    assert "take it off the workflow" in str(exc.value)


@pytest.mark.asyncio
async def test_configure_refuses_an_empty_workflow(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    with pytest.raises(service.WorkflowError):
        await service.configure_steps(session, item.id, [])


@pytest.mark.asyncio
async def test_performance_reads_the_step_trail(session: AsyncSession) -> None:
    pid = await _project(session)
    talk = await service.raise_item(session, project_id=pid, kind="toolbox", title="Talk", fields={})
    for s in sorted(talk.steps, key=lambda x: x.position):
        await service.complete_step(session, s.id, user_id="u1")
    await service.raise_item(
        session, project_id=pid, kind="delay", title="Wet weather", fields={"Duration (hrs)": "6.5"}
    )
    await service.raise_item(session, project_id=pid, kind="delay", title="Access", fields={"Duration (hrs)": "2"})

    stats = await service.performance(session, pid)
    assert stats["closed"] == 1 and stats["open"] == 2
    assert stats["avg_days_to_close"] == 0.0
    # The claim number: every delay's hours, summed off the register.
    assert stats["lost_hours"] == "8.5"


def test_document_resolve_refuses_traversal(tmp_path, monkeypatch) -> None:
    from app.modules.register_workflow import documents

    monkeypatch.setattr(documents, "ATTACH_ROOT", tmp_path)
    folder = tmp_path / "item-1"
    folder.mkdir()
    (folder / "quote.pdf").write_bytes(b"%PDF")
    (tmp_path / "secret.txt").write_bytes(b"not yours")

    path, media, inline = documents.resolve("item-1", "quote.pdf")
    assert path.name == "quote.pdf" and media == "application/pdf" and inline is True
    # Climbing out is refused, however it is spelled.
    for hostile in ("../secret.txt", "..\\secret.txt", "/etc/passwd"):
        with pytest.raises(documents.DocumentError):
            documents.resolve("item-1", hostile)


def test_eml_reading_blocks_the_read_receipt() -> None:
    from app.modules.register_workflow import documents

    raw = (
        b"From: sales@supplier.example\r\n"
        b"To: owner@example.com\r\n"
        b"Subject: Quote 5501\r\n"
        b'Content-Type: text/html; charset="utf-8"\r\n\r\n'
        b'<p>Our price is $4,120.00</p><img src="https://track.example/pixel.gif">'
        b"<script>alert(1)</script>"
    )
    out = documents.read_eml(raw)
    assert out["subject"] == "Quote 5501"
    assert "4,120.00" in out["html"]
    # A tracking pixel tells the supplier exactly when the buyer opened
    # their price. It never renders.
    assert "track.example" not in out["html"]
    assert "<script" not in out["html"]
    assert out["remote_content_blocked"] is True


# -- Hardening found by the stress harness --------------------------------


def test_control_characters_never_reach_the_database() -> None:
    """A NUL byte in a subject 500'd the insert - PostgreSQL rejects it.

    Found by the live abuse harness posting a title of "abc\\x00def".
    """
    from app.modules.register_workflow.service import clean_text

    assert clean_text("abc" + chr(0) + "def") == "abcdef"
    assert clean_text("a" + chr(7) + chr(27) + "b") == "ab"
    # Tab / newline / CR survive: a pasted Excel table is made of them.
    assert clean_text("a\tb\nc\r") == "a\tb\nc\r"
    # It recurses, because the fields bag is nested.
    assert clean_text({"k" + chr(0): ["v" + chr(0)]}) == {"k": ["v"]}


def test_reserved_field_keys_are_server_owned() -> None:
    """A client could forge the send log and the attachment list.

    The send log is what "sent to N" counts, and the attachment list is
    what rides out on the next email - both must be the server's alone.
    """
    from app.modules.register_workflow.service import sanitise_fields

    forged = {
        "Package": "x",
        "_send_log": [{"contact_name": "FORGED"}],
        "_attachments": [{"filename": "../../etc/passwd", "email": True}],
    }
    assert sanitise_fields(forged) == {"Package": "x"}
    # A genuine one already on the record survives an edit untouched.
    assert sanitise_fields({"Package": "x"}, previous={"_send_log": ["real"]}) == {
        "Package": "x",
        "_send_log": ["real"],
    }


@pytest.mark.asyncio
async def test_a_forged_attachment_path_can_never_ride_the_email(session: AsyncSession, tmp_path, monkeypatch) -> None:
    """The serious one: a forged _attachments entry pointing outside the
    item's folder would have exfiltrated an arbitrary file as an email
    attachment on a Linux host."""
    from pathlib import Path

    from app.modules.register_workflow import emailing

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="X", fields=RFQ_FIELDS)

    root = Path(tmp_path) / "att"
    monkeypatch.setattr(emailing, "ATTACH_ROOT", root)
    folder = root / str(item.id)
    folder.mkdir(parents=True)
    (folder / "ok.pdf").write_bytes(b"%PDF")
    # A real file OUTSIDE the item's folder, the thing an attacker wants.
    secret = root / "secret.txt"
    secret.write_bytes(b"not yours")

    # Written straight onto the row, bypassing the API sanitiser, to prove
    # the email builder itself refuses rather than trusting stored data.
    item.fields = dict(
        item.fields,
        _attachments=[
            {"filename": "ok.pdf", "email": True},
            {"filename": "../secret.txt", "email": True},
            {"filename": str(secret), "email": True},
        ],
    )
    await session.flush()

    ride, missing = emailing.attachment_paths(item)
    assert [Path(p).name for p in ride] == ["ok.pdf"]
    # Both escape attempts are refused and reported, never silently sent.
    assert len(missing) == 2
    built = await emailing.build_item_email(session, item)
    assert "secret" not in built["html"]
    assert all("secret" not in p for p in built["attachments"])


@pytest.mark.asyncio
async def test_a_signed_step_names_the_person_not_their_id(session: AsyncSession) -> None:
    """Who signed a gate must read as a NAME on every surface.

    ``completed_by`` stores a uuid, which the conversation log used to
    print raw: a gate override - whose entire purpose is that somebody put
    their name to a reason - answered "who signed this?" with
    ``7bed966d-6364-…``. Remove the resolution in
    ``_name_the_signers`` and this fails.
    """
    signer = User(
        email=f"signer-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Sam Rivera",
        role="admin",
    )
    session.add(signer)
    await session.flush()

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    await service.complete_step(session, steps[0].id, user_id=str(signer.id))

    payload = await service.item_payload_enriched(session, item)
    first = sorted(payload["steps"], key=lambda s: s["position"])[0]
    assert first["completed_by_name"] == "Sam Rivera"
    # The id itself is still on the record - the name is an addition, not
    # a replacement, so anything keying off the user id keeps working.
    assert first["completed_by"] == str(signer.id)


@pytest.mark.asyncio
async def test_an_unresolvable_signer_falls_back_to_the_id(session: AsyncSession) -> None:
    """A deleted account must never blank the trail.

    Falling back to the id keeps the audit answerable ("that is a user who
    no longer exists") where an empty string would read as "nobody signed
    this" - the opposite of what happened.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    gone = str(uuid.uuid4())
    await service.complete_step(session, steps[0].id, user_id=gone)

    payload = await service.item_payload_enriched(session, item)
    first = sorted(payload["steps"], key=lambda s: s["position"])[0]
    assert first["completed_by_name"] == gone
