"""‌⁠‍Change Order service - business logic for change order management.

Stateless service layer. Handles:
- Change order CRUD with auto-generated codes
- Item management with cost_delta calculation
- Status transitions (draft -> submitted -> approved/rejected)
- Cost impact recalculation from items
"""

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.changeorders.models import (
    ChangeOrder,
    ChangeOrderApproval,
    ChangeOrderItem,
)
from app.modules.changeorders.repository import ChangeOrderRepository
from app.modules.changeorders.schemas import (
    ChangeOrderCreate,
    ChangeOrderItemCreate,
    ChangeOrderItemUpdate,
    ChangeOrderUpdate,
)

logger = logging.getLogger(__name__)

_CENTS = Decimal("0.01")


def _dec(value: object) -> Decimal:
    """Coerce an API number (float/int/str) to an exact ``Decimal``.

    Always routes through ``str()`` so a binary float such as ``0.1`` does
    not poison money math with ``0.1000000000000000055…``. Bad input
    degrades to ``Decimal("0")`` rather than raising - the schema layer
    already validates ranges/NaN.
    """
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _round2(value: Decimal) -> Decimal:
    """Round a money ``Decimal`` to 2 dp (HALF_UP) at the persist boundary."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    """‌⁠‍Fire-and-forget event publish. Swallows errors so a transient event
    bus outage never breaks the main transaction."""
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        logger.debug("Event publish skipped: %s", name)


async def _safe_audit(
    session: AsyncSession,
    *,
    actor_id: str | uuid.UUID | None,
    order_id: uuid.UUID,
    from_status: str,
    to_status: str,
    reason: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Write an ActivityLog row for a CO status transition.

    Wrapped in try/except so an audit-log failure (e.g. a partially
    migrated DB without ``oe_activity_log``) never rolls back the
    business transition. The audit row sits in the same SQLAlchemy
    session as the status write, so commit semantics are atomic: both
    or neither land.
    """
    try:
        from app.core.audit_log import log_activity

        await log_activity(
            session,
            actor_id=actor_id,
            entity_type="change_order",
            entity_id=str(order_id),
            action="status_changed",
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            metadata=dict(metadata or {}),
        )
    except Exception:
        logger.warning(
            "ActivityLog write skipped for change_order %s (%s → %s)",
            order_id,
            from_status,
            to_status,
            exc_info=True,
        )


# Valid status transitions.
# ``executed`` is a terminal state added in R7 hardening: after an approved CO
# is actually executed on site, it moves to ``executed`` so dashboards can
# distinguish "approved in principle" from "work done / cost committed."
VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["submitted"],
    "submitted": ["approved", "rejected", "draft"],
    "approved": ["executed"],
    "rejected": ["draft"],
    "executed": [],
}


# ── What-If impact simulator (TOP-30 #11) ────────────────────────────────────


def _index(value: Decimal) -> str:
    """Format an EVM performance index to 4 dp, trailing zeros trimmed."""
    q = value.quantize(Decimal("0.0001")).normalize()
    # ``normalize()`` can yield scientific notation for whole numbers
    # (e.g. Decimal('1E+0')); render plainly so the wire value is "1".
    return format(q, "f")


def _parse_iso_date(raw: str | None) -> datetime | None:
    """Best-effort parse of an ISO date / datetime string. Never raises."""
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # Accept a trailing Z and date-only forms.
    candidate = text.replace("Z", "+00:00")
    for attempt in (candidate, candidate[:10]):
        try:
            return datetime.fromisoformat(attempt)
        except (ValueError, TypeError):
            continue
    return None


def _compute_impact_projection(
    *,
    bac: Decimal,
    ev: Decimal,
    ac: Decimal,
    pv: Decimal,
    co_cost_base: Decimal,
    schedule_days: int,
    planned_end: str | None,
    item_count: int,
    target_boq_name: str | None,
) -> dict:
    """Deterministically project the cost / schedule / EVM / BOQ effect of a CO.

    Pure function (no DB, no I/O) so it is unit-testable in isolation. Every
    money figure is in the project base currency; the caller FX-converts the
    CO's native cost before passing ``co_cost_base``. The EVM formulas mirror
    ``finance.create_evm_snapshot`` exactly so a simulated forecast lines up
    with the snapshot the project would actually record once the CO lands.
    """
    zero = Decimal("0")
    spi = (ev / pv) if pv != 0 else zero
    cpi = (ev / ac) if ac != 0 else zero

    def _eac(bac_v: Decimal) -> Decimal:
        # CPI-based forecast; falls back to AC + remaining BAC when CPI == 0.
        if cpi != 0:
            return ac + (bac_v - ev) / cpi
        return ac + (bac_v - ev)

    bac_after = bac + co_cost_base
    eac_before = _eac(bac).quantize(_CENTS)
    eac_after = _eac(bac_after).quantize(_CENTS)
    vac_before = (bac - eac_before).quantize(_CENTS)
    vac_after = (bac_after - eac_after).quantize(_CENTS)

    pct = float((co_cost_base / bac * 100).quantize(_CENTS)) if bac > 0 else 0.0

    current_end: str | None = None
    projected_end: str | None = None
    parsed_end = _parse_iso_date(planned_end)
    if parsed_end is not None:
        current_end = parsed_end.date().isoformat()
        projected_end = (parsed_end + timedelta(days=schedule_days)).date().isoformat()

    return {
        "cost": {
            "budget_before": str(_round2(bac)),
            "budget_after": str(_round2(bac_after)),
            "delta": str(_round2(co_cost_base)),
            "pct_of_budget": pct,
        },
        "schedule": {
            "current_end_date": current_end,
            "projected_end_date": projected_end,
            "days_added": schedule_days,
            "finish_moves": schedule_days > 0,
        },
        "evm": {
            "bac_before": str(_round2(bac)),
            "bac_after": str(_round2(bac_after)),
            "eac_before": str(eac_before),
            "eac_after": str(eac_after),
            "vac_before": str(vac_before),
            "vac_after": str(vac_after),
            "spi": _index(spi),
            "cpi": _index(cpi),
        },
        "boq": {
            "item_count": item_count,
            "sections_added": 1 if item_count > 0 else 0,
            "positions_added": item_count,
            "target_boq_name": target_boq_name,
        },
    }


# ── AI / heuristic change-order draft (TOP-30 #11) ───────────────────────────

# Currency tokens we recognise next to a number when guessing a cost offline.
_CCY_HINT = r"(?:[$€£]|USD|EUR|GBP|CAD|AUD|CHF|SEK|NOK|DKK|PLN|BRL|INR|AED|SAR|TRY)"
# A money-looking number, optional thousands separators, optional k/m suffix.
_NUM = r"\d[\d.,\s]*"
_MONEY_RE = re.compile(
    rf"(?:{_CCY_HINT}\s*({_NUM})\s*([kKmM])?)"  # $15,000 / USD 15k
    rf"|(?:({_NUM})\s*([kKmM])\b)"  # 15k
    rf"|(?:({_NUM})\s*([kKmM])?\s*{_CCY_HINT})",  # 15,000 CAD / 15k EUR
    re.IGNORECASE,
)
_DAYS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[-\s]?\s*(?:calendar|working|business|extra)?\s*days?\b",
    re.IGNORECASE,
)
_DRAFT_SYSTEM = (
    "You are a senior quantity surveyor drafting a construction change order "
    "(variation) from raw site notes. Reply ONLY with a JSON object. Be "
    "conservative: never invent figures the text does not support."
)


def _parse_amount_token(token: str, suffix: str | None) -> Decimal:
    """Turn a matched numeric token (+ optional k/m) into a Decimal.

    Handles the common ``15,000`` / ``15.000`` / ``15 000`` / ``15k`` forms.
    Thousands separators are stripped; a trailing 1-2 digit group after the
    final separator is treated as a decimal fraction. Degrades to 0 on garbage.
    """
    raw = (token or "").strip()
    if not raw:
        return Decimal("0")
    raw = raw.replace(" ", "")
    # Decide whether the last '.'/',' is a decimal point (<=2 trailing digits
    # and only one such separator) or a thousands separator.
    last_sep = max(raw.rfind(","), raw.rfind("."))
    decimal_part = ""
    if last_sep != -1:
        tail = raw[last_sep + 1 :]
        if 1 <= len(tail) <= 2 and tail.isdigit() and raw.count(raw[last_sep]) == 1:
            decimal_part = "." + tail
            raw = raw[:last_sep]
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return Decimal("0")
    try:
        value = Decimal(digits + decimal_part)
    except InvalidOperation:
        return Decimal("0")
    mult = {"k": Decimal("1000"), "m": Decimal("1000000")}.get((suffix or "").lower())
    if mult is not None:
        value *= mult
    return value


def _heuristic_money(text: str) -> Decimal:
    """Largest money-looking amount in the text, or 0 if none is found."""
    best = Decimal("0")
    for m in _MONEY_RE.finditer(text or ""):
        token = m.group(1) or m.group(3) or m.group(5)
        suffix = m.group(2) or m.group(4) or m.group(6)
        value = _parse_amount_token(token, suffix)
        if value > best:
            best = value
    return best


def _heuristic_days(text: str) -> int:
    """First plausible day-count in the text (0-3650), else 0."""
    for m in _DAYS_RE.finditer(text or ""):
        try:
            days = int(round(float(m.group(1))))
        except (ValueError, TypeError):
            continue
        if 0 <= days <= 3650:
            return days
    return 0


def _draft_title(text: str) -> str:
    """Derive a short title from the first meaningful line / sentence."""
    cleaned = (text or "").strip()
    if not cleaned:
        return "Change order"
    first_line = cleaned.splitlines()[0].strip()
    snippet = re.split(r"(?<=[.!?])\s", first_line)[0].strip() or first_line
    return snippet[:120] or "Change order"


def _heuristic_draft(
    text: str,
    currency: str,
    source_kind: str,
    source_id: uuid.UUID | None,
) -> dict:
    """Deterministic offline draft when no AI provider key is configured.

    Reads the obvious cost / schedule signals out of the source text so the
    feature still produces a usable, clearly-labelled draft with low confidence
    rather than failing when the platform has no LLM key.
    """
    amount = _heuristic_money(text)
    days = _heuristic_days(text)
    title = _draft_title(text)
    has_signal = amount > 0 or days > 0
    confidence = 45 if has_signal else 20
    lines: list[dict] = []
    if amount > 0:
        lines.append(
            {
                "description": title,
                "unit": "lsum",
                "quantity": "1",
                "rate": str(_round2(amount)),
                "cost_delta": str(_round2(amount)),
                "confidence": confidence,
            }
        )
    return {
        "title": title,
        "description": (text or "").strip()[:5000],
        "reason_category": "unforeseen" if source_kind == "daily_log" else "client_request",
        "cost_impact": str(_round2(amount)),
        "schedule_impact_days": days,
        "currency": currency,
        "lines": lines,
        "confidence": confidence,
        "ai_used": False,
        "provider": "heuristic",
        "source_kind": source_kind,
        "source_id": source_id,
        "note": (
            "Offline draft - no AI provider key is configured, so cost and "
            "schedule were read from the obvious figures in the text. Please "
            "verify every value before creating the change order."
        ),
    }


def _draft_prompt(source_kind: str, source_text: str, currency: str) -> str:
    """Build the user prompt for the AI change-order drafter."""
    ccy = currency or "the project currency"
    label = {
        "rfi": "an RFI (request for information) thread",
        "daily_log": "a daily site-diary entry",
        "free_text": "site notes",
    }.get(source_kind, "site notes")
    return (
        f"Draft a construction change order from {label}. Express money in "
        f"{ccy}. Return ONLY a JSON object with keys: title (short string), "
        "description (string), reason_category (one of client_request, "
        "design_change, unforeseen, regulatory, error), cost_impact (decimal "
        "string, signed), schedule_impact_days (integer), confidence (0-100), "
        "lines (array of objects with description, unit, quantity, rate, "
        "cost_delta, confidence 0-100). Do not invent figures the text does "
        f"not support.\n\nSOURCE:\n{source_text[:8000]}"
    )


def _normalise_ai_draft(
    data: dict,
    currency: str,
    source_kind: str,
    source_id: uuid.UUID | None,
    provider: str,
) -> dict:
    """Coerce a model's JSON into the AIDraftResponse shape, defensively."""
    reason = str(data.get("reason_category") or "client_request")
    if reason not in {"client_request", "design_change", "unforeseen", "regulatory", "error"}:
        reason = "client_request"

    def _conf(v: object, default: int = 70) -> int:
        try:
            return max(0, min(100, int(round(float(v)))))
        except (ValueError, TypeError):
            return default

    raw_lines = data.get("lines") if isinstance(data.get("lines"), list) else []
    lines: list[dict] = []
    for entry in raw_lines[:50]:
        if not isinstance(entry, dict):
            continue
        lines.append(
            {
                "description": str(entry.get("description") or "")[:5000],
                "unit": str(entry.get("unit") or "")[:20],
                "quantity": str(entry.get("quantity") or "0")[:50],
                "rate": str(entry.get("rate") or "0")[:50],
                "cost_delta": str(entry.get("cost_delta") or "0")[:50],
                "confidence": _conf(entry.get("confidence"), 70),
            }
        )
    try:
        days = int(round(float(data.get("schedule_impact_days") or 0)))
    except (ValueError, TypeError):
        days = 0
    return {
        "title": str(data.get("title") or "Change order")[:255],
        "description": str(data.get("description") or "")[:5000],
        "reason_category": reason,
        "cost_impact": str(data.get("cost_impact") or "0")[:50],
        "schedule_impact_days": max(0, days),
        "currency": currency,
        "lines": lines,
        "confidence": _conf(data.get("confidence"), 70),
        "ai_used": True,
        "provider": provider,
        "source_kind": source_kind,
        "source_id": source_id,
        "note": (
            "AI-generated draft. Treat every figure as a suggestion and verify "
            "with a quantity surveyor before creating the change order."
        ),
    }


class ChangeOrderService:
    """‌⁠‍Business logic for change order operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ChangeOrderRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_order(self, data: ChangeOrderCreate) -> ChangeOrder:
        """Create a new change order with auto-generated code.

        BUG-354 race condition: ``count + 1`` is not atomic - two concurrent
        creates could both read ``count=4`` and both emit ``CO-005``. We
        retry on integrity-error (unique-constraint violation) by re-reading
        the current max ordinal from the DB and bumping from there. After
        ``_MAX_RETRIES`` collisions we surface the error rather than looping
        forever.
        """
        from sqlalchemy.exc import IntegrityError

        _MAX_RETRIES = 5

        # BUG-385 follow-up: ``cost_impact`` was silently dropped at create
        # time because it wasn't threaded into the ORM constructor here.
        # The schema now accepts it (added alongside Phase 1); this picks
        # it up so manual-entry COs persist their headline amount. When
        # line items are added later ``add_item`` recomputes the total via
        # ``_recalculate_cost_impact``, so a line-based CO still ends up
        # with the correct sum.
        from decimal import Decimal, InvalidOperation

        try:
            initial_cost_impact = Decimal(str(data.cost_impact)) if data.cost_impact else Decimal("0")
        except (InvalidOperation, ValueError, TypeError):
            initial_cost_impact = Decimal("0")

        # Resolve currency: caller-supplied → project default → "" (honest
        # unknown). Task #217 / the architecture guide forbid a literal "EUR" here - a
        # change order on a BRL/USD/etc. project must inherit that project's
        # currency, never silently become Euro. Resolved once, before the
        # retry loop, so a code-collision retry doesn't re-query the project.
        currency = await self._resolve_currency(data.project_id, data.currency)

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            count = await self.repo.count_for_project(data.project_id)
            code = f"CO-{count + 1 + attempt:03d}"

            order = ChangeOrder(
                project_id=data.project_id,
                code=code,
                title=data.title,
                description=data.description,
                reason_category=data.reason_category,
                schedule_impact_days=data.schedule_impact_days,
                currency=currency,
                cost_impact=initial_cost_impact,
                metadata_=data.metadata,
            )
            try:
                order = await self.repo.create(order)
                logger.info(
                    "Change order created: %s for project %s (attempt %d)",
                    code,
                    data.project_id,
                    attempt + 1,
                )
                return order
            except IntegrityError as exc:
                # Another transaction picked the same code. Roll back and
                # retry with a bumped ordinal.
                last_exc = exc
                await self.session.rollback()
                continue

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Could not generate a unique change-order code after "
                f"{_MAX_RETRIES} attempts (concurrent contention). Please retry."
            ),
        ) from last_exc

    async def _resolve_currency(
        self,
        project_id: uuid.UUID,
        requested: str | None,
    ) -> str:
        """Resolve the currency to stamp on a new change order.

        Precedence: explicit caller value → owning project's currency →
        empty string. NEVER returns a literal "EUR": a change order must
        inherit the project's currency so a non-Eurozone project's scope
        changes are not silently mis-stamped as Euro (task #217).
        """
        explicit = (requested or "").strip()
        if explicit:
            return explicit

        from sqlalchemy import select

        from app.modules.projects.models import Project

        try:
            project = (await self.session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        except Exception:
            # No real session (unit-test stub) or transient lookup error -
            # fall back to empty rather than guessing a currency.
            logger.debug("Project currency lookup skipped for %s", project_id)
            return ""
        if project is not None and getattr(project, "currency", None):
            return str(project.currency)
        return ""

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_order(self, order_id: uuid.UUID) -> ChangeOrder:
        """Get change order by ID. Raises 404 if not found."""
        order = await self.repo.get_by_id(order_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Change order not found",
            )
        return order

    async def list_orders(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[ChangeOrder], int]:
        """List change orders for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
        )

    async def list_orders_for_owner(
        self,
        owner_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[ChangeOrder], int]:
        """List change orders across every project owned by the user."""
        return await self.repo.list_for_owner(
            owner_id,
            offset=offset,
            limit=limit,
            status=status_filter,
        )

    async def get_summary(self, project_id: uuid.UUID) -> dict:
        """Get aggregated stats for a project's change orders."""
        return await self.repo.get_summary(project_id)

    # ── What-If impact simulator (TOP-30 #11) ─────────────────────────────

    async def _count_items(self, order_id: uuid.UUID) -> int:
        """Number of line items on a change order (0 on lookup failure)."""
        from sqlalchemy import func, select

        try:
            return int(
                (
                    await self.session.execute(
                        select(func.count())
                        .select_from(ChangeOrderItem)
                        .where(ChangeOrderItem.change_order_id == order_id)
                    )
                ).scalar_one()
            )
        except Exception:
            return 0

    async def _first_unlocked_boq_name(self, project_id: uuid.UUID) -> str | None:
        """Name of the BOQ a CO would write into (oldest unlocked), or None."""
        from sqlalchemy import select

        try:
            from app.modules.boq.models import BOQ

            boq = (
                await self.session.execute(
                    select(BOQ)
                    .where(BOQ.project_id == project_id)
                    .where(BOQ.is_locked.is_(False))
                    .order_by(BOQ.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            return boq.name if boq is not None else None
        except Exception:
            return None

    async def simulate_impact(
        self,
        order_id: uuid.UUID,
        *,
        cost_override: str | None = None,
        schedule_override: int | None = None,
    ) -> dict:
        """Read-only what-if projection of a change order's cost/schedule effect.

        Nothing is persisted. The baseline budget/EVM figures come from the
        same finance aggregation that powers the dashboard, converted into the
        project's base currency (never blending currencies); the CO's own cost
        is FX-converted the same way before being layered on top. The result
        lets a reviewer see the budget, finish-date, EVM and BOQ consequences
        of approving the CO *before* deciding.
        """
        from app.modules.finance.repository import BudgetRepository
        from app.modules.finance.service import _convert_to_base, _project_fx_map

        order = await self.get_order(order_id)

        co_cost_native = _dec(cost_override) if cost_override is not None else _dec(order.cost_impact)
        schedule_days = (
            int(schedule_override) if schedule_override is not None else int(order.schedule_impact_days or 0)
        )
        co_currency = (order.currency or "").strip().upper()
        notes: list[str] = []

        project = await self._load_project(order.project_id)
        base_ccy = (getattr(project, "currency", "") or "").strip().upper() if project else ""
        planned_end = getattr(project, "planned_end_date", None) if project else None
        fx_map = _project_fx_map(project)

        agg = await BudgetRepository(self.session).aggregate_for_dashboard(project_id=order.project_id)

        def _base(amounts: dict) -> Decimal:
            converted, _missing = _convert_to_base(amounts, base_currency=base_ccy, fx_rates_map=fx_map)
            return Decimal(str(converted))

        revised = _base(agg["revised_by_currency"])
        original = _base(agg["original_by_currency"])
        bac = revised or original
        ac = _base(agg["actual_by_currency"])
        committed = _base(agg["committed_by_currency"])
        pv = bac
        ev = committed if committed > 0 else ac

        if co_currency and base_ccy and co_currency != base_ccy:
            converted, missing = _convert_to_base(
                {co_currency: co_cost_native},
                base_currency=base_ccy,
                fx_rates_map=fx_map,
            )
            co_cost_base = Decimal(str(converted))
            fx_converted = co_currency not in missing
            if not fx_converted:
                notes.append(
                    f"No FX rate is configured for {co_currency}, so its cost is shown unconverted "
                    "in the budget projection. Add an FX rate in project settings for an accurate figure."
                )
        else:
            co_cost_base = co_cost_native
            fx_converted = True

        item_count = await self._count_items(order.id)
        target_boq_name = await self._first_unlocked_boq_name(order.project_id)

        if not _parse_iso_date(planned_end):
            notes.append("The project has no planned end date, so only the number of days added is shown.")
        if bac <= 0:
            notes.append("No project budget is recorded yet, so cost-percentage and EVM figures are limited.")
        if item_count == 0:
            notes.append("This change order has no line items yet, so the BOQ preview is empty.")

        projection = _compute_impact_projection(
            bac=bac,
            ev=ev,
            ac=ac,
            pv=pv,
            co_cost_base=co_cost_base,
            schedule_days=schedule_days,
            planned_end=planned_end,
            item_count=item_count,
            target_boq_name=target_boq_name,
        )

        await _safe_publish(
            "changeorder.impact_simulated",
            {
                "change_order_id": str(order.id),
                "project_id": str(order.project_id),
                "code": order.code,
                "cost_delta_base": str(_round2(co_cost_base)),
                "schedule_days": schedule_days,
            },
            source_module="changeorders",
        )

        return {
            "order_id": order.id,
            "code": order.code,
            "base_currency": base_ccy,
            "as_of": datetime.now(UTC).isoformat(),
            "co_cost_native": str(_round2(co_cost_native)),
            "co_currency": co_currency or base_ccy,
            "co_cost_base": str(_round2(co_cost_base)),
            "fx_converted": fx_converted,
            "notes": notes,
            **projection,
        }

    async def publish_scenario(self, order_id: uuid.UUID, snapshot: dict) -> ChangeOrder:
        """Persist a what-if snapshot into the CO metadata for the audit trail.

        Keeps at most the last 10 scenarios so the JSON column never grows
        without bound. Storing in ``metadata_`` (rather than a dedicated
        column) keeps this LIGHTWEIGHT and avoids a migration - the data is
        display/audit-only and read-rarely.
        """
        order = await self.get_order(order_id)
        md = dict(order.metadata_) if isinstance(order.metadata_, dict) else {}
        scenarios = list(md.get("simulations") or [])
        scenarios.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "snapshot": snapshot,
            }
        )
        md["simulations"] = scenarios[-10:]
        order.metadata_ = md
        await self.session.flush()
        logger.info("Published what-if scenario for change order %s", order.code)
        return order

    async def ai_draft(
        self,
        *,
        project_id: uuid.UUID,
        source_kind: str,
        source_text: str,
        source_id: uuid.UUID | None,
        currency: str,
        user_id: str | uuid.UUID | None,
    ) -> dict:
        """Draft a change order from source text via AI, with a heuristic fallback.

        When an AI provider key is resolvable the text is sent to the model for
        structured extraction; on any failure (no key, provider error, bad
        JSON) the deterministic :func:`_heuristic_draft` takes over so the
        endpoint always returns a usable, clearly-labelled proposal. The draft
        is never saved - the caller reviews it and creates the CO separately.
        """
        resolved_currency = await self._resolve_currency(project_id, currency)

        provider = api_key = model = None
        try:
            from app.modules.ai.ai_client import resolve_provider_key_model
            from app.modules.ai.repository import AISettingsRepository

            settings = await AISettingsRepository(self.session).get_by_user_id(str(user_id)) if user_id else None
            provider, api_key, model = resolve_provider_key_model(settings)
        except Exception as exc:  # noqa: BLE001 - any resolution failure -> heuristic
            logger.debug("CO AI draft: no usable provider key (%s); using heuristic", exc)

        if provider and api_key:
            try:
                from app.modules.ai.ai_client import call_ai, extract_json

                text, _tokens = await call_ai(
                    provider,
                    api_key,
                    _DRAFT_SYSTEM,
                    _draft_prompt(source_kind, source_text, resolved_currency),
                    model=model,
                    max_tokens=1500,
                )
                data = extract_json(text)
                if isinstance(data, dict):
                    return _normalise_ai_draft(data, resolved_currency, source_kind, source_id, provider)
                logger.info("CO AI draft: model returned no JSON object; using heuristic")
            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                logger.info("CO AI draft fell back to heuristic: %s", exc)

        return _heuristic_draft(source_text, resolved_currency, source_kind, source_id)

    async def _load_project(self, project_id: uuid.UUID):  # noqa: ANN202 - ORM/stub
        """Load the owning Project, tolerating unit-test stub sessions."""
        from sqlalchemy import select

        from app.modules.projects.models import Project

        try:
            return (await self.session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        except Exception:
            return None

    # ── Update ────────────────────────────────────────────────────────────

    async def update_order(
        self,
        order_id: uuid.UUID,
        data: ChangeOrderUpdate,
    ) -> ChangeOrder:
        """Update change order fields. Only draft orders can be edited."""
        order = await self.get_order(order_id)

        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft change orders can be edited",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        # T3: coerce UUID lists to plain str lists so the JSON column
        # stores stable hex strings on both Postgres and SQLite (which
        # serializes JSON via stdlib ``json.dumps`` that refuses UUID).
        for key in ("linked_po_ids", "linked_rfi_ids"):
            if key in fields and fields[key] is not None:
                fields[key] = [str(x) for x in fields[key]]

        if not fields:
            return order

        await self.repo.update_fields(order_id, **fields)
        await self.session.refresh(order)

        logger.info("Change order updated: %s (fields=%s)", order_id, list(fields.keys()))
        return order

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_order(self, order_id: uuid.UUID) -> None:
        """Delete a change order. Only draft orders can be deleted."""
        order = await self.get_order(order_id)

        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft change orders can be deleted",
            )

        await self.repo.delete(order_id)
        logger.info("Change order deleted: %s", order_id)

    # ── Status transitions ────────────────────────────────────────────────

    async def _assert_not_self_approval(
        self,
        order: "ChangeOrder",
        user_id: str,
        action: str,
    ) -> None:
        """BUG-353: prevent the same user who submitted from approving / rejecting.

        Self-approval is a classic four-eyes-principle violation - in
        construction it means a site manager could both request and sign
        off a scope change without anyone else seeing it. Enforced at
        service layer so router shortcuts don't bypass it.
        """
        if order.submitted_by and str(order.submitted_by) == str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(f"You cannot {action} a change order you submitted yourself (four-eyes principle)."),
            )

    async def submit_order(self, order_id: uuid.UUID, user_id: str) -> ChangeOrder:
        """Submit a change order for approval."""
        order = await self.get_order(order_id)
        self._validate_transition(order.status, "submitted")
        # Snapshot the from-status so the audit row records the
        # transition accurately even after update_fields() expires the
        # in-memory order.
        from_status = order.status
        code_snapshot = order.code

        now = datetime.now(UTC).isoformat()[:19]
        await self.repo.update_fields(
            order_id,
            status="submitted",
            submitted_by=user_id,
            submitted_at=now,
        )
        # Audit trail: every CO status transition writes an
        # ActivityLog row so dispute timelines (FIDIC, ISO 9001, SCL
        # Protocol) can be reproduced byte-for-byte. The session ties
        # the audit row to the same transaction as the status write.
        await _safe_audit(
            self.session,
            actor_id=user_id,
            order_id=order_id,
            from_status=from_status,
            to_status="submitted",
            metadata={"code": code_snapshot},
        )
        await self.session.refresh(order)

        logger.info("Change order submitted: %s by %s", code_snapshot, user_id)
        return order

    async def approve_order(
        self,
        order_id: uuid.UUID,
        user_id: str,
        *,
        boq_id: uuid.UUID | None = None,
        _from_chain: bool = False,
    ) -> ChangeOrder:
        """Approve a submitted change order.

        On approval the order's ``cost_impact`` is applied to
        ``project.budget_estimate`` so downstream EVM / reporting reflect the
        new contractual commitment. A ``changeorder.approved`` event is
        published so other modules (budget dashboards, notifications) can
        react without coupling directly to this service.

        T3 forward-compat: if this CO has any rows in its approval chain,
        the caller must drive the chain via ``advance_approval`` and we
        refuse the single-step approval with HTTP 409 - silently bypassing
        the chain would let one user approve a CO that was supposed to
        require N signatures.
        """
        from decimal import Decimal, InvalidOperation

        from sqlalchemy import select

        from app.modules.projects.models import Project

        order = await self.get_order(order_id)
        # Idempotent: re-approving an already-approved change order is a
        # no-op (ENH-095). Prevents double budget-writeback if a client
        # retries an approval call after a flaky network round-trip.
        if order.status == "approved":
            return order
        # T3: gate the legacy single-step path on the presence of an
        # approval chain. Existing v3.10.1 clients keep working for COs
        # that have no chain; new chain-driven COs return 409 here so a
        # stale client can't shortcut multi-step routing. The internal
        # ``_from_chain=True`` escape hatch lets ``advance_approval``
        # reuse the same budget-writeback / BOQ-section code path on
        # final approval without tripping the gate.
        if not _from_chain and await self._has_approval_chain(order_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This change order has a multi-step approval chain. "
                    "Use POST /v1/changeorders/{id}/advance-approval instead."
                ),
            )
        # The four-eyes principle still applies on the legacy path, but
        # a chain-driven final approval has already enforced that the
        # acting user is a designated approver - keep the chain path
        # free of the self-approval check so a submitter can legally be
        # an approver later in the chain.
        if not _from_chain:
            await self._assert_not_self_approval(order, user_id, "approve")
        self._validate_transition(order.status, "approved")

        # Snapshot fields that are safe to use in the event payload later
        # (update_fields calls expire_all). ``project_id_uuid`` keeps the
        # native UUID for downstream SQL (stub tests look up the project
        # by exact UUID match, and Project.id is also typed as UUID).
        project_id_uuid: uuid.UUID = order.project_id
        project_id_s = str(project_id_uuid)
        code_s = order.code
        cost_impact_s = order.cost_impact or "0"
        currency_s = order.currency

        now = datetime.now(UTC).isoformat()[:19]
        from_status_snapshot = order.status
        await self.repo.update_fields(
            order_id,
            status="approved",
            approved_by=user_id,
            approved_at=now,
        )
        await _safe_audit(
            self.session,
            actor_id=user_id,
            order_id=order_id,
            from_status=from_status_snapshot,
            to_status="approved",
            metadata={
                "code": code_s,
                "cost_impact": str(cost_impact_s),
                "currency": currency_s,
                "via_chain": _from_chain,
            },
        )

        # Writeback: project.budget_estimate += cost_impact. Stored as string
        # to keep Decimal precision regardless of DB backend.
        try:
            delta = Decimal(str(cost_impact_s))
        except (InvalidOperation, ValueError):
            delta = Decimal("0")
        project_updated = False
        if delta != 0:
            # Use the project_id_s snapshot captured before update_fields()
            # called expire_all() - accessing ``order.project_id`` here
            # would trigger a sync-context attribute refresh and raise
            # ``MissingGreenlet`` under async aiosqlite.
            project = (
                await self.session.execute(select(Project).where(Project.id == project_id_uuid))
            ).scalar_one_or_none()
            if project is not None:
                try:
                    current = Decimal(str(project.budget_estimate)) if project.budget_estimate else Decimal("0")
                except (InvalidOperation, ValueError):
                    current = Decimal("0")
                project.budget_estimate = str(current + delta)
                project_updated = True
                await self.session.flush()

        # v2.6.45: Push CO items into the project's primary BOQ as a
        # dedicated section. Construction PMs expect approved scope to
        # appear in the BOQ - previously only project.budget_estimate
        # moved, leaving the BOQ silently out of date.
        # Re-fetch the order so its ``items`` collection is fresh -
        # repo.update_fields() above called session.expire_all() which
        # invalidated the original ORM instance.
        fresh_for_apply = await self.repo.get_by_id(order_id)
        boq_result = await self._apply_to_boq(fresh_for_apply or order, boq_id=boq_id)

        # v2.9.17 Gap B: write a ProjectBudget delta row so EVM BAC reflects
        # the post-CO scope. Wrapped in try/except - never roll back the
        # approval if the budget write fails.
        budget_writeback = await self._write_budget_delta_row(
            order_id=order_id,
            project_id_uuid=project_id_uuid,
            code=code_s,
            cost_impact=delta,
            currency=currency_s,
        )

        await _safe_publish(
            "changeorder.approved",
            {
                "change_order_id": str(order_id),
                "project_id": project_id_s,
                "code": code_s,
                "cost_impact": str(delta),
                "approved_by": user_id,
                "project_budget_updated": project_updated,
                "boq_applied": boq_result.get("applied", False),
                "boq_section_id": boq_result.get("section_id"),
                "boq_positions_added": boq_result.get("positions_added", 0),
                "budget_row_id": budget_writeback.get("budget_id"),
                "budget_row_action": budget_writeback.get("action"),
            },
            source_module="oe_changeorders",
        )

        fresh = await self.repo.get_by_id(order_id)
        logger.info(
            "Change order approved: %s by %s (delta=%s, boq=%s)",
            code_s,
            user_id,
            delta,
            boq_result,
        )
        return fresh or order

    async def _write_budget_delta_row(
        self,
        *,
        order_id: uuid.UUID,
        project_id_uuid: uuid.UUID,
        code: str,
        cost_impact: Decimal,
        currency: str | None,
    ) -> dict:
        """Create or update a ProjectBudget delta row for an approved CO.

        EVM BAC = SUM(revised_budget) across the project's budget rows, so
        approved scope changes need their own row to surface in dashboards.
        Keyed idempotently by ``metadata_->>'change_order_id' == order_id``
        so re-approving (or a second pass on the same CO) updates the
        existing row instead of inserting duplicates.

        Returns ``{"action": "created"|"updated"|"skipped", "budget_id": str|None}``
        - the ``action`` value flows into the ``changeorder.approved`` event
        payload so subscribers can tell what happened. Never raises: a
        budget-write failure must not roll back the approval.
        """
        from sqlalchemy import select

        from app.modules.finance.models import ProjectBudget

        try:
            # Resolve currency: CO-level → project default → "EUR" only as
            # a last-resort literal because ProjectBudget.currency_code is
            # NOT NULL and a missing project here is exceptional.
            currency_code = currency
            if not currency_code:
                from app.modules.projects.models import Project

                project = (
                    await self.session.execute(select(Project).where(Project.id == project_id_uuid))
                ).scalar_one_or_none()
                if project is not None:
                    currency_code = project.currency
            # Empty when neither CO nor project carries a currency -
            # the budget row stores empty rather than mis-stamping EUR
            # onto a non-Eurozone project.
            currency_code = currency_code or ""

            # Idempotent lookup keyed by metadata.change_order_id.
            existing = (
                (await self.session.execute(select(ProjectBudget).where(ProjectBudget.project_id == project_id_uuid)))
                .scalars()
                .all()
            )
            match: ProjectBudget | None = None
            for row in existing:
                md = row.metadata_ if isinstance(row.metadata_, dict) else {}
                if md.get("change_order_id") == str(order_id):
                    match = row
                    break

            category = f"Change Order {code}"
            if match is not None:
                match.revised_budget = cost_impact
                match.currency_code = currency_code
                match.category = category
                # Re-affirm the metadata key in case it was stripped manually.
                md = dict(match.metadata_) if isinstance(match.metadata_, dict) else {}
                md["change_order_id"] = str(order_id)
                md["change_order_code"] = code
                md["origin"] = "change_order"
                match.metadata_ = md
                await self.session.flush()
                return {"action": "updated", "budget_id": str(match.id)}

            budget = ProjectBudget(
                project_id=project_id_uuid,
                wbs_id=str(order_id),
                category=category,
                currency_code=currency_code,
                original_budget=Decimal("0"),
                revised_budget=cost_impact,
                committed=Decimal("0"),
                actual=Decimal("0"),
                forecast_final=Decimal("0"),
                metadata_={
                    "change_order_id": str(order_id),
                    "change_order_code": code,
                    "origin": "change_order",
                },
            )
            self.session.add(budget)
            await self.session.flush()
            return {"action": "created", "budget_id": str(budget.id)}
        except Exception:
            logger.warning(
                "Budget delta-row write failed for change order %s - approval still committed.",
                code,
                exc_info=True,
            )
            return {"action": "skipped", "budget_id": None}

    async def _apply_to_boq(
        self,
        order: ChangeOrder,
        *,
        boq_id: uuid.UUID | None = None,
    ) -> dict:
        """Push the approved CO's items into the project's first non-locked BOQ.

        Idempotent - if a section with ``metadata.change_order_id == order.id``
        already exists, returns ``already_applied`` and does nothing. Section
        ordinal is ``CO-{code}`` (assumed unique because CO codes are unique
        per project), description ``{code}: {title}``. Each ChangeOrderItem
        becomes a child Position with ``source='manual'`` and metadata link
        back to the CO/CO-item, using the existing schema.

        Returns a dict describing what happened so the event payload can
        surface it to subscribers and the UI:

        - ``applied=True`` + ``section_id`` + ``positions_added`` on success
        - ``applied=False`` + ``reason`` on no-op (no BOQ, all locked, already
          applied, or no items)
        """
        from sqlalchemy import select

        from app.modules.boq.models import BOQ, Position

        # Items must be fetched async - accessing ``order.items`` on an
        # ORM object whose attributes were expired by a prior flush()
        # triggers MissingGreenlet inside async SQLAlchemy. Pull them
        # explicitly so we don't depend on lazy-load state.
        try:
            items = list(
                (
                    await self.session.execute(
                        select(ChangeOrderItem)
                        .where(ChangeOrderItem.change_order_id == order.id)
                        .order_by(ChangeOrderItem.sort_order)
                    )
                )
                .scalars()
                .all()
            )
        except Exception:
            # Test stubs (SimpleNamespace) don't have a real session.
            # Fall back to whatever the stub exposes.
            items = list(getattr(order, "items", None) or [])
        if not items:
            return {"applied": False, "reason": "no_items"}

        if boq_id is not None:
            boq = (await self.session.execute(select(BOQ).where(BOQ.id == boq_id))).scalar_one_or_none()
            if boq is None:
                return {"applied": False, "reason": "boq_not_found"}
            if boq.project_id != order.project_id:
                return {"applied": False, "reason": "boq_project_mismatch"}
            if boq.is_locked:
                return {"applied": False, "reason": "boq_locked"}
        else:
            boq = (
                await self.session.execute(
                    select(BOQ)
                    .where(BOQ.project_id == order.project_id)
                    .where(BOQ.is_locked.is_(False))
                    .order_by(BOQ.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if boq is None:
                logger.info(
                    "Change order %s approved but no unlocked BOQ in project %s - BOQ writeback skipped",
                    order.code,
                    order.project_id,
                )
                return {"applied": False, "reason": "no_active_boq"}
            logger.warning(
                "Change order %s applied to BOQ %s by created_at fallback (no explicit boq_id supplied)",
                order.code,
                boq.id,
            )

        # Idempotent guard: section keyed by change_order_id in metadata.
        existing_sections = (
            (
                await self.session.execute(
                    select(Position).where(Position.boq_id == boq.id).where(Position.unit == "section")
                )
            )
            .scalars()
            .all()
        )
        for sec in existing_sections:
            md = sec.metadata_ if isinstance(sec.metadata_, dict) else {}
            if md.get("change_order_id") == str(order.id):
                return {
                    "applied": False,
                    "reason": "already_applied",
                    "section_id": str(sec.id),
                }

        # Pick a unique ordinal for the new section. CO codes are unique
        # per project (uq_changeorders_project_code), so ``CO-{code}`` is
        # collision-free across both first-time and re-issued COs.
        section_ordinal = f"CO-{order.code}"
        # Sort_order goes to the end of the BOQ.
        max_order_row = (
            await self.session.execute(
                select(Position.sort_order)
                .where(Position.boq_id == boq.id)
                .order_by(Position.sort_order.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        next_order = (max_order_row or 0) + 1

        section = Position(
            boq_id=boq.id,
            parent_id=None,
            ordinal=section_ordinal,
            description=f"{order.code}: {order.title}",
            unit="section",
            quantity="0",
            unit_rate="0",
            total="0",
            classification={},
            source="manual",
            confidence=None,
            cad_element_ids=[],
            metadata_={
                "change_order_id": str(order.id),
                "change_order_code": order.code,
                "origin": "change_order",
            },
            sort_order=next_order,
        )
        self.session.add(section)
        await self.session.flush()

        positions_added = 0
        item_total = Decimal("0")
        for idx, item in enumerate(items, start=1):
            try:
                qty = Decimal(str(item.new_quantity or "0"))
            except (InvalidOperation, ValueError):
                qty = Decimal("0")
            try:
                rate = Decimal(str(item.new_rate or "0"))
            except (InvalidOperation, ValueError):
                rate = Decimal("0")
            line_total = qty * rate
            item_total += line_total

            position = Position(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal=f"{section_ordinal}.{idx:03d}",
                description=item.description or "(no description)",
                unit=item.unit or "lsum",
                quantity=str(qty),
                unit_rate=str(rate),
                total=str(line_total),
                classification={},
                source="manual",
                confidence=None,
                cad_element_ids=[],
                metadata_={
                    "change_order_id": str(order.id),
                    "change_order_item_id": str(item.id),
                    "change_type": item.change_type,
                    "origin": "change_order",
                },
                sort_order=next_order + idx,
            )
            self.session.add(position)
            positions_added += 1

        # Surface the rolled-up cost on the section row so it's visible in
        # the BOQ tree without forcing the UI to recompute. The UI already
        # treats sections as headers (unit='section'), so the total renders
        # as a subtotal.
        section.total = str(item_total)
        await self.session.flush()

        logger.info(
            "Change order %s applied to BOQ %s: section=%s, %d positions, total=%s",
            order.code,
            boq.id,
            section.id,
            positions_added,
            item_total,
        )
        return {
            "applied": True,
            "boq_id": str(boq.id),
            "section_id": str(section.id),
            "positions_added": positions_added,
            "section_total": str(item_total),
        }

    async def reject_order(self, order_id: uuid.UUID, user_id: str) -> ChangeOrder:
        """Reject a submitted change order.

        BUG-351: writes to dedicated ``rejected_by`` / ``rejected_at`` fields
        rather than reusing the ``approved_*`` columns. Audit trails and
        dashboards now show "rejected by X" instead of "approved by X"
        when a CO is refused.
        """
        order = await self.get_order(order_id)
        await self._assert_not_self_approval(order, user_id, "reject")
        self._validate_transition(order.status, "rejected")
        # Snapshot pre-transition state for the audit row.
        from_status = order.status
        code_snapshot = order.code

        now = datetime.now(UTC).isoformat()[:19]
        await self.repo.update_fields(
            order_id,
            status="rejected",
            rejected_by=user_id,
            rejected_at=now,
        )
        await _safe_audit(
            self.session,
            actor_id=user_id,
            order_id=order_id,
            from_status=from_status,
            to_status="rejected",
            metadata={"code": code_snapshot},
        )
        fresh = await self.repo.get_by_id(order_id)

        logger.info(
            "Change order rejected: %s by %s",
            (fresh or order).code,
            user_id,
        )
        return fresh or order

    async def execute_order(self, order_id: uuid.UUID, user_id: str) -> ChangeOrder:
        """Mark an approved change order as executed (work completed on site).

        R7 hardening: the ``executed`` terminal state distinguishes COs that
        have been approved-in-principle from those where the scope change has
        actually been carried out, giving project controllers an accurate view
        of committed vs. realised cost impact.
        """
        order = await self.get_order(order_id)
        self._validate_transition(order.status, "executed")
        from_status = order.status
        code_snapshot = order.code

        now = datetime.now(UTC).isoformat()[:19]
        await self.repo.update_fields(order_id, status="executed")
        await _safe_audit(
            self.session,
            actor_id=user_id,
            order_id=order_id,
            from_status=from_status,
            to_status="executed",
            metadata={"code": code_snapshot},
        )
        fresh = await self.repo.get_by_id(order_id)
        logger.info("Change order executed: %s by %s", code_snapshot, user_id)
        return fresh or order

    def _validate_transition(self, current: str, target: str) -> None:
        """Validate a status transition."""
        allowed = VALID_TRANSITIONS.get(current, [])
        if target not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot transition from '{current}' to '{target}'",
            )

    # ── Items ─────────────────────────────────────────────────────────────

    async def add_item(
        self,
        order_id: uuid.UUID,
        data: ChangeOrderItemCreate,
    ) -> ChangeOrderItem:
        """Add an item to a change order and recalculate cost impact."""
        order = await self.get_order(order_id)

        # BUG-352: items are frozen once a CO leaves ``draft``. A submitted
        # CO represents a commitment already under review by the other
        # party, so silently mutating its line items is a contractual
        # integrity hazard. Revert to draft via an explicit transition if
        # changes are needed.
        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Items can only be modified while change order is in 'draft' status",
            )

        # Capture identifying fields BEFORE the recalculation. update_fields
        # expires the session, so accessing `order.code` afterwards would
        # trigger a lazy load and crash with MissingGreenlet in async context.
        order_code = order.code

        # Decimal money math - go through ``str()`` so a float like 0.1
        # doesn't enter the calculation as 0.1000000000000000055…; round
        # only at the persisted boundary (presentation rounds again in the
        # response builder / UI).
        cost_delta = (_dec(data.new_quantity) * _dec(data.new_rate)) - (
            _dec(data.original_quantity) * _dec(data.original_rate)
        )

        item = ChangeOrderItem(
            change_order_id=order_id,
            description=data.description,
            change_type=data.change_type,
            original_quantity=str(data.original_quantity),
            new_quantity=str(data.new_quantity),
            original_rate=str(data.original_rate),
            new_rate=str(data.new_rate),
            cost_delta=str(_round2(cost_delta)),
            unit=data.unit,
            sort_order=data.sort_order,
            metadata_=data.metadata,
        )
        item = await self.repo.create_item(item)

        await self._recalculate_cost_impact(order_id)

        # _recalculate_cost_impact expires all session objects, so the freshly
        # created item's attributes are stale - refresh before returning so the
        # router can build the response without lazy-loading.
        await self.session.refresh(item)

        logger.info("Item added to change order %s: %s", order_code, data.description[:40])
        return item

    async def update_item(
        self,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        data: ChangeOrderItemUpdate,
    ) -> ChangeOrderItem:
        """Update an item and recalculate cost impact."""
        order = await self.get_order(order_id)

        # BUG-352: items are frozen once a CO leaves ``draft``. A submitted
        # CO represents a commitment already under review by the other
        # party, so silently mutating its line items is a contractual
        # integrity hazard. Revert to draft via an explicit transition if
        # changes are needed.
        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Items can only be modified while change order is in 'draft' status",
            )

        item = await self.repo.get_item_by_id(item_id)
        if item is None or item.change_order_id != order_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Change order item not found",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Recalculate cost_delta if quantities or rates changed. Decimal
        # throughout - mixing the stored string column with an incoming
        # float and rounding once keeps the persisted delta exact.
        orig_qty = _dec(fields.get("original_quantity", item.original_quantity))
        new_qty = _dec(fields.get("new_quantity", item.new_quantity))
        orig_rate = _dec(fields.get("original_rate", item.original_rate))
        new_rate = _dec(fields.get("new_rate", item.new_rate))

        if any(k in fields for k in ("original_quantity", "new_quantity", "original_rate", "new_rate")):
            cost_delta = (new_qty * new_rate) - (orig_qty * orig_rate)
            fields["cost_delta"] = str(_round2(cost_delta))

        # Convert float fields to strings for storage
        for key in ("original_quantity", "new_quantity", "original_rate", "new_rate"):
            if key in fields:
                fields[key] = str(fields[key])

        if fields:
            await self.repo.update_item_fields(item_id, **fields)
            await self._recalculate_cost_impact(order_id)
            await self.session.refresh(item)

        return item

    async def delete_item(self, order_id: uuid.UUID, item_id: uuid.UUID) -> None:
        """Delete an item and recalculate cost impact."""
        order = await self.get_order(order_id)

        # BUG-352: items are frozen once a CO leaves ``draft``. A submitted
        # CO represents a commitment already under review by the other
        # party, so silently mutating its line items is a contractual
        # integrity hazard. Revert to draft via an explicit transition if
        # changes are needed.
        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Items can only be modified while change order is in 'draft' status",
            )

        # Capture the code before recalculation expires the session.
        order_code = order.code

        item = await self.repo.get_item_by_id(item_id)
        if item is None or item.change_order_id != order_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Change order item not found",
            )

        await self.repo.delete_item(item_id)
        await self._recalculate_cost_impact(order_id)

        logger.info("Item deleted from change order %s: %s", order_code, item_id)

    async def _recalculate_cost_impact(self, order_id: uuid.UUID) -> None:
        """Recalculate the total cost impact from all items.

        Re-entrancy safe: the expected ``cost_impact`` is computed in a
        single pass over ``sum(items.cost_delta)`` and only persisted when it
        differs from the value already stored, so a concurrent retry that
        sees the items already settled becomes a no-op rather than
        re-running the writeback. On a flush failure the in-flight item
        change is rolled back so a retry cannot double-count.
        """
        items = await self.repo.list_items_for_order(order_id)
        total = _round2(sum((_dec(item.cost_delta) for item in items), Decimal("0")))
        expected = str(total)

        order = await self.repo.get_by_id(order_id)
        current = (order.cost_impact if order is not None else None) or "0"
        # Compare on rounded Decimal so a "12.30" vs "12.3" representation
        # difference does not trigger a spurious write. When the stored value
        # already equals the recomputed total this is a no-op, which keeps a
        # concurrent retry from re-running the budget writeback downstream.
        if _round2(_dec(current)) == total:
            return

        try:
            await self.repo.update_fields(order_id, cost_impact=expected)
        except Exception:
            # The caller has already added/deleted the line item that drove
            # this recalculation; rolling back here unwinds that change too
            # so a retried request re-derives the total from a clean slate
            # rather than double-counting a partially applied delta.
            await self.session.rollback()
            raise

    # ── T3: construction management platform style multi-step approval chain ──

    async def _has_approval_chain(self, order_id: uuid.UUID) -> bool:
        """True iff this CO has at least one row in its approval chain.

        Wrapped in try/except so unit-test stubs (which expose ``approvals``
        as a plain list rather than via a SQLAlchemy query) and partially
        migrated DBs still resolve cleanly to "no chain".
        """
        from sqlalchemy import func, select

        try:
            stmt = select(func.count()).select_from(
                select(ChangeOrderApproval).where(ChangeOrderApproval.change_order_id == order_id).subquery()
            )
            count = (await self.session.execute(stmt)).scalar_one()
            return bool(count and int(count) > 0)
        except Exception:
            logger.debug(
                "Approval-chain probe skipped for %s (likely test stub)",
                order_id,
            )
            return False

    async def list_approvals(
        self,
        order_id: uuid.UUID,
    ) -> list[ChangeOrderApproval]:
        """Return the approval rows for ``order_id`` ordered by ``step_order``."""
        from sqlalchemy import select

        # Guarantee the CO exists (404s if not) before we expose its chain -
        # otherwise an unauth caller could enumerate CO ids by probing the
        # /approvals endpoint.
        await self.get_order(order_id)

        stmt = (
            select(ChangeOrderApproval)
            .where(ChangeOrderApproval.change_order_id == order_id)
            .order_by(ChangeOrderApproval.step_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def start_approval_chain(
        self,
        order_id: uuid.UUID,
        approver_user_ids: list[uuid.UUID],
    ) -> list[ChangeOrderApproval]:
        """Start a sequential approval chain on ``order_id``.

        Creates one ``ChangeOrderApproval`` row per supplied user with
        ``step_order`` 1..N, ``decision='pending'``, and sets the CO's
        ``current_approval_step`` cursor to 1 so the first approver is
        recognised as the active one.

        The chain can only be started on a CO in ``submitted`` state -
        starting it on a ``draft`` CO would let scope authors hand-pick
        their own approvers before review, and starting it on
        ``approved``/``rejected`` is non-sensical.

        Re-running on a CO that already has a chain is rejected (409) to
        avoid silently overwriting an in-flight chain.
        """
        if not approver_user_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one approver is required to start a chain.",
            )

        order = await self.get_order(order_id)
        if order.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Approval chain can only be started on a 'submitted' "
                    f"change order (current status: '{order.status}')."
                ),
            )

        if await self._has_approval_chain(order_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "An approval chain already exists for this change order. Use /advance-approval to drive it forward."
                ),
            )

        # Four-eyes principle (extends BUG-353): the submitter cannot
        # also be an approver on their own CO's chain. The single-step
        # ``approve_order`` / ``reject_order`` paths enforce this via
        # ``_assert_not_self_approval``; without the equivalent guard
        # here a scope author could discreetly slot themselves into the
        # chain (e.g. as step 2 of 3) and silently rubber-stamp their
        # own change - defeating the multi-approver requirement that
        # the chain exists to encode.
        if order.submitted_by:
            submitter_s = str(order.submitted_by)
            if any(str(aid) == submitter_s for aid in approver_user_ids):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "The change-order submitter cannot be an approver "
                        "on their own chain (four-eyes principle). Remove "
                        "the submitter from the approver list."
                    ),
                )

        rows: list[ChangeOrderApproval] = []
        for step, approver_id in enumerate(approver_user_ids, start=1):
            row = ChangeOrderApproval(
                change_order_id=order_id,
                step_order=step,
                approver_user_id=approver_id,
                decision="pending",
            )
            self.session.add(row)
            rows.append(row)

        await self.repo.update_fields(order_id, current_approval_step=1)
        # Race-safety: ``_has_approval_chain`` is a TOCTOU check - two
        # concurrent callers can both pass the probe and then both
        # attempt to write step 1. The unique index
        # ``uq_oe_changeorder_approval_change_order_id_step_order``
        # catches the second writer at flush time; surface that to the
        # caller as a 409 (matches the "already exists" path above) and
        # roll back so the partially-built chain doesn't leak.
        from sqlalchemy.exc import IntegrityError

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "An approval chain was concurrently started for this "
                    "change order. Use /advance-approval to drive it forward."
                ),
            ) from exc

        await _safe_publish(
            "changeorders.approval.started",
            {
                "co_id": str(order_id),
                "steps": len(rows),
                "first_approver_user_id": str(approver_user_ids[0]),
            },
            source_module="oe_changeorders",
        )
        logger.info(
            "Approval chain started for CO %s: %d steps",
            order_id,
            len(rows),
        )
        return rows

    async def advance_approval(
        self,
        order_id: uuid.UUID,
        user_id: str,
        decision: str,
        comments: str | None = None,
    ) -> ChangeOrderApproval:
        """Record the current approver's decision on the active step.

        Behaviour:

        * Looks up the row at ``step_order == co.current_approval_step``
          and verifies the caller is its assigned approver. Mismatch ⇒
          403 (a different user can't act on someone else's step).
        * ``decision='approved'``: stamps the row + advances the cursor.
          When the last step is approved, the CO transitions to
          ``approved`` and the same side-effects as the legacy
          ``approve_order`` fire (budget writeback, BOQ section, event).
        * ``decision='rejected'``: stamps the row, clears the cursor,
          and the CO transitions to ``rejected`` - downstream pending
          steps stay pending (audit trail) but the chain is dead.
        """
        from sqlalchemy import select

        if decision not in ("approved", "rejected"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Decision must be 'approved' or 'rejected'.",
            )

        order = await self.get_order(order_id)
        if order.status not in ("submitted",):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Cannot advance approval - change order is not in 'submitted' state (got '{order.status}')."),
            )
        cursor = order.current_approval_step
        if cursor is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("No approval chain is active - call /approval-chain first."),
            )

        # Resolve the active step's row.
        active_row = (
            await self.session.execute(
                select(ChangeOrderApproval).where(
                    ChangeOrderApproval.change_order_id == order_id,
                    ChangeOrderApproval.step_order == cursor,
                )
            )
        ).scalar_one_or_none()
        if active_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(f"No approval step at cursor {cursor} for this change order."),
            )

        # Caller must be the assigned approver. Compare as strings so
        # GUID-typed and str-typed JWT subjects compare cleanly.
        if active_row.approver_user_id is None or str(active_row.approver_user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=("You are not the assigned approver for the current step of this change order."),
            )

        if active_row.decision != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("This step has already been decided - chain may be out of sync."),
            )

        # Race-safety: the python-side "set active_row.decision" pattern
        # is a TOCTOU window when two approvers click at the same moment.
        # Both fetch the row with decision='pending' before either commits,
        # both then overwrite the column and both bump the cursor - the
        # CO advances two steps at once and the last write wins on
        # decided_at / comments.
        #
        # The conditional UPDATE below pushes the win condition to the
        # database: only ONE caller's WHERE clause can match a row that
        # is still ``pending``; the loser sees rowcount==0 and 409s
        # cleanly. Combined with the existing cursor read this gives
        # single-winner semantics without a SELECT … FOR UPDATE round
        # trip (works the same on SQLite dev and Postgres prod).
        from sqlalchemy import update as sa_update

        decided_at = datetime.now(UTC)
        update_stmt = (
            sa_update(ChangeOrderApproval)
            .where(ChangeOrderApproval.id == active_row.id)
            .where(ChangeOrderApproval.decision == "pending")
            .values(
                decision=decision,
                decided_at=decided_at,
                **({"comments": comments} if comments is not None else {}),
            )
        )
        result = await self.session.execute(update_stmt)
        # rowcount is None on some dialects when the connection didn't
        # report it (e.g. async drivers in autocommit). Treat that as a
        # success only when ``active_row`` reflects pending (we just
        # checked it above) - but if the driver reports 0, fail hard so
        # we never silently drop the loser.
        affected = getattr(result, "rowcount", None)
        if affected == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("This approval step was concurrently decided by another approver - refresh and retry."),
            )
        # Keep the in-memory row in sync for the rest of this method so
        # downstream code (event payload, return value) sees the new
        # decision / timestamp.
        active_row.decision = decision
        active_row.decided_at = decided_at
        if comments is not None:
            active_row.comments = comments
        await self.session.flush()

        # Total step count to know whether we just signed off the last one.
        total_steps = (
            (
                await self.session.execute(
                    select(ChangeOrderApproval).where(ChangeOrderApproval.change_order_id == order_id)
                )
            )
            .scalars()
            .all()
        )
        n_steps = len(total_steps)

        if decision == "rejected":
            # Chain dies here. Clear the cursor + flip the CO to rejected.
            now = datetime.now(UTC).isoformat()[:19]
            await self.repo.update_fields(
                order_id,
                status="rejected",
                rejected_by=user_id,
                rejected_at=now,
                current_approval_step=None,
            )
            # Audit row records the rejection point so the chain
            # timeline shows exactly which step killed the CO.
            await _safe_audit(
                self.session,
                actor_id=user_id,
                order_id=order_id,
                from_status="submitted",
                to_status="rejected",
                reason=comments,
                metadata={
                    "via_chain": True,
                    "step_order": cursor,
                },
            )
            await _safe_publish(
                "changeorders.approval.advanced",
                {
                    "co_id": str(order_id),
                    "step_order": cursor,
                    "decision": "rejected",
                    "by_user_id": str(user_id),
                    "chain_complete": True,
                },
                source_module="oe_changeorders",
            )
            logger.info(
                "Approval chain rejected at step %d for CO %s by %s",
                cursor,
                order_id,
                user_id,
            )
            return active_row

        # decision == 'approved'
        if cursor >= n_steps:
            # Last step approved → final approval. Delegate the budget /
            # BOQ side-effects to the legacy approve_order path by
            # clearing the cursor (so the chain-gate doesn't fire) and
            # calling it. Snapshot now in case the cursor check is racy.
            await self.repo.update_fields(order_id, current_approval_step=None)
            await _safe_publish(
                "changeorders.approval.advanced",
                {
                    "co_id": str(order_id),
                    "step_order": cursor,
                    "decision": "approved",
                    "by_user_id": str(user_id),
                    "chain_complete": True,
                },
                source_module="oe_changeorders",
            )
            # Drive the final side-effects through the same code path
            # the single-step approval uses so budget writeback / BOQ
            # section creation stay consistent. ``_from_chain=True``
            # bypasses the chain-presence gate (we already drove the
            # chain) and the four-eyes self-approval check (the chain
            # already documented every approver).
            await self.approve_order(order_id, user_id, _from_chain=True)
            logger.info(
                "Approval chain completed for CO %s on step %d by %s",
                order_id,
                cursor,
                user_id,
            )
            return active_row

        # Mid-chain approval: bump the cursor and keep going.
        await self.repo.update_fields(order_id, current_approval_step=cursor + 1)
        await _safe_publish(
            "changeorders.approval.advanced",
            {
                "co_id": str(order_id),
                "step_order": cursor,
                "decision": "approved",
                "by_user_id": str(user_id),
                "chain_complete": False,
            },
            source_module="oe_changeorders",
        )
        logger.info(
            "Approval step %d → approved for CO %s by %s (next: %d)",
            cursor,
            order_id,
            user_id,
            cursor + 1,
        )
        return active_row
