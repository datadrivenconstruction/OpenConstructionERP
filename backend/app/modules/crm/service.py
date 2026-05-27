"""‌⁠‍CRM service — business logic for sales pipeline, forecasting, analytics.

Pure helpers (no I/O) for math + state-machine validation are kept at module
level so they can be unit-tested in isolation. Anything that hits the DB
lives on :class:`CrmService`.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.events import event_bus
from app.modules.crm.models import (
    Account,
    CrmActivity,
    Forecast,
    Lead,
    Opportunity,
    OpportunityStageHistory,
)
from app.modules.crm.repository import (
    AccountRepository,
    ActivityRepository,
    ForecastRepository,
    LeadRepository,
    OpportunityRepository,
    PipelineStageRepository,
    StageHistoryRepository,
    WinLossReasonRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.crm.schemas import (
        AccountCreate,
        AccountUpdate,
        ActivityCreate,
        ActivityUpdate,
        LeadConvertRequest,
        LeadCreate,
        LeadUpdate,
        OpportunityCreate,
        OpportunityUpdate,
        PipelineStageCreate,
        PipelineStageUpdate,
        WinLossReasonCreate,
        WinLossReasonUpdate,
    )

logger = logging.getLogger(__name__)


# ── PII redaction (GDPR Art. 5(1)(c) data-minimisation in logs) ────────────
#
# Round-5 audit (v4.3.0): Lead.contact_email / Lead.contact_phone were
# previously written into INFO log records by ``create_lead`` /
# ``convert_lead`` via the generic ``logger.info("CRM lead created: %s", ...)``
# pattern. Lead emails and phones are PII; once they hit syslog / journald
# they outlive the row itself and survive every GDPR "forget" request.
# Mirror the ``contacts`` module: redact at the boundary, never log raw
# values, never put raw values in audit ``details``.


def _redact_email(email: str | None) -> str:
    """Return ``j***@example.com`` so support can still triage by domain."""
    if not email:
        return "<no-email>"
    if "@" not in email:
        return "<redacted>"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if local else f"***@{domain}"


def _redact_phone(phone: str | None) -> str:
    """Return ``+49…567`` — preserves dial-code + last 3 digits only."""
    if not phone:
        return "<no-phone>"
    cleaned = re.sub(r"\D", "", phone)
    if len(cleaned) <= 4:
        return "<redacted>"
    prefix = phone[:3] if phone.startswith("+") else cleaned[:2]
    return f"{prefix}…{cleaned[-3:]}"


def _safe_lead_label(lead: Any) -> str:
    """Build a log-safe label from a Lead row. Never interpolates raw PII."""
    name = getattr(lead, "contact_name", None) or ""
    # First name + last-initial only — full names are also PII under most
    # interpretations of GDPR Art. 4(1).
    parts = name.split()
    if not parts:
        return "<lead:?>"
    if len(parts) == 1:
        return f"<lead:{parts[0][:1]}>"
    return f"<lead:{parts[0]} {parts[-1][:1]}>"


# ── Viewer-aware PII redaction (response boundary) ────────────────────────
#
# R7 audit: ``LeadResponse`` historically echoed raw ``contact_email`` /
# ``contact_phone`` to anyone holding ``crm.read`` (VIEWER role). That
# leaks GDPR-class PII into rep dashboards, audit exports and any sub-
# contractor with read-only access. Redact at the response boundary so
# only the lead owner (``assigned_to``), admins and managers see full
# values. Everyone else gets ``j***@example.com`` / ``+49…567``.

_PII_FULL_ACCESS_ROLES: frozenset[str] = frozenset({"admin", "manager"})


def viewer_can_see_lead_pii(
    lead: Any,
    *,
    viewer_id: str | None,
    viewer_role: str | None,
) -> bool:
    """Return True iff the viewer is owner / manager+ / admin."""
    if viewer_role and viewer_role.lower() in _PII_FULL_ACCESS_ROLES:
        return True
    assigned_to = getattr(lead, "assigned_to", None)
    if assigned_to is None or viewer_id is None:
        return False
    return str(assigned_to) == str(viewer_id)


def _redact_email_response(email: str | None) -> str | None:
    """Response-safe email redaction. Returns None on missing — never a label."""
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if local else f"***@{domain}"


def _redact_phone_response(phone: str | None) -> str | None:
    """Response-safe phone redaction. Returns None on missing — never a label."""
    if not phone:
        return None
    cleaned = re.sub(r"\D", "", phone)
    if len(cleaned) <= 4:
        return None
    prefix = phone[:3] if phone.startswith("+") else cleaned[:2]
    return f"{prefix}…{cleaned[-3:]}"


def redact_lead_pii(
    lead: Any,
    *,
    viewer_id: str | None,
    viewer_role: str | None,
) -> tuple[str | None, str | None]:
    """Return ``(email, phone)`` tuple — full values for owners, redacted otherwise.

    Use this in router handlers BEFORE constructing the ``LeadResponse`` so
    the response payload itself never carries raw PII for non-owners. Logs
    and audit-trail entries should still use ``_redact_email`` directly.
    """
    raw_email = getattr(lead, "contact_email", None)
    raw_phone = getattr(lead, "contact_phone", None)
    if viewer_can_see_lead_pii(lead, viewer_id=viewer_id, viewer_role=viewer_role):
        return raw_email, raw_phone
    return _redact_email_response(raw_email), _redact_phone_response(raw_phone)


# ── State machines ─────────────────────────────────────────────────────────


_LEAD_TRANSITIONS: dict[str, set[str]] = {
    "new": {"qualifying", "disqualified"},
    "qualifying": {"qualified", "disqualified"},
    "qualified": {"converted", "disqualified"},
    "disqualified": set(),
    "converted": set(),
}


_OPPORTUNITY_TRANSITIONS: dict[str, set[str]] = {
    "open": {"won", "lost", "abandoned"},
    "won": set(),
    "lost": set(),
    "abandoned": set(),
}


def allowed_lead_transitions(current: str) -> set[str]:
    """‌⁠‍Return the set of valid status transitions from ``current``."""
    return set(_LEAD_TRANSITIONS.get(current, set()))


def allowed_opportunity_transitions(current: str) -> set[str]:
    """‌⁠‍Return the set of valid status transitions for an opportunity from ``current``."""
    return set(_OPPORTUNITY_TRANSITIONS.get(current, set()))


# ── Pure helpers (math / aggregations) ─────────────────────────────────────


def _q2(value: Decimal | int | float) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_weighted_value(value: Decimal | int | float, probability_percent: int) -> Decimal:
    """weighted = value * probability / 100  (rounded to 2dp).

    Negative probabilities are clamped to 0; >100 clamped to 100.
    """
    pct = max(0, min(100, int(probability_percent)))
    return _q2(Decimal(value) * Decimal(pct) / Decimal(100))


def _opp_value(opp: Any) -> Decimal:
    """Return estimated_value as Decimal, coercing None/missing."""
    raw = getattr(opp, "estimated_value", 0) or 0
    return Decimal(raw)


def _opp_weighted(opp: Any) -> Decimal:
    raw = getattr(opp, "weighted_value", None)
    if raw is None:
        return compute_weighted_value(_opp_value(opp), getattr(opp, "probability_percent", 0))
    return Decimal(raw)


def compute_pipeline_metrics(opportunities: Iterable[Any]) -> dict[str, Any]:
    """Pure aggregation over opportunities — pipeline counts + weighted value.

    Returns:
        {
          "open_count": int,
          "weighted_value": Decimal,
          "total_value": Decimal,
          "by_stage": { stage_id_str: {"count": int, "weighted": Decimal, "total": Decimal} },
          "win_rate_30d": Decimal,
        }
    """
    opps = list(opportunities)
    open_opps = [o for o in opps if getattr(o, "status", None) == "open"]

    total_value = sum((_opp_value(o) for o in open_opps), Decimal(0))
    weighted_value = sum((_opp_weighted(o) for o in open_opps), Decimal(0))

    by_stage: dict[str, dict[str, Any]] = {}
    for o in open_opps:
        sid = str(getattr(o, "stage_id", "") or "")
        bucket = by_stage.setdefault(sid, {"count": 0, "weighted": Decimal(0), "total": Decimal(0)})
        bucket["count"] += 1
        bucket["weighted"] += _opp_weighted(o)
        bucket["total"] += _opp_value(o)

    # 30-day win rate over closed deals
    now = datetime.now(UTC).date().isoformat()
    cutoff = (datetime.now(UTC).date()).toordinal() - 30
    recent_won = 0
    recent_lost = 0
    for o in opps:
        won_at = getattr(o, "won_at", None)
        lost_at = getattr(o, "lost_at", None)
        if getattr(o, "status", None) == "won" and won_at:
            try:
                ordinal = datetime.fromisoformat(won_at[:10]).toordinal()
                if ordinal >= cutoff:
                    recent_won += 1
            except (ValueError, TypeError):
                pass
        elif getattr(o, "status", None) == "lost" and lost_at:
            try:
                ordinal = datetime.fromisoformat(lost_at[:10]).toordinal()
                if ordinal >= cutoff:
                    recent_lost += 1
            except (ValueError, TypeError):
                pass

    denom = recent_won + recent_lost
    win_rate_30d = _q2(Decimal(recent_won) * Decimal(100) / Decimal(denom)) if denom else Decimal("0.00")

    return {
        "open_count": len(open_opps),
        "weighted_value": _q2(weighted_value),
        "total_value": _q2(total_value),
        "by_stage": {
            k: {
                "count": v["count"],
                "weighted": _q2(v["weighted"]),
                "total": _q2(v["total"]),
            }
            for k, v in by_stage.items()
        },
        "win_rate_30d": win_rate_30d,
        "_now": now,
    }


def _period_bounds(period: str) -> tuple[str, str]:
    """Return ('YYYY-MM-DD','YYYY-MM-DD') start/end ISO dates for 'YYYY-Qn'."""
    try:
        year_str, q_str = period.split("-Q")
        year = int(year_str)
        q = int(q_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid period format '{period}', expected 'YYYY-Qn'") from exc

    if q not in (1, 2, 3, 4):
        raise ValueError(f"Invalid quarter '{q}' in period '{period}'")

    start_month = 3 * (q - 1) + 1
    end_month = start_month + 2
    end_day = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    # Leap year handling for Q1
    if end_month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        end_day_val = 29
    else:
        end_day_val = end_day[end_month]

    return (
        f"{year:04d}-{start_month:02d}-01",
        f"{year:04d}-{end_month:02d}-{end_day_val:02d}",
    )


def compute_forecast(opportunities: Iterable[Any], period: str) -> dict[str, Any]:
    """Pure forecast computation for a period.

    Filters opportunities to those with ``expected_close_date`` within the
    period bounds, sums their weighted/total/won values, and marks
    high-probability deals (>= 80%) as committed.
    """
    start_date, end_date = _period_bounds(period)

    pipeline_value = Decimal(0)
    weighted_value = Decimal(0)
    won_value = Decimal(0)
    committed_value = Decimal(0)

    for o in opportunities:
        close_date = getattr(o, "expected_close_date", None)
        if not close_date or not (start_date <= str(close_date)[:10] <= end_date):
            continue
        value = _opp_value(o)
        weighted = _opp_weighted(o)
        st = getattr(o, "status", None)
        prob = int(getattr(o, "probability_percent", 0) or 0)
        if st == "won":
            won_value += value
            weighted_value += value  # fully realised
            pipeline_value += value
            committed_value += value
        elif st == "open":
            pipeline_value += value
            weighted_value += weighted
            if prob >= 80:
                committed_value += value

    return {
        "period": period,
        "pipeline_value": _q2(pipeline_value),
        "weighted_value": _q2(weighted_value),
        "won_value": _q2(won_value),
        "committed_value": _q2(committed_value),
        "computed_at": datetime.now(UTC).isoformat(),
    }


def compute_win_rate(
    opportunities: Iterable[Any],
    period_start: str | None,
    period_end: str | None,
) -> Decimal:
    """win = won / (won + lost) within a date window applied to won_at / lost_at.

    Pure: returns Decimal('0.00') when the denominator is zero.
    """
    won = 0
    lost = 0
    for o in opportunities:
        st = getattr(o, "status", None)
        if st == "won":
            d = getattr(o, "won_at", None)
        elif st == "lost":
            d = getattr(o, "lost_at", None)
        else:
            continue
        if d is None:
            continue
        d10 = str(d)[:10]
        if period_start is not None and d10 < period_start:
            continue
        if period_end is not None and d10 > period_end:
            continue
        if st == "won":
            won += 1
        else:
            lost += 1
    denom = won + lost
    if denom == 0:
        return Decimal("0.00")
    return _q2(Decimal(won) * Decimal(100) / Decimal(denom))


def compute_average_sales_cycle(opportunities: Iterable[Any]) -> int:
    """Average days from ``created_at`` to ``won_at``/``lost_at`` for closed deals.

    Returns 0 when nothing has closed yet.
    """
    cycles: list[int] = []
    for o in opportunities:
        st = getattr(o, "status", None)
        if st not in ("won", "lost"):
            continue
        created = getattr(o, "created_at", None)
        if isinstance(created, datetime):
            created_d = created.date()
        elif isinstance(created, str) and created:
            try:
                created_d = datetime.fromisoformat(created[:10]).date()
            except ValueError:
                continue
        else:
            continue

        closed = getattr(o, "won_at" if st == "won" else "lost_at", None)
        if not closed:
            continue
        try:
            closed_d = datetime.fromisoformat(str(closed)[:10]).date()
        except (ValueError, TypeError):
            continue
        delta = (closed_d - created_d).days
        if delta >= 0:
            cycles.append(delta)
    return int(round(sum(cycles) / len(cycles))) if cycles else 0


def compute_lost_reasons_breakdown(
    opportunities: Iterable[Any],
    period_start: str | None,
    period_end: str | None,
) -> dict[str, int]:
    """Histogram of ``lost_reason_code`` for lost deals in the window."""
    out: dict[str, int] = {}
    for o in opportunities:
        if getattr(o, "status", None) != "lost":
            continue
        d = getattr(o, "lost_at", None)
        d10 = str(d)[:10] if d else None
        if period_start is not None and (d10 is None or d10 < period_start):
            continue
        if period_end is not None and (d10 is None or d10 > period_end):
            continue
        code = getattr(o, "lost_reason_code", None) or "unspecified"
        out[code] = out.get(code, 0) + 1
    return out


def convert_opportunity_to_project_payload(opportunity: Any) -> dict[str, Any]:
    """Build a Project-creation payload from a closed-won opportunity.

    Used by the Projects module subscriber that auto-creates a Project on
    ``crm.opportunity.won`` events.
    """
    # Estimated value goes downstream into Project.budget — keep it as a
    # str-formatted Decimal so the subscriber casts back to Decimal without
    # the float-binary-rounding hop. Round-5 audit fixed a ~1-cent drift on
    # round-trip for values >= $10M.
    return {
        "name": getattr(opportunity, "title", "") or "Opportunity Project",
        "description": getattr(opportunity, "description", "") or "",
        "estimated_value": str(_opp_value(opportunity)),
        "currency": getattr(opportunity, "currency", "") or "",
        "owner_user_id": (str(opportunity.owner_user_id) if getattr(opportunity, "owner_user_id", None) else None),
        "source_module": "crm",
        "source_entity": "opportunity",
        "source_id": str(getattr(opportunity, "id", "") or ""),
        "account_id": (str(opportunity.account_id) if getattr(opportunity, "account_id", None) else None),
        # If the deal was already linked to a delivery/estimate project,
        # surface it so the Projects subscriber reuses it instead of
        # spawning a duplicate.
        "existing_project_id": (str(opportunity.project_id) if getattr(opportunity, "project_id", None) else None),
        "primary_contact_id": (
            str(opportunity.primary_contact_id) if getattr(opportunity, "primary_contact_id", None) else None
        ),
    }


# ── Service class ─────────────────────────────────────────────────────────


class CrmService:
    """Business logic for the CRM module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.account_repo = AccountRepository(session)
        self.lead_repo = LeadRepository(session)
        self.opportunity_repo = OpportunityRepository(session)
        self.stage_repo = PipelineStageRepository(session)
        self.history_repo = StageHistoryRepository(session)
        self.activity_repo = ActivityRepository(session)
        self.forecast_repo = ForecastRepository(session)
        self.reason_repo = WinLossReasonRepository(session)

    # ── Accounts ─────────────────────────────────────────────────────────

    async def create_account(self, data: AccountCreate, user_id: str | None = None) -> Account:
        account = Account(
            name=data.name,
            industry=data.industry,
            size_category=data.size_category,
            country=data.country,
            website=data.website,
            primary_contact_id=data.primary_contact_id,
            description=data.description,
            status=data.status,
            owner_user_id=data.owner_user_id,
            tags=list(data.tags or []),
        )
        await self.account_repo.create(account)
        logger.info("CRM account created: %s", account.id)
        return account

    async def get_account(self, account_id: uuid.UUID) -> Account:
        account = await self.account_repo.get_by_id(account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
        return account

    async def update_account(self, account_id: uuid.UUID, data: AccountUpdate) -> Account:
        account = await self.get_account(account_id)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.account_repo.update_fields(account_id, **fields)
            await self.session.refresh(account)
        return account

    async def delete_account(self, account_id: uuid.UUID) -> None:
        await self.get_account(account_id)
        await self.account_repo.delete(account_id)

    # ── Leads ────────────────────────────────────────────────────────────

    async def create_lead(self, data: LeadCreate, user_id: str | None = None) -> Lead:
        # Lead-dedup race: two concurrent inbound webhooks for the same
        # email both passed Pydantic + auth, both call create_lead in
        # parallel, both hit INSERT. Without a guard the second one
        # returns a 500 (no unique index) OR a 200 with a silent
        # duplicate row (with index). Round-5 audit: pre-check (best
        # effort), then translate any IntegrityError on the INSERT
        # itself to 409 — mirrors the contacts module pattern.
        normalised_email = data.contact_email.strip().lower() if data.contact_email else None
        if normalised_email:
            existing = await self.lead_repo.find_by_email(normalised_email)
            # Only block when the existing row is still in an "active" state.
            # disqualified / converted leads are historical and must not stop
            # a fresh inbound for the same person months later.
            if existing is not None and existing.status in ("new", "qualifying", "qualified"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"An active lead with email '{_redact_email(normalised_email)}' "
                        f"already exists (id={existing.id})."
                    ),
                )

        lead = Lead(
            account_id=data.account_id,
            contact_name=data.contact_name,
            contact_email=normalised_email,
            contact_phone=data.contact_phone,
            source=data.source,
            status=data.status,
            assigned_to=data.assigned_to,
            qualification_notes=data.qualification_notes,
        )
        try:
            await self.lead_repo.create(lead)
        except IntegrityError:
            # Race winner already inserted. Roll back our flushed state and
            # surface as 409 so the caller can fetch the existing row.
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A lead with this email already exists.",
            ) from None
        # PII-safe log: never interpolate raw email / phone.
        logger.info(
            "CRM lead created: id=%s label=%s email=%s",
            lead.id,
            _safe_lead_label(lead),
            _redact_email(normalised_email),
        )
        return lead

    async def get_lead(self, lead_id: uuid.UUID) -> Lead:
        lead = await self.lead_repo.get_by_id(lead_id)
        if lead is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
        return lead

    async def update_lead(self, lead_id: uuid.UUID, data: LeadUpdate) -> Lead:
        lead = await self.get_lead(lead_id)
        fields = data.model_dump(exclude_unset=True)
        if "status" in fields and fields["status"] != lead.status:
            self._check_lead_transition(lead.status, fields["status"])
        if fields:
            await self.lead_repo.update_fields(lead_id, **fields)
            await self.session.refresh(lead)
        return lead

    async def delete_lead(self, lead_id: uuid.UUID) -> None:
        await self.get_lead(lead_id)
        await self.lead_repo.delete(lead_id)

    async def forget_lead(self, lead_id: uuid.UUID, user_id: str | None = None) -> dict[str, Any]:
        """GDPR Art. 17 right-to-erasure for a lead and its trail.

        Unlike ``delete_lead`` (which removes the row but leaves PII trapped
        in audit logs and activity bodies), this:

        * Nulls / scrubs every PII column on the Lead row itself (preserves
          the row so downstream foreign keys — e.g. converted_opportunity_id
          — stay valid; auditors still see "a lead existed").
        * Scrubs PII bodies / subjects on every CrmActivity linked to the
          lead.
        * Writes an audit-log entry recording **who** triggered the erasure
          and **when**, so the org can prove compliance.
        * Logs only the redacted label — never the raw values being erased.

        Returns a small summary dict so the API can report what was touched
        (counts only; never the values).
        """
        lead = await self.get_lead(lead_id)
        original_label = _safe_lead_label(lead)
        scrub_marker = f"<erased:{datetime.now(UTC).date().isoformat()}>"

        # 1. Scrub the lead row itself. Keep status / lifecycle so audit
        #    counts (e.g. win-rate denominators) stay consistent.
        # R8 audit: ``source`` is String(32) but some integrations write a
        # free-form referral label such as "referral:john.doe@corp.com" —
        # that is GDPR-class PII (Art. 4(1) direct identifier) and must be
        # erased alongside the contact fields.
        await self.lead_repo.update_fields(
            lead_id,
            contact_name=scrub_marker,
            contact_email=None,
            contact_phone=None,
            source=scrub_marker,
            qualification_notes="",
        )

        # 2. Scrub linked activities.
        # ``update_fields`` calls ``session.expire_all()`` between iterations
        # which invalidates every loaded attribute; if we held ``act`` and
        # read ``act.id`` on the next loop, SQLAlchemy would re-trigger IO
        # outside the async greenlet (raising MissingGreenlet). Snapshot the
        # IDs up-front so the loop never touches stale ORM state.
        # R8 audit: ``outcome`` is a free-text field that reps often populate
        # with direct-speech notes ("Spoke to John, he said …") — PII risk
        # identical to body/subject. Scrub it alongside body.
        activities, _ = await self.activity_repo.list_all(limit=10000, lead_id=lead_id)
        activity_ids = [act.id for act in activities]
        for activity_id in activity_ids:
            await self.activity_repo.update_fields(
                activity_id,
                subject=scrub_marker,
                body="",
                outcome=None,
            )

        # 3. Audit-log the action (best-effort; never block the erasure).
        try:
            from app.core.audit import audit_log

            await audit_log(
                self.session,
                action="forget",
                entity_type="crm_lead",
                entity_id=str(lead_id),
                user_id=user_id,
                details={
                    "label": original_label,
                    "activities_scrubbed": len(activities),
                    "reason": "gdpr_art_17",
                },
            )
        except Exception:  # noqa: BLE001
            logger.warning("CRM forget_lead: audit-log write skipped")

        logger.info(
            "CRM lead erased (GDPR): id=%s label=%s by=%s activities_scrubbed=%s",
            lead_id,
            original_label,
            user_id,
            len(activities),
        )
        return {
            "lead_id": str(lead_id),
            "activities_scrubbed": len(activities),
            "erased_at": datetime.now(UTC).isoformat(),
        }

    def _check_lead_transition(self, current: str, target: str) -> None:
        if target not in allowed_lead_transitions(current):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid lead status transition: {current} → {target}",
            )

    async def qualify_lead(
        self,
        lead_id: uuid.UUID,
        qualification_notes: str,
        user_id: str | None = None,
    ) -> Lead:
        """Move new→qualifying→qualified (depending on current state)."""
        lead = await self.get_lead(lead_id)
        now_iso = datetime.now(UTC).isoformat()

        if lead.status == "new":
            target = "qualifying"
        elif lead.status == "qualifying":
            target = "qualified"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot qualify lead in status '{lead.status}'",
            )

        fields: dict[str, Any] = {
            "status": target,
            "qualification_notes": qualification_notes or lead.qualification_notes,
        }
        if target == "qualified":
            fields["qualified_at"] = now_iso

        await self.lead_repo.update_fields(lead_id, **fields)
        await self.session.refresh(lead)

        if target == "qualified":
            event_bus.publish_detached(
                "crm.lead.qualified",
                data={
                    "lead_id": str(lead_id),
                    "account_id": str(lead.account_id) if lead.account_id else None,
                    "qualified_by": user_id,
                },
                source_module="crm",
            )
        logger.info("CRM lead %s → %s", lead_id, target)
        return lead

    async def disqualify_lead(self, lead_id: uuid.UUID, user_id: str | None = None) -> Lead:
        lead = await self.get_lead(lead_id)
        self._check_lead_transition(lead.status, "disqualified")
        await self.lead_repo.update_fields(lead_id, status="disqualified")
        await self.session.refresh(lead)
        return lead

    async def convert_lead(
        self,
        lead_id: uuid.UUID,
        payload: LeadConvertRequest,
        user_id: str | None = None,
    ) -> tuple[Lead, Opportunity]:
        """Convert a qualified lead into an opportunity."""
        lead = await self.get_lead(lead_id)
        if lead.status != "qualified":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only qualified leads can be converted",
            )
        # Validate stage exists
        stage = await self.stage_repo.get_by_id(payload.stage_id)
        if stage is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid stage_id for new opportunity",
            )
        if await self.account_repo.get_by_id(payload.account_id) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid account_id for new opportunity",
            )

        opp = Opportunity(
            account_id=payload.account_id,
            title=payload.title,
            description=payload.description,
            estimated_value=payload.estimated_value,
            currency=payload.currency,
            expected_close_date=payload.expected_close_date,
            probability_percent=payload.probability_percent,
            stage_id=payload.stage_id,
            weighted_value=compute_weighted_value(payload.estimated_value, payload.probability_percent),
            owner_user_id=lead.assigned_to,
            status="open",
        )
        await self.opportunity_repo.create(opp)

        now_iso = datetime.now(UTC).isoformat()
        await self.lead_repo.update_fields(
            lead_id,
            status="converted",
            converted_at=now_iso,
            converted_opportunity_id=opp.id,
        )
        await self.session.refresh(lead)

        # Initial stage history entry
        await self.history_repo.create(
            OpportunityStageHistory(
                opportunity_id=opp.id,
                from_stage_id=None,
                to_stage_id=opp.stage_id,
                changed_at=now_iso,
                changed_by=_to_uuid_or_none(user_id),
            )
        )

        event_bus.publish_detached(
            "crm.lead.converted",
            data={
                "lead_id": str(lead_id),
                "opportunity_id": str(opp.id),
                "account_id": str(payload.account_id),
                "converted_by": user_id,
            },
            source_module="crm",
        )
        logger.info(
            "CRM lead %s (%s) converted → opportunity %s",
            lead_id,
            _safe_lead_label(lead),
            opp.id,
        )
        return lead, opp

    # ── Opportunities ────────────────────────────────────────────────────

    async def create_opportunity(self, data: OpportunityCreate, user_id: str | None = None) -> Opportunity:
        stage = await self.stage_repo.get_by_id(data.stage_id)
        if stage is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid stage_id",
            )
        if await self.account_repo.get_by_id(data.account_id) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid account_id for new opportunity",
            )

        opp = Opportunity(
            account_id=data.account_id,
            title=data.title,
            description=data.description,
            estimated_value=data.estimated_value,
            currency=data.currency,
            expected_close_date=data.expected_close_date,
            probability_percent=data.probability_percent,
            stage_id=data.stage_id,
            weighted_value=compute_weighted_value(data.estimated_value, data.probability_percent),
            source=data.source,
            owner_user_id=data.owner_user_id,
            status=data.status,
            notes=data.notes,
            primary_contact_id=data.primary_contact_id,
            project_id=data.project_id,
            competitor_names=list(data.competitor_names or []),
        )
        await self.opportunity_repo.create(opp)

        await self.history_repo.create(
            OpportunityStageHistory(
                opportunity_id=opp.id,
                from_stage_id=None,
                to_stage_id=opp.stage_id,
                changed_at=datetime.now(UTC).isoformat(),
                changed_by=_to_uuid_or_none(user_id),
            )
        )
        logger.info("CRM opportunity created: %s", opp.id)
        return opp

    async def get_opportunity(self, opportunity_id: uuid.UUID) -> Opportunity:
        opp = await self.opportunity_repo.get_by_id(opportunity_id)
        if opp is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
        return opp

    async def update_opportunity(self, opportunity_id: uuid.UUID, data: OpportunityUpdate) -> Opportunity:
        opp = await self.get_opportunity(opportunity_id)
        fields = data.model_dump(exclude_unset=True)

        if "status" in fields and fields["status"] != opp.status:
            target_status = fields["status"]
            if target_status not in allowed_opportunity_transitions(opp.status):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(f"Invalid opportunity status transition: {opp.status} → {target_status}"),
                )
            # ``won``/``lost`` carry mandatory side-effects (won_at/lost_at
            # stamping, probability + weighted recompute, loss-reason
            # validation, and the crm.opportunity.won/lost events that drive
            # downstream Project creation and analytics). A generic PATCH
            # would silently skip all of them, leaving a "won" deal with
            # won_at=None — which corrupts sales-cycle, win-rate and forecast
            # math. Force callers through the dedicated endpoints.
            if target_status in ("won", "lost"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot set status '{target_status}' via update — use the dedicated win/lose endpoint instead"
                    ),
                )

        # Recompute weighted_value if value or probability changed
        if "estimated_value" in fields or "probability_percent" in fields:
            value = fields.get("estimated_value", opp.estimated_value)
            prob = fields.get("probability_percent", opp.probability_percent)
            fields["weighted_value"] = compute_weighted_value(value, prob)

        if fields:
            await self.opportunity_repo.update_fields(opportunity_id, **fields)
            await self.session.refresh(opp)
        return opp

    async def delete_opportunity(self, opportunity_id: uuid.UUID) -> None:
        await self.get_opportunity(opportunity_id)
        await self.opportunity_repo.delete(opportunity_id)

    async def transition_opportunity_stage(
        self,
        opportunity_id: uuid.UUID,
        to_stage_id: uuid.UUID,
        user_id: str | None = None,
        override_probability_percent: int | None = None,
    ) -> Opportunity:
        """Move an opportunity to another pipeline stage with history + event."""
        opp = await self.get_opportunity(opportunity_id)

        if opp.status != "open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot move stage on a non-open opportunity (status={opp.status})",
            )

        if opp.stage_id == to_stage_id:
            return opp

        new_stage = await self.stage_repo.get_by_id(to_stage_id)
        if new_stage is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid to_stage_id",
            )
        if new_stage.is_final and (new_stage.is_won or new_stage.is_lost):
            # Stages marked won/lost must go through win_opportunity / lose_opportunity
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Cannot move directly to a final won/lost stage — use the dedicated win/lose endpoint instead"),
            )

        # Update probability if user did not override and stage carries a default
        new_prob = (
            override_probability_percent
            if override_probability_percent is not None
            else new_stage.default_probability_percent
        )

        # Compute duration in previous stage
        from_stage_id = opp.stage_id
        prev_change_ts: int | None = None
        try:
            history = await self.history_repo.list_for_opportunity(opportunity_id)
            if history:
                last = history[-1]
                last_dt = last.created_at
                if isinstance(last_dt, datetime):
                    prev_change_ts = int(last_dt.timestamp())
        except Exception:  # noqa: BLE001
            prev_change_ts = None
        duration = int(datetime.now(UTC).timestamp()) - prev_change_ts if prev_change_ts is not None else None

        now_iso = datetime.now(UTC).isoformat()
        fields: dict[str, Any] = {
            "stage_id": to_stage_id,
            "probability_percent": new_prob,
            "weighted_value": compute_weighted_value(opp.estimated_value, new_prob),
        }
        await self.opportunity_repo.update_fields(opportunity_id, **fields)

        await self.history_repo.create(
            OpportunityStageHistory(
                opportunity_id=opportunity_id,
                from_stage_id=from_stage_id,
                to_stage_id=to_stage_id,
                changed_at=now_iso,
                changed_by=_to_uuid_or_none(user_id),
                duration_in_previous_seconds=duration,
            )
        )
        await self.session.refresh(opp)

        event_bus.publish_detached(
            "crm.opportunity.stage_changed",
            data={
                "opportunity_id": str(opportunity_id),
                "from_stage_id": str(from_stage_id),
                "to_stage_id": str(to_stage_id),
                "changed_by": user_id,
            },
            source_module="crm",
        )
        return opp

    async def win_opportunity(
        self,
        opportunity_id: uuid.UUID,
        user_id: str | None = None,
        won_at: str | None = None,
        win_reason_code: str | None = None,
    ) -> Opportunity:
        opp = await self.get_opportunity(opportunity_id)
        if "won" not in allowed_opportunity_transitions(opp.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot win an opportunity with status '{opp.status}'",
            )
        # Validate win_reason_code against the catalogue. ``lost`` already
        # checks lost_reason_code; ``won`` was previously a silent no-op
        # accepting any free-text string, including codes from the lost-only
        # side of the catalogue — that broke win-rate dashboards segmented
        # by reason. Round-5 audit closes the gap.
        if win_reason_code is not None:
            reason = await self.reason_repo.get_by_code(win_reason_code)
            if reason is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown win_reason_code '{win_reason_code}'",
                )
            if not reason.is_win_reason:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(f"Reason '{win_reason_code}' is not flagged as a win reason in the catalogue"),
                )
        won_at_iso = won_at or datetime.now(UTC).date().isoformat()
        fields: dict[str, Any] = {
            "status": "won",
            "won_at": won_at_iso,
            "probability_percent": 100,
            "weighted_value": _q2(_opp_value(opp)),
        }
        await self.opportunity_repo.update_fields(opportunity_id, **fields)
        await self.session.refresh(opp)

        payload = convert_opportunity_to_project_payload(opp)
        event_bus.publish_detached(
            "crm.opportunity.won",
            data={
                "opportunity_id": str(opportunity_id),
                "account_id": str(opp.account_id),
                "won_at": won_at_iso,
                "win_reason_code": win_reason_code,
                "project_payload": payload,
                "won_by": user_id,
            },
            source_module="crm",
        )
        logger.info("CRM opportunity won: %s", opportunity_id)
        return opp

    async def lose_opportunity(
        self,
        opportunity_id: uuid.UUID,
        lost_reason_code: str,
        user_id: str | None = None,
        lost_at: str | None = None,
    ) -> Opportunity:
        opp = await self.get_opportunity(opportunity_id)
        if "lost" not in allowed_opportunity_transitions(opp.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot lose an opportunity with status '{opp.status}'",
            )
        # Validate reason exists in catalog (skip if not configured yet)
        reason = await self.reason_repo.get_by_code(lost_reason_code)
        if reason is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown lost_reason_code '{lost_reason_code}'",
            )
        if not reason.is_loss_reason:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Reason '{lost_reason_code}' is not a loss reason",
            )

        lost_at_iso = lost_at or datetime.now(UTC).date().isoformat()
        await self.opportunity_repo.update_fields(
            opportunity_id,
            status="lost",
            lost_at=lost_at_iso,
            lost_reason_code=lost_reason_code,
            probability_percent=0,
            weighted_value=Decimal("0"),
        )
        await self.session.refresh(opp)
        event_bus.publish_detached(
            "crm.opportunity.lost",
            data={
                "opportunity_id": str(opportunity_id),
                "account_id": str(opp.account_id),
                "lost_at": lost_at_iso,
                "lost_reason_code": lost_reason_code,
                "lost_by": user_id,
            },
            source_module="crm",
        )
        logger.info("CRM opportunity lost: %s (%s)", opportunity_id, lost_reason_code)
        return opp

    # ── Pipeline stages (catalog) ────────────────────────────────────────

    async def create_stage(self, data: PipelineStageCreate) -> Any:
        from app.modules.crm.models import PipelineStage

        stage = PipelineStage(**data.model_dump())
        await self.stage_repo.create(stage)
        return stage

    async def update_stage(self, stage_id: uuid.UUID, data: PipelineStageUpdate) -> Any:
        stage = await self.stage_repo.get_by_id(stage_id)
        if stage is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline stage not found")
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.stage_repo.update_fields(stage_id, **fields)
            await self.session.refresh(stage)
        return stage

    async def delete_stage(self, stage_id: uuid.UUID) -> None:
        stage = await self.stage_repo.get_by_id(stage_id)
        if stage is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline stage not found")
        await self.stage_repo.delete(stage_id)

    # ── Win/loss reasons (catalog) ───────────────────────────────────────

    async def create_reason(self, data: WinLossReasonCreate) -> Any:
        from app.modules.crm.models import WinLossReason

        reason = WinLossReason(**data.model_dump())
        await self.reason_repo.create(reason)
        return reason

    async def update_reason(self, reason_id: uuid.UUID, data: WinLossReasonUpdate) -> Any:
        reason = await self.reason_repo.get_by_id(reason_id)
        if reason is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reason not found")
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.reason_repo.update_fields(reason_id, **fields)
            await self.session.refresh(reason)
        return reason

    async def delete_reason(self, reason_id: uuid.UUID) -> None:
        reason = await self.reason_repo.get_by_id(reason_id)
        if reason is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reason not found")
        await self.reason_repo.delete(reason_id)

    # ── Activities ───────────────────────────────────────────────────────

    async def create_activity(
        self,
        data: ActivityCreate,
        user_id: str | None = None,
    ) -> CrmActivity:
        # Activity-owner spoofing: before v4.3.0 the request body's
        # ``owner_user_id`` was trusted blindly — a regular EDITOR could
        # POST {"owner_user_id": "<sales-director-uuid>", ...} and falsely
        # attribute a touch to anyone in the org, corrupting per-rep
        # activity dashboards and commission reports. Round-5 audit:
        # always pin owner_user_id to the calling user.
        current_uuid = _to_uuid_or_none(user_id)
        if data.owner_user_id is not None and current_uuid is not None and data.owner_user_id != current_uuid:
            logger.warning(
                "CRM: discarding owner_user_id spoof attempt by user=%s (claimed=%s)",
                user_id,
                data.owner_user_id,
            )
        activity = CrmActivity(
            owner_user_id=current_uuid,
            account_id=data.account_id,
            opportunity_id=data.opportunity_id,
            lead_id=data.lead_id,
            kind=data.kind,
            subject=data.subject,
            body=data.body,
            due_at=data.due_at,
            completed_at=data.completed_at,
            outcome=data.outcome,
            external_calendar_event_id=data.external_calendar_event_id,
        )
        await self.activity_repo.create(activity)
        return activity

    async def get_activity(self, activity_id: uuid.UUID) -> CrmActivity:
        activity = await self.activity_repo.get_by_id(activity_id)
        if activity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
        return activity

    async def update_activity(self, activity_id: uuid.UUID, data: ActivityUpdate) -> CrmActivity:
        activity = await self.get_activity(activity_id)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.activity_repo.update_fields(activity_id, **fields)
            await self.session.refresh(activity)
        return activity

    async def delete_activity(self, activity_id: uuid.UUID) -> None:
        await self.get_activity(activity_id)
        await self.activity_repo.delete(activity_id)

    # ── Forecast ─────────────────────────────────────────────────────────

    async def compute_and_store_forecast(
        self,
        period: str,
        owner_user_id: uuid.UUID | None = None,
    ) -> Forecast:
        opps = await self.opportunity_repo.list_all(limit=100000)
        # Apply owner filter if requested
        all_opps = opps[0]
        if owner_user_id is not None:
            all_opps = [o for o in all_opps if o.owner_user_id == owner_user_id]
        computed = compute_forecast(all_opps, period)
        forecast = Forecast(
            period=period,
            owner_user_id=owner_user_id,
            pipeline_value=computed["pipeline_value"],
            weighted_value=computed["weighted_value"],
            won_value=computed["won_value"],
            committed_value=computed["committed_value"],
            computed_at=computed["computed_at"],
        )
        return await self.forecast_repo.upsert(forecast)

    async def get_forecast(self, period: str, owner_user_id: uuid.UUID | None = None) -> Forecast:
        existing = await self.forecast_repo.get_by_period(period, owner_user_id)
        if existing is not None:
            return existing
        return await self.compute_and_store_forecast(period, owner_user_id)

    # ── Hierarchy ────────────────────────────────────────────────────────

    async def account_tree(
        self,
        root_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return the full account-tree, or the sub-tree rooted at ``root_id``."""
        accounts, _ = await self.account_repo.list_all(limit=10000)
        return build_account_tree(accounts, root_id=root_id)

    async def set_account_parent(
        self,
        account_id: uuid.UUID,
        parent_account_id: uuid.UUID | None,
    ) -> Account:
        """Set the parent of an account. Detects simple cycles."""
        account = await self.get_account(account_id)
        if parent_account_id is not None:
            if parent_account_id == account_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Account cannot be its own parent",
                )
            await self.get_account(parent_account_id)  # 404 if missing
            # Cycle check: walk up from parent looking for account_id
            current = parent_account_id
            depth = 0
            while current is not None and depth < 100:
                row = await self.account_repo.get_by_id(current)
                if row is None:
                    break
                if row.id == account_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Setting this parent would create a cycle",
                    )
                current = row.parent_account_id
                depth += 1
        await self.account_repo.update_fields(
            account_id,
            parent_account_id=parent_account_id,
        )
        await self.session.refresh(account)
        return account

    # ── BANT scoring ────────────────────────────────────────────────────

    async def score_opportunity(
        self,
        opportunity_id: uuid.UUID,
        *,
        budget: int,
        authority: int,
        need: int,
        timeline: int,
        weights: dict[str, int] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Compute a BANT score for an opportunity and persist into notes JSON.

        The score is stored in ``Opportunity.competitor_names`` extras? No —
        we have no JSON field on Opportunity. We persist into the dedicated
        ``probability_percent`` (which the user can override) and into
        an audit trail via a CrmActivity of kind 'score'.
        """
        opp = await self.get_opportunity(opportunity_id)
        score = compute_opportunity_score(
            budget_score=budget,
            authority_score=authority,
            need_score=need,
            timeline_score=timeline,
            weights=weights,
        )

        # Persist the score: bump probability_percent to the BANT total (capped
        # at 100) and log a system Activity with the full breakdown.
        new_prob = int(min(100, max(0, round(score["total"]))))
        new_weighted = compute_weighted_value(opp.estimated_value, new_prob)
        await self.opportunity_repo.update_fields(
            opportunity_id,
            probability_percent=new_prob,
            weighted_value=new_weighted,
        )
        score_activity = CrmActivity(
            owner_user_id=_to_uuid_or_none(user_id),
            account_id=opp.account_id,
            opportunity_id=opportunity_id,
            kind="score",
            subject=f"BANT score: {score['total']} ({score['band']})",
            body=(
                f"Budget={score['budget']} / Authority={score['authority']} / "
                f"Need={score['need']} / Timeline={score['timeline']} → "
                f"weighted total {score['total']}/100 ({score['band']})."
            ),
        )
        await self.activity_repo.create(score_activity)
        event_bus.publish_detached(
            "crm.opportunity.scored",
            data={
                "opportunity_id": str(opportunity_id),
                "score": score,
                "scored_by": user_id,
            },
            source_module="crm",
        )
        await self.session.refresh(opp)
        return {**score, "opportunity_id": str(opportunity_id)}

    # ── Activity timeline (unified) ─────────────────────────────────────

    async def activity_timeline(
        self,
        *,
        account_id: uuid.UUID | None = None,
        opportunity_id: uuid.UUID | None = None,
        lead_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return a unified, chronological timeline of activities + state events.

        When opportunity_id is given, it also includes stage-history rows
        (immutable record of every stage change) sorted into the same feed.
        """
        rows: list[dict[str, Any]] = []
        # Pull regular activities matching any of the filters via list_all.
        activities, _ = await self.activity_repo.list_all(
            limit=limit,
            account_id=account_id,
            opportunity_id=opportunity_id,
            lead_id=lead_id,
        )

        for act in activities:
            ts = getattr(act, "completed_at", None) or getattr(act, "due_at", None) or getattr(act, "created_at", None)
            rows.append(
                {
                    "kind": getattr(act, "kind", "note"),
                    "entry_type": "activity",
                    "timestamp": str(ts) if ts is not None else None,
                    "subject": getattr(act, "subject", ""),
                    "body": getattr(act, "body", ""),
                    "outcome": getattr(act, "outcome", None),
                    "source_id": str(getattr(act, "id", "")),
                }
            )

        if opportunity_id is not None:
            try:
                history = await self.history_repo.list_for_opportunity(opportunity_id)
            except Exception:  # noqa: BLE001
                history = []
            for h in history:
                rows.append(
                    {
                        "kind": "stage_change",
                        "entry_type": "stage_history",
                        "timestamp": (getattr(h, "changed_at", None) or str(getattr(h, "created_at", "") or "")),
                        "subject": "Stage changed",
                        "body": (
                            f"{getattr(h, 'from_stage_id', None)} → "
                            f"{getattr(h, 'to_stage_id', None)} "
                            f"(duration={getattr(h, 'duration_in_previous_seconds', None)}s)"
                        ),
                        "source_id": str(getattr(h, "id", "")),
                    }
                )

        # Sort newest-first by timestamp string (ISO-friendly).
        rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        return rows[:limit]

    # ── Stage-weighted forecast ─────────────────────────────────────────

    async def stage_weighted_forecast(
        self,
        owner_user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        opps_rows, _ = await self.opportunity_repo.list_all(limit=10000)
        if owner_user_id is not None:
            opps_rows = [o for o in opps_rows if o.owner_user_id == owner_user_id]
        stages_rows = await self.stage_repo.list_all()
        stages_by_id = {s.id: s for s in stages_rows}
        return compute_stage_weighted_forecast(opps_rows, stages_by_id)


def _to_uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# ── BANT scoring (pure) ───────────────────────────────────────────────────

# Default BANT-weights — sum must equal 100. Callers can override per tenant.
_DEFAULT_BANT_WEIGHTS = {
    "budget": 30,
    "authority": 25,
    "need": 25,
    "timeline": 20,
}


def compute_opportunity_score(
    *,
    budget_score: int,
    authority_score: int,
    need_score: int,
    timeline_score: int,
    weights: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Pure: compute a BANT score for an opportunity.

    Each input is 0-100. Returns a dict with the four normalised scores,
    the weighted total (0-100), and a coarse band:
        90+  → "hot"
        70+  → "warm"
        50+  → "lukewarm"
        else → "cold"
    """
    w = dict(_DEFAULT_BANT_WEIGHTS)
    if weights:
        # Trust caller weights but clamp to [0, 100] each, normalise sum to 100.
        clean = {k: max(0, min(100, int(v))) for k, v in weights.items() if k in w}
        total_w = sum(clean.values())
        if total_w > 0:
            for k in w:
                w[k] = int(round(clean.get(k, 0) * 100 / total_w))

    def _clamp(v: Any) -> int:
        try:
            x = int(v)
        except (TypeError, ValueError):
            return 0
        return max(0, min(100, x))

    b = _clamp(budget_score)
    a = _clamp(authority_score)
    n = _clamp(need_score)
    t = _clamp(timeline_score)
    total = (b * w["budget"] + a * w["authority"] + n * w["need"] + t * w["timeline"]) / 100.0
    total = round(total, 2)
    if total >= 90:
        band = "hot"
    elif total >= 70:
        band = "warm"
    elif total >= 50:
        band = "lukewarm"
    else:
        band = "cold"
    return {
        "budget": b,
        "authority": a,
        "need": n,
        "timeline": t,
        "weights": w,
        "total": total,
        "band": band,
    }


# ── Account hierarchy (pure tree building) ────────────────────────────────


def build_account_tree(
    accounts: Iterable[Any],
    root_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Pure: build a nested account hierarchy.

    Each account must expose ``id``, ``parent_account_id``, ``name``,
    ``role``. Returns a list of dicts ``{id, name, role, children: [...]}``.
    When ``root_id`` is None, returns every account that has no parent (or
    whose parent is missing from the input list).
    """
    rows = list(accounts)
    by_parent: dict[str | None, list[Any]] = {}
    for a in rows:
        parent = getattr(a, "parent_account_id", None)
        key = str(parent) if parent is not None else None
        by_parent.setdefault(key, []).append(a)

    seen_ids = {str(getattr(a, "id", "")) for a in rows}

    def _serialise(a: Any) -> dict[str, Any]:
        node_children = by_parent.get(str(a.id), [])
        return {
            "id": str(a.id),
            "name": getattr(a, "name", ""),
            "role": getattr(a, "role", "general_contractor"),
            "status": getattr(a, "status", "active"),
            "industry": getattr(a, "industry", None),
            "country": getattr(a, "country", None),
            "children": [_serialise(c) for c in node_children],
        }

    if root_id is not None:
        roots = [a for a in rows if getattr(a, "id", None) == root_id]
    else:
        roots = []
        for a in rows:
            parent = getattr(a, "parent_account_id", None)
            if parent is None or str(parent) not in seen_ids:
                roots.append(a)
    return [_serialise(r) for r in roots]


# ── Stage-weighted forecast breakdown ─────────────────────────────────────


def compute_stage_weighted_forecast(
    opportunities: Iterable[Any],
    stages_by_id: dict[uuid.UUID, Any] | None = None,
) -> dict[str, Any]:
    """Pure: aggregate weighted pipeline by pipeline stage.

    Returns ``{by_stage: {stage_id: {name, probability, count, total,
    weighted}}, grand_total, grand_weighted}`` — useful for the kanban
    forecast view.
    """
    by_stage: dict[str, dict[str, Any]] = {}
    grand_total = Decimal(0)
    grand_weighted = Decimal(0)
    stages_by_id = stages_by_id or {}
    for o in opportunities:
        if getattr(o, "status", None) != "open":
            continue
        sid = getattr(o, "stage_id", None)
        if sid is None:
            continue
        sid_str = str(sid)
        stage_meta = stages_by_id.get(sid) if isinstance(sid, uuid.UUID) else None
        stage_name = getattr(stage_meta, "name", "") or getattr(stage_meta, "code", "") or sid_str
        prob = getattr(o, "probability_percent", 0) or 0
        if stage_meta is not None and getattr(stage_meta, "default_probability_percent", None) is not None:
            # Prefer per-opp prob but record stage default as reference
            stage_default = stage_meta.default_probability_percent
        else:
            stage_default = prob
        value = _opp_value(o)
        weighted = _opp_weighted(o)
        bucket = by_stage.setdefault(
            sid_str,
            {
                "stage_id": sid_str,
                "stage_name": stage_name,
                "stage_default_probability": int(stage_default),
                "count": 0,
                "total": Decimal(0),
                "weighted": Decimal(0),
            },
        )
        bucket["count"] += 1
        bucket["total"] += value
        bucket["weighted"] += weighted
        grand_total += value
        grand_weighted += weighted
    return {
        "by_stage": {k: {**v, "total": _q2(v["total"]), "weighted": _q2(v["weighted"])} for k, v in by_stage.items()},
        "grand_total": _q2(grand_total),
        "grand_weighted": _q2(grand_weighted),
    }
