# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow business logic - where the rails are enforced.

Every rule below is refused SERVER-SIDE. The UI mirrors them for a good
experience, but the UI is not the rail: a rail enforced in one code path
is not a rail.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.register_workflow import templates
from app.modules.register_workflow.models import RegisterItem, RegisterStep

logger = logging.getLogger(__name__)


class WorkflowError(Exception):
    """Router-facing refusal with a message the person can act on."""


class GateBlocked(WorkflowError):
    """A gate refused because its subject rule is not satisfied yet.

    Carries the machine-readable payload so the UI can offer the signed
    override rather than dead-ending the user.
    """

    def __init__(self, message: str, detail: dict[str, Any]) -> None:
        super().__init__(message)
        self.detail = detail


#: Ways of typing nothing. The point of an override is a reason a human
#: can read in six weeks and understand, so these are refused by name.
#: Ported from the old app's ``_JUNK_REASON``.
GATE_REASON_JUNK = frozenset(
    {
        "n/a",
        "na",
        "n\a",
        "nil",
        "none",
        "no",
        "-",
        "--",
        ".",
        "x",
        "tbc",
        "tba",
        "later",
        "asap",
        "unknown",
        "idk",
        "no reason",
        "because",
    }
)


def gate_reason_bad(reason: str | None) -> str:
    """ "" when this justification will still mean something later, else why not.

    This cannot judge whether a reason is TRUE - only a person can. It
    refuses the ways of writing nothing, and says what it wants instead.
    """
    text = " ".join(str(reason or "").split())
    if not text:
        return "It needs a reason."
    if text.strip(" .-").lower() in GATE_REASON_JUNK:
        return f'"{text}" is not a reason - say what is actually happening.'
    if len(text) < 12:
        return f'"{text}" is too short to mean anything in six weeks - one plain sentence is enough.'
    return ""


#: Keys the SERVER owns inside ``item.fields``. A client that could set
#: these could forge the send log (fabricating "sent to N", which the
#: quote rule counts) or point an attachment at any path on the box and
#: have it ride out on the next email.
RESERVED_FIELD_KEYS = ("_send_log", "_attachments", "_notified", "_links", "_withdrawn")

#: The third status, beside open and closed. An item that has already
#: left the building cannot be deleted - the register is an audit trail,
#: and a supplier holding an RFQ that no longer exists on our side is
#: exactly the position the trail exists to prevent. It is WITHDRAWN
#: instead: still on the record, plainly marked, out of every open list
#: and count, and refusing further work until somebody reopens it.
WITHDRAWN = "withdrawn"

#: Where the withdrawal is stamped, inside the server-owned key space so
#: an edit cannot rewrite who withdrew an item or why.
WITHDRAWN_KEY = "_withdrawn"

#: PostgreSQL text columns reject NUL outright (the insert 500s), and a
#: stray control character in a subject is never meaningful. Tab, newline
#: and carriage return are KEPT - a pasted Excel table is made of them.
_CONTROL_STRIP = {c: None for c in range(32) if c not in (9, 10, 13)}
_CONTROL_STRIP[127] = None


def single_line(value: str) -> str:
    """Text that will end up in a mail HEADER, with CR/LF collapsed.

    `clean_text` deliberately keeps tab/newline/CR because a pasted Excel
    table is made of them - but a title flows into the Subject line, and
    "Cable ladder\r\nBcc: silent@evil.example" is a header injection.
    Python 3.12's email library refuses it (a 500 AFTER the send was
    already logged); an older runtime, or any client that builds the
    header itself, would have honoured the forged Bcc.
    """
    return " ".join(str(value or "").split())


def clean_text(value: Any) -> Any:
    """Strip control characters from a value, recursing into containers."""
    if isinstance(value, str):
        return value.translate(_CONTROL_STRIP)
    if isinstance(value, list):
        return [clean_text(v) for v in value]
    if isinstance(value, dict):
        return {clean_text(k): clean_text(v) for k, v in value.items()}
    return value


def sanitise_fields(fields: dict[str, Any] | None, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Client-supplied fields, with the server-owned keys preserved.

    Anything the client sends under a reserved key is dropped and the
    value already on the record is kept, so a forged send log cannot be
    injected through the raise form or a PATCH.
    """
    clean = {k: clean_text(v) for k, v in (fields or {}).items() if k not in RESERVED_FIELD_KEYS}
    for key in RESERVED_FIELD_KEYS:
        if previous and key in previous:
            clean[key] = previous[key]
    return clean


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ── Raising an item ──────────────────────────────────────────────────────


#: The house prefix on every reference. One token, so a forwarded reply
#: carrying only "REG-RFQ-000123" is unambiguous in anyone's inbox.
#: Configurable per workspace (Settings > Branding > Organisation, or
#: OE_REGISTER_HOUSE) so the code carries nobody's company acronym.


def reference_house() -> str:
    from app.core.app_branding import org_reference_prefix

    return org_reference_prefix()


#: Six digits on the UN-SCOPED series (``REG-MSG-000042``). Wide enough
#: to never roll over on a business this size.
REFERENCE_DIGITS = 6

#: Four on a PER-JOB series. One job does not raise ten thousand RFIs, and
#: the reference already names the job - ``REG-RFI-25406-0001`` reads
#: aloud better than ``REG-RFI-25406-000001``.
JOB_REFERENCE_DIGITS = 4

#: How long a job number may be once normalised.
#:
#: ``RegisterItem.reference`` is String(40) and the counter's ``scope`` is
#: String(40). At this cap the longest reference that can be minted is
#: ``REG-RFI-<16>-00001`` = 30 characters, so both columns still have
#: room even after the sequence outgrows its four-digit padding. Without a
#: cap a long project code built a reference too long for its own column:
#: a database error on raise, or a silently truncated reference that no
#: reply could ever be matched against.
JOB_NUMBER_MAX = 16

#: The house code the platform generates when a project is created with no
#: number of its own (``projects/service.py``: ``PRJ-{YEAR}-{SEQ:04d}``).
#: It is not a job number anybody outside the platform would recognise, and
#: a reference built from it - ``REG-RFI-PRJ20260001-0001`` - is unreadable
#: and means nothing to anybody on site. Treated as "not set yet".
_AUTO_PROJECT_CODE_RX = re.compile(r"^PRJ-\d{4}-\d{4}$", re.I)


def normalise_job_number(code: str | None) -> str:
    """The job number as it appears INSIDE a reference.

    Letters and digits only, uppercased: a reference has to survive a
    subject line, being read down the phone, and being matched back out of
    a reply, and a job number carrying spaces or slashes would break the
    inbound matcher's word boundaries.
    """
    return re.sub(r"[^A-Za-z0-9]", "", str(code or "")).upper()


async def job_number_for(session: AsyncSession, project_id: uuid.UUID) -> str:
    """This job's number, or a refusal that says how to set it.

    A deliberate call: rather than quietly fall back to an un-scoped
    reference, raising is REFUSED until the job number is set. Two shapes
    of reference in one register - with no way to tell from an old one
    which job it belonged to - is the mess this change exists to end.
    """
    from app.modules.projects.models import Project

    row = (await session.execute(select(Project.project_code).where(Project.id == project_id))).scalar_one_or_none()
    code = str(row or "").strip()
    if not code or _AUTO_PROJECT_CODE_RX.match(code):
        raise WorkflowError(
            "This job has no job number yet. Set it on the project as "
            '"Project number / code" (for example 25406), then raise this again - '
            "every reference carries the job number, so one cannot be minted without it."
        )
    job = normalise_job_number(code)
    if not job:
        raise WorkflowError(
            f"The project number {code!r} has no letters or digits in it, so it cannot go into "
            "a reference. Set it to the job number (for example 25406)."
        )
    if len(job) > JOB_NUMBER_MAX:
        raise WorkflowError(
            f"The project number {code!r} is too long for a reference "
            f"({len(job)} characters once punctuation is removed; the limit is {JOB_NUMBER_MAX}). "
            "Set it to the job number (for example 25406)."
        )
    await _refuse_a_shared_job_number(session, project_id, job, code)
    return job


async def _refuse_a_shared_job_number(session: AsyncSession, project_id: uuid.UUID, job: str, code: str) -> None:
    """No two jobs may answer to the same job number.

    Punctuation comes out before the number goes into a reference, so
    ``25-406`` and ``25406`` - and ``ab12`` and ``AB12`` - are the same
    job number by the time it is minted. Left alone, two different jobs
    would share one counter and their references would be
    indistinguishable: ``REG-RFI-25406-0002`` could belong to either, and
    a reply quoting it could be filed against the wrong job. That is the
    precise ambiguity per-job numbering exists to remove, so it is refused
    at the point of raising rather than discovered later.

    Only projects that HAVE a code are considered, and only the normalised
    form is compared - which is the form that actually reaches a reference.
    """
    from app.modules.projects.models import Project

    rows = (
        await session.execute(
            select(Project.id, Project.name, Project.project_code).where(
                Project.id != project_id,
                Project.project_code.isnot(None),
                Project.project_code != "",
            )
        )
    ).all()
    for other_id, other_name, other_code in rows:
        if normalise_job_number(other_code) != job:
            continue
        raise WorkflowError(
            f"Job number {job} is already used by another job "
            f"({other_name or other_id}, whose project number is {other_code!r}). "
            "Two jobs sharing a number would give them references nobody can tell apart. "
            f"Set this job's project number to its own job number - {code!r} normalises "
            f"to {job}."
        )


def format_reference(prefix: str, number: int, job: str = "") -> str:
    """``REG-RFI-25406-0001`` on a job, ``REG-MSG-000042`` un-scoped."""
    house = reference_house()
    if job:
        return f"{house}-{prefix}-{job}-{number:0{JOB_REFERENCE_DIGITS}d}"
    return f"{house}-{prefix}-{number:0{REFERENCE_DIGITS}d}"


async def _highest_legacy(session: AsyncSession, prefix: str, job: str = "") -> int:
    """The biggest number already issued in this series.

    Seeds the counter on first use so a store that already holds RFQ-004
    does not start again at 1 and hand a live number to a second package.

    Scoped by JOB when one is given: the ``25406`` series is seeded only
    from ``REG-RFQ-25406-####``, never from another job's numbers and
    never from the old un-scoped ``REG-RFQ-000123``. Seeding a fresh job
    from the global high-water mark would start its register at 0124.
    """
    rows = (await session.execute(select(RegisterItem.reference).where(RegisterItem.kind.isnot(None)))).scalars().all()
    if job:
        pattern = re.compile(rf"(^|-){re.escape(prefix)}-{re.escape(job)}-(\d+)$", re.I)
    else:
        # Both legacy shapes: "RFQ-004" and "REG-RFQ-000123".
        pattern = re.compile(rf"(^|-){re.escape(prefix)}-(\d+)$", re.I)
    highest = 0
    for ref in rows:
        m = pattern.search(str(ref or ""))
        if m:
            highest = max(highest, int(m.group(2)))
    return highest


#: The per-EMAIL series. Every outbound email gets its own number -
#: "which email are we talking about" is a different question from
#: "which item", and a dispute about what was sent WHEN is settled by
#: the mail's own identifier, the way document control numbers every mail.
EMAIL_PREFIX = "MSG"


async def next_email_reference(session: AsyncSession) -> str:
    """Burn and return the next REG-MSG-###### under the counter lock."""
    from app.modules.register_workflow.models import RegisterCounter

    row = (
        await session.execute(
            select(RegisterCounter)
            .where(RegisterCounter.prefix == EMAIL_PREFIX, RegisterCounter.scope == "")
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = RegisterCounter(prefix=EMAIL_PREFIX, scope="", value=0)
        session.add(row)
        await session.flush()
    row.value = int(row.value or 0) + 1
    await session.flush()
    return format_reference(EMAIL_PREFIX, row.value)


async def peek_email_reference(session: AsyncSession) -> str:
    """What the NEXT email will be numbered, without burning it - the
    preview shows this, the draft mints it. Same contract as item refs."""
    from app.modules.register_workflow.models import RegisterCounter

    row = (
        await session.execute(
            select(RegisterCounter).where(RegisterCounter.prefix == EMAIL_PREFIX, RegisterCounter.scope == "")
        )
    ).scalar_one_or_none()
    return format_reference(EMAIL_PREFIX, (row.value if row else 0) + 1)


async def _peek_reference(session: AsyncSession, project_id: uuid.UUID, kind: str) -> str:
    """What the NEXT mint will be, without burning it.

    The live preview shows the reference the item is about to get. Minting
    for a preview would burn a number every time somebody opened a form
    and changed their mind, and the register would read as a list of gaps.
    """
    from app.modules.register_workflow.models import RegisterCounter

    prefix = templates.KIND_PREFIX.get(kind, kind.upper())
    job = await job_number_for(session, project_id)
    row = (
        await session.execute(
            select(RegisterCounter).where(RegisterCounter.prefix == prefix, RegisterCounter.scope == job)
        )
    ).scalar_one_or_none()
    current = row.value if row is not None else await _highest_legacy(session, prefix, job)
    return format_reference(prefix, current + 1, job)


async def _next_reference(session: AsyncSession, project_id: uuid.UUID, kind: str) -> str:
    """Burn and return the next reference for this kind. Never re-issued.

    The counter row is taken WITH A LOCK: two people raising an RFQ on the
    same job in the same second must not both read the same number and
    mint REG-RFQ-25406-0003 twice.

    The series is PER JOB. Scoping used to mean two jobs both held an
    ``RFI-004`` with no way to tell them apart; the job number now sits
    inside the reference, so ``REG-RFI-25406-0004`` and
    ``REG-RFI-24190-0004`` are different strings and the old ambiguity
    cannot come back.
    """
    from sqlalchemy.exc import IntegrityError

    from app.modules.register_workflow.models import RegisterCounter

    prefix = templates.KIND_PREFIX.get(kind, kind.upper())
    job = await job_number_for(session, project_id)
    row = None
    for attempt in (1, 2):
        row = (
            await session.execute(
                select(RegisterCounter)
                .where(RegisterCounter.prefix == prefix, RegisterCounter.scope == job)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is not None:
            break
        # FIRST mint for this (kind, job): two people can reach here
        # together - both found no row, both insert, and the loser
        # violates uq_(prefix, scope). That means "somebody else just
        # created the counter", not a server error - so the insert runs
        # in a SAVEPOINT (a failed flush otherwise poisons the whole
        # session) and the loser goes back around to LOCK the winner's
        # row instead.
        try:
            async with session.begin_nested():
                row = RegisterCounter(prefix=prefix, scope=job, value=await _highest_legacy(session, prefix, job))
                session.add(row)
                await session.flush()
            break
        except IntegrityError as exc:
            row = None
            if attempt == 2:
                # Twice means this is NOT the race: the insert keeps
                # violating something the retry cannot see - on both live
                # installs (31 Aug) it was a stale UNIQUE index on prefix
                # alone left over from before per-job scoping. Say so
                # instead of 500ing with nothing on the screen.
                raise WorkflowError(
                    "The reference counter could not be created for this job. "
                    "If this keeps happening, the counter table likely still "
                    "carries the old UNIQUE index on prefix alone - run the "
                    "register_workflow v0004 heal (drop the unique "
                    "ix_oe_register_workflow_counter_prefix, recreate it "
                    "non-unique)."
                ) from exc
    assert row is not None  # both loop exits above set it
    row.value = int(row.value or 0) + 1
    await session.flush()
    return format_reference(prefix, row.value, job)


def _due_from_fields(kind: str, fields: dict[str, Any]) -> str | None:
    """The due date is whichever field the kind marks as its deadline."""
    for label, _t, is_due, _internal in templates.FIELDS.get(kind, []):
        if is_due:
            value = str(fields.get(label) or "").strip()
            return value or None
    return None


async def raise_item(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    kind: str,
    title: str,
    fields: dict[str, Any],
    recipient_contact_ids: list[str] | None = None,
    raised_from_id: str | None = None,
    user_id: str | None = None,
) -> RegisterItem:
    """Create a register item and lay its workflow spine down.

    Refuses a kind it does not know and any raise form missing a field
    the kind marks required - the delivery block on an RFQ is not
    optional, because a supplier cannot quote freight to nowhere.
    """
    if kind not in templates.KINDS:
        raise WorkflowError(f"Unknown register kind {kind!r}")
    missing = [label for label in templates.REQUIRED.get(kind, ()) if not str(fields.get(label) or "").strip()]
    if missing:
        raise WorkflowError("These are needed before it can be raised: " + ", ".join(missing))

    # A MONEY FIELD MUST BE READABLE AS MONEY. "50k", "approx 50,000" and
    # "$50,000 + GST" all used to store as 0, and 0 sits below the $3,000
    # tier - so the quote gate quietly stopped asking for competitive
    # prices on a fifty-thousand-dollar package. Refuse at the form rather
    # than guess, and say what was typed so the fix is obvious.
    from app.core.money_text import parse_amount

    unreadable = [
        f["label"]
        for f in templates.spec_for(kind)["fields"]
        if f.get("type") == "money"
        and str(fields.get(f["label"]) or "").strip()
        and parse_amount(fields.get(f["label"])) is None
    ]
    if unreadable:
        raise WorkflowError(
            "These need to be an amount - write it in dollars (50000, $50,000 or 50k): " + ", ".join(unreadable)
        )

    # Never trust the client with the server-owned keys, and never hand
    # PostgreSQL a control character.
    fields = sanitise_fields(fields)
    title = single_line(clean_text(title))

    # MAX+1 races under concurrent raises; the unique constraint turns the
    # loser into an IntegrityError, so retry rather than 500.
    from sqlalchemy.exc import IntegrityError

    for _attempt in range(25):
        reference = await _next_reference(session, project_id, kind)
        item = RegisterItem(
            project_id=project_id,
            kind=kind,
            reference=reference,
            title=(title or "").strip()[:500] or reference,
            due_date=_due_from_fields(kind, fields),
            fields=fields,
            recipient_contact_ids=[str(c) for c in (recipient_contact_ids or [])],
            raised_from_id=raised_from_id,
            created_by=user_id,
        )
        for position, spec in enumerate(templates.FLOWS.get(kind, [])):
            item.steps.append(
                RegisterStep(
                    position=position,
                    step_type=spec["t"],
                    name=spec["name"],
                    owner=spec.get("owner", ""),
                    branches=spec.get("branches", {}),
                    raises_kind=_raises_kind(spec["name"]),
                )
            )
        session.add(item)
        try:
            await session.flush()
            break
        except IntegrityError:
            await session.rollback()
            continue
    else:
        raise WorkflowError("Could not allocate a reference - try again")

    # The record itself belongs to the platform's own register, so every
    # other module sees real data instead of a parallel copy. A missing
    # sibling module leaves the item workflow-only rather than refusing.
    from app.modules.register_workflow import native

    linked = await native.create_native(
        session,
        kind=kind,
        project_id=project_id,
        reference=item.reference,
        title=item.title,
        fields=fields,
        recipient_contact_ids=item.recipient_contact_ids,
        user_id=user_id,
    )
    if linked:
        item.linked_entity_type, item.linked_entity_id = linked
        await session.flush()

    # Close the interlink loop both ways: the source step records what it
    # raised, so nobody types the VO number twice.
    if raised_from_id:
        await _mark_source_raised(session, raised_from_id, kind, item.reference)

    from app.modules.register_workflow import events

    events.item_raised(item)
    _announce_current_gate(item)
    return item


def _announce_current_gate(item: RegisterItem) -> None:
    """If the step now standing is a gate, say so on the bus.

    Called after every action that can MOVE the current step. A gate the
    platform never mentions is a gate somebody finds a week later.
    """
    from app.modules.register_workflow import events

    current = next((s for s in _ordered(item) if (s.state or "open") == "open"), None)
    if current is not None and current.step_type == "gate":
        events.gate_open(item, current)


def _raises_kind(step_name: str) -> str | None:
    """Which register a step starts, if any (the ＋ Raise button)."""
    low = step_name.lower()
    patterns = {
        "variation": r"variation raised",
        "delay": r"delay notice raised",
        "order": r"order card raised",
        "rfq": r"rfq raised",
        "rfi": r"rfi raised",
    }
    for kind, rx in patterns.items():
        if re.search(rx, low):
            return kind
    return None


async def _mark_source_raised(session: AsyncSession, source_item_id: str, kind: str, reference: str) -> None:
    try:
        src = await session.get(RegisterItem, uuid.UUID(str(source_item_id)))
    except (ValueError, AttributeError):
        return
    if src is None:
        return
    for st in src.steps:
        if st.raises_kind == kind and not st.raised_reference:
            st.raised_reference = reference
            break
    await session.flush()


# ── Stepping the workflow ────────────────────────────────────────────────


def _ordered(item: RegisterItem) -> list[RegisterStep]:
    return sorted(item.steps, key=lambda s: s.position)


async def _gate_check(session: AsyncSession, item: RegisterItem, step: RegisterStep) -> None:
    """Subject-specific gate rules. Raises GateBlocked when unsatisfied.

    The RFQ compare gate is the one with teeth: it asks the SAME quote
    rule the award enforces, so a package cannot pass the compare step
    and then be refused at award (or worse, the reverse).
    """
    if step.step_type != "gate":
        return
    if item.kind != "rfq" or "quotes compared" not in step.name.lower():
        return
    linked = item.linked_entity_id
    if not linked or item.linked_entity_type != "rfq":
        # No native RFQ behind this item, so there is nothing to count
        # prices in. This used to return silently, which ticked the
        # compare gate on a $50k package with no quotes at all - exactly
        # the state a failed native create leaves behind.
        raise GateBlocked(
            "This package has no RFQ record behind it, so the quotes cannot be "
            "counted. Re-raise it, or pass the gate with a written reason.",
            {"gate": "quotes", "can_force": True, "quote_gate": None},
        )
    try:
        from app.modules.rfq_bidding.models import RFQ
        from app.modules.rfq_bidding.service import RFQService
    except ImportError:  # pragma: no cover - rfq module absent
        return
    rfq = (await session.execute(select(RFQ).where(RFQ.id == uuid.UUID(linked)))).scalar_one_or_none()
    if rfq is None:
        return
    gate = RFQService(session).quote_gate_status(rfq)
    if not gate["passes"]:
        raise GateBlocked(
            f"The quote rule for a package of {gate['value']} requires "
            f"{gate['required']} written price(s); {gate['counted']} recorded. "
            "(A supplier asking a question does not count as a quote.)",
            {"gate": "quotes", "can_force": True, "quote_gate": gate},
        )


async def complete_step(
    session: AsyncSession,
    step_id: uuid.UUID,
    *,
    user_id: str | None,
    override_reason: str | None = None,
) -> RegisterStep:
    """Tick one step. In order, gates signed, routes refused here."""
    step = await session.get(RegisterStep, step_id)
    if step is None:
        raise WorkflowError("Step not found")
    item = await session.get(RegisterItem, step.item_id)
    if item is None:
        raise WorkflowError("Register item not found")
    ensure_not_withdrawn(item, "tick anything on it")

    if step.state == "done":
        raise WorkflowError("That step is already done")
    if step.step_type == "route":
        raise WorkflowError("This is a decision, not a tick - choose which way the item goes.")

    # IN ORDER. Ticking step 5 while step 3 is open would make the record
    # claim work happened that did not.
    for earlier in _ordered(item):
        if earlier.position >= step.position:
            break
        if earlier.state == "open":
            raise WorkflowError(f"Finish the earlier steps first - '{earlier.name}' is still open.")

    if step.step_type == "gate":
        # BLOCK FIRST, THEN LET A REASON FORCE IT. A reason is permission
        # to pass a gate that ACTUALLY refused - never permission to skip
        # asking. Taking the reason as a bypass had two costs: the rule
        # was never consulted (a $50k package with one quote sailed
        # through), and a gate that would have passed clean was branded
        # "passed below the rule" forever.
        reason = (override_reason or "").strip()
        try:
            await _gate_check(session, item, step)
        except GateBlocked as blocked:
            if not reason:
                raise
            bad = gate_reason_bad(reason)
            if bad:
                # Still a refusal, and still forceable - the UI re-asks
                # rather than dead-ending on a one-character answer.
                raise GateBlocked(bad, {**blocked.detail, "reason_rejected": True}) from None
            step.override_reason = reason[:300]
            logger.warning(
                "register_workflow.gate_forced %s",
                {
                    "item": str(item.id),
                    "step": step.name,
                    "reason": step.override_reason,
                    "by": user_id,
                },
            )
        else:
            # It passed on its own merits. Anything typed into the
            # override box is discarded rather than recorded, so the file
            # never claims a clean pass was forced.
            step.override_reason = None

    step.state = "done"
    step.completed_by = user_id
    step.completed_at = _now()
    await _recompute_status(session, item)
    await session.flush()
    _announce_current_gate(item)
    return step


async def uncomplete_step(session: AsyncSession, step_id: uuid.UUID) -> RegisterStep:
    """Undo, in reverse order only - history is not rewritten sideways."""
    step = await session.get(RegisterStep, step_id)
    if step is None:
        raise WorkflowError("Step not found")
    item = await session.get(RegisterItem, step.item_id)
    if item is None:
        raise WorkflowError("Register item not found")
    ensure_not_withdrawn(item, "undo anything on it")
    for later in _ordered(item):
        if later.position <= step.position:
            continue
        # ANY disposed-of later step blocks the undo, not just a done one:
        # re-opening step 1 under a step 2 that was marked not-required
        # leaves the record claiming work happened out of order.
        if later.state != "open":
            raise WorkflowError(f"Undo the later steps first - '{later.name}' is already dealt with.")
    step.state = "open"
    step.completed_by = None
    step.completed_at = None
    # The override reason belongs to the tick that needed it. Left behind,
    # it re-attached to a later CLEAN pass and the file then permanently
    # claimed a gate was forced when it was not.
    step.override_reason = None
    # UNDOING A DECISION PUTS THE OPTIONS BACK. Refusing the undo outright
    # left one mis-click on a four-way fork with no fix inside the app.
    # The branch's still-open follow-on steps come off with it - otherwise
    # the loop above (any later step already dealt with blocks the undo)
    # is the only thing standing between a second choice and BOTH paths
    # sitting on one item.
    if step.step_type == "route":
        undone = step.chosen_branch
        stripped = _strip_branch_steps(item, step)
        step.chosen_branch = None
        logger.info(
            "register_workflow.route_undone %s",
            {"item": str(item.id), "route": step.name, "was": undone, "removed": stripped},
        )
    await _recompute_status(session, item)
    await session.flush()
    return step


def _strip_branch_steps(item: RegisterItem, route: RegisterStep) -> list[str]:
    """Take the chosen branch's still-open steps back off the item.

    Matched by name, one removal per name the branch contributed, and
    only after the route's own position - a step of the same name that
    was already on the spine before the fork is not the branch's to take.
    """
    names = list((route.branches or {}).get(route.chosen_branch or "", []))
    if not names:
        return []
    candidates = [s for s in _ordered(item) if s.position > route.position and s.state == "open"]
    removed: list[RegisterStep] = []
    for name in names:
        match = next((s for s in candidates if s.name == name and s not in removed), None)
        if match is not None:
            removed.append(match)
    for s in removed:
        # Through the relationship, not session.delete: the caller reads
        # ``item.steps`` straight after and a bare delete leaves the
        # loaded collection showing the branch it just undid.
        item.steps.remove(s)
    # Close the gaps so the next insert lands where the person is looking.
    for index, s in enumerate(_ordered(item)):
        s.position = index
    return [s.name for s in removed]


async def mark_not_required(session: AsyncSession, step_id: uuid.UUID, *, user_id: str | None) -> RegisterStep:
    """⊘ a step that does not apply. NEVER a gate: a gate is a hold point
    somebody signs, and one you can wave away is not a hold point."""
    step = await session.get(RegisterStep, step_id)
    if step is None:
        raise WorkflowError("Step not found")
    item = await session.get(RegisterItem, step.item_id)
    if item is not None:
        ensure_not_withdrawn(item, "mark anything on it not-required")
    if step.step_type == "gate":
        raise WorkflowError(
            "A gate is a hold point somebody signs - it cannot be waived. If it does "
            "not apply to this job, take it off the workflow with a written reason."
        )
    if step.step_type == "route":
        raise WorkflowError("A decision cannot be marked not-required - choose a way.")
    if step.state == "done":
        raise WorkflowError("That step is already done")
    step.state = "not_required"
    step.completed_by = user_id
    step.completed_at = _now()
    item = await session.get(RegisterItem, step.item_id)
    if item is not None:
        await _recompute_status(session, item)
    await session.flush()
    return step


async def take_route(session: AsyncSession, step_id: uuid.UUID, branch: str, *, user_id: str | None) -> RegisterStep:
    """Choose a branch: tick the route and APPEND that path's steps.

    The record then shows the path actually taken, not every path that
    was once possible.
    """
    step = await session.get(RegisterStep, step_id)
    if step is None:
        raise WorkflowError("Step not found")
    routed_item = await session.get(RegisterItem, step.item_id)
    if routed_item is not None:
        ensure_not_withdrawn(routed_item, "choose a way for it")
    if step.step_type != "route":
        raise WorkflowError("That step is not a decision")
    if step.state == "done":
        raise WorkflowError("That decision has already been made")
    branches = step.branches or {}
    if branch not in branches:
        raise WorkflowError(
            "Unknown branch - choose one of: " + ", ".join(sorted(branches)) if branches else "No branches"
        )
    item = await session.get(RegisterItem, step.item_id)
    if item is None:
        raise WorkflowError("Register item not found")
    for earlier in _ordered(item):
        if earlier.position >= step.position:
            break
        if earlier.state == "open":
            raise WorkflowError(f"Finish the earlier steps first - '{earlier.name}' is still open.")

    step.state = "done"
    step.chosen_branch = branch
    step.completed_by = user_id
    step.completed_at = _now()

    tail = max((s.position for s in item.steps), default=step.position)
    for offset, name in enumerate(branches[branch], start=1):
        item.steps.append(
            RegisterStep(
                position=tail + offset,
                step_type="step",
                name=name,
                raises_kind=_raises_kind(name),
            )
        )
    await _recompute_status(session, item)
    await session.flush()
    return step


#: A decision a person can actually stand in front of and choose from.
#: Past this it is not a fork, it is a form - and every one of these paths
#: is stored in a JSON column that is read on every render of the item.
MAX_BRANCHES = 12
MAX_BRANCH_STEPS = 20


def _clean_branches(branches: dict[str, Any]) -> dict[str, list[str]]:
    """Bound and clean a route's paths.

    ``branches`` arrives as a free-shape JSON object straight off the
    request. Unbounded, a single call could store a few hundred kilobytes
    of nonsense on an item and every subsequent render would carry it -
    and the picker would offer two hundred buttons nobody can choose
    between. Capped here rather than in the schema, so the CAP is a rail
    and not a detail of one request model.
    """
    # REFUSED, not quietly trimmed. A cap that truncates stores a mangled
    # decision the person never sees and cannot tell from the one they
    # meant to make; a cap that refuses is a sentence they can act on.
    if len(branches) > MAX_BRANCHES:
        raise WorkflowError(
            f"A decision can offer at most {MAX_BRANCHES} paths - {len(branches)} is a form, not a fork."
        )
    out: dict[str, list[str]] = {}
    for label, steps in branches.items():
        name = single_line(str(label))[:80].strip()
        if not name:
            continue
        if not isinstance(steps, (list, tuple)):
            steps = []
        if len(steps) > MAX_BRANCH_STEPS:
            raise WorkflowError(
                f"The path {name!r} carries {len(steps)} steps - {MAX_BRANCH_STEPS} is the most a branch can add."
            )
        out[name] = [single_line(str(s))[:300].strip() for s in steps if str(s or "").strip()]
    if not out:
        raise WorkflowError("A decision needs the paths it can take - pick one from the library.")
    return out


async def add_step(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    name: str,
    step_type: str = "step",
    owner: str = "",
    after_position: int | None = None,
    branches: dict[str, list[str]] | None = None,
) -> RegisterStep:
    """Slot the next action in where the person actually is.

    Inserted AFTER ``after_position`` (default: after the last done step),
    because the thing you just decided to do comes next, not at the end.
    """
    item = await session.get(RegisterItem, item_id)
    if item is None:
        raise WorkflowError("Register item not found")
    ensure_not_withdrawn(item, "add a step to it")
    if step_type not in ("step", "gate", "route"):
        raise WorkflowError("A step, a gate or a decision - nothing else")
    # A DECISION WITHOUT OPTIONS IS NOT A DECISION. Adding a route with no
    # branches would render a fork whose picker was empty and which
    # nothing could ever get past, so the branches come with it or the
    # add is refused.
    if step_type == "route" and not branches:
        raise WorkflowError("A decision needs the paths it can take - pick one from the library.")
    if step_type == "route":
        branches = _clean_branches(branches or {})
    ordered = _ordered(item)
    done = [s.position for s in ordered if (s.state or "open") != "open"]
    last_done = max(done) if done else -1
    highest = max((s.position for s in ordered), default=-1)
    if after_position is None:
        after_position = last_done
    # CLAMP. An unbounded value renumbered completed steps and let an open
    # step sit BEFORE signed history, so the item's "current step" pointed
    # at something earlier than work already done.
    if after_position < last_done or after_position > highest:
        raise WorkflowError("A new step goes after the work already done and no further than the end.")
    for s in ordered:
        if s.position > after_position:
            s.position += 1
    new = _build_step(
        position=after_position + 1,
        step_type=step_type,
        name=name,
        owner=owner,
        branches=branches,
    )
    # Append through the relationship, not session.add: the caller holds
    # this item and reads ``item.steps`` straight after, and a bare add
    # leaves the loaded collection stale until a refresh nobody does.
    item.steps.append(new)
    await _recompute_status(session, item)
    await session.flush()
    return new


def _build_step(
    *,
    position: int,
    step_type: str,
    name: str,
    owner: str = "",
    branches: dict[str, list[str]] | None = None,
) -> RegisterStep:
    """One fresh step row, the way ``add_step`` makes it.

    ``configure_steps`` builds its rewritten list through the same
    constructor so a decision added by either door carries the same
    fields (bounded name/owner, a COPY of its branches, the raise it
    starts). Two builders drifted once - the configurator forgot
    ``raises_kind`` - and the ＋ Raise button vanished off rewritten
    flows.
    """
    return RegisterStep(
        position=position,
        step_type=step_type,
        name=name.strip()[:300],
        owner=(owner or "")[:60],
        branches=dict(branches or {}),
        raises_kind=_raises_kind(name),
    )


async def update_item(
    session: AsyncSession,
    item: RegisterItem,
    *,
    title: str | None = None,
    fields: dict[str, Any] | None = None,
    recipient_contact_ids: list[str] | None = None,
) -> RegisterItem:
    """Correct a raised item - a typo, a wrong date, a changed quantity.

    THE MONEY RAIL RIDES HERE, not on the caller. The quote gate tiers
    off max(estimate, every standing price), so lowering the estimate on
    an ISSUED package is a gate bypass dressed as an admin correction: a
    $50,000 package holding one $2,900 quote drops to $2,900, under the
    $3,000 tier, and awards on a single price. The native RFQ service has
    refused this for its own screen since the stress pass; editing the
    register item reached the same figure through a different door, and a
    rail enforced in one code path is not a rail.

    Raising the estimate is always allowed - it can only ask for MORE
    quotes. A package nobody has been asked about yet is freely editable.
    """
    ensure_not_withdrawn(item, "edit it")
    if title is not None:
        item.title = clean_text(title)[:500]

    if fields is not None:
        # Reserved keys stay as the server left them: an edit must not be
        # a way to rewrite the send log or the attachment list.
        cleaned = sanitise_fields(fields, previous=item.fields or {})
        await _guard_estimate(session, item, cleaned)
        item.fields = cleaned
        item.due_date = _due_from_fields(item.kind, cleaned)
        # The native record is what the gate and the award actually read.
        # Leaving it behind meant a corrected value showed on the register
        # and the OLD one still drove the rule.
        await _push_estimate_to_native(session, item, cleaned)

    if recipient_contact_ids is not None:
        item.recipient_contact_ids = [str(c) for c in recipient_contact_ids]

    await session.flush()
    return item


async def _guard_estimate(session: AsyncSession, item: RegisterItem, incoming: dict[str, Any]) -> None:
    """Refuse a downward correction to an issued package's value."""
    if item.kind != "rfq" or item.linked_entity_type != "rfq" or not item.linked_entity_id:
        return
    # HAS ANYBODY ACTUALLY BEEN ASKED? The native rail keys off the RFQ
    # status, and this module creates its RFQs as "published" the moment
    # the item is raised - before a single email has gone out. Applied
    # blindly that locks the figure seconds after typing it, with no way
    # back but cancelling the package: the same "no legitimate exit" shape
    # as a gate that cannot be taken off a workflow.
    #
    # The send log is the honest test, and it is what the rail's own
    # reasoning appeals to - "out with suppliers". Nothing sent, nothing
    # asked, so the estimate is still a guess and freely correctable.
    from app.modules.register_workflow.emailing import SEND_LOG_KEY

    if not (item.fields or {}).get(SEND_LOG_KEY):
        return
    try:
        from app.modules.rfq_bidding.models import RFQ
        from app.modules.rfq_bidding.service import RFQService
    except ImportError:  # pragma: no cover - rfq module absent
        return
    try:
        rfq = (
            await session.execute(select(RFQ).where(RFQ.id == uuid.UUID(str(item.linked_entity_id))))
        ).scalar_one_or_none()
    except (ValueError, AttributeError):
        return
    if rfq is None:
        return
    from fastapi import HTTPException

    try:
        RFQService(session)._reject_lowering_the_estimate(
            rfq, {"estimated_value": str(incoming.get("Estimated value $") or "")}
        )
    except HTTPException as exc:
        detail = exc.detail
        raise WorkflowError(detail if isinstance(detail, str) else str(detail.get("error", detail))) from None


async def _push_estimate_to_native(session: AsyncSession, item: RegisterItem, fields: dict[str, Any]) -> None:
    """Carry a corrected value onto the RFQ the gate actually reads."""
    if item.kind != "rfq" or item.linked_entity_type != "rfq" or not item.linked_entity_id:
        return
    value = str(fields.get("Estimated value $") or "").strip()
    if not value:
        return
    try:
        from app.modules.rfq_bidding.models import RFQ

        rfq = (
            await session.execute(select(RFQ).where(RFQ.id == uuid.UUID(str(item.linked_entity_id))))
        ).scalar_one_or_none()
        if rfq is None:
            return
        meta = dict(rfq.metadata_ or {})
        meta["estimated_value"] = value
        rfq.metadata_ = meta
        await session.flush()
    except Exception:  # noqa: BLE001 - the register edit still stands
        logger.warning("Could not push the corrected value onto %s", item.reference, exc_info=True)


async def _recompute_status(session: AsyncSession, item: RegisterItem) -> None:
    """An item is closed when nothing is left open, unless it is withdrawn.

    Withdrawn is TERMINAL and derived from nothing: it was put there by a
    person with a reason. Recomputing over the top of it would quietly
    resurrect an item into the open register the moment anything touched
    its steps.

    ``state`` carries a PYTHON-side default, so a step that has not been
    flushed yet still reads ``None`` - and ``None != "open"`` was true of
    every freshly appended step. That made configure_steps, take_route
    and add_step mark the item CLOSED with its whole new path still to
    do: the item then vanished from the open register, the overdue count
    and the performance figures. Treat an unflushed step as open.
    """
    if item.status == WITHDRAWN:
        return
    item.status = "closed" if all((s.state or "open") != "open" for s in item.steps) else "open"


# ── Raised in error: delete it, or withdraw it ───────────────────────────
#
# THE RAIL: something nobody outside has seen can be deleted; something
# that has already left the building must be WITHDRAWN, not erased.
#
# Until now there was no third option and no first one either - junk
# raised by mistake was permanent, and six test items had to be deleted
# straight out of the database. That is the wrong fix twice over: it is
# not available to the person who made the mistake, and it leaves the
# native record, the reciprocal links and the evidence folder behind.
#
# What is NEVER given back is the reference. The counter is a separate
# row and nothing here touches it, so deleting the newest RFQ leaves the
# next raise on the NEXT number: a supplier holding REG-RFQ-25406-0005
# must never receive a different package under the same reference.


def withdrawal(item: RegisterItem) -> dict[str, Any]:
    """The withdrawal stamp on this item - {} when it is not withdrawn."""
    raw = (item.fields or {}).get(WITHDRAWN_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def is_withdrawn(item: RegisterItem) -> bool:
    return item.status == WITHDRAWN


def ensure_not_withdrawn(item: RegisterItem, action: str) -> None:
    """Refuse a mutation on a withdrawn item, saying when and why it went.

    A withdrawn RFQ that could still be emailed, quoted or awarded is not
    withdrawn at all - it is just badly labelled. Every door into the
    item's state comes through here, and the message names the reopen so
    the answer is never "you cannot".
    """
    if item.status != WITHDRAWN:
        return
    info = withdrawal(item)
    when = str(info.get("at") or "")[:10]
    why = " ".join(str(info.get("reason") or "").split())
    said = f"{item.reference} was withdrawn"
    if when:
        said += f" on {when}"
    if why:
        said += f" - {why}"
    raise WorkflowError(f"{said}. Reopen it before you {action}.")


def _and_list(parts: list[str]) -> str:
    """ "a", "a and b", "a, b and c" - the way a person would say it."""
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _plural(count: int, one: str, many: str = "") -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


async def _rfq_activity(session: AsyncSession, entity_id: str) -> tuple[int, bool]:
    """(quotes recorded, awarded?) on the native RFQ behind an item."""
    from sqlalchemy import func

    from app.modules.rfq_bidding.models import RFQAward, RFQBid

    rfq_id = uuid.UUID(str(entity_id))
    quotes = (
        await session.execute(select(func.count()).select_from(RFQBid).where(RFQBid.rfq_id == rfq_id))
    ).scalar_one()
    award = (await session.execute(select(RFQAward.id).where(RFQAward.rfq_id == rfq_id))).scalar_one_or_none()
    return int(quotes or 0), award is not None


async def deletion_blockers(session: AsyncSession, item: RegisterItem) -> list[str]:
    """Everything that makes this item a record rather than a mistake.

    Phrased as the second half of "This RFQ ..." so the refusal reads as
    one sentence. An empty list means nobody outside this workspace has
    seen the item and it can be erased.

    FAILS CLOSED. If a check cannot be run - a sibling module mid-
    migration, a query that throws - the item is not deletable. The cost
    of a wrong refusal is one withdrawal; the cost of a wrong deletion is
    a hole in the audit trail.
    """
    from app.modules.register_workflow import emailing, tracking

    blockers: list[str] = []

    sends = emailing.send_log(item)
    if sends:
        blockers.append("has been emailed to " + _plural(len(sends), "supplier" if item.kind == "rfq" else "recipient"))

    try:
        replies = await tracking._replies_for(session, item)
    except Exception:  # noqa: BLE001 - see FAILS CLOSED above
        logger.warning("Could not check replies before deleting %s", item.reference, exc_info=True)
        blockers.append("could not be checked for replies")
        replies = []
    if replies:
        blockers.append(f"has {_plural(len(replies), 'reply', 'replies')} on file")

    if item.linked_entity_type == "rfq" and item.linked_entity_id:
        try:
            quotes, awarded = await _rfq_activity(session, item.linked_entity_id)
        except Exception:  # noqa: BLE001 - see FAILS CLOSED above
            logger.warning("Could not check quotes on %s", item.reference, exc_info=True)
            blockers.append("could not be checked for quotes")
            quotes, awarded = 0, False
        if quotes:
            blockers.append(f"has {_plural(quotes, 'quote')}")
        if awarded:
            blockers.append("has been awarded")

    children = (
        (await session.execute(select(RegisterItem.reference).where(RegisterItem.raised_from_id == str(item.id))))
        .scalars()
        .all()
    )
    if children:
        blockers.append(f"is what {_and_list([str(c) for c in children[:3]])} was raised from")

    return blockers


def deletion_refusal(item: RegisterItem, blockers: list[str]) -> str:
    """The 409's one-sentence answer, naming what actually stops it."""
    kind = templates.KIND_PREFIX.get(item.kind, item.kind.upper())
    return f"This {kind} {_and_list(blockers)} - withdraw it instead of deleting it."


def raised_by(item: RegisterItem, user_id: str | None) -> bool:
    """Did THIS caller raise this item?

    Fails closed on either side being blank: an item with no
    ``created_by`` (older rows, an import) belongs to nobody, so nobody
    gets the raiser's shortcut on it and it takes a manager to delete.
    """
    mine = str(user_id or "").strip().lower()
    raiser = str(item.created_by or "").strip().lower()
    return bool(mine and raiser and mine == raiser)


def foreign_delete_refusal(item: RegisterItem) -> str:
    """The 403's answer: not your mistake to erase, and what to do instead."""
    return f"{item.reference} was raised by another person - only a manager can delete it. You can withdraw it instead."


async def delete_item(session: AsyncSession, item: RegisterItem) -> None:
    """Erase an item nobody has seen, and everything hanging off it.

    Steps go with it through the ORM cascade. What does NOT cascade, and
    what a raw ``DELETE FROM`` in the database missed every time, is the
    rest: the reciprocal link sitting on the far end of an item link, the
    native record this raise created (a published RFQ nobody asked for is
    junk on the RFQ register too), and the evidence folder on disk.

    Call ``deletion_blockers`` first - this does not re-check.
    """
    import shutil

    from app.modules.register_workflow import emailing, linking

    # The far end of every item link. Leaving it behind renders as
    # "linked to REG-RFQ-25406-0005" pointing at nothing.
    for link in linking.links_of(item):
        if link.get("type") != "item" or not link.get("target_id"):
            continue
        try:
            target = await session.get(RegisterItem, uuid.UUID(str(link["target_id"])))
        except (ValueError, TypeError):
            target = None
        if target is None:
            continue
        back = [
            x for x in linking.links_of(target) if not (x.get("type") == "item" and x.get("target_id") == str(item.id))
        ]
        fields = dict(target.fields or {})
        fields[linking.LINKS_KEY] = back
        target.fields = fields

    if item.linked_entity_type and item.linked_entity_id:
        from app.modules.register_workflow import native

        await native.delete_native(session, item.linked_entity_type, item.linked_entity_id)

    folder = (emailing.ATTACH_ROOT / str(item.id)).resolve()
    item_id = item.id
    await session.delete(item)
    await session.flush()

    # The files last, and only once the row is gone: a failed delete must
    # not leave a live item whose evidence has been shredded.
    try:
        if folder.is_dir():
            shutil.rmtree(folder)
    except OSError:  # pragma: no cover - a locked file is not a failure
        logger.warning("Evidence folder for %s could not be removed", item_id, exc_info=True)


async def withdraw_item(session: AsyncSession, item: RegisterItem, *, reason: str, user_id: str | None) -> RegisterItem:
    """Take an issued item out of play WITHOUT erasing it.

    The reason is validated exactly the way a gate override is: this is
    the same kind of act - a person overruling the ordinary course, on
    the record, in words somebody can read in six weeks.
    """
    if is_withdrawn(item):
        raise WorkflowError(f"{item.reference} is already withdrawn.")
    bad = gate_reason_bad(reason)
    if bad:
        raise WorkflowError(bad)

    text = " ".join(str(reason).split())[:2000]
    stamp = _now()
    fields = dict(item.fields or {})
    fields[WITHDRAWN_KEY] = {"reason": text, "at": stamp, "by": str(user_id) if user_id else None}
    item.fields = fields
    item.status = WITHDRAWN

    # THE AUDIT LINE GOES IN THE STEP TRAIL, where the rest of this
    # item's history already lives - so "what happened to this?" is
    # answered by the same list that answers everything else about it.
    ordered = _ordered(item)
    step = _build_step(
        position=max((s.position for s in ordered), default=-1) + 1,
        step_type="step",
        name="Withdrawn",
    )
    step.state = "done"
    step.completed_by = user_id
    step.completed_at = stamp
    step.override_reason = text[:300]
    item.steps.append(step)
    await session.flush()
    logger.info(
        "register_workflow.withdrawn %s",
        {"item": str(item.id), "reference": item.reference, "by": user_id, "reason": text},
    )
    return item


async def reopen_item(session: AsyncSession, item: RegisterItem, *, reason: str, user_id: str | None) -> RegisterItem:
    """Put a withdrawn item back where it was - reason-gated both ways.

    Withdrawing by mistake is as easy as raising by mistake, and a
    terminal state with no way out is how people end up raising a second
    item that duplicates the first.
    """
    if not is_withdrawn(item):
        raise WorkflowError(f"{item.reference} is not withdrawn.")
    bad = gate_reason_bad(reason)
    if bad:
        raise WorkflowError(bad)

    text = " ".join(str(reason).split())[:2000]
    stamp = _now()
    fields = dict(item.fields or {})
    fields.pop(WITHDRAWN_KEY, None)
    item.fields = fields

    ordered = _ordered(item)
    step = _build_step(
        position=max((s.position for s in ordered), default=-1) + 1,
        step_type="step",
        name="Reopened",
    )
    step.state = "done"
    step.completed_by = user_id
    step.completed_at = stamp
    step.override_reason = text[:300]
    item.steps.append(step)

    # Back to whatever the trail says it is, not blindly to "open".
    item.status = "open"
    await _recompute_status(session, item)
    await session.flush()
    return item


# ── Reading ──────────────────────────────────────────────────────────────


def _days_until(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    try:
        return (date.fromisoformat(str(iso_date)[:10]) - date.today()).days
    except ValueError:
        return None


def item_payload(item: RegisterItem) -> dict[str, Any]:
    """One item as the workspace renders it, with the derived figures the
    UI must never compute for itself (progress, ball-in-court, overdue)."""
    steps = _ordered(item)
    done = [s for s in steps if s.state != "open"]
    current = next((s for s in steps if s.state == "open"), None)
    days = _days_until(item.due_date)
    gone = withdrawal(item)
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "kind": item.kind,
        "reference": item.reference,
        "title": item.title,
        "status": item.status,
        "due_date": item.due_date,
        "days_until_due": days,
        "is_overdue": bool(item.status == "open" and days is not None and days < 0),
        "fields": item.fields or {},
        # WHY IT IS NOT IN PLAY, on the row itself. A withdrawn item shows
        # in the closed view carrying its reason, so nobody has to open it
        # to find out what happened - or, worse, raise it again.
        "withdrawn_reason": str(gone.get("reason") or ""),
        "withdrawn_at": gone.get("at") or None,
        "withdrawn_by": gone.get("by") or None,
        "recipient_contact_ids": item.recipient_contact_ids or [],
        "raised_from_id": item.raised_from_id,
        "linked_entity_type": item.linked_entity_type,
        "linked_entity_id": item.linked_entity_id,
        "steps_total": len(steps),
        "steps_done": len(done),
        "current_step": current.name if current else None,
        # A gate always sits with US; anything waiting on a written answer
        # sits with THEM. This is the ball-in-court the register reports.
        # A withdrawn item is with NOBODY: it still carries open steps
        # (history is not rewritten), and counting those against a
        # supplier would keep chasing a package that was cancelled.
        "ball_in_court": (
            "nobody"
            if item.status == WITHDRAWN
            else "us"
            if current is None or current.step_type == "gate"
            else ("them" if re.search(r"receiv|acknowledg|response|answer|quotes", current.name, re.I) else "us")
        ),
        # WHO, by name, as well as WHICH SIDE. The us/them above is derived
        # from the step and drives the tracking maths; this is the person
        # it has actually been put on, the way the native RFI register
        # carries a ball_in_court beside its assignee. Derived stays
        # derived - an explicit assignment adds a name, it does not
        # silently rewrite the side the counters are built from.
        "ball_in_court_name": str((item.fields or {}).get("Ball in court") or "").strip(),
        "responsible": str((item.fields or {}).get("Responsible") or "").strip(),
        "steps": [
            {
                "id": str(s.id),
                "position": s.position,
                "type": s.step_type,
                "name": s.name,
                "owner": s.owner,
                "state": s.state,
                "branches": list((s.branches or {}).keys()),
                "chosen_branch": s.chosen_branch,
                "completed_at": s.completed_at,
                "completed_by": s.completed_by,
                "override_reason": s.override_reason,
                "raises_kind": s.raises_kind,
                "raised_reference": s.raised_reference,
            }
            for s in steps
        ],
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


async def item_payload_enriched(session: AsyncSession, item: RegisterItem) -> dict[str, Any]:
    """The item payload plus live native facts (quotes, gate, award, status).

    One call the workspace can render a whole row from - the register never
    asks the UI to stitch two modules' answers together.
    """
    from app.modules.register_workflow import native

    payload = item_payload(item)
    payload["native"] = await native.enrich(session, item.linked_entity_type, item.linked_entity_id)
    await _name_the_signers(session, payload)
    return payload


async def _name_the_signers(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Put a PERSON against every completed step, not a user id.

    ``completed_by`` stores the user's uuid, which is the right thing to
    store and the wrong thing to show: "who signed this gate" answered
    with ``7bed966d-6364-…`` is not an answer, and on a gate override -
    where the whole point is that somebody put their name to a reason -
    it defeats the record.

    One query for every id on the item, not one per step. The id is left
    on the payload untouched; ``completed_by_name`` is added beside it,
    falling back to the id when the account has since been deleted so the
    trail never goes blank.
    """
    steps = payload.get("steps") or []
    ids = {str(s["completed_by"]) for s in steps if s.get("completed_by")}
    if not ids:
        return
    # PARSE EACH ID ON ITS OWN. A single unparseable value (older rows
    # carry free-text ids) would otherwise throw inside the IN clause and
    # cost every OTHER signer on the item their name.
    lookup: list[uuid.UUID] = []
    for i in ids:
        try:
            lookup.append(uuid.UUID(i))
        except (ValueError, AttributeError, TypeError):
            continue
    names: dict[str, str] = {}
    if lookup:
        try:
            from app.modules.users.models import User

            rows = (await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(lookup)))).all()
            names = {str(r[0]): (r[1] or r[2] or "") for r in rows}
        except Exception:  # noqa: BLE001 - a naming nicety must never break the register
            logger.warning("Could not resolve step signers", exc_info=True)
    for s in steps:
        who = str(s.get("completed_by") or "")
        if who:
            s["completed_by_name"] = names.get(who) or who


async def list_items(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    kind: str | None = None,
    status: str | None = None,
) -> list[RegisterItem]:
    stmt = select(RegisterItem).where(RegisterItem.project_id == project_id)
    if kind:
        stmt = stmt.where(RegisterItem.kind == kind)
    if status == "closed":
        # "Show closed" is the one view a withdrawn item belongs in. It is
        # done with, the same as a closed one, and hiding it from BOTH
        # views would make an item somebody withdrew this morning
        # unreachable except by its direct link.
        stmt = stmt.where(RegisterItem.status.in_(("closed", WITHDRAWN)))
    elif status:
        stmt = stmt.where(RegisterItem.status == status)
    stmt = stmt.order_by(RegisterItem.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


#: The native registers a register item can mirror (native.create_native).
LINKED_ENTITY_TYPES: tuple[str, ...] = ("rfi", "rfq", "order", "variation")

#: How many native ids one reverse lookup may name. A page lists at most a
#: few hundred rows; anything past this is a runaway query string.
LINKED_LOOKUP_MAX_IDS = 500


async def linked_items(
    session: AsyncSession,
    project_id: uuid.UUID,
    entity_type: str,
    entity_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """The reverse lookup: which register items stand behind these native rows.

    The base modules (RFI list, purchase orders, bid packages) know their
    own ids and nothing about the registers; this answers "was this RFI
    raised from a register item, and which one" for a whole page in one
    call, keyed by the native id so a row can be decorated without a
    per-row round trip.

    ``entity_ids`` narrows to the rows actually on screen. An empty list
    means "nothing on screen" and answers nothing; ``None`` means the
    whole project.
    """
    stmt = select(RegisterItem).where(
        RegisterItem.project_id == project_id,
        RegisterItem.linked_entity_type == entity_type,
        RegisterItem.linked_entity_id.is_not(None),
    )
    if entity_ids is not None:
        wanted = [str(i).strip() for i in entity_ids if str(i).strip()][:LINKED_LOOKUP_MAX_IDS]
        if not wanted:
            return []
        stmt = stmt.where(RegisterItem.linked_entity_id.in_(wanted))
    stmt = stmt.order_by(RegisterItem.created_at.desc())
    items = list((await session.execute(stmt)).scalars().all())
    out: list[dict[str, Any]] = []
    for item in items:
        payload = item_payload(item)
        out.append(
            {
                "item_id": payload["id"],
                "reference": payload["reference"],
                "kind": payload["kind"],
                "status": payload["status"],
                "title": payload["title"],
                "due_date": payload["due_date"],
                "is_overdue": payload["is_overdue"],
                "linked_entity_id": payload["linked_entity_id"],
                "ball_in_court": payload["ball_in_court"],
            }
        )
    return out


async def summary(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Per-kind open/total/overdue counts - the workspace header."""
    items = await list_items(session, project_id)
    out: dict[str, Any] = {}
    for kind in templates.KINDS:
        mine = [i for i in items if i.kind == kind]
        payloads = [item_payload(i) for i in mine]
        out[kind] = {
            "total": len(mine),
            "open": sum(1 for p in payloads if p["status"] == "open"),
            "overdue": sum(1 for p in payloads if p["is_overdue"]),
            "with_them": sum(1 for p in payloads if p["ball_in_court"] == "them" and p["status"] == "open"),
            # Counted so the header can say "2 withdrawn" rather than
            # leaving the total looking wrong against the open count.
            "withdrawn": sum(1 for p in payloads if p["status"] == WITHDRAWN),
        }
    return out


async def prefill_from(session: AsyncSession, source_item_id: uuid.UUID, target_kind: str) -> dict[str, Any]:
    """The interlink: fields for a new item, carried from the source.

    "You never type the VO number twice" - the source's reference and its
    narrative land in the target's matching fields, prefixed so the new
    record says where it came from.
    """
    src = await session.get(RegisterItem, source_item_id)
    if src is None:
        raise WorkflowError("Source item not found")
    if target_kind not in templates.KINDS:
        raise WorkflowError(f"Unknown register kind {target_kind!r}")
    link = templates.LINKS.get(target_kind, {})
    fields: dict[str, Any] = {}
    if link.get("ref_into"):
        fields[link["ref_into"]] = src.reference
    if link.get("narrative_into"):
        narrative = ""
        for label in (
            "Question",
            "Description of change",
            "Materials / scope required",
            "Work that stopped",
            "Package",
        ):
            if str((src.fields or {}).get(label) or "").strip():
                narrative = str(src.fields[label]).strip()
                break
        fields[link["narrative_into"]] = f"From {src.reference}: {narrative or src.title}"
    # The delivery block travels wherever the target has one.
    for label in ("Delivery to", "Site contact", "Delivery window / site hours", "Delivery notes / access"):
        value = (src.fields or {}).get(label)
        if value and any(f[0] == label for f in templates.FIELDS.get(target_kind, [])):
            fields[label] = value
    return {
        "kind": target_kind,
        "raised_from_id": str(src.id),
        "raised_from_reference": src.reference,
        "title": f"From {src.reference}: {src.title}"[:500],
        "fields": fields,
        "recipient_contact_ids": list(src.recipient_contact_ids or []),
    }


# ── Performance: how the job is actually running ─────────────────────────


async def performance(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Closing speed, punctuality, the oldest open item, lost hours.

    Every figure is derived from the step trail, not from a field
    somebody remembered to fill in: an item is "closed" when its last
    step completed, and "on time" when that happened on or before the
    due date it carried.
    """
    items = await list_items(session, project_id)
    today = date.today()

    closed_durations: list[int] = []
    on_time = 0
    closed_with_due = 0
    oldest_open_days = 0
    oldest_open_ref = ""
    lost_hours = Decimal("0")

    for item in items:
        payload = item_payload(item)
        # A WITHDRAWN ITEM IS NOT A FIGURE. It was raised in error or
        # cancelled: counting its hours into the claim, or its age into
        # "oldest open", reports work that is not happening.
        if item.status == WITHDRAWN:
            continue
        if item.kind == "delay":
            raw = str((item.fields or {}).get("Duration (hrs)") or "").strip()
            try:
                lost_hours += Decimal(re.sub(r"[^\d.]", "", raw) or "0")
            except (InvalidOperation, ValueError):
                pass

        if payload["status"] == "closed":
            stamps = [s.completed_at for s in item.steps if s.completed_at]
            if stamps and item.created_at:
                try:
                    last = datetime.fromisoformat(max(stamps)).date()
                    closed_durations.append(max(0, (last - item.created_at.date()).days))
                    if item.due_date:
                        closed_with_due += 1
                        if last <= date.fromisoformat(item.due_date[:10]):
                            on_time += 1
                except ValueError:
                    pass
        elif item.created_at:
            age = (today - item.created_at.date()).days
            if age > oldest_open_days:
                oldest_open_days, oldest_open_ref = age, item.reference

    return {
        "open": sum(1 for i in items if i.status == "open"),
        "closed": sum(1 for i in items if i.status == "closed"),
        "avg_days_to_close": round(sum(closed_durations) / len(closed_durations), 1) if closed_durations else None,
        "closed_on_time_pct": round(on_time / closed_with_due * 100) if closed_with_due else None,
        "oldest_open_days": oldest_open_days or None,
        "oldest_open_reference": oldest_open_ref or None,
        # The claim number: hours the crew stood around, summed off the
        # delay register.
        "lost_hours": format(lost_hours, "f"),
    }


async def portfolio(session: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    """Open/overdue counts per job - where the heat is today."""
    try:
        from app.modules.projects.models import Project
    except ImportError:  # pragma: no cover
        return []
    # SCOPE IT. This took a user_id and never used it, so any register
    # reader got the name of every job in the deployment plus which ones
    # were running hot - and on a construction ERP a project name IS a
    # client name. `None` is the admin sentinel meaning "do not filter";
    # an empty set correctly returns nothing.
    from app.dependencies import accessible_project_ids

    stmt = select(RegisterItem.project_id).distinct()
    allowed = await accessible_project_ids(session, user_id)
    if allowed is not None:
        if not allowed:
            return []
        stmt = stmt.where(RegisterItem.project_id.in_(allowed))
    rows = (await session.execute(stmt)).scalars().all()
    out: list[dict[str, Any]] = []
    for pid in rows:
        name = (await session.execute(select(Project.name).where(Project.id == pid))).scalar_one_or_none()
        if name is None:
            continue  # project gone; its rows cascade away shortly
        payloads = [item_payload(i) for i in await list_items(session, pid)]
        out.append(
            {
                "project_id": str(pid),
                "project_name": name,
                "open": sum(1 for p in payloads if p["status"] == "open"),
                "overdue": sum(1 for p in payloads if p["is_overdue"]),
                "with_them": sum(1 for p in payloads if p["status"] == "open" and p["ball_in_court"] == "them"),
            }
        )
    out.sort(key=lambda r: (-r["overdue"], -r["open"], r["project_name"]))
    return out


async def configure_steps(
    session: AsyncSession,
    item_id: uuid.UUID,
    remaining: list[dict[str, Any]],
    *,
    retire_reason: str | None = None,
    user_id: str | None = None,
) -> RegisterItem:
    """Rewrite the REMAINING steps: reorder, rename, add, remove.

    Completed steps are history and are never touched - not reordered,
    not renamed, not removed. Whatever ``remaining`` says, it can only
    describe the work still to come, and it runs after the last finished
    step in the order given.

    Each entry: ``{"name": str, "type": "step"|"gate"|"route", "owner": str,
    "branches": {label: [step names]}}``. A step that is still on the list
    (matched BY NAME against the open steps) keeps its own type, owner
    and route branches - a rewrite cannot retype it or invent branches it
    was never given, and ``branches`` on a kept entry is ignored.

    A NEW entry typed ``route`` is a real decision, made the same way
    ``add_step`` makes one: its ``branches`` come with it or it is
    refused, because a fork with no paths is a dead end nothing can pass.

    A gate or a decision left OFF the list is retired rather than deleted:
    it stays on the record marked not-required, carrying ``retire_reason``
    forever. Without a reason it cannot be taken off at all.
    """
    item = await session.get(RegisterItem, item_id)
    if item is None:
        raise WorkflowError("Register item not found")
    ensure_not_withdrawn(item, "reconfigure its workflow")

    done = [s for s in _ordered(item) if s.state != "open"]
    open_steps = [s for s in _ordered(item) if s.state == "open"]
    open_names = {s.name for s in open_steps}

    cleaned: list[dict[str, Any]] = []
    # Steps are matched BY NAME - by the editor, by this rewrite and by the
    # compare gate - so two rows that differ only by case ("Send it" /
    # "send it") are one name wearing two coats: a typo'd variant that
    # would render as a second step and match nothing. The editor refuses
    # them; so does the server, or the rail lives in one place only. (A
    # genuine repeat - "Chased by phone" twice - is the same name and is
    # kept as it always was.)
    seen_names: dict[str, str] = {}
    for entry in remaining:
        name = str(entry.get("name") or "").strip()[:300]
        if not name:
            raise WorkflowError("Every step needs a name")
        low = name.casefold()
        other = seen_names.setdefault(low, name)
        if other != name:
            raise WorkflowError(
                f"'{name}' and '{other}' differ only by case - steps are matched by name, so each needs its own"
            )
        step_type = entry.get("type") if entry.get("type") in ("step", "gate", "route") else "step"
        branches: dict[str, list[str]] = {}
        if step_type == "route" and name not in open_names:
            # The one place the configurator may CREATE a decision. Same
            # rail as add_step: no paths, no decision.
            raw = entry.get("branches")
            if not raw or not isinstance(raw, dict):
                raise WorkflowError("A decision needs at least one path")
            branches = _clean_branches(raw)
        cleaned.append(
            {
                "name": name,
                "type": step_type,
                "owner": str(entry.get("owner") or "")[:60],
                "branches": branches,
            }
        )
    if not cleaned:
        raise WorkflowError("A workflow needs at least one step still to do")

    # A GATE or a ROUTE cannot be dropped or renamed SILENTLY. Renaming
    # one was the sharpest hole found: the compare gate is matched BY
    # NAME, so "Comparison complete" still rendered as a gate and still
    # ticked, while the quote rule it was supposed to enforce was never
    # consulted.
    #
    # But refusing outright left a gate that genuinely does not apply to
    # this job with no exit except an override - which then records that
    # the rule was passed below its threshold, a thing that did not
    # happen. So: taking one off is allowed WITH A WRITTEN REASON, and it
    # is retired in place, not deleted. The record keeps the hold point,
    # marked not-required, saying who took it off and why.
    protected = [s for s in open_steps if s.step_type in ("gate", "route")]
    kept = {e["name"] for e in cleaned}
    lost = [s for s in protected if s.name not in kept]
    retired: list[RegisterStep] = []
    if lost:
        reason = (retire_reason or "").strip()
        if not reason:
            raise WorkflowError(
                "These are hold points and decisions - they cannot be removed or "
                "renamed without a written reason: " + ", ".join(s.name for s in lost)
            )
        bad = gate_reason_bad(reason)
        if bad:
            raise WorkflowError(bad)
        for s in lost:
            s.state = "not_required"
            s.override_reason = f"Taken off this workflow: {reason[:300]}"
            s.completed_by = user_id
            s.completed_at = _now()
            retired.append(s)
            open_steps.remove(s)
        logger.warning(
            "register_workflow.hold_point_retired %s",
            {
                "item": str(item.id),
                "steps": [s.name for s in retired],
                "reason": reason[:300],
                "by": user_id,
            },
        )
        # Retired steps are history now, and history keeps its place.
        done = [s for s in _ordered(item) if s.state != "open"]

    # Snapshot what the old open steps knew (type, owner, route branches)
    # BEFORE dropping them, then remove them through the relationship -
    # ``session.delete`` alone leaves them in the loaded collection, so
    # the caller reading ``item.steps`` straight after would see both the
    # old and the new list.
    # Keyed by (name, position): two open steps sharing a name collapsed
    # into one entry, and a replay of the same payload silently retyped a
    # plain step into a gate.
    by_name: dict[str, dict[str, Any]] = {}
    for offset, s in enumerate(open_steps):
        by_name.setdefault(s.name, {"step_type": s.step_type, "owner": s.owner, "branches": s.branches, "seen": 0})
        _ = offset
    for s in open_steps:
        item.steps.remove(s)
    await session.flush()

    position = (max((s.position for s in done), default=-1)) + 1
    for entry in cleaned:
        previous = by_name.get(entry["name"])
        item.steps.append(
            _build_step(
                position=position,
                step_type=previous["step_type"] if previous else entry["type"],
                name=entry["name"],
                owner=entry["owner"] or (previous["owner"] if previous else ""),
                # A kept step keeps ITS branches; only a brand-new decision
                # brings its own (validated above).
                branches=previous["branches"] if previous else entry["branches"],
            )
        )
        position += 1
    await _recompute_status(session, item)
    await session.flush()
    return item
