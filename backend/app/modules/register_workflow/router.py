# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow API (mounted at ``/api/v1/register-workflow/``).

GET  /spec                       - field specs + flows + actions, all kinds
GET  /items?project_id=&kind=    - the register rows
GET  /linked?project_id=&entity_type=  - native row id -> register item
GET  /summary?project_id=        - per-kind counts for the header
POST /items                      - raise one
GET  /items/{id}                 - one item with its steps
PATCH /items/{id}                - edit fields / title / recipients
DELETE /items/{id}               - erase one nobody has seen (else 409)
POST /items/{id}/withdraw        - take an issued one out of play
POST /items/{id}/reopen          - put a withdrawn one back
POST /items/{id}/steps           - slot the next action in
GET  /items/{id}/prefill/{kind}  - the interlink payload
POST /steps/{id}/complete        - tick (gate override optional)
POST /steps/{id}/uncomplete      - undo, reverse order only
POST /steps/{id}/not-required    - ⊘ (never a gate)
POST /steps/{id}/route           - choose a branch
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)

# The permissions import is for its side effect: it registers
# register_workflow.* in the live permission registry. Nothing else
# imports that file (the module loader only loads router/models/hooks/
# events), and an UNregistered permission is denied for every non-admin
# role - without this line only admins could use the registers.
from app.modules.register_workflow import permissions as _permissions  # noqa: F401
from app.modules.register_workflow import service, templates
from app.modules.register_workflow.models import RegisterItem, RegisterStep
from app.modules.register_workflow.schemas import RegisterWorkflowListResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["register_workflow"])


def _like_escape(value: str) -> str:
    """Neutralise LIKE metacharacters in a user-supplied search term.

    Bound parameters stop SQL injection; they do NOT stop `%` and `_`
    from widening the pattern itself, which is how a PO number typed as
    "%" pulled an entire project's correspondence onto one order.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RaiseRequest(BaseModel):
    project_id: uuid.UUID
    kind: str = Field(max_length=20)
    title: str = Field(default="", max_length=500)
    fields: dict = Field(default_factory=dict)
    recipient_contact_ids: list[str] = Field(default_factory=list, max_length=200)
    raised_from_id: str | None = None


class ItemUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    fields: dict | None = None
    recipient_contact_ids: list[str] | None = None


class AddStepRequest(BaseModel):
    name: str = Field(max_length=300)
    step_type: str = Field(default="step", pattern=r"^(step|gate|route)$")
    owner: str = Field(default="", max_length=60)
    after_position: int | None = None
    #: Only for a decision: {branch label: [step names that path adds]}.
    branches: dict[str, list[str]] = Field(default_factory=dict)


class CompleteRequest(BaseModel):
    override_reason: str | None = Field(default=None, max_length=2000)


class RouteRequest(BaseModel):
    branch: str = Field(max_length=200)


class ItemEmailRequest(BaseModel):
    """Preview/draft options for a register item's email."""

    contact_id: str | None = Field(default=None, max_length=36)
    extra_to: list[str] = Field(default_factory=list, max_length=20)
    #: A sentence or two added to THIS send, above the details. Not stored
    #: on the item: it is what you want to say to this supplier this time,
    #: not a change to the record. Sanitised like every other body text.
    extra_note: str = Field(default="", max_length=4000)


class QuoteRequest(BaseModel):
    """One supplier's price, typed into the compare panel."""

    bidder_contact_id: str = Field(max_length=36)
    amount: str = Field(max_length=50)
    lead_time: str = Field(default="", max_length=60)
    quote_number: str = Field(default="", max_length=40)
    notes: str = Field(default="", max_length=2000)


class AwardRequest(BaseModel):
    bid_id: uuid.UUID
    reason: str = Field(max_length=5000)
    po_number: str = Field(default="", max_length=60)
    gate_override_reason: str = Field(default="", max_length=2000)


class AwardConfirmRequest(BaseModel):
    """The order-confirmation email to the winning supplier after an award."""

    contact_id: str = Field(max_length=36)
    po_number: str = Field(default="", max_length=60)
    amount: str = Field(default="", max_length=50)
    #: Additional details the awarder wants to add to this order.
    note: str = Field(default="", max_length=4000)


class WithdrawRequest(BaseModel):
    """Why an issued item is being taken out of play - or put back.

    Validated the way a gate override is (``service.gate_reason_bad``):
    this is the same kind of act, a person overruling the ordinary course
    on the record, and "n/a" six weeks later is not a record of anything.
    """

    reason: str = Field(max_length=2000)


async def _item_or_404(session, item_id: uuid.UUID) -> RegisterItem:
    item = await session.get(RegisterItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Register item not found")
    return item


def _caller_holds(payload: object, permission: str) -> bool:
    """Does this caller hold ``permission``?

    The same three rules ``RequirePermission`` applies - admin bypasses,
    the JWT's own list, then the live registry for a token issued before
    a role mapping changed - asked as a QUESTION rather than as a gate.
    A route-level dependency can only demand one permission of everybody;
    the delete rail below needs "your own item with update, or anybody's
    with delete", which no single dependency can express.
    """
    data = payload if isinstance(payload, dict) else {}
    role = str(data.get("role") or "")
    if role == "admin":
        return True
    if permission in (data.get("permissions") or []):
        return True
    from app.core.permissions import permission_registry

    return permission_registry.role_has_permission(role, permission)


def _refuse_withdrawn(item: RegisterItem, action: str) -> None:
    """409 on a withdrawn item, for the doors that do not run through the
    service's own mutators (email, the send log, quotes, the award).

    A withdrawn RFQ that could still be emailed or awarded is not
    withdrawn at all - it is just labelled that way on one screen.
    """
    try:
        service.ensure_not_withdrawn(item, action)
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


async def _step_item(session, step_id: uuid.UUID) -> tuple[RegisterStep, RegisterItem]:
    step = await session.get(RegisterStep, step_id)
    if step is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Step not found")
    item = await _item_or_404(session, step.item_id)
    return step, item


@router.get("/spec")
async def get_spec(
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """Everything the UI needs to render every register, generically."""
    return {
        "kinds": list(templates.KINDS),
        "specs": {kind: templates.spec_for(kind) for kind in templates.KINDS},
    }


class ComposePreviewRequest(BaseModel):
    """Live preview of the email a raise WOULD send - nothing persisted.

    The contract: preview while composing, with the coming reference
    peeked but never burned; Raise-then-draft produces exactly what was
    on screen.
    """

    project_id: uuid.UUID
    kind: str = Field(max_length=20)
    title: str = Field(default="", max_length=500)
    fields: dict = Field(default_factory=dict)
    recipient_contact_ids: list[str] = Field(default_factory=list, max_length=200)
    contact_id: str | None = Field(default=None, max_length=36)


@router.post("/preview-email")
async def preview_compose_email(
    payload: ComposePreviewRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """Render the email for an item that does not exist yet.

    A TRANSIENT item (never added to the session) carries the form's
    current values through the same builder the raised item will use, so
    the live preview is byte-for-byte the eventual draft. The reference
    shown is the next one - peeked read-only, not minted.
    """
    from app.modules.register_workflow import emailing

    await verify_project_access(payload.project_id, user_id, session)
    if payload.kind not in templates.KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown register kind {payload.kind!r}")
    # The peek needs the job number, and a job with none set is a REFUSAL,
    # not a crash: this runs on every keystroke in the raise form, so it
    # has to come back as the message telling you to set the number.
    try:
        reference = await service._peek_reference(session, payload.project_id, payload.kind)
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    ghost = RegisterItem(
        project_id=payload.project_id,
        kind=payload.kind,
        reference=reference,
        title=service.single_line(payload.title or "")[:500] or reference,
        # The preview built its ghost from RAW fields, so it was the one
        # path where a forged `_send_log`/`_attachments` still reached the
        # email builder. Same sanitiser as every other entry point.
        fields=service.sanitise_fields(payload.fields),
        recipient_contact_ids=[str(c) for c in payload.recipient_contact_ids],
    )
    try:
        built = await emailing.build_item_email(session, ghost, contact_id=payload.contact_id)
    except emailing.EmailingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    built["peeked_reference"] = reference
    return built


@router.post("/items/{item_id}/email/preview")
async def preview_item_email(
    item_id: uuid.UUID,
    payload: ItemEmailRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """Render one recipient's tailored email. No side effects, no log -
    and byte-for-byte what /email/draft opens in Outlook."""
    from app.modules.register_workflow import emailing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        return await emailing.build_item_email(
            session,
            item,
            contact_id=payload.contact_id,
            extra_to=payload.extra_to,
            extra_note=payload.extra_note,
            # Peeked, not minted: a preview must not burn a number every
            # time somebody looks. The draft mints the real one.
            email_ref=await service.peek_email_reference(session),
        )
    except emailing.EmailingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


@router.post("/items/{item_id}/email/draft")
async def draft_item_email(
    item_id: uuid.UUID,
    payload: ItemEmailRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Open the tailored draft in Outlook and log the send on the item.

    ``contact_id`` empty + a multi-recipient item = DRAFT ALL: one draft
    per supplier, each addressed to them alone, in one confirmed click.
    """
    from app.modules.outlook_bridge.ps import OutlookUnavailable
    from app.modules.outlook_bridge.service import open_payload_in_outlook
    from app.modules.register_workflow import emailing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    _refuse_withdrawn(item, "email it")

    targets: list[str | None]
    if payload.contact_id:
        targets = [payload.contact_id]
    elif item.recipient_contact_ids:
        targets = list(item.recipient_contact_ids)
    else:
        targets = [None]

    opened = 0
    try:
        for cid in targets:
            # EACH EMAIL GETS ITS OWN NUMBER, minted the moment the draft
            # is real - Draft ALL produces N refs, one per supplier's
            # copy, so "what was REG-MSG-000042" has exactly one answer.
            email_ref = await service.next_email_reference(session)
            built = await emailing.build_item_email(
                session,
                item,
                contact_id=cid,
                extra_to=payload.extra_to,
                extra_note=payload.extra_note,
                email_ref=email_ref,
            )
            await open_payload_in_outlook(session, built, user_id=str(user_id))
            await emailing.record_send(
                session,
                item,
                contact_id=cid,
                contact_name=built["contact_name"],
                subject=built["subject"],
                channel="outlook",
                user_id=str(user_id),
                email_ref=email_ref,
                html=built["html"],
            )
            opened += 1
    except emailing.EmailingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except OutlookUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    await session.commit()
    return {
        "opened": opened,
        "item": await service.item_payload_enriched(session, await _item_or_404(session, item_id)),
    }


@router.post("/items/{item_id}/email/eml")
async def eml_item_email(
    item_id: uuid.UUID,
    payload: ItemEmailRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
):
    """The same tailored email as an editable .eml (the browser/server path).

    Downloading counts as a send for the log - the draft is in the user's
    hands either way.
    """
    from fastapi.responses import Response

    from app.modules.outlook_bridge.eml import build_eml
    from app.modules.register_workflow import emailing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    _refuse_withdrawn(item, "email it")
    try:
        email_ref = await service.next_email_reference(session)
        built = await emailing.build_item_email(
            session,
            item,
            contact_id=payload.contact_id,
            extra_to=payload.extra_to,
            # THE NOTE RIDES HERE TOO. It did not, so the preview showed a
            # sentence to the supplier that the downloaded .eml never
            # carried - the one thing "what you preview is what goes" is
            # supposed to make impossible.
            extra_note=payload.extra_note,
            email_ref=email_ref,
        )
    except emailing.EmailingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    # BUILD FIRST, LOG SECOND. record_send + commit used to run before
    # build_eml, so anything the builder refused left the register
    # claiming an email had gone out that was never produced - and "sent
    # to N" is exactly what the quote gate counts.
    try:
        body = build_eml(built)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"That draft cannot be built: {exc}") from None
    await emailing.record_send(
        session,
        item,
        contact_id=payload.contact_id,
        contact_name=built["contact_name"],
        subject=built["subject"],
        channel="eml",
        user_id=str(user_id),
        email_ref=email_ref,
        html=built["html"],
    )
    await session.commit()
    filename = f"{built['reference_number'] or 'draft'}.eml".replace("/", "-")
    return Response(
        content=body,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/items/{item_id}/suggestions")
async def item_suggestions(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """Figures the analyser read out of this package's replies.

    Suggestions only - each carries the verbatim words it came from, and
    a person confirms it onto the bid. Replies that cannot be placed with
    confidence come back under ``unmatched`` rather than guessed onto the
    nearest supplier.
    """
    from app.modules.register_workflow import suggestions

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    return await suggestions.suggestions_for(session, item)


class LogSentRequest(BaseModel):
    """Record an email that went out some other way."""

    contact_id: str | None = Field(default=None, max_length=36)
    contact_name: str = Field(default="", max_length=200)
    sent_on: str = Field(default="", max_length=20)


class LogSentManyRequest(BaseModel):
    """Record several already-sent emails in one go.

    The register almost always issues to a LIST - three suppliers on a
    package - so logging them one at a time was three round trips and
    three chances to give up half way. One call, one transaction.
    """

    entries: list[LogSentRequest] = Field(default_factory=list, max_length=50)


class LogReplyRequest(BaseModel):
    """Capture a reply that came back some other way.

    On a server with no mailbox bridge, a supplier's quote or an RFI answer
    still lands in someone's inbox. This files that reply against the item by
    hand so the tracking board flips to "replied" (and, when the body carries
    a price, "quoted") and the workflow keeps moving - exactly as if the
    bridge had swept it in.
    """

    #: Who the reply is from. A contact id is best (the tracking board can
    #: attribute it deterministically); a typed name/email is the fallback
    #: for a sender who is not in the book.
    contact_id: str | None = Field(default=None, max_length=36)
    from_name: str = Field(default="", max_length=200)
    from_email: str = Field(default="", max_length=200)
    #: The reply's own subject, if you have it. Left blank we build one from
    #: the item title; either way the item reference and the sender name are
    #: appended so the same matcher the bridge uses can file and attribute it.
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    #: When it arrived (any parseable date); blank means "now".
    received_on: str = Field(default="", max_length=40)


class ConfigureStepsRequest(BaseModel):
    """The steps still TO DO, in the order they should run.

    Each entry is ``{"name", "type": "step"|"gate"|"route", "owner",
    "branches"}``. A name already open on the item is KEPT (type, owner
    and branches as they were - ``type``/``branches`` are ignored for it);
    anything else is new. A new ``route`` must carry ``branches``
    (``{label: [step names]}``) or the whole request is refused.
    """

    remaining: list[dict] = Field(default_factory=list, max_length=200)
    #: Required only when a gate or a decision is being taken off the
    #: workflow. It goes on the record beside the retired hold point.
    retire_reason: str = Field(default="", max_length=300)


@router.post("/items/{item_id}/configure")
async def configure_workflow(
    item_id: uuid.UUID,
    payload: ConfigureStepsRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Reorder / add / remove the REMAINING steps.

    Completed steps are history: they cannot be moved, renamed or deleted
    here, whatever the payload says. A gate or a decision may be taken off
    the workflow, but only with ``retire_reason`` - it is then retired
    onto the record rather than deleted from it. A NEW decision may be
    added here with its ``branches``; a kept one keeps the branches it has.
    """
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        await service.configure_steps(
            session,
            item_id,
            payload.remaining,
            retire_reason=payload.retire_reason,
            user_id=str(user_id),
        )
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


@router.post("/items/{item_id}/log-sent-many")
async def log_already_sent_many(
    item_id: uuid.UUID,
    payload: LogSentManyRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Tick the ones that already went out, all in one commit."""
    from app.modules.register_workflow import emailing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    _refuse_withdrawn(item, "log a send against it")
    if not payload.entries:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nobody was ticked")
    for entry in payload.entries:
        name = entry.contact_name.strip()
        if not name and entry.contact_id:
            try:
                name, _first, _email = await emailing._contact(session, entry.contact_id)
            except emailing.EmailingError:
                name = ""
        await emailing.record_send(
            session,
            item,
            contact_id=entry.contact_id,
            contact_name=name or "(logged by hand)",
            subject=f"{item.reference} - {item.title}",
            channel="logged",
            user_id=str(user_id),
            at=entry.sent_on.strip() or None,
            email_ref=await service.next_email_reference(session),
        )
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


@router.post("/items/{item_id}/log-sent")
async def log_already_sent(
    item_id: uuid.UUID,
    payload: LogSentRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """ "Already sent" - for mail that left outside the app.

    Plenty of correspondence goes out by phone-then-email, or from a
    colleague's mailbox. Without this the register under-counts what was
    actually issued, and the quote gate reads a package as unasked when
    three suppliers already have it.
    """
    from app.modules.register_workflow import emailing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    _refuse_withdrawn(item, "log a send against it")
    name = payload.contact_name.strip()
    if not name and payload.contact_id:
        try:
            name, _first, _email = await emailing._contact(session, payload.contact_id)
        except emailing.EmailingError:
            name = ""
    await emailing.record_send(
        session,
        item,
        contact_id=payload.contact_id,
        contact_name=name or "(logged by hand)",
        subject=f"{item.reference} - {item.title}",
        channel="logged",
        email_ref=await service.next_email_reference(session),
        user_id=str(user_id),
        at=payload.sent_on.strip() or None,
    )
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


@router.post("/items/{item_id}/log-reply")
async def log_reply(
    item_id: uuid.UUID,
    payload: LogReplyRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Manually file a reply against this item.

    Reuses the Inbound Capture Gateway (``capture_message``), so a
    hand-entered reply is indistinguishable downstream from one the mailbox
    bridge swept in: it publishes ``correspondence.created`` and auto-
    analyses, and - because the item reference and the sender name ride in
    the subject - the tracking board files it against this item and
    attributes it to the right supplier with the same matcher the bridge
    uses. This is the workflow's kick-start on a deployment where the
    mailbox bridge is not available.
    """
    from app.modules.inbound_capture.normalize import normalize_email
    from app.modules.inbound_capture.service import capture_message
    from app.modules.register_workflow import emailing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    _refuse_withdrawn(item, "file a reply against it")

    name = payload.from_name.strip()
    email = payload.from_email.strip()
    if payload.contact_id:
        try:
            c_name, _first, c_email = await emailing._contact(session, payload.contact_id)
            name = name or c_name
            email = email or c_email
        except emailing.EmailingError:
            pass
    if not (name or email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say who the reply is from")

    # Both the item reference and the sender name go in the subject: the
    # reference is how tracking finds THIS item, the name is how it
    # attributes the reply to the right supplier row. Append only what is
    # missing so a real reply subject is left as the reader typed it.
    subject = payload.subject.strip() or f"Re: {item.title}".strip()
    if name and name.lower() not in subject.lower():
        subject = f"{subject} - {name}"
    if item.reference.lower() not in subject.lower():
        subject = f"{subject} [{item.reference}]"

    parsed = {
        "from": email or name,
        "subject": subject[:500],
        "text": payload.body,
        "date": payload.received_on.strip(),
        # Blank id: a hand-entered reply is never a de-dupe key, so it is
        # always inserted (the gateway's documented caveat for blank ids).
        "message_id": "",
        "attachments": [],
    }
    await capture_message(session, item.project_id, normalize_email(parsed), created_by=str(user_id))
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


@router.post("/items/{item_id}/quotes")
async def record_quote(
    item_id: uuid.UUID,
    payload: QuoteRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Record a supplier's price on the native RFQ (the compare panel).

    A typed figure IS a quote for the gate's purposes - the same rule the
    compare panel shows and the award enforces.
    """
    from app.modules.register_workflow import native

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    _refuse_withdrawn(item, "record a quote on it")
    if item.linked_entity_type != "rfq" or not item.linked_entity_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has no RFQ behind it")
    try:
        result = await native.record_bid(
            session,
            rfq_entity_id=item.linked_entity_id,
            bidder_contact_id=payload.bidder_contact_id,
            amount=payload.amount,
            lead_time=payload.lead_time,
            quote_number=payload.quote_number,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await session.commit()
    enriched = await service.item_payload_enriched(session, await _item_or_404(session, item_id))
    return {**enriched, "recorded": result}


@router.post("/items/{item_id}/award")
async def award(
    item_id: uuid.UUID,
    payload: AwardRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    request_role: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Award through the NATIVE rfq_bidding service.

    Which means the tiered quote gate, the mandatory written reason, the
    ranked-table snapshot and the confirmation correspondence all apply
    here exactly as they do on the RFQ screen - one award path, one set
    of rules.
    """
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    _refuse_withdrawn(item, "award it")
    if item.linked_entity_type != "rfq" or not item.linked_entity_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has no RFQ behind it")
    try:
        from app.modules.rfq_bidding.service import RFQService
    except ImportError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "RFQ module not installed") from None

    # THE BID MUST BELONG TO THIS ITEM'S RFQ. Without this the endpoint
    # took any bid id and awarded it: a user could award a contract on a
    # job they cannot see, and the award landed with no trail on the
    # project that owns it.
    from app.modules.rfq_bidding.models import RFQBid

    bid = await session.get(RFQBid, payload.bid_id)
    if bid is None or str(bid.rfq_id) != str(item.linked_entity_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That quote is not on this package")

    role = request_role.get("role") if isinstance(request_role, dict) else None
    try:
        await RFQService(session).award_bid(
            payload.bid_id,
            actor_id=str(user_id),
            # The workspace is the buyer's own screen; award authority is
            # already checked by the native service against this role.
            actor_role=role or "manager",
            reason=payload.reason,
            gate_override_reason=payload.gate_override_reason or None,
            po_number=payload.po_number or None,
        )
    except HTTPException:
        raise
    await session.commit()
    # The award is the moment the money is committed - the one event on
    # this module worth interrupting somebody for.
    from app.modules.register_workflow import events

    # The bid stores a CONTACT ID and `bid_amount`, not a name and an
    # `amount`. Guessing the attribute names published "awarded to " with
    # an empty supplier - a notification that names nobody is noise.
    supplier = ""
    try:
        from app.modules.contacts.models import Contact

        contact = await session.get(Contact, uuid.UUID(str(bid.bidder_contact_id)))
        if contact is not None:
            supplier = (
                contact.company_name
                or " ".join(x for x in [contact.first_name, contact.last_name] if x)
                or (contact.primary_email or "")
            )
    except Exception:  # noqa: BLE001 - the award stands whatever the bell does
        logger.debug("Could not name the winner on %s", item.reference, exc_info=True)
    events.award_made(
        item,
        supplier=supplier,
        amount=str(getattr(bid, "bid_amount", "") or ""),
        po_number=payload.po_number or "",
    )
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


@router.post("/items/{item_id}/award-confirmation/preview")
async def preview_award_confirmation(
    item_id: uuid.UUID,
    payload: AwardConfirmRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """Preview the order confirmation to the winning supplier. No side effects.

    Byte-for-byte what the .eml carries. The email reference is peeked, not
    minted, so previewing never burns a number.
    """
    from app.modules.register_workflow import emailing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        return await emailing.build_award_confirmation(
            session,
            item,
            contact_id=payload.contact_id,
            po_number=payload.po_number,
            amount=payload.amount,
            note=payload.note,
            email_ref=await service.peek_email_reference(session),
        )
    except emailing.EmailingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


@router.post("/items/{item_id}/award-confirmation/eml")
async def eml_award_confirmation(
    item_id: uuid.UUID,
    payload: AwardConfirmRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
):
    """The order confirmation as an editable .eml, logged as a send on the item.

    The server-and-browser path that needs no mailbox bridge: download it,
    open it, press Send. Downloading counts as the send for the trail.
    """
    from fastapi.responses import Response

    from app.modules.outlook_bridge.eml import build_eml
    from app.modules.register_workflow import emailing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    _refuse_withdrawn(item, "email it")
    try:
        email_ref = await service.next_email_reference(session)
        built = await emailing.build_award_confirmation(
            session,
            item,
            contact_id=payload.contact_id,
            po_number=payload.po_number,
            amount=payload.amount,
            note=payload.note,
            email_ref=email_ref,
        )
    except emailing.EmailingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    # Build first, log second - so a draft the builder refuses never leaves
    # the register claiming an order confirmation went out that never did.
    try:
        body = build_eml(built)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"That confirmation cannot be built: {exc}") from None
    await emailing.record_send(
        session,
        item,
        contact_id=payload.contact_id,
        contact_name=built["contact_name"],
        subject=built["subject"],
        channel="eml",
        user_id=str(user_id),
        email_ref=email_ref,
        html=built["html"],
    )
    await session.commit()
    filename = f"{built['reference_number'] or 'order'}-confirmation.eml".replace("/", "-")
    return Response(
        content=body,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/items/{item_id}/attachments")
async def upload_attachment(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Evidence drop: attach a file to the item; if the item is currently
    ON an "…attached" step, the drop ticks it - attaching IS the step."""
    import re as _re
    from pathlib import Path

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)

    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "25 MB cap per file")
    safe = _re.sub(r"[^\w.\- ]", "_", file.filename or "file")[:120]
    folder = Path("uploads/register_workflow") / str(item.id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / safe
    n = 1
    while dest.exists():  # collision → numbered, never overwritten
        stem, dot, ext = safe.rpartition(".")
        dest = folder / (f"{stem or ext}-{n}.{ext}" if dot else f"{safe}-{n}")
        n += 1
    dest.write_bytes(raw)

    fields = dict(item.fields or {})
    atts = list(fields.get("_attachments") or [])
    # Default ON: a file dropped on an item is nearly always the thing
    # the supplier needs to see. The per-file toggle below turns it off
    # for internal-only evidence (a photo of the damage, our own notes).
    atts.append({"filename": dest.name, "size": len(raw), "by": str(user_id), "email": True})
    fields["_attachments"] = atts
    item.fields = fields
    await session.flush()

    # Evidence auto-tick: only the CURRENT step, only a plain step, only
    # when its name says something is attached.
    try:
        current = next((s for s in sorted(item.steps, key=lambda x: x.position) if s.state == "open"), None)
        if (
            current is not None
            and current.step_type == "step"
            and _re.search(r"attach|photo|evidence|sign-on|docket", current.name, _re.I)
        ):
            await service.complete_step(session, current.id, user_id=str(user_id))
    except Exception:  # noqa: BLE001
        pass
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


class AttachmentFlag(BaseModel):
    filename: str = Field(max_length=200)
    email: bool


@router.patch("/items/{item_id}/attachments")
async def set_attachment_flag(
    item_id: uuid.UUID,
    payload: AttachmentFlag,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Decide whether one attachment rides the register email.

    Some evidence belongs on the record but not in a supplier's inbox -
    damage photos, our own markups, the internal cost sheet.
    """
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    fields = dict(item.fields or {})
    atts = [dict(a) for a in (fields.get("_attachments") or []) if isinstance(a, dict)]
    hit = next((a for a in atts if a.get("filename") == payload.filename), None)
    if hit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    hit["email"] = payload.email
    fields["_attachments"] = atts
    item.fields = fields
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


@router.get("/items/{item_id}/documents/{filename}")
async def get_document(
    item_id: uuid.UUID,
    filename: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
):
    """Serve one attachment for the viewer.

    A ``.eml`` comes back as READ JSON, not raw: headers, a sanitised
    body and the inner attachment names, with remote images stripped -
    in a supplier's quote those are read receipts.
    """
    from fastapi.responses import FileResponse

    from app.modules.register_workflow import documents

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        path, media, inline = documents.resolve(str(item.id), filename)
    except documents.DocumentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None

    if path.suffix.lower() in (".eml", ".msg"):
        return documents.read_eml(path.read_bytes())
    return FileResponse(
        path,
        media_type=media,
        # Unknown types download rather than render: a hostile filename
        # must never execute in the browser.
        content_disposition_type="inline" if inline else "attachment",
        filename=path.name,
    )


@router.get("/stats")
async def register_stats(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """How the job is actually running: closing speed, punctuality,
    the oldest thing still open, and the delay register's lost hours -
    which is the number a claim is built from."""
    await verify_project_access(project_id, user_id, session)
    return await service.performance(session, project_id)


def _page(rows: list[dict], limit: int, offset: int) -> RegisterWorkflowListResponse:
    """Wrap a set the service returns whole. ``total`` describes the set,
    not the window, so a caller can tell the two apart."""
    start = max(0, offset)
    return RegisterWorkflowListResponse(
        items=rows[start : start + max(1, limit)], total=len(rows), limit=limit, offset=start
    )


@router.get("/portfolio")
async def portfolio(
    session: SessionDep,
    user_id: CurrentUserId,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> RegisterWorkflowListResponse:
    """Every job the caller can see, with its open/overdue counts.

    One screen answering "where is the heat today" without opening each
    job in turn.
    """
    return _page(await service.portfolio(session, str(user_id)), limit, offset)


@router.get("/items/{item_id}/thread")
async def item_thread(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> RegisterWorkflowListResponse:
    """The item's correspondence thread: every register email logged on it
    plus every captured message that mentions its references."""
    from sqlalchemy import or_
    from sqlalchemy import select as _select

    from app.modules.correspondence.models import Correspondence
    from app.modules.register_workflow import emailing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)

    refs = {item.reference}
    # Every email sent off this item carries its own REG-MSG-###### - a
    # reply quoting only that number still belongs in this thread.
    for s in (item.fields or {}).get("_send_log") or []:
        if isinstance(s, dict) and s.get("email_ref"):
            refs.add(str(s["email_ref"]))
    native = await service.item_payload_enriched(session, item)
    for key in ("rfq_number", "rfi_number", "code", "po_number"):
        value = (native.get("native") or {}).get(key)
        if value:
            refs.add(str(value))

    # ESCAPE THE PATTERN. `po_number` is whatever the user typed into
    # "Our PO #", and a bare `%` there matched every subject on the job -
    # HR, medical, other suppliers' pricing - and filed it onto this
    # purchase order as its evidence trail.
    conds = []
    for ref in refs:
        pattern = "%" + _like_escape(str(ref)) + "%"
        conds.append(Correspondence.subject.ilike(pattern, escape="\\"))
        conds.append(Correspondence.notes.ilike(pattern, escape="\\"))
    rows = (
        (
            await session.execute(
                _select(Correspondence)
                .where(Correspondence.project_id == item.project_id)
                .where(or_(*conds))
                .order_by(Correspondence.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
        if conds
        else []
    )

    thread: list[dict] = [
        {
            "type": "send",
            "at": s.get("at"),
            "who": s.get("contact_name") or "",
            "subject": s.get("subject") or "",
            "channel": s.get("channel"),
            # The mail's own number - the thread answers "what was
            # REG-MSG-000042" by showing it on the row that sent it.
            "email_ref": s.get("email_ref") or "",
            # The body EXACTLY as it went out, when we have it. Sends
            # logged as "already sent" carry none - that mail left from
            # somebody's own Outlook and we would be inventing it.
            "html": s.get("html") or "",
            "contact_id": s.get("contact_id"),
        }
        for s in emailing.send_log(item)
    ]
    for row in rows:
        entry = {
            "type": "correspondence",
            "id": str(row.id),
            "at": row.created_at.isoformat() if row.created_at else None,
            "direction": row.direction,
            "reference": row.reference_number,
            "subject": row.subject,
            "status": row.status,
            "category": None,
            "confidence": None,
        }
        try:
            from app.modules.comms_intelligence.repository import CommsAnalysisRepository

            analysis = await CommsAnalysisRepository(session).get_for_correspondence(str(row.id))
            if analysis:
                entry["category"] = analysis.category
                entry["confidence"] = analysis.confidence
        except ImportError:  # pragma: no cover
            pass
        thread.append(entry)
    thread.sort(key=lambda x: str(x.get("at") or ""), reverse=True)
    return _page(thread, limit, offset)


@router.get("/items")
async def list_items(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    kind: str | None = Query(default=None, max_length=20),
    # "closed" also answers with WITHDRAWN items: they are done with, and
    # the closed view is the one place a person looks for an item that is
    # no longer in play. "withdrawn" narrows to just those.
    item_status: str | None = Query(default=None, alias="status", pattern=r"^(open|closed|withdrawn)$"),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> RegisterWorkflowListResponse:
    await verify_project_access(project_id, user_id, session)
    items = await service.list_items(session, project_id, kind=kind, status=item_status)
    return _page([await service.item_payload_enriched(session, i) for i in items], limit, offset)


@router.get("/linked")
async def linked_items(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    entity_type: str = Query(pattern=r"^(rfi|rfq|order|variation)$"),
    # Comma-separated native ids to narrow to the rows on screen. Absent
    # = every linked item on the project.
    entity_ids: str | None = Query(default=None, max_length=40_000),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> RegisterWorkflowListResponse:
    """Reverse lookup for the base modules: native row id -> register item.

    ``[{item_id, reference, kind, status, title, due_date, is_overdue,
    linked_entity_id, ball_in_court}]`` for this project's items whose
    ``linked_entity_type`` is ``entity_type``.
    """
    await verify_project_access(project_id, user_id, session)
    ids = None
    if entity_ids is not None:
        ids = [part.strip() for part in entity_ids.split(",") if part.strip()]
    return _page(await service.linked_items(session, project_id, entity_type, ids), limit, offset)


@router.get("/summary")
async def get_summary(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    await verify_project_access(project_id, user_id, session)
    return await service.summary(session, project_id)


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def raise_item(
    payload: RaiseRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.create")),
) -> dict:
    await verify_project_access(payload.project_id, user_id, session)
    try:
        item = await service.raise_item(
            session,
            project_id=payload.project_id,
            kind=payload.kind,
            title=payload.title,
            fields=payload.fields,
            recipient_contact_ids=payload.recipient_contact_ids,
            raised_from_id=payload.raised_from_id,
            user_id=str(user_id),
        )
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    await session.commit()
    # Enriched: the caller gets the native record it just created (RFQ
    # number, live quote gate) in the same answer, so the UI never has to
    # re-fetch to learn what it made.
    return await service.item_payload_enriched(session, item)


@router.get("/items/{item_id}")
async def get_item(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    return await service.item_payload_enriched(session, item)


@router.patch("/items/{item_id}")
async def update_item(
    item_id: uuid.UUID,
    payload: ItemUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        await service.update_item(
            session,
            item,
            title=payload.title,
            fields=payload.fields,
            recipient_contact_ids=payload.recipient_contact_ids,
        )
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await session.commit()
    return await service.item_payload_enriched(session, item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> None:
    """Erase an item raised in error - ONLY one nobody outside has seen.

    THE RECORD RAIL COMES FIRST, and it binds everybody: no send log, no
    replies, no quotes, no award, and nothing raised from it. Anything
    else is a record of something that happened and is WITHDRAWN instead,
    never erased, whatever permission the caller holds - a supplier
    holding an RFQ that no longer exists on our side is the exact
    position the trail is for. (409)

    THE PERMISSION RAIL IS SECOND, and it is deliberately two-sided:

    * the person who RAISED it may delete their own unseen mistake with
      ``register_workflow.update`` - a cleanup you have to ask a manager
      for is the "delete it out of the database for me" problem again;
    * anybody else needs ``register_workflow.delete``, the manager-level
      permission the module already declares.  (403)

    Both refusals answer with the same ``{error, reasons: [...]}`` shape,
    so one renderer in the UI covers either.
    """
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)

    blockers = await service.deletion_blockers(session, item)
    if blockers:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"error": service.deletion_refusal(item, blockers), "reasons": blockers},
        )
    if not service.raised_by(item, str(user_id)) and not _caller_holds(caller, "register_workflow.delete"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "error": service.foreign_delete_refusal(item),
                "reasons": [
                    "it was raised by somebody else",
                    "deleting another person's item needs the manager-level register_workflow.delete permission",
                ],
            },
        )
    reference = item.reference
    await service.delete_item(session, item)
    await session.commit()
    logger.info("register_workflow.deleted %s", {"reference": reference, "by": str(user_id)})


@router.post("/items/{item_id}/withdraw")
async def withdraw_item(
    item_id: uuid.UUID,
    payload: WithdrawRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Take an issued item out of play, on the record, with a reason.

    It leaves the open register, the deadline sweep, the tracking board
    and the with-them/with-us counts, keeps its reference for ever, and
    refuses every further mutation until somebody reopens it.
    """
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        await service.withdraw_item(session, item, reason=payload.reason, user_id=str(user_id))
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


@router.post("/items/{item_id}/reopen")
async def reopen_item(
    item_id: uuid.UUID,
    payload: WithdrawRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Put a withdrawn item back where it was - reason-gated both ways."""
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        await service.reopen_item(session, item, reason=payload.reason, user_id=str(user_id))
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


@router.get("/items/{item_id}/prefill/{target_kind}")
async def prefill(
    item_id: uuid.UUID,
    target_kind: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        return await service.prefill_from(session, item_id, target_kind)
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


@router.post("/items/{item_id}/steps", status_code=status.HTTP_201_CREATED)
async def add_step(
    item_id: uuid.UUID,
    payload: AddStepRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    # 409, not the 400 a bad step name gets: nothing about the request is
    # wrong, the item is simply not in play. The service refuses it too -
    # this is only about answering with the state, not the shape.
    _refuse_withdrawn(item, "add a step to it")
    try:
        await service.add_step(
            session,
            item_id,
            name=payload.name,
            step_type=payload.step_type,
            owner=payload.owner,
            after_position=payload.after_position,
            branches=payload.branches,
        )
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item_id))


@router.post("/steps/{step_id}/complete")
async def complete_step(
    step_id: uuid.UUID,
    payload: CompleteRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    step, item = await _step_item(session, step_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        await service.complete_step(session, step_id, user_id=str(user_id), override_reason=payload.override_reason)
    except service.GateBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"error": str(exc), **exc.detail}) from None
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item.id))


@router.post("/steps/{step_id}/uncomplete")
async def uncomplete_step(
    step_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    step, item = await _step_item(session, step_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        await service.uncomplete_step(session, step_id)
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item.id))


@router.post("/steps/{step_id}/not-required")
async def not_required(
    step_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    step, item = await _step_item(session, step_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        await service.mark_not_required(session, step_id, user_id=str(user_id))
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item.id))


@router.post("/steps/{step_id}/route")
async def take_route(
    step_id: uuid.UUID,
    payload: RouteRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    step, item = await _step_item(session, step_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        await service.take_route(session, step_id, payload.branch, user_id=str(user_id))
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await session.commit()
    return await service.item_payload_enriched(session, await _item_or_404(session, item.id))


# ── Email tracking, side-by-side comparison, and reading a reply ─────────


@router.get("/items/{item_id}/tracking")
async def item_tracking(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """Who was asked, who answered, who is silent and for how long."""
    from app.modules.register_workflow import tracking

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    return await tracking.tracking_for(session, item)


@router.get("/tracking")
async def project_email_tracking(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """Every outstanding ask on the job, longest silence first."""
    from app.modules.register_workflow import tracking

    await verify_project_access(project_id, user_id, session)
    return await tracking.project_tracking(session, project_id)


@router.get("/items/{item_id}/compare")
async def item_compare(
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """One column per supplier - figures, evidence and their documents."""
    from app.modules.register_workflow import comparing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    return await comparing.quotes_side_by_side(session, item)


@router.get("/field-suggestions")
async def field_suggestions(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    kind: str = Query(default="rfq", max_length=20),
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """What to pre-fill each field with, and what this job has used before.

    The delivery address defaults to the PROJECT's address; dates default
    to today and today+7; everything else offers this job's own history.
    """
    from app.modules.register_workflow import field_memory

    await verify_project_access(project_id, user_id, session)
    return await field_memory.suggestions_for(session, project_id=project_id, kind=kind)


@router.post("/deadline-sweep")
async def deadline_sweep(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """Announce what has newly fallen due, onto the platform's own bus.

    A POST because it writes: each reason is remembered so it fires at
    most once per item per day. Without that the 45-second poll would
    republish the same overdue RFI every 45 seconds until somebody
    silenced the bell permanently.
    """
    from app.modules.register_workflow import notifying

    await verify_project_access(project_id, user_id, session)
    result = await notifying.sweep_project(session, project_id=project_id)
    await session.commit()
    return result


class LinkRequest(BaseModel):
    """One cross-link: an item by reference, a cost centre, a deliverable
    or a URL."""

    link_type: str = Field(pattern=r"^(item|cost_centre|deliverable|url)$")
    value: str = Field(max_length=200)


class UnlinkRequest(BaseModel):
    index: int = Field(ge=0, le=200)


@router.post("/items/{item_id}/links")
async def add_item_link(
    item_id: uuid.UUID,
    payload: LinkRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Connect this item to an RFI, a cost centre, a deliverable or a URL.

    Item links land on BOTH ends - standing on either shows the other.
    """
    from app.modules.register_workflow import linking

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        links = await linking.add_link(session, item, link_type=payload.link_type, value=payload.value)
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    await session.commit()
    return {"links": links}


@router.post("/items/{item_id}/links/remove")
async def remove_item_link(
    item_id: uuid.UUID,
    payload: UnlinkRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    from app.modules.register_workflow import linking

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        links = await linking.remove_link(session, item, index=payload.index)
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    await session.commit()
    return {"links": links}


@router.get("/supplier-ranking")
async def supplier_ranking(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    kind: str = Query(default="rfq", max_length=20),
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """Which suppliers to float to the top of the picker, and why.

    Server-side because "recent" and "on this job" are facts about the
    data, not about the browser - and because a 434-company directory
    cannot be ranked from the 40 rows a search happened to return.
    """
    from app.modules.register_workflow import ranking

    await verify_project_access(project_id, user_id, session)
    return await ranking.ranking_for(session, project_id=project_id, kind=kind)


@router.get("/items/{item_id}/messages/{correspondence_id}")
async def read_message(
    item_id: uuid.UUID,
    correspondence_id: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """One received email, sanitised for rendering in the buyer's session."""
    from app.modules.register_workflow import comparing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        return await comparing.message_for_viewing(session, item, correspondence_id)
    except comparing.CompareError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


class ReplyDraftRequest(BaseModel):
    """Reply / reply-all / forward, off ONE message."""

    mode: str = Field(default="reply", max_length=20)
    #: Additive on a reply, and the whole answer on a forward.
    to: list[str] = Field(default_factory=list, max_length=30)
    body: str = Field(default="", max_length=50_000)


@router.post("/items/{item_id}/messages/{correspondence_id}/reply-preview")
async def preview_reply(
    item_id: uuid.UUID,
    correspondence_id: str,
    payload: ReplyDraftRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
) -> dict:
    """What the draft WILL be - same builder as the draft endpoint below.

    Preview and send going through different code is how a screen ends up
    showing something other than what left the building.
    """
    from app.modules.register_workflow import comparing, replying

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        built = await replying.build_reply(
            session,
            item,
            correspondence_id=correspondence_id,
            mode=payload.mode,
            to=payload.to,
            body=payload.body,
        )
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except comparing.CompareError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    # Server paths are not the browser's business.
    return {k: v for k, v in built.items() if k != "attachment_paths"}


@router.post("/items/{item_id}/messages/{correspondence_id}/reply-draft")
async def draft_reply(
    item_id: uuid.UUID,
    correspondence_id: str,
    payload: ReplyDraftRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.update")),
) -> dict:
    """Open the SAME payload the preview showed as an Outlook draft.

    Nothing is sent from here: the draft opens in the user's Outlook,
    where they read it and press Send themselves. That is the rule the
    whole email path is built on.
    """
    from app.modules.outlook_bridge import service as bridge
    from app.modules.register_workflow import comparing, replying

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    _refuse_withdrawn(item, "reply from it")
    try:
        built = await replying.build_reply(
            session,
            item,
            correspondence_id=correspondence_id,
            mode=payload.mode,
            to=payload.to,
            body=payload.body,
        )
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except comparing.CompareError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None

    shown = {k: v for k, v in built.items() if k != "attachment_paths"}
    try:
        # ONE draft path for the whole product: the bridge writes the body
        # to a file (a Windows command line caps at 32,767 characters and a
        # draft is many times that), opens it, and logs it on the record.
        await bridge.open_payload_in_outlook(
            session,
            {**built, "cc": [], "bcc": [], "attachments": built.get("attachment_paths") or []},
            user_id=str(user_id),
        )
    except Exception as exc:  # noqa: BLE001 - no Outlook is an ordinary state here
        # What was typed is handed straight back, so a machine without
        # Outlook loses the draft-opening, not the draft.
        logger.info("register_workflow.reply_draft_unavailable %s", exc)
        return {**shown, "opened": False, "error": str(exc)}
    await session.commit()
    return {**shown, "opened": True}


@router.get("/items/{item_id}/messages/{correspondence_id}/documents/{filename}")
async def read_message_document(
    item_id: uuid.UUID,
    correspondence_id: str,
    filename: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("register_workflow.read")),
):
    """A supplier's quote document, proxied so the browser needs no key.

    The path comes from the RECORD, never from the request - the request
    only names which message and which of its filenames.
    """
    from fastapi.responses import FileResponse

    from app.modules.register_workflow import comparing

    item = await _item_or_404(session, item_id)
    await verify_project_access(item.project_id, user_id, session)
    try:
        path, media, inline = await comparing.find_document(session, item, correspondence_id, filename)
    except comparing.CompareError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path,
        media_type=media,
        headers={
            "Content-Disposition": f'{disposition}; filename="{path.name}"',
            # Untrusted content served same-origin: stop it doing anything
            # but render, and never let it be sniffed into something else.
            "Content-Security-Policy": "default-src 'none'; object-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )
