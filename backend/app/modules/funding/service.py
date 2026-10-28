# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Public funding business logic.

Three things here are worth more than the CRUD around them.

**Deadlines are derived, once, from the award.** The moment an award is
recorded, every date the programme's own terms imply becomes knowable: when
the report is due, how long money may sit unspent, how long the vouchers must
be kept. Working them out at read time would mean every screen recomputes
them and a change to the programme's terms silently moves a deadline that has
already been communicated to a person. So they are written down as
obligations, once, and the rows say they came from a programme rule.

**Rollups are derived, always.** Approved against drawn against received is
the question every funding officer asks, and each part already lives in a
row. A stored total is the copy that is wrong in the screenshot somebody
forwards to an auditor.

**Validation is part of reading an application, not a screen somebody opens.**
``GET /applications/{id}`` returns the findings with the record.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.funding.models import (
    FundingApplication,
    FundingObligation,
    FundingProgramme,
)
from app.modules.funding.repository import (
    ApplicationRepository,
    CostAllocationRepository,
    DisbursementRepository,
    ObligationRepository,
    ProgrammeRepository,
    ProofOfUseRepository,
)
from app.modules.funding.validators import FUNDING_RULE_SET

logger = logging.getLogger(__name__)

#: Obligation kinds this module generates from a programme's terms. Only
#: these are replaced when an award is re-recorded; anything a person typed
#: survives untouched.
DERIVED_OBLIGATION_KINDS = ["final_report", "retention_end", "spend_window"]

#: The English sentence behind each derived obligation's ``detail_key``.
#:
#: A derived deadline is explained twice, once as a message key with the
#: values it interpolates and once as prose. The key is the contract, because
#: it is the half that can still be translated after the row is written; the
#: prose is what a caller with no message bundle reads. They are kept in one
#: table so the two halves cannot say different things, which is what happens
#: when a sentence is edited at the call site and its key is not.
#:
#: ``retention_end`` appears twice on purpose. The same kind of deadline is
#: worded one way while it is counted from the end of the award period and
#: another way once the proof of use has been accepted and it is recounted
#: from that day. A caller cannot tell those apart from ``kind`` alone, which
#: is why the key is stored on the row rather than derived from it.
OBLIGATION_DETAIL_TEMPLATES: dict[str, str] = {
    "funding.obligation_detail.final_report": (
        "Due {days} days after the award period ends, under the terms of {programme}"
    ),
    "funding.obligation_detail.retention_end": (
        "{years} years of record keeping required by {programme}. "
        "Recomputed from the acceptance date once the proof of use is accepted."
    ),
    "funding.obligation_detail.retention_end_accepted": (
        "{years} years from acceptance of the proof of use on {accepted_on}"
    ),
    "funding.obligation_detail.spend_window": "{days} days from receipt, under the terms of {programme}",
}


def render_detail(detail_key: str, params: dict[str, Any]) -> str:
    """The English prose for one derived obligation.

    Args:
        detail_key: A key of :data:`OBLIGATION_DETAIL_TEMPLATES`.
        params: The values the template interpolates. Extra values are
            ignored, so a caller may pass everything it knows about the row.

    Returns:
        The rendered sentence, or an empty string when the key is unknown or
        a value the template needs is missing. Empty rather than half a
        sentence: the key and the parameters are still on the row, and a
        caller that can translate loses nothing.
    """
    template = OBLIGATION_DETAIL_TEMPLATES.get(detail_key, "")
    if not template:
        return ""
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        logger.warning("funding obligation detail %s was given no value for one of its placeholders", detail_key)
        return ""


#: The values a derived title names that its message key does not interpolate.
#:
#: ``funding.obligation_kind.spend_window`` reads "Spend the funds drawn", with
#: no placeholder in it, and it stays that way: the same key labels the group a
#: deadline belongs to as well as the deadline itself, so a draw number put
#: inside it would split that group into one bucket per draw. The English title
#: does say which draw, so the number travels beside the key instead of inside
#: it, and a caller attaches it the way its own screen attaches a reference.
TITLE_REFERENCE_PARAMS: tuple[str, ...] = ("sequence",)


def obligation_title_key(row: FundingObligation) -> str:
    """The message key for a row's title, or empty when there is not one.

    A deadline this module derived is named by its ``kind``, which is an enum
    and is translated wherever the reader is. A deadline somebody typed is
    named by what they typed, and replacing their words with a translation of
    something else loses the note they wrote.

    ``source`` is what separates the two. ``programme_rule`` is the value this
    module writes on the rows it derives, and the one it forces hand written
    obligations away from, so it is the single value that means "the server
    wrote this title". Asking about ``manual`` alone answered the award notice
    case wrongly: a condition copied out of a notice is typed by a person
    exactly as a manual one is, and it came back with a key beside it, so a
    caller that believed the key showed "Condition of the award" where
    somebody had written what the condition actually was.

    A row carrying no words of its own still gets the kind key, because an
    empty key beside an empty title leaves a reader with an empty cell.

    Args:
        row: The obligation to name.

    Returns:
        A ``funding.obligation_kind.`` key, or an empty string when the title
        belongs to the person who typed it.
    """
    if row.source != "programme_rule" and str(row.title or "").strip():
        return ""
    return f"funding.obligation_kind.{row.kind}"


def obligation_title_params(row: FundingObligation) -> dict[str, Any]:
    """The references a row's title names, for a caller rendering its key.

    Empty for a title somebody typed, which has no key to go beside, and empty
    for the kinds whose title is the whole sentence.

    ``detail_params`` is read defensively rather than indexed. It is newer than
    the table and arrives nullable on an installation that reached it through
    the boot heal, so a row written before it existed reads back ``None``.
    Indexing that is a 500 on the summary endpoint, which is the one endpoint
    that stayed up the last time these columns caught somebody out.

    Args:
        row: The obligation whose title is being named.

    Returns:
        The subset of the row's stored values that its title refers to.
    """
    if not obligation_title_key(row):
        return {}
    stored = getattr(row, "detail_params", None) or {}
    return {name: stored[name] for name in TITLE_REFERENCE_PARAMS if name in stored}


#: The fields of an obligation whose words the server wrote itself, in the
#: order a refusal reports them.
#:
#: Both are prose beside a message key, and on a derived row both keys are the
#: server's: ``title_key`` is worked out from ``source`` and ``detail_key`` is
#: stored on the row. A caller is told to render the keys and ignore the
#: prose, so words typed into either field of a derived row are not merely
#: overridden, they are never read. They are listed together because the rule
#: is one rule; splitting it is how the title came to be guarded while the
#: detail was not.
SERVER_AUTHORED_TEXT_FIELDS: tuple[str, ...] = ("title", "detail")

#: The key a caller renders to say the refusal below in its reader's language,
#: and the English it says when the caller has no message bundle. Same
#: arrangement as an obligation's own prose, for the same reason: this server
#: is not told which language the reader has.
DERIVED_WORDING_MESSAGE_KEY = "funding.obligation.derived_wording_is_not_editable"
DERIVED_WORDING_MESSAGE = (
    "This deadline is derived from the programme's terms and its wording is written from them, so it "
    "cannot be replaced here. Add an obligation of your own to track it in your own words."
)


def server_authored_fields_replaced(row: FundingObligation, changes: dict[str, Any]) -> tuple[str, ...]:
    """The server-authored fields a change would replace on a derived row.

    ``obligation_title_key`` decides whether a title is the server's by asking
    ``source``, which is only ever true because this module writes the titles
    of the rows it derives. Nothing was keeping it true afterwards: a change
    could put somebody's words on a ``programme_rule`` row, the row kept that
    source, and so it kept the key, and a caller trusting the key put the
    stock sentence back over what they had typed. This is the guard that makes
    the discriminator hold rather than a second way of deciding it.

    Sending the same words back is not a replacement. A client that reads a
    row, edits its status and sends the whole object is changing nothing here,
    and refusing that would break the one flow the shipped screens use.

    Args:
        row: The obligation as it currently stands.
        changes: The fields the caller actually set, already validated.

    Returns:
        The names of the fields that would be replaced, in the order of
        :data:`SERVER_AUTHORED_TEXT_FIELDS`. Empty when the change leaves the
        server's words alone, which is always the case off a derived row.
    """
    if row.source != "programme_rule":
        return ()
    replaced = []
    for field in SERVER_AUTHORED_TEXT_FIELDS:
        if field not in changes:
            continue
        # ``None`` arrives when a caller sets the field to null, which asks
        # for the server's sentence to be replaced by nothing at all. That is
        # a replacement like any other, so it is compared rather than skipped.
        incoming = "" if changes[field] is None else str(changes[field])
        if incoming.strip() != str(getattr(row, field, "") or "").strip():
            replaced.append(field)
    return tuple(replaced)


def iso_day(value: Any) -> str:
    """The calendar day of an ISO-8601 value, or empty when there is none."""
    text = str(value or "").strip()
    if len(text) < 10:
        return ""
    candidate = text[:10]
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return ""
    return candidate


def _plus_days(day: str, days: int) -> str:
    """``day`` moved forward by ``days``, or empty when either is missing."""
    base = iso_day(day)
    if not base or days <= 0:
        return ""
    return (date.fromisoformat(base) + timedelta(days=days)).isoformat()


def _plus_years(day: str, years: int) -> str:
    """``day`` moved forward by whole years.

    February the twenty-ninth plus one year is the twenty-eighth, which is
    what every retention rule means and what ``timedelta`` cannot express.
    """
    base = iso_day(day)
    if not base or years <= 0:
        return ""
    start = date.fromisoformat(base)
    try:
        return start.replace(year=start.year + years).isoformat()
    except ValueError:
        return start.replace(year=start.year + years, day=28).isoformat()


class FundingService:
    """Stateless operations over the funding records of one tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.programmes = ProgrammeRepository(session)
        self.applications = ApplicationRepository(session)
        self.disbursements = DisbursementRepository(session)
        self.proofs = ProofOfUseRepository(session)
        self.obligations = ObligationRepository(session)
        self.allocations = CostAllocationRepository(session)

    # ── Awards and the deadlines that follow ────────────────────────────

    async def record_award(
        self,
        application: FundingApplication,
        *,
        approved: bool,
        decided_on: str = "",
        award_reference: str = "",
        approved_amount: Decimal = Decimal("0"),
        award_period_start: str = "",
        award_period_end: str = "",
        conditions: str = "",
        rejection_reason: str = "",
    ) -> FundingApplication:
        """Record the authority's decision and regenerate its deadlines."""
        application.decided_on = iso_day(decided_on) or decided_on
        if not approved:
            application.status = "rejected"
            application.rejection_reason = rejection_reason
            application.approved_amount = Decimal("0")
            # A rejection cancels the deadlines the module derived from an
            # earlier approval. Conditions somebody typed in are left, since
            # they may still describe an appeal.
            await self.obligations.delete_derived(application.id, DERIVED_OBLIGATION_KINDS)
            await self.session.flush()
            return application

        application.status = "approved"
        application.award_reference = award_reference
        application.approved_amount = approved_amount
        application.award_period_start = iso_day(award_period_start) or award_period_start
        application.award_period_end = iso_day(award_period_end) or award_period_end
        application.conditions = conditions
        application.rejection_reason = ""

        programme = await self.programmes.get(application.programme_id)
        await self._regenerate_obligations(application, programme)
        await self.session.flush()
        return application

    async def _regenerate_obligations(
        self,
        application: FundingApplication,
        programme: FundingProgramme | None,
    ) -> None:
        """Replace the programme-derived deadlines of one application."""
        await self.obligations.delete_derived(application.id, DERIVED_OBLIGATION_KINDS)
        if programme is None:
            return

        period_end = iso_day(application.award_period_end)

        # The report that closes the award. Its due date is the programme's
        # standing rule applied to the end of the award period; when the
        # programme names no rule, no obligation is invented, because an
        # invented deadline is worse than a missing one: people plan to it.
        due_days = int(programme.proof_of_use_due_days or 0)
        due = _plus_days(period_end, due_days)
        if due:
            detail_key = "funding.obligation_detail.final_report"
            detail_params = {"days": due_days, "programme": programme.code}
            await self.obligations.create(
                application_id=application.id,
                kind="final_report",
                title="Final proof of use",
                detail=render_detail(detail_key, detail_params),
                detail_key=detail_key,
                detail_params=detail_params,
                due_on=due,
                source="programme_rule",
                source_reference=programme.code,
                status="open",
            )

        # How long the vouchers must be kept. Counted from the end of the
        # award period rather than from acceptance of the report, because
        # acceptance has not happened yet and a date nobody can compute is a
        # date nobody diarises. It is recomputed on acceptance.
        retention_years = int(programme.retention_years or 0)
        retention = _plus_years(period_end, retention_years)
        if retention:
            detail_key = "funding.obligation_detail.retention_end"
            detail_params = {"years": retention_years, "programme": programme.code}
            await self.obligations.create(
                application_id=application.id,
                kind="retention_end",
                title="Records may be destroyed",
                detail=render_detail(detail_key, detail_params),
                detail_key=detail_key,
                detail_params=detail_params,
                due_on=retention,
                source="programme_rule",
                source_reference=programme.code,
                status="open",
            )

    async def on_funds_received(
        self,
        application: FundingApplication,
        disbursement: Any,
        received_on: str,
    ) -> None:
        """Stamp the spend deadline a receipt starts, and diarise it.

        Several jurisdictions require money to be spent within a short window
        of arriving, and missing it turns into an interest claim rather than
        a warning. The deadline is written onto the draw so it cannot move if
        the programme's terms are edited afterwards.
        """
        disbursement.received_on = iso_day(received_on) or received_on
        disbursement.status = "paid"

        programme = await self.programmes.get(application.programme_id)
        window = int(getattr(programme, "disbursement_spend_days", 0) or 0)
        deadline = _plus_days(disbursement.received_on, window)
        disbursement.spend_deadline_on = deadline
        if deadline:
            detail_key = "funding.obligation_detail.spend_window"
            detail_params = {
                "days": window,
                "programme": getattr(programme, "code", ""),
                # Which draw this window belongs to. The sentence does not
                # use it; the title does, and a caller rendering the title
                # from ``kind`` would otherwise be left matching draws on the
                # deadline date and guessing whenever two of them share one.
                "sequence": disbursement.sequence,
            }
            await self.obligations.create(
                application_id=application.id,
                kind="spend_window",
                title=f"Spend the funds drawn in request {disbursement.sequence}",
                detail=render_detail(detail_key, detail_params),
                detail_key=detail_key,
                detail_params=detail_params,
                due_on=deadline,
                source="programme_rule",
                source_reference=getattr(programme, "code", ""),
                status="open",
            )
        await self.session.flush()

    async def on_proof_accepted(self, application: FundingApplication, proof: Any, accepted_on: str) -> None:
        """Move the retention deadline onto the date acceptance actually was."""
        proof.accepted_on = iso_day(accepted_on) or accepted_on
        proof.status = "accepted"

        programme = await self.programmes.get(application.programme_id)
        years = int(getattr(programme, "retention_years", 0) or 0)
        proof.retention_until = _plus_years(proof.accepted_on, years)
        if proof.retention_until:
            await self.obligations.delete_derived(application.id, ["retention_end"])
            detail_key = "funding.obligation_detail.retention_end_accepted"
            detail_params = {"years": years, "accepted_on": proof.accepted_on}
            await self.obligations.create(
                application_id=application.id,
                kind="retention_end",
                title="Records may be destroyed",
                detail=render_detail(detail_key, detail_params),
                detail_key=detail_key,
                detail_params=detail_params,
                due_on=proof.retention_until,
                source="programme_rule",
                source_reference=getattr(programme, "code", ""),
                status="open",
            )
        await self.session.flush()

    # ── Rollups ─────────────────────────────────────────────────────────

    async def application_summary(self, application: FundingApplication, today: str = "") -> dict[str, Any]:
        """Where one application stands, entirely derived from its rows."""
        draws = await self.disbursements.totals(application.id)
        allocated = await self.allocations.totals(application.id)
        obligations = await self.obligations.list_for_application(application.id)
        programme = await self.programmes.get(application.programme_id)

        approved = Decimal(str(application.approved_amount or 0))
        received = draws["received"]
        base = Decimal(str(application.eligible_cost_base or 0))

        own_rate = Decimal(str(getattr(programme, "own_share_percent", 0) or 0))
        own_required = (base * own_rate / Decimal("100")).quantize(Decimal("0.01")) if base > 0 else Decimal("0")
        effective_rate = (approved * Decimal("100") / base).quantize(Decimal("0.01")) if base > 0 else Decimal("0")

        day = iso_day(today)
        open_rows = [row for row in obligations if row.status == "open"]
        overdue = [row for row in open_rows if day and iso_day(row.due_on) and iso_day(row.due_on) < day]
        upcoming = sorted((row for row in open_rows if iso_day(row.due_on)), key=lambda row: iso_day(row.due_on))

        return {
            "application_id": application.id,
            "currency": application.currency,
            "approved_amount": approved,
            "requested_amount": Decimal(str(application.requested_amount or 0)),
            "drawn_amount": draws["requested"],
            "received_amount": received,
            # What the award still owes, floored at zero: an overpayment is a
            # different conversation and showing it as a negative claim would
            # invite somebody to draw it.
            "outstanding_amount": max(approved - received, Decimal("0")),
            "eligible_cost_base": base,
            "allocated_amount": allocated["amount"],
            "allocated_eligible_amount": allocated["eligible"],
            "own_share_required": own_required,
            "own_share_recorded": Decimal(str(application.own_share_amount or 0)),
            "effective_funding_rate_percent": effective_rate,
            "obligations_open": len(open_rows),
            "obligations_overdue": len(overdue),
            "next_due_on": iso_day(upcoming[0].due_on) if upcoming else "",
            # The title carries whatever the obligation carries, which for a
            # derived deadline is English. The key and its references travel
            # beside it so a caller can name the next deadline in its reader's
            # language rather than repeating the server's, and can tell the two
            # cases apart: an empty key means the words are somebody's own and
            # the title is the right thing to show.
            #
            # ``kind`` alone could not answer that. A hand written obligation
            # is usually a ``condition`` but does not have to be, and a derived
            # one is a ``final_report`` the same way an award notice condition
            # somebody typed can be. The key is decided by who wrote the title,
            # which is a different question from what the deadline is about.
            "next_due_title": upcoming[0].title if upcoming else "",
            "next_due_kind": upcoming[0].kind if upcoming else "",
            "next_due_title_key": obligation_title_key(upcoming[0]) if upcoming else "",
            "next_due_title_params": obligation_title_params(upcoming[0]) if upcoming else {},
        }

    async def project_summary(self, project_id: uuid.UUID, today: str = "") -> dict[str, Any]:
        """Every application on one project, added up."""
        applications = await self.applications.list_for_project(project_id)
        ids = [row.id for row in applications]

        draws = await self.disbursements.list_for_applications(ids)
        obligations = await self.obligations.list_for_applications(ids)

        live = [row for row in applications if row.status not in ("withdrawn", "rejected")]
        approved_rows = [row for row in applications if row.status == "approved"]

        approved_total = sum((Decimal(str(row.approved_amount or 0)) for row in approved_rows), Decimal("0"))
        received_total = sum((Decimal(str(row.amount_received or 0)) for row in draws), Decimal("0"))
        # The base is the largest eligible base any live application declares,
        # not their sum. Two programmes funding the same building are looking
        # at the same costs, and adding the bases would halve the intensity
        # exactly where it matters.
        base = max((Decimal(str(row.eligible_cost_base or 0)) for row in live), default=Decimal("0"))

        caps = []
        for row in live:
            programme = await self.programmes.get(row.programme_id)
            cap = Decimal(str(getattr(programme, "aid_intensity_cap_percent", 0) or 0))
            if cap > 0:
                caps.append(cap)

        intensity = (approved_total * Decimal("100") / base).quantize(Decimal("0.01")) if base > 0 else Decimal("0")

        day = iso_day(today)
        open_rows = [row for row in obligations if row.status == "open"]
        overdue = [row for row in open_rows if day and iso_day(row.due_on) and iso_day(row.due_on) < day]

        return {
            "project_id": project_id,
            "currency": applications[0].currency if applications else "EUR",
            "application_count": len(applications),
            "approved_count": len(approved_rows),
            "approved_amount": approved_total,
            "received_amount": received_total,
            "outstanding_amount": max(approved_total - received_total, Decimal("0")),
            "eligible_cost_base": base,
            "aid_intensity_percent": intensity,
            "aid_intensity_cap_percent": min(caps) if caps else Decimal("0"),
            "obligations_open": len(open_rows),
            "obligations_overdue": len(overdue),
        }

    # ── Validation ──────────────────────────────────────────────────────

    async def validate_application(
        self,
        application: FundingApplication,
        *,
        locale: str = "en",
        today: str = "",
    ) -> list[dict[str, Any]]:
        """Run the funding rule set over one application.

        The payload carries the application's own peers on the project,
        because cumulation cannot be judged from one application alone, and
        it carries the caller's date, because "late" is a question about a
        calendar and the server's own clock is not the reader's.
        """
        programme = await self.programmes.get(application.programme_id)
        disbursements = await self.disbursements.list_for_application(application.id)
        proofs = await self.proofs.list_for_application(application.id)
        peers = await self.applications.list_for_project(application.project_id)

        peer_rows = []
        for row in peers:
            peer_programme = await self.programmes.get(row.programme_id)
            peer_rows.append(
                {
                    "id": str(row.id),
                    "status": row.status,
                    "approved_amount": row.approved_amount,
                    "requested_amount": row.requested_amount,
                    "aid_intensity_cap_percent": getattr(peer_programme, "aid_intensity_cap_percent", 0),
                }
            )

        payload = {
            "application": {
                "id": str(application.id),
                "project_id": str(application.project_id),
                "code": application.code,
                "status": application.status,
                # Carried so a finding can say which currency its amounts are
                # in. A workspace running a euro programme alongside a sterling
                # one gets two findings whose numbers mean different things,
                # and a bare figure does not say which is which.
                "currency": application.currency,
                "submitted_on": application.submitted_on,
                "measure_start_on": application.measure_start_on,
                "early_start_approved": application.early_start_approved,
                "early_start_reference": application.early_start_reference,
                "award_period_start": application.award_period_start,
                "award_period_end": application.award_period_end,
                "eligible_cost_base": application.eligible_cost_base,
                "own_share_amount": application.own_share_amount,
                "approved_amount": application.approved_amount,
            },
            "programme": {
                "code": getattr(programme, "code", ""),
                "requires_application_before_start": getattr(programme, "requires_application_before_start", True),
                "own_share_percent": getattr(programme, "own_share_percent", 0),
                "aid_intensity_cap_percent": getattr(programme, "aid_intensity_cap_percent", 0),
            },
            "disbursements": [
                {
                    "id": str(row.id),
                    "code": row.code,
                    "sequence": row.sequence,
                    "status": row.status,
                    "period_from": row.period_from,
                    "period_to": row.period_to,
                }
                for row in disbursements
            ],
            "proofs_of_use": [
                {
                    "id": str(row.id),
                    "kind": row.kind,
                    "status": row.status,
                    "due_on": row.due_on,
                    "submitted_on": row.submitted_on,
                }
                for row in proofs
            ],
            "project_applications": peer_rows,
            "clock": {"today": iso_day(today)},
        }

        context = ValidationContext(
            data=payload,
            project_id=str(application.project_id),
            metadata={"locale": locale},
        )
        results: list[dict[str, Any]] = []
        # The registry resolves a rule set through a set, so the order it
        # hands back is not stable between runs. Sorted by rule id, because a
        # findings list that reshuffles itself on refresh reads as if the
        # data changed.
        rules = sorted(rule_registry.get_rules_for_sets([FUNDING_RULE_SET]), key=lambda item: item.rule_id)
        for rule in rules:
            try:
                for result in await rule.validate(context):
                    results.append(
                        {
                            "rule_id": result.rule_id,
                            "rule_name": result.rule_name,
                            "severity": str(result.severity),
                            "category": str(result.category),
                            "passed": result.passed,
                            "message": result.message,
                            "element_ref": result.element_ref,
                            "suggestion": result.suggestion,
                        }
                    )
            except Exception:
                # One rule failing must not cost the reader the other four,
                # and must not turn a read of the record into a 500.
                logger.exception("funding rule %s failed", getattr(rule, "rule_id", "?"))
        return results
