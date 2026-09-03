# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register item emails - one tailored draft per recipient, preview-first.

The raise flow, whole: every ticked supplier gets their OWN draft, the
Notified block shows only the people THAT copy is addressed to - one
supplier is never shown the others - internal money never leaves the
building, and an RFI/variation/delay carries the orange fill-in RESPONSE
BOX so the reply comes back in writing, in the shape the register can
file.

ONE builder feeds preview, the Outlook draft and the .eml download -
what you preview is byte-for-byte what goes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.register_workflow import templates
from app.modules.register_workflow.models import RegisterItem

logger = logging.getLogger(__name__)

#: What the response box asks for, per kind (ported QRESPOND). RFQ and
#: toolbox have none - they are not asking for a form back.
RESPONSE_BOX: dict[str, list[str]] = {
    "rfi": ["Response", "Answered by", "Date"],
    "variation": ["Approved / not approved", "Client ref / VO no.", "Signed", "Date"],
    "delay": ["Acknowledged by", "Comments", "Date"],
}

#: Reserved key inside ``item.fields`` carrying the send log. Prefixed so
#: it can never collide with a form label (labels never start with "_").
SEND_LOG_KEY = "_send_log"
ATTACH_KEY = "_attachments"

#: Where item evidence lives on disk (mirrors the router's upload path).
ATTACH_ROOT = Path("uploads/register_workflow")


def attachment_paths(item: RegisterItem) -> tuple[list[str], list[str]]:
    """(paths that will ride the email, names of the ones that cannot).

    Only files marked ``email: true`` are candidates, and only ones that
    actually exist on disk are returned as paths - the email must never
    claim an attachment it did not carry. A missing file is reported so
    the caller can say so out loud rather than quietly dropping it.
    """
    ride: list[str] = []
    missing: list[str] = []
    for att in (item.fields or {}).get(ATTACH_KEY) or []:
        if not isinstance(att, dict) or not att.get("email"):
            continue
        name = str(att.get("filename") or "")
        if not name:
            continue
        # CONTAINMENT, not string trust: the stored name is reduced to a
        # bare filename and the resolved path must still sit inside this
        # item's own folder. Without this, a forged "../../../etc/passwd"
        # would ride out of the building as an email attachment.
        folder = (ATTACH_ROOT / str(item.id)).resolve()
        bare = Path(name).name
        if not bare or bare in {".", ".."}:
            missing.append(name)
            continue
        path = (folder / bare).resolve()
        if path.parent != folder:
            logger.warning("Attachment %r on %s escapes its folder - refused", name, item.reference)
            missing.append(name)
            continue
        if path.is_file():
            ride.append(str(path))
        else:
            missing.append(name)
    return ride, missing


class EmailingError(Exception):
    pass


async def _contact(session: AsyncSession, contact_id: str) -> tuple[str, str, str]:
    """(display name, first name, email) for one contact id."""
    try:
        from app.modules.contacts.models import Contact
    except ImportError:  # pragma: no cover
        raise EmailingError("The contacts module is not installed") from None
    try:
        cid = uuid.UUID(str(contact_id))
    except ValueError:
        raise EmailingError(f"Bad contact id {contact_id!r}") from None
    row = (await session.execute(select(Contact).where(Contact.id == cid))).scalar_one_or_none()
    if row is None:
        raise EmailingError("Contact not found")
    display = row.company_name or " ".join(x for x in [row.first_name, row.last_name] if x) or (row.primary_email or "")
    first = (row.first_name or (display.split()[0] if display else "")) or "there"
    return display, first, row.primary_email or ""


async def _all_recipients(session: AsyncSession, item: RegisterItem) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for cid in item.recipient_contact_ids or []:
        try:
            out.append(await _contact(session, str(cid)))
        except EmailingError:
            continue
    return out


async def build_item_email(
    session: AsyncSession,
    item: RegisterItem,
    *,
    contact_id: str | None = None,
    extra_to: list[str] | None = None,
    extra_note: str = "",
    email_ref: str = "",
) -> dict[str, Any]:
    """The email payload for one recipient of one register item.

    ``contact_id`` picks WHICH recipient's tailored copy (None = a copy
    addressed to nobody yet, for kinds with no directory recipient or for
    previewing before anyone is picked). The Notified block lists ONLY the
    addressees of this copy: naming everyone asked would hand each
    supplier its competitor list.
    """
    from app.modules.outlook_bridge import outbound

    kind = item.kind
    spec_fields = templates.FIELDS.get(kind, [])
    recipients = await _all_recipients(session, item)
    today = datetime.now(UTC).strftime("%d/%m/%Y")

    target: tuple[str, str, str] | None = None
    if contact_id:
        target = await _contact(session, contact_id)

    # Project line, the way the job is named.
    project_name = ""
    try:
        from app.modules.projects.models import Project

        project_name = (
            await session.execute(select(Project.name).where(Project.id == item.project_id))
        ).scalar_one_or_none() or ""
    except Exception:  # noqa: BLE001
        pass

    # Details pairs in the FORM's order - the reader gets the same document
    # the register holds (minus internal money, stripped in the builder AND
    # here, belt and braces). A value carrying tab-separated lines is
    # pasted Excel cells: it renders as a real TABLE, not a squashed
    # paragraph - the Materials table the suppliers actually price from.
    pairs: list[tuple[str, str]] = [("Reference", item.reference)]
    # THE MAIL'S OWN NUMBER, visible on the document. "Please see
    # REG-MSG-000042" is answerable in one search; "the email I sent you
    # Tuesday" is not. Peeked on preview, minted on draft.
    if email_ref:
        pairs.append(("Email ref", email_ref))
    tables: list[tuple[str, list[list[str]]]] = []
    for label, _t, _due, internal in spec_fields:
        if internal:
            continue
        value = str((item.fields or {}).get(label) or "").strip()
        if not value:
            continue
        lines = [ln for ln in value.splitlines() if ln.strip()]
        if len(lines) >= 2 and all("\t" in ln for ln in lines[:2]):
            # PAD RAGGED ROWS out to the widest one. Excel drops trailing
            # empty cells, and the final line loses its trailing tab to
            # the .strip() above, so a row whose last cell is blank
            # arrived NARROWER than the heading row - and the email then
            # rendered it with fewer cells than the columns it was meant
            # to line up under.
            grid = [ln.split("\t") for ln in lines]
            width = max(len(r) for r in grid)
            tables.append((label, [r + [""] * (width - len(r)) for r in grid]))
        else:
            pairs.append((label, value))

    company = target[0].upper() if target else ""
    subject_bits = (
        [templates.KIND_PREFIX.get(kind, kind.upper())]
        + ([company] if company else [])
        + [
            item.reference,
            item.title,
        ]
    )
    subject = " - ".join(b for b in subject_bits if b)

    ride, missing = attachment_paths(item)
    attached_names = [Path(p).name for p in ride]
    if missing:
        logger.warning("Attachments missing on disk for %s: %s", item.reference, missing)

    # WHO THIS EMAIL SAYS IT WENT TO - and it is only ever the people THIS
    # copy is addressed to, never the whole ask list.
    #
    # Listing everyone asked told each supplier exactly who they were
    # bidding against, which is their commercial advantage handed over for
    # free: a tailored RFQ never shows one supplier the others. The
    # standing reply-capture mailbox is excluded too - it is plumbing, not
    # a party to the document.
    standing = {a.strip().lower() for a in _standing_cc()}
    # Date AND TIME, name AND address. A line reading only "Acme
    # Electrical" does not say which address it reached or when, which is
    # exactly what a dispute about whether a supplier was told turns on.
    stamp = datetime.now(UTC).strftime("%d/%m/%Y %H:%M")
    notified_here: list[tuple[str, str, str]] = []
    if target:
        notified_here.append((target[0] or target[2], target[2], stamp))
    for address in extra_to or []:
        if address and address.strip().lower() not in standing:
            notified_here.append((address.strip(), address.strip(), stamp))

    # ONE dict of content, rendered twice. The HTML part and the
    # text/plain part are built from the SAME structured data rather than
    # the text being scraped out of the markup, so the two can never
    # drift and the plain part reads like a document somebody wrote.
    content = {
        "eyebrow": templates.KIND_LABELS.get(kind, kind.upper()),
        "title": item.title or item.reference,
        "project_line": project_name or f"Register entry {item.reference}",
        "intro": templates.KIND_INTRO.get(kind, ""),
        # WHAT YOU WANT TO SAY THIS TIME. Deliberately not stored on the
        # item: it belongs to this send, to this supplier - a change to
        # the record is an edit to the fields, not a line in one email.
        "body_text": str(extra_note or "").strip(),
        "pairs": pairs,
        "notified": notified_here,
        "footer_ref": (f"{item.reference}  ·  {email_ref}" if email_ref else item.reference),
        "greeting": f"Hi {target[1]}," if target else "Hi,",
        "hero_right": item.reference,
        "response_box": RESPONSE_BOX.get(kind),
        "tables": tables,
        "attached": attached_names,
    }
    html = outbound.build_register_email_html(**content)
    text = outbound.build_register_email_text(**content)
    return {
        "item_id": str(item.id),
        "reference_number": item.reference,
        "email_ref": email_ref,
        "contact_id": contact_id,
        "contact_name": target[0] if target else "",
        "to": ([target[2]] if target and target[2] else []) + [a for a in (extra_to or []) if a],
        "cc": _standing_cc(),
        "bcc": [],
        "subject": subject,
        "html": html,
        # The text/plain alternative every generated message carries.
        "text": text,
        "notified": [{"name": n, "email": em, "date": s} for n, em, s in notified_here],
        "attachments": ride,
        "attachment_names": attached_names,
        "attachments_missing": missing,
        "correspondence_id": "",  # register emails log on the ITEM, not a correspondence row
    }


async def build_award_confirmation(
    session: AsyncSession,
    item: RegisterItem,
    *,
    contact_id: str,
    po_number: str = "",
    amount: str = "",
    note: str = "",
    email_ref: str = "",
) -> dict[str, Any]:
    """The order-confirmation email to the winning supplier.

    Sent once an RFQ is awarded: it tells the winner they were successful,
    carries the purchase-order number and whatever note the awarder adds, and
    reads as an order confirmation rather than a repeat of the RFQ request. The
    payload shape matches :func:`build_item_email`, so it rides the same
    ``.eml`` / draft / send-log plumbing, and it renders server-side, so it
    works on a deployment with no mailbox bridge.
    """
    from app.modules.outlook_bridge import outbound

    target = await _contact(session, contact_id)  # (name, first, email)

    project_name = ""
    try:
        from app.modules.projects.models import Project

        project_name = (
            await session.execute(select(Project.name).where(Project.id == item.project_id))
        ).scalar_one_or_none() or ""
    except Exception:  # noqa: BLE001
        pass

    po = po_number.strip()
    pairs: list[tuple[str, str]] = [("Reference", item.reference)]
    if po:
        pairs.append(("Purchase order", po))
    if amount.strip():
        pairs.append(("Awarded value", amount.strip()))
    if email_ref:
        pairs.append(("Email ref", email_ref))
    pairs.append(("Package", item.title or item.reference))

    stamp = datetime.now(UTC).strftime("%d/%m/%Y %H:%M")
    notified_here = [(target[0] or target[2], target[2], stamp)]

    subject = " - ".join(
        b
        for b in [
            "Purchase Order" if po else "Order confirmation",
            po,
            item.title or item.reference,
        ]
        if b
    )

    # Rendered twice off one dict, exactly as the item email is - the
    # winning supplier's plain-text client gets the order, not a stub.
    content = {
        "eyebrow": "Order confirmation",
        "title": item.title or item.reference,
        "project_line": project_name or f"Register entry {item.reference}",
        "intro": (
            "Thank you - your quote has been accepted and this package is "
            "awarded to you. Please proceed in line with the purchase order "
            "below. Anything else we need from you is noted underneath."
        ),
        # The awarder's own words for this order - additional details, a
        # delivery instruction, a caveat. Not stored on the item.
        "body_text": str(note or "").strip(),
        "pairs": pairs,
        "notified": notified_here,
        "footer_ref": (f"{item.reference}  ·  {email_ref}" if email_ref else item.reference),
        "greeting": f"Hi {target[1]}," if target[1] else "Hi,",
        "hero_right": (po or item.reference),
        "response_box": None,
        "tables": [],
        "attached": [],
    }
    html = outbound.build_register_email_html(**content)
    text = outbound.build_register_email_text(**content)
    return {
        "item_id": str(item.id),
        "reference_number": item.reference,
        "email_ref": email_ref,
        "contact_id": contact_id,
        "contact_name": target[0] if target else "",
        "to": ([target[2]] if target and target[2] else []),
        "cc": _standing_cc(),
        "bcc": [],
        "subject": subject,
        "html": html,
        "text": text,
        "notified": [{"name": n, "email": em, "date": s} for n, em, s in notified_here],
        "attachments": [],
        "attachment_names": [],
        "attachments_missing": [],
        "correspondence_id": "",
    }


def _standing_cc() -> list[str]:
    import os

    raw = os.environ.get("OE_OUTLOOK_CC", "")
    return [a.strip() for a in raw.split(",") if a.strip()]


# ── The send log ─────────────────────────────────────────────────────────


#: Register kind → the Project Mail display type its filed copy carries.
#: "Request For Information" keeps document control's capital-F spelling so register
#: RFIs and workspace RFIs land under ONE type filter, not two.
KIND_PM_TYPE: dict[str, str] = {
    "rfi": "Request For Information",
    "rfq": "Request for Quotation",
    "order": "Purchase Order",
    "variation": "Variation",
    "delay": "Delay Notice",
    "toolbox": "Toolbox Talk",
}

#: Register kind → core correspondence_type (letter|email|notice|memo).
KIND_CORR_TYPE: dict[str, str] = {
    "rfi": "letter",
    "rfq": "email",
    "order": "memo",
    "variation": "notice",
    "delay": "notice",
    "toolbox": "memo",
}


async def _file_project_mail_copy(
    session: AsyncSession,
    item: RegisterItem,
    *,
    contact_id: str | None,
    contact_name: str,
    subject: str,
    channel: str,
    user_id: str | None,
    at: str | None,
    email_ref: str,
    html: str,
) -> None:
    """File this send as an OUTGOING correspondence row so it appears in
    Project Mail beside everything else that left the building.

    This is what ties the registers into the one correspondence view: an
    RFQ issued to three suppliers is three mails in the register's send
    log AND three rows in Project Mail, threaded together per item
    (``thread_key = rw:<item id>``), and a supplier's reply - swept in by
    the monitored inbox with ``REG-RFQ-…`` in its subject - stitches onto
    that thread with no user action.
    """
    from app.modules.correspondence.schemas import CorrespondenceCreate
    from app.modules.correspondence.service import CorrespondenceService

    to_ids: list[str] = []
    to_email = ""
    if contact_id:
        try:
            uuid.UUID(str(contact_id))
            to_ids = [str(contact_id)]
            _display, _first, to_email = await _contact(session, str(contact_id))
        except (ValueError, EmailingError):
            to_ids = []

    # Plain text for the heuristics pass; the full HTML rides in metadata.
    try:
        from app.modules.project_mail.service import html_to_text, workspace_org

        notes = html_to_text(html) if html else ""
        from_org = workspace_org()
    except Exception:  # noqa: BLE001 - project_mail absent: file with basics
        notes = ""
        from_org = ""

    import re as _re

    sent_iso = datetime.now(UTC).strftime("%Y-%m-%d")
    if at and _re.match(r"^\d{4}-\d{2}-\d{2}", at):
        sent_iso = at[:10]
    due = item.due_date if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.due_date or "") else None

    data = CorrespondenceCreate(
        project_id=item.project_id,
        direction="outgoing",
        subject=(subject or item.reference)[:500],
        to_contact_ids=to_ids,
        date_sent=sent_iso,
        correspondence_type=KIND_CORR_TYPE.get(item.kind, "email"),
        status="awaiting_response" if due else "open",
        response_required_by=due,
        notes=(notes or subject or item.reference)[:5000],
        metadata={
            "project_mail": {
                # The email's own number is the display number; the ITEM
                # reference rides in ``ref`` - it is what a reply quotes,
                # and the thread stitcher matches on it.
                "mail_no": email_ref or item.reference,
                "ref": item.reference,
                # The item reference also NAMES this mail for the thread
                # stitcher - it is the token a supplier's reply quotes.
                # (``ref`` alone cannot serve: on workspace mails that key
                # means "the mail I reply to".)
                "match_refs": [item.reference],
                "type": KIND_PM_TYPE.get(item.kind, "General Correspondence"),
                "thread_key": f"rw:{item.id}",
                "to": [contact_name] if contact_name else [],
                "cc": [],
                "from": "",
                "fromOrg": from_org,
                "to_emails": [to_email] if to_email else [],
                "cc_emails": [],
                "body_html": html or "",
                "channel": channel,
                "register_item_id": str(item.id),
                "register_kind": item.kind,
            }
        },
    )
    await CorrespondenceService(session).create_correspondence(data, user_id=str(user_id) if user_id else None)


def send_log(item: RegisterItem) -> list[dict[str, Any]]:
    log = (item.fields or {}).get(SEND_LOG_KEY)
    return list(log) if isinstance(log, list) else []


async def record_send(
    session: AsyncSession,
    item: RegisterItem,
    *,
    contact_id: str | None,
    contact_name: str,
    subject: str,
    channel: str,
    user_id: str | None,
    at: str | None = None,
    email_ref: str = "",
    html: str = "",
) -> None:
    """📧 on the record: who was drafted, when, through what.

    This is the log "sent to N" counts from - and if "Sent to ..." is the
    step the item is currently ON, it ticks itself, because opening the
    draft IS doing that step. Only the current step: the in-order rail is
    never bypassed by a convenience.
    """
    fields = dict(item.fields or {})
    log = list(fields.get(SEND_LOG_KEY) or [])
    log.append(
        {
            # A back-dated entry is the truth for mail that went out
            # days ago; "now" would quietly rewrite when it happened.
            "at": at or datetime.now(UTC).isoformat(timespec="seconds"),
            # The mail's own number - the send log is where "what was
            # REG-MSG-000042" gets answered six weeks later.
            "email_ref": email_ref,
            "contact_id": contact_id,
            "contact_name": contact_name,
            "subject": subject,
            "channel": channel,
            "by": user_id,
            # THE DOCUMENT AS IT WENT OUT. Kept verbatim rather than
            # rebuilt on demand: the fields move on - a date gets
            # corrected, a note is reworded - and regenerating the body
            # later would show a supplier a document they were never
            # sent. A record of what was sent has to be what was sent.
            #
            # Only ever OUR OWN rendered template, never a third party's
            # markup, and it is displayed in a sandboxed frame.
            "html": html or "",
        }
    )
    fields[SEND_LOG_KEY] = log
    item.fields = fields
    await session.flush()

    # Mirror into Project Mail. A SAVEPOINT, not a bare try/except: a
    # failed flush poisons the session, and the send log above - which the
    # quote gate counts - must survive this mirror failing.
    try:
        async with session.begin_nested():
            await _file_project_mail_copy(
                session,
                item,
                contact_id=contact_id,
                contact_name=contact_name,
                subject=subject,
                channel=channel,
                user_id=user_id,
                at=at,
                email_ref=email_ref,
                html=html,
            )
    except Exception:  # noqa: BLE001 - the mirror is secondary to the log
        logger.warning("Register send on %s did not file into Project Mail", item.reference, exc_info=True)

    try:
        from app.modules.register_workflow import service

        current = next((s for s in sorted(item.steps, key=lambda x: x.position) if s.state == "open"), None)
        if current is not None and current.step_type == "step" and "sent" in current.name.lower():
            await service.complete_step(session, current.id, user_id=user_id)
    except Exception:  # noqa: BLE001 - the tick is a convenience, never a failure
        logger.debug("Send auto-tick skipped for %s", item.reference, exc_info=True)
