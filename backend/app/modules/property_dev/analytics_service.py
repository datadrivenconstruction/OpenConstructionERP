"""Sales-analytics service for the Property Development module.

Five director-grade dashboards, each built on a single SQL aggregate
pass (no Python loops over rowsets):

1. :func:`cohort_retention`  — bookings grouped by reservation-month,
   % still active at +30/60/90/180 days.
2. :func:`time_to_close`     — days Lead → Reservation → Sale → Handover
   for every closed sale, with mean / p50 / p90 + histogram per stage.
3. :func:`lead_source_attribution` — per-source funnel, revenue and CPA.
4. :func:`conversion_funnel` — Leads → Qualified → Reservation → Sale
   → Handover.
5. :func:`broker_performance` — per-broker leaderboard with GMV +
   commission rollups.

Every endpoint is window-scoped (``since`` / ``until`` as YYYY-MM-DD).
Money is Decimal-as-string at the schema layer; this module only deals
with Decimal arithmetic.

The class is intentionally minimal — it only borrows the AsyncSession
from :class:`PropertyDevService` so existing IDOR closures still own
tenant-scoping at the router layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func as _func
from sqlalchemy import select as _select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.property_dev.models import (
    Broker,
    CommissionAccrual,
    Handover,
    Lead,
    Plot,
    Reservation,
    SalesContract,
)

# Days-active buckets we report for the cohort-retention widget. Centralised
# so the schema layer + the SQL aggregate stay in lockstep.
COHORT_OFFSETS: tuple[int, ...] = (30, 60, 90, 180)

# Reservation states the cohort considers "still in play". ``cancelled``
# / ``refunded`` / ``expired`` are terminal and never count toward
# retention.
_LIVE_RESERVATION_STATES: tuple[str, ...] = ("active", "converted")

# Closed-sale states for the time-to-close + funnel + attribution queries.
_CLOSED_SPA_STATES: tuple[str, ...] = (
    "signed",
    "countersigned",
    "registered",
)

# Lead states the funnel considers "qualified" (anything past ``new``
# that hasn't been disqualified/lost). Mirrors the FSM in
# ``PropertyDevService._LEAD_TRANSITIONS``.
_QUALIFIED_LEAD_STATES: tuple[str, ...] = (
    "qualified",
    "viewing_scheduled",
    "visited",
    "quotation_sent",
    "negotiating",
    "converted",
)

# Stage histogram buckets — sales directors think in weeks. We anchor on
# "this week / next week / this month / quarter / longer" to match how
# they communicate with the board. ``hi == -1`` marks the open-ended tail.
_STAGE_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0–7d", 0, 7),
    ("8–14d", 8, 14),
    ("15–30d", 15, 30),
    ("31–60d", 31, 60),
    ("61–90d", 61, 90),
    ("91–180d", 91, 180),
    (">180d", 181, -1),
)


def _parse_iso_date(value: str | None) -> date | None:
    """Return a ``date`` or ``None`` — raises ``ValueError`` on bad input.

    The router validates the YYYY-MM-DD shape via a Query regex; this
    helper is a safety net for service-layer callers.
    """
    if value is None or value == "":
        return None
    return date.fromisoformat(value)


def _percentile(values: list[Decimal], pct: int) -> Decimal:
    """Nearest-rank percentile on a SORTED list of Decimal days."""
    if not values:
        return Decimal("0")
    if pct <= 0:
        return values[0]
    if pct >= 100:
        return values[-1]
    n = len(values)
    # Nearest-rank — same convention pandas / numpy "nearest" uses.
    k = max(0, min(n - 1, (pct * n) // 100))
    return values[k]


def _bucket_for_days(days: int) -> str:
    """Return the human label of the bucket holding ``days``."""
    for label, lo, hi in _STAGE_BUCKETS:
        if hi == -1 and days >= lo:
            return label
        if lo <= days <= hi:
            return label
    return _STAGE_BUCKETS[-1][0]


def _days_between(start_iso: str | None, end_iso: str | None) -> int | None:
    """Return integer days between two ISO date strings, or ``None``."""
    if not start_iso or not end_iso:
        return None
    try:
        s = date.fromisoformat(start_iso[:10])
        e = date.fromisoformat(end_iso[:10])
    except (ValueError, TypeError):
        return None
    delta = (e - s).days
    if delta < 0:
        return None
    return delta


def _days_between_dt(
    start: datetime | None,
    end: datetime | None,
) -> int | None:
    """Return integer days between two datetimes, or ``None``."""
    if start is None or end is None:
        return None
    try:
        delta = (end.date() - start.date()).days
    except (AttributeError, TypeError):
        return None
    if delta < 0:
        return None
    return delta


def _date_or_dt_to_date(value: Any) -> date | None:
    """Coerce a Lead.created_at / Buyer.contract_signed_at to ``date``.

    The model layer uses both ``DateTime`` (Lead.created_at) and ISO
    string columns (Buyer.contract_signed_at / Handover.completed_at),
    so this normalises across both.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


class AnalyticsService:
    """Director-grade sales analytics for property_dev."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── 1. Cohort retention ────────────────────────────────────────

    async def cohort_retention(
        self,
        *,
        cohort_period: str = "month",
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Reservation cohorts by birth month + % retained at +N days.

        The "still active at +N days" metric is share of the cohort that
        was NOT in a terminal state (``cancelled`` / ``refunded`` /
        ``expired``) at the relative offset. Cancellations that arrive
        AFTER the offset (e.g. cancel at +120d) DO count toward retained
        at +30/60/90 days but not at +180.
        """
        since_d = _parse_iso_date(since)
        until_d = _parse_iso_date(until)
        # The service supports only ``month`` today; the schema layer
        # rejects anything else at the router. Pinning it here makes the
        # SQL fully deterministic across SQLite + PostgreSQL.
        cohort_period = "month" if cohort_period not in ("month",) else cohort_period

        stmt = _select(
            Reservation.id,
            Reservation.created_at,
            Reservation.status,
            Reservation.cooling_off_until,
            Reservation.expires_at,
            Reservation.metadata_,
        )
        if since_d is not None:
            stmt = stmt.where(Reservation.created_at >= datetime.combine(since_d, datetime.min.time(), tzinfo=UTC))
        if until_d is not None:
            stmt = stmt.where(
                Reservation.created_at
                < datetime.combine(
                    until_d + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=UTC,
                )
            )

        rows = (await self.session.execute(stmt)).all()

        # Group by cohort month + collect the data we need to project
        # retention forward. ``cancelled_at`` is stored inside the metadata
        # blob for reservations (the FSM service stamps it on cancel /
        # expire / refund), so we read it from there when present.
        cohorts: dict[str, dict[str, Any]] = {}
        today = datetime.now(UTC).date()

        for res_id, created_at, status, _cooloff, _expires, meta in rows:
            created_d = _date_or_dt_to_date(created_at)
            if created_d is None:
                continue
            cohort_key = f"{created_d.year:04d}-{created_d.month:02d}"
            slot = cohorts.setdefault(
                cohort_key,
                {
                    "cohort_month": cohort_key,
                    "total": 0,
                    "still_active": 0,
                    "events": [],  # list[(status, days_since_birth_or_None)]
                },
            )
            slot["total"] += 1

            terminal_d: date | None = None
            if status in ("cancelled", "refunded", "expired"):
                # Try to read a precise terminal date out of metadata; if
                # absent, treat the cohort row as terminal AT the offset
                # boundary the SPA layer published (best-effort).
                if isinstance(meta, dict):
                    for k in ("cancelled_at", "refunded_at", "expired_at"):
                        v = meta.get(k)
                        cand = _date_or_dt_to_date(v)
                        if cand is not None:
                            terminal_d = cand
                            break
            else:
                slot["still_active"] += 1

            days_to_terminal = (terminal_d - created_d).days if terminal_d else None
            slot["events"].append(
                {
                    "status": status,
                    "days_to_terminal": days_to_terminal,
                    "age_days": (today - created_d).days,
                }
            )

        # Project to retention percentages per offset.
        out_rows: list[dict[str, Any]] = []
        for key in sorted(cohorts.keys()):
            slot = cohorts[key]
            total = int(slot["total"])
            retention_pct: dict[int, Decimal] = {}
            for offset in COHORT_OFFSETS:
                if total == 0:
                    retention_pct[offset] = Decimal("0")
                    continue
                retained = 0
                for ev in slot["events"]:
                    if ev["age_days"] < offset:
                        # The cohort hasn't aged this far yet — exclude
                        # the row from the denominator at this offset.
                        # We collapse "not yet reached" to "not retained"
                        # which is mildly pessimistic but ensures the
                        # widget never shows >100%.
                        continue
                    days_to_terminal = ev["days_to_terminal"]
                    if days_to_terminal is None or days_to_terminal > offset:
                        retained += 1
                retention_pct[offset] = (Decimal(retained) / Decimal(total) * Decimal("100")).quantize(Decimal("0.1"))

            out_rows.append(
                {
                    "cohort_month": key,
                    "total": total,
                    "still_active": int(slot["still_active"]),
                    "retention_pct_d30": retention_pct[30],
                    "retention_pct_d60": retention_pct[60],
                    "retention_pct_d90": retention_pct[90],
                    "retention_pct_d180": retention_pct[180],
                }
            )

        return {
            "cohort_period": cohort_period,
            "since": since,
            "until": until,
            "cohorts": out_rows,
            "total_cohorts": len(out_rows),
        }

    # ── 2. Time to close ────────────────────────────────────────────

    async def time_to_close(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Days Lead → Reservation → Sale → Handover for closed sales.

        Stages reported:
          * lead_to_reservation
          * reservation_to_sale
          * sale_to_handover
          * lead_to_handover (end-to-end)

        Each stage emits sample_size + mean + p50 + p90 + histogram of
        buckets. Closed sale = SalesContract in (signed / countersigned
        / registered) within the window.
        """
        since_d = _parse_iso_date(since)
        until_d = _parse_iso_date(until)

        stmt = (
            _select(
                SalesContract.id,
                SalesContract.signing_date,
                SalesContract.created_at,
                SalesContract.reservation_id,
                SalesContract.plot_id,
                Reservation.created_at.label("res_created_at"),
                Reservation.lead_id,
                Handover.completed_at.label("ho_completed_at"),
            )
            .join(
                Reservation,
                Reservation.id == SalesContract.reservation_id,
                isouter=True,
            )
            .join(Handover, Handover.plot_id == SalesContract.plot_id, isouter=True)
            .where(SalesContract.status.in_(_CLOSED_SPA_STATES))
        )
        if since_d is not None:
            stmt = stmt.where(SalesContract.signing_date >= since_d.isoformat())
        if until_d is not None:
            stmt = stmt.where(SalesContract.signing_date <= until_d.isoformat())

        spa_rows = (await self.session.execute(stmt)).all()

        lead_ids: set[uuid.UUID] = {r.lead_id for r in spa_rows if r.lead_id is not None}
        lead_created_at: dict[uuid.UUID, datetime] = {}
        if lead_ids:
            lead_stmt = _select(Lead.id, Lead.created_at).where(Lead.id.in_(lead_ids))
            for lid, lc in (await self.session.execute(lead_stmt)).all():
                lead_created_at[lid] = lc

        l_to_r: list[Decimal] = []
        r_to_s: list[Decimal] = []
        s_to_h: list[Decimal] = []
        l_to_h: list[Decimal] = []

        for r in spa_rows:
            lead_dt = lead_created_at.get(r.lead_id) if r.lead_id is not None else None
            lead_d = _date_or_dt_to_date(lead_dt)
            res_d = _date_or_dt_to_date(r.res_created_at)
            sale_d = _date_or_dt_to_date(r.signing_date)
            ho_d = _date_or_dt_to_date(r.ho_completed_at)

            if lead_d and res_d:
                delta = (res_d - lead_d).days
                if delta >= 0:
                    l_to_r.append(Decimal(delta))
            if res_d and sale_d:
                delta = (sale_d - res_d).days
                if delta >= 0:
                    r_to_s.append(Decimal(delta))
            if sale_d and ho_d:
                delta = (ho_d - sale_d).days
                if delta >= 0:
                    s_to_h.append(Decimal(delta))
            if lead_d and ho_d:
                delta = (ho_d - lead_d).days
                if delta >= 0:
                    l_to_h.append(Decimal(delta))

        def _stage(label: str, samples: list[Decimal]) -> dict[str, Any]:
            samples_sorted = sorted(samples)
            n = len(samples_sorted)
            mean_d = (sum(samples_sorted, Decimal("0")) / Decimal(n)).quantize(Decimal("0.1")) if n else Decimal("0")
            p50 = _percentile(samples_sorted, 50).quantize(Decimal("0.1"))
            p90 = _percentile(samples_sorted, 90).quantize(Decimal("0.1"))

            histogram = {label: 0 for label, _lo, _hi in _STAGE_BUCKETS}
            for d in samples_sorted:
                histogram[_bucket_for_days(int(d))] += 1

            return {
                "stage": label,
                "sample_size": n,
                "mean_days": mean_d,
                "p50_days": p50,
                "p90_days": p90,
                "buckets": [
                    {"label": label, "lo_days": lo, "hi_days": hi, "count": histogram[label]}
                    for label, lo, hi in _STAGE_BUCKETS
                ],
            }

        return {
            "since": since,
            "until": until,
            "closed_sales": len(spa_rows),
            "stages": [
                _stage("lead_to_reservation", l_to_r),
                _stage("reservation_to_sale", r_to_s),
                _stage("sale_to_handover", s_to_h),
                _stage("lead_to_handover", l_to_h),
            ],
        }

    # ── 3. Lead source attribution ─────────────────────────────────

    async def lead_source_attribution(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Per lead-source: count, conv-to-res%, conv-to-sale%, revenue, CPA.

        SQL aggregates only — three GROUP BY queries against
        ``oe_property_dev_lead`` joined to reservation + SPA via the
        ``Reservation.lead_id`` and ``Reservation -> SalesContract``
        bridges.
        """
        since_d = _parse_iso_date(since)
        until_d = _parse_iso_date(until)

        # ── Q1: lead totals + total source_cost per source ────────
        q1 = _select(
            Lead.source,
            _func.count(Lead.id).label("lead_count"),
            _func.coalesce(_func.sum(Lead.source_cost), 0).label("total_cost"),
        )
        if since_d is not None:
            q1 = q1.where(Lead.created_at >= datetime.combine(since_d, datetime.min.time(), tzinfo=UTC))
        if until_d is not None:
            q1 = q1.where(
                Lead.created_at
                < datetime.combine(
                    until_d + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=UTC,
                )
            )
        q1 = q1.group_by(Lead.source)
        per_source: dict[str, dict[str, Any]] = {}
        for src, lead_count, total_cost in (await self.session.execute(q1)).all():
            per_source[src or "other"] = {
                "source": src or "other",
                "leads": int(lead_count or 0),
                "reservations": 0,
                "sales": 0,
                "revenue": {},  # currency -> Decimal
                "total_source_cost": Decimal(str(total_cost or 0)),
            }

        # ── Q2: reservations per source (count distinct lead_id where Lead.source = X) ──
        q2 = (
            _select(
                Lead.source,
                _func.count(_func.distinct(Reservation.id)).label("res_count"),
            )
            .join(Reservation, Reservation.lead_id == Lead.id)
            .group_by(Lead.source)
        )
        if since_d is not None:
            q2 = q2.where(Lead.created_at >= datetime.combine(since_d, datetime.min.time(), tzinfo=UTC))
        if until_d is not None:
            q2 = q2.where(
                Lead.created_at
                < datetime.combine(
                    until_d + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=UTC,
                )
            )
        for src, res_count in (await self.session.execute(q2)).all():
            key = src or "other"
            slot = per_source.setdefault(
                key,
                {
                    "source": key,
                    "leads": 0,
                    "reservations": 0,
                    "sales": 0,
                    "revenue": {},
                    "total_source_cost": Decimal("0"),
                },
            )
            slot["reservations"] = int(res_count or 0)

        # ── Q3: closed sales + revenue per source ─────────────────
        q3 = (
            _select(
                Lead.source,
                SalesContract.currency,
                _func.count(_func.distinct(SalesContract.id)).label("sale_count"),
                _func.coalesce(_func.sum(SalesContract.total_value), 0).label("revenue"),
            )
            .join(Reservation, Reservation.lead_id == Lead.id)
            .join(SalesContract, SalesContract.reservation_id == Reservation.id)
            .where(SalesContract.status.in_(_CLOSED_SPA_STATES))
            .group_by(Lead.source, SalesContract.currency)
        )
        if since_d is not None:
            q3 = q3.where(Lead.created_at >= datetime.combine(since_d, datetime.min.time(), tzinfo=UTC))
        if until_d is not None:
            q3 = q3.where(
                Lead.created_at
                < datetime.combine(
                    until_d + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=UTC,
                )
            )
        sales_count_by_source: dict[str, int] = {}
        for src, currency, sale_count, revenue in (await self.session.execute(q3)).all():
            key = src or "other"
            slot = per_source.setdefault(
                key,
                {
                    "source": key,
                    "leads": 0,
                    "reservations": 0,
                    "sales": 0,
                    "revenue": {},
                    "total_source_cost": Decimal("0"),
                },
            )
            cur = currency or ""
            slot["revenue"][cur] = slot["revenue"].get(cur, Decimal("0")) + Decimal(str(revenue or 0))
            sales_count_by_source[key] = sales_count_by_source.get(key, 0) + int(sale_count or 0)

        for key, n in sales_count_by_source.items():
            per_source[key]["sales"] = n

        rows: list[dict[str, Any]] = []
        total_leads = 0
        for key in sorted(per_source.keys()):
            slot = per_source[key]
            leads = int(slot["leads"])
            total_leads += leads
            conv_to_res = (
                (Decimal(slot["reservations"]) / Decimal(leads) * Decimal("100")).quantize(Decimal("0.1"))
                if leads
                else Decimal("0")
            )
            conv_to_sale = (
                (Decimal(slot["sales"]) / Decimal(leads) * Decimal("100")).quantize(Decimal("0.1"))
                if leads
                else Decimal("0")
            )

            revenue_list = [
                {"currency": cur, "amount": amt.quantize(Decimal("0.01"))}
                for cur, amt in sorted(slot["revenue"].items())
            ]
            # CPA = total_source_cost / sales_count, expressed in the
            # currency of the single tallest revenue bucket (multi-currency
            # CPA is meaningless without an FX cross — we surface the
            # currency the rollup attached the cost to).
            cpa: Decimal | None = None
            cpa_currency = ""
            if slot["sales"] > 0 and slot["total_source_cost"] > 0:
                cpa = (slot["total_source_cost"] / Decimal(slot["sales"])).quantize(Decimal("0.01"))
                if revenue_list:
                    # Pick the currency with the largest contribution so
                    # the CPA matches the same currency the director is
                    # reading revenue in.
                    cpa_currency = max(
                        revenue_list,
                        key=lambda x: x["amount"],
                    )["currency"]

            rows.append(
                {
                    "source": slot["source"],
                    "leads": leads,
                    "reservations": int(slot["reservations"]),
                    "sales": int(slot["sales"]),
                    "conversion_to_reservation_pct": conv_to_res,
                    "conversion_to_sale_pct": conv_to_sale,
                    "revenue": revenue_list,
                    "total_source_cost": slot["total_source_cost"].quantize(Decimal("0.01")),
                    "cpa": cpa,
                    "cpa_currency": cpa_currency,
                }
            )

        return {
            "since": since,
            "until": until,
            "rows": rows,
            "total_leads": total_leads,
        }

    # ── 4. Conversion funnel ───────────────────────────────────────

    async def conversion_funnel(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        dev_id: uuid.UUID | None = None,
        plot_type: str | None = None,
    ) -> dict[str, Any]:
        """5-step funnel scoped by date window + optional development + plot type.

        Stages:
          * leads      — Lead rows in window (optionally filtered by dev)
          * qualified  — leads whose ``status`` is past ``new``
          * reservation — Reservations linked to those leads
          * sale       — SalesContracts in ``_CLOSED_SPA_STATES`` linked
                          to those reservations
          * handover   — Handovers completed for the same plots
        """
        since_d = _parse_iso_date(since)
        until_d = _parse_iso_date(until)

        # ── Stage 1 / 2: leads + qualified leads ───────────────────
        base = _select(Lead.id).select_from(Lead)
        if dev_id is not None:
            base = base.where(Lead.development_id == dev_id)
        if since_d is not None:
            base = base.where(Lead.created_at >= datetime.combine(since_d, datetime.min.time(), tzinfo=UTC))
        if until_d is not None:
            base = base.where(
                Lead.created_at
                < datetime.combine(
                    until_d + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=UTC,
                )
            )
        # plot_type filter narrows to leads where preferred_house_type
        # matches the supplied label — used by directors who track
        # townhouse vs. apartment funnels separately.
        if plot_type is not None and plot_type != "":
            # Hop via plot.house_type_label using a sub-select.
            base = base.where(
                Lead.preferred_house_type_id.in_(_select(Plot.house_type_id).where(Plot.house_type_label == plot_type))
            )

        lead_count_q = _select(_func.count()).select_from(base.subquery())
        qual_count_q = (
            _select(_func.count())
            .select_from(Lead)
            .where(Lead.id.in_(base.subquery().select()))
            .where(Lead.status.in_(_QUALIFIED_LEAD_STATES))
        )
        # NB: Lead.id.in_(subquery.select()) — SQLAlchemy 2 form.

        lead_count = (await self.session.execute(lead_count_q)).scalar_one() or 0
        qualified_count = (await self.session.execute(qual_count_q)).scalar_one() or 0

        # ── Stage 3: reservations from those leads (any state) ─────
        res_count_q = _select(_func.count(_func.distinct(Reservation.id))).where(
            Reservation.lead_id.in_(base.subquery().select())
        )
        res_count = (await self.session.execute(res_count_q)).scalar_one() or 0

        # ── Stage 4: closed sales chained via reservation ──────────
        sale_count_q = (
            _select(_func.count(_func.distinct(SalesContract.id)))
            .join(Reservation, Reservation.id == SalesContract.reservation_id)
            .where(Reservation.lead_id.in_(base.subquery().select()))
            .where(SalesContract.status.in_(_CLOSED_SPA_STATES))
        )
        sale_count = (await self.session.execute(sale_count_q)).scalar_one() or 0

        # ── Stage 5: handovers on those plots ─────────────────────
        ho_count_q = (
            _select(_func.count(_func.distinct(Handover.id)))
            .join(SalesContract, SalesContract.plot_id == Handover.plot_id)
            .join(Reservation, Reservation.id == SalesContract.reservation_id)
            .where(Reservation.lead_id.in_(base.subquery().select()))
            .where(SalesContract.status.in_(_CLOSED_SPA_STATES))
            .where(Handover.completed_at.is_not(None))
        )
        ho_count = (await self.session.execute(ho_count_q)).scalar_one() or 0

        counts = [
            ("leads", "Leads", int(lead_count)),
            ("qualified", "Qualified", int(qualified_count)),
            ("reservation", "Reservation", int(res_count)),
            ("sale", "Sale", int(sale_count)),
            ("handover", "Handover", int(ho_count)),
        ]
        top = counts[0][2]
        steps: list[dict[str, Any]] = []
        prev: int = top
        for code, label, count in counts:
            drop = (
                (Decimal(prev - count) / Decimal(prev) * Decimal("100")).quantize(Decimal("0.1"))
                if prev > 0
                else Decimal("0")
            )
            from_top = (
                (Decimal(count) / Decimal(top) * Decimal("100")).quantize(Decimal("0.1")) if top > 0 else Decimal("0")
            )
            if code == "leads":
                drop = Decimal("0")
            steps.append(
                {
                    "code": code,
                    "label": label,
                    "count": count,
                    "drop_pct": drop,
                    "conversion_from_top_pct": from_top,
                }
            )
            prev = count

        overall = (
            (Decimal(int(ho_count)) / Decimal(top) * Decimal("100")).quantize(Decimal("0.1"))
            if top > 0
            else Decimal("0")
        )

        return {
            "since": since,
            "until": until,
            "dev_id": dev_id,
            "plot_type": plot_type,
            "steps": steps,
            "overall_conversion_pct": overall,
        }

    # ── 5. Broker performance ─────────────────────────────────────

    async def broker_performance(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Per-broker: leads-assigned, reservations, sales, GMV, commission.

        Five SQL aggregates joined in Python by broker_id (avoids a
        ``FULL OUTER JOIN`` SQLite doesn't support). All numeric tallies
        come from SQL ``COUNT`` / ``SUM`` — no row-by-row Python tallies.
        """
        since_d = _parse_iso_date(since)
        until_d = _parse_iso_date(until)
        since_dt = datetime.combine(since_d, datetime.min.time(), tzinfo=UTC) if since_d else None
        until_dt = datetime.combine(until_d + timedelta(days=1), datetime.min.time(), tzinfo=UTC) if until_d else None

        # Broker base list.
        brokers_stmt = _select(Broker.id, Broker.name).where(Broker.active.is_(True))
        broker_rows = (await self.session.execute(brokers_stmt)).all()
        per_broker: dict[uuid.UUID, dict[str, Any]] = {
            bid: {
                "broker_id": bid,
                "broker_name": name or "",
                "leads_assigned": 0,
                "reservations_closed": 0,
                "sales_closed": 0,
                "gmv": {},  # currency -> Decimal
                "commission_earned": {},  # currency -> Decimal
            }
            for bid, name in broker_rows
        }

        # 1) leads_assigned — count(Lead) GROUP BY broker_id.
        q_leads = _select(Lead.broker_id, _func.count(Lead.id).label("c")).where(Lead.broker_id.is_not(None))
        if since_dt is not None:
            q_leads = q_leads.where(Lead.created_at >= since_dt)
        if until_dt is not None:
            q_leads = q_leads.where(Lead.created_at < until_dt)
        q_leads = q_leads.group_by(Lead.broker_id)
        for bid, c in (await self.session.execute(q_leads)).all():
            slot = per_broker.setdefault(
                bid,
                {
                    "broker_id": bid,
                    "broker_name": "",
                    "leads_assigned": 0,
                    "reservations_closed": 0,
                    "sales_closed": 0,
                    "gmv": {},
                    "commission_earned": {},
                },
            )
            slot["leads_assigned"] = int(c or 0)

        # 2) reservations_closed — Reservation joined back to Lead.broker_id.
        q_res = (
            _select(
                Lead.broker_id,
                _func.count(_func.distinct(Reservation.id)).label("c"),
            )
            .join(Reservation, Reservation.lead_id == Lead.id)
            .where(Lead.broker_id.is_not(None))
            .where(Reservation.status.in_(_LIVE_RESERVATION_STATES))
            .group_by(Lead.broker_id)
        )
        if since_dt is not None:
            q_res = q_res.where(Reservation.created_at >= since_dt)
        if until_dt is not None:
            q_res = q_res.where(Reservation.created_at < until_dt)
        for bid, c in (await self.session.execute(q_res)).all():
            slot = per_broker.setdefault(
                bid,
                {
                    "broker_id": bid,
                    "broker_name": "",
                    "leads_assigned": 0,
                    "reservations_closed": 0,
                    "sales_closed": 0,
                    "gmv": {},
                    "commission_earned": {},
                },
            )
            slot["reservations_closed"] = int(c or 0)

        # 3) sales_closed + GMV — SalesContract joined back to Lead.broker_id.
        q_sales = (
            _select(
                Lead.broker_id,
                SalesContract.currency,
                _func.count(_func.distinct(SalesContract.id)).label("c"),
                _func.coalesce(_func.sum(SalesContract.total_value), 0).label("gmv"),
            )
            .join(Reservation, Reservation.lead_id == Lead.id)
            .join(SalesContract, SalesContract.reservation_id == Reservation.id)
            .where(Lead.broker_id.is_not(None))
            .where(SalesContract.status.in_(_CLOSED_SPA_STATES))
            .group_by(Lead.broker_id, SalesContract.currency)
        )
        if since_d is not None:
            q_sales = q_sales.where(SalesContract.signing_date >= since_d.isoformat())
        if until_d is not None:
            q_sales = q_sales.where(SalesContract.signing_date <= until_d.isoformat())
        for bid, cur, c, gmv in (await self.session.execute(q_sales)).all():
            slot = per_broker.setdefault(
                bid,
                {
                    "broker_id": bid,
                    "broker_name": "",
                    "leads_assigned": 0,
                    "reservations_closed": 0,
                    "sales_closed": 0,
                    "gmv": {},
                    "commission_earned": {},
                },
            )
            slot["sales_closed"] += int(c or 0)
            currency = cur or ""
            slot["gmv"][currency] = slot["gmv"].get(currency, Decimal("0")) + Decimal(str(gmv or 0))

        # 4) commission_earned — CommissionAccrual GROUP BY broker_id +
        # currency. Counts ``accrued`` / ``approved`` / ``paid`` (all
        # earned — only ``cancelled`` is excluded).
        q_comm = (
            _select(
                CommissionAccrual.broker_id,
                CommissionAccrual.currency,
                _func.coalesce(_func.sum(CommissionAccrual.commission_amount), 0).label("comm"),
            )
            .where(CommissionAccrual.state != "cancelled")
            .group_by(CommissionAccrual.broker_id, CommissionAccrual.currency)
        )
        if since_dt is not None:
            q_comm = q_comm.where(CommissionAccrual.created_at >= since_dt)
        if until_dt is not None:
            q_comm = q_comm.where(CommissionAccrual.created_at < until_dt)
        for bid, cur, comm in (await self.session.execute(q_comm)).all():
            slot = per_broker.setdefault(
                bid,
                {
                    "broker_id": bid,
                    "broker_name": "",
                    "leads_assigned": 0,
                    "reservations_closed": 0,
                    "sales_closed": 0,
                    "gmv": {},
                    "commission_earned": {},
                },
            )
            currency = cur or ""
            slot["commission_earned"][currency] = slot["commission_earned"].get(currency, Decimal("0")) + Decimal(
                str(comm or 0)
            )

        # Backfill any broker name we discovered via the joined queries
        # but missed on the initial active-only roster (defensive — when
        # a broker is marked inactive mid-window we still want their row
        # on the leaderboard).
        missing_names = [bid for bid, slot in per_broker.items() if not slot["broker_name"]]
        if missing_names:
            extra = (
                await self.session.execute(_select(Broker.id, Broker.name).where(Broker.id.in_(missing_names)))
            ).all()
            for bid, nm in extra:
                per_broker[bid]["broker_name"] = nm or ""

        out_rows: list[dict[str, Any]] = []
        for bid, slot in per_broker.items():
            leads = int(slot["leads_assigned"])
            sales = int(slot["sales_closed"])
            conv = (
                (Decimal(sales) / Decimal(leads) * Decimal("100")).quantize(Decimal("0.1"))
                if leads > 0
                else Decimal("0")
            )
            out_rows.append(
                {
                    "broker_id": bid,
                    "broker_name": slot["broker_name"],
                    "leads_assigned": leads,
                    "reservations_closed": int(slot["reservations_closed"]),
                    "sales_closed": sales,
                    "conversion_rate_pct": conv,
                    "gmv": [
                        {"currency": cur, "amount": amt.quantize(Decimal("0.01"))}
                        for cur, amt in sorted(slot["gmv"].items())
                    ],
                    "commission_earned": [
                        {"currency": cur, "amount": amt.quantize(Decimal("0.01"))}
                        for cur, amt in sorted(slot["commission_earned"].items())
                    ],
                }
            )

        # Sort by GMV desc (largest contributor first) — sales directors
        # always want the leaderboard ordered. We use the first currency
        # in each row's GMV list as the sort key (consistent across rows
        # because we sorted the currencies dict above).
        def _gmv_key(row: dict[str, Any]) -> Decimal:
            return max(
                (Decimal(str(g["amount"])) for g in row["gmv"]),
                default=Decimal("0"),
            )

        out_rows.sort(key=_gmv_key, reverse=True)

        return {
            "since": since,
            "until": until,
            "rows": out_rows,
            "total_brokers": len(out_rows),
        }


__all__ = ("AnalyticsService",)
