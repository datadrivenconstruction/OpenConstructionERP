# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍KPI formula registry - every system KPI as a registered Python function.

Each KPI:
    * Is registered with :func:`register_kpi(code)`
    * Returns a :class:`KPIComputation` (Decimal value + record count + breakdown)
    * Gracefully degrades to ``Decimal("0")`` with ``source_record_count=0``
      when its source module is missing or any query raises (``ImportError``
      / ``OperationalError``). The module is read-only across the platform
      and must never crash because an upstream module was uninstalled.

The registry is process-local. Custom KPIs registered by community
modules survive a hot reload of this file but not a worker restart -
modules should register inside their own ``on_startup`` hook.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from decimal import Decimal
from typing import Any, Awaitable, Callable

from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Portfolio access scoping (IDOR defence) ─────────────────────────────
# A portfolio-mode call (``project_id is None``) must not silently
# aggregate over every project in the deployment. The router resolves the
# caller's accessible project IDs via ``app.dependencies.accessible_project_ids``
# and threads the resulting ``allowed_project_ids`` set down here:
#
#   * ``None``        -> no restriction (admin, or a single-project call
#                        where ``verify_project_access`` already gated the id)
#   * non-empty set   -> restrict the portfolio aggregation to these projects
#   * empty set       -> the caller can reach no project, so the aggregation
#                        must yield nothing / zero (never "all rows")
#
# The restriction only applies in portfolio mode; a single-project call
# (``project_id`` set) is unaffected because it is already access-checked.


def _scope_portfolio(
    stmt: Any,
    project_column: Any,
    project_id: uuid.UUID | None,
    allowed_project_ids: set[uuid.UUID] | None,
) -> Any:
    """Restrict a portfolio query to the caller's accessible projects.

    No-op when ``project_id`` is set (single-project, already gated) or when
    ``allowed_project_ids`` is ``None`` (admin / unrestricted). An empty
    allowed set yields a guaranteed-false predicate so the query returns
    nothing rather than every project's rows.
    """
    if project_id is not None or allowed_project_ids is None:
        return stmt
    if not allowed_project_ids:
        return stmt.where(false())
    return stmt.where(project_column.in_(allowed_project_ids))


@dataclass
class KPIComputation:
    """‌⁠‍The shape every KPI formula returns."""

    value: Decimal = Decimal("0")
    unit: str = "ratio"
    source_record_count: int = 0
    breakdown: dict[str, Any] = field(default_factory=dict)


KPIFormula = Callable[..., Awaitable[KPIComputation]]

# Global registry - populated by @register_kpi decorators below.
KPI_FORMULAS: dict[str, KPIFormula] = {}

# Metadata for system KPIs - drives the seed step that writes KPIDefinition
# rows. Order must match @register_kpi declarations or seeding is wrong.
SYSTEM_KPI_META: dict[str, dict[str, Any]] = {}


def register_kpi(
    code: str,
    *,
    name: str | None = None,
    unit: str = "ratio",
    category: str = "operational",
    aggregation: str = "last",
    source_modules: list[str] | None = None,
    target_default: Decimal | None = None,
    description: str = "",
) -> Callable[[KPIFormula], KPIFormula]:
    """‌⁠‍Decorator registering a KPI formula in :data:`KPI_FORMULAS`.

    Also stores metadata used by :func:`bootstrap_system_kpis` when
    seeding the :class:`KPIDefinition` table on startup.
    """

    def decorator(fn: KPIFormula) -> KPIFormula:
        KPI_FORMULAS[code] = fn
        SYSTEM_KPI_META[code] = {
            "code": code,
            "name": name or code.replace("_", " ").title(),
            "description": description or (fn.__doc__ or "").strip().split("\n")[0],
            "formula_ref": code,
            "source_modules": source_modules or [],
            "unit": unit,
            "target_default": target_default,
            "aggregation": aggregation,
            "category": category,
            "is_system": True,
        }
        return fn

    return decorator


# ── Helpers ────────────────────────────────────────────────────────────


async def _safe_count(session: AsyncSession, query: Any) -> int:
    """Run ``COUNT(*)`` over a select, returning 0 on any failure."""
    try:
        result = await session.execute(query)
        rows = list(result.scalars().all())
        return len(rows)
    except Exception:
        logger.debug("KPI safe_count: query failed", exc_info=True)
        return 0


def _to_decimal(value: Any) -> Decimal:
    """Coerce anything to Decimal, returning 0 on failure."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator


# ── Currency / FX helpers ──────────────────────────────────────────────
# Money KPIs must never blend mixed currencies. Within a single project we
# convert each row's amount into the project's BASE currency using the
# project's ``fx_rates`` table (mirrors ``boq.service._project_fx_map`` /
# ``_position_total_in_base``). The ``rate`` is BASE units per 1 unit of
# foreign, so a foreign amount contributes ``amount * rate``. Across the
# whole portfolio (``project_id is None``) we deliberately do NOT collapse
# everything into one scalar - the breakdown carries a per-currency map so
# the UI can group by ISO code instead of presenting a meaningless sum.


def _fx_map(project: Any) -> dict[str, str]:
    """Project ``Project.fx_rates`` JSON list into ``{CODE: rate}``.

    Defensive against missing attribute / malformed rows - returns an
    empty dict on any error so callers can pass it through unguarded.
    """
    if project is None:
        return {}
    raw = getattr(project, "fx_rates", None)
    if not isinstance(raw, list):
        return {}
    out: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip().upper()
        rate = str(entry.get("rate") or "").strip()
        if code and rate:
            out[code] = rate
    return out


def _amount_in_base(
    amount: Decimal,
    currency_code: str | None,
    fx_map: dict[str, str] | None,
    base_currency: str,
) -> Decimal:
    """Convert one amount into the project BASE currency.

    Missing / matching currency → treated as base. A foreign currency with
    no FX rate is summed in its own units anyway (never zeroed) so a
    forgotten rate degrades visibly rather than silently dropping money -
    the caller surfaces the unconverted codes via :func:`_missing_fx_codes`.
    """
    base = (base_currency or "").strip().upper()
    code = (currency_code or "").strip().upper()
    if code and code != base and fx_map:
        fx = fx_map.get(code)
        if fx:
            converted = _to_decimal(fx)
            if converted > 0:
                return amount * converted
    return amount


async def _project_currency_and_fx(
    session: AsyncSession,
    project_id: uuid.UUID | None,
) -> tuple[str, dict[str, str]]:
    """Resolve a project's base currency + FX map.

    For a portfolio call (``project_id is None``) there is no single base
    currency, so an empty base ("") is returned and callers fall back to
    per-currency grouping.
    """
    if project_id is None:
        return "", {}
    try:
        from app.modules.projects.models import Project  # type: ignore

        proj = await session.get(Project, project_id)
        if proj is None:
            return "", {}
        base = str(getattr(proj, "currency", "") or "").strip().upper()
        return base, _fx_map(proj)
    except ImportError:
        return "", {}
    except Exception:
        logger.debug("project currency/fx probe failed", exc_info=True)
        return "", {}


def _add_currency_bucket(
    buckets: dict[str, Decimal],
    amount: Decimal,
    currency_code: str | None,
    fallback: str,
) -> None:
    """Accumulate ``amount`` into the per-ISO-code bucket map (portfolio mode)."""
    code = (currency_code or "").strip().upper() or (fallback or "").strip().upper()
    buckets[code] = buckets.get(code, Decimal("0")) + amount


def _missing_fx_codes(
    codes_seen: set[str],
    fx_map: dict[str, str],
    base_currency: str,
) -> list[str]:
    """Foreign currency codes encountered that have no FX rate to base."""
    base = (base_currency or "").strip().upper()
    have = {k.upper() for k in fx_map}
    return sorted(c for c in codes_seen if c and c != base and c not in have)


def _portfolio_money_breakdown(
    by_currency: dict[str, Decimal],
) -> tuple[Decimal, dict[str, Any]]:
    """Reduce a per-currency bucket map into a headline value + breakdown.

    Portfolio (``project_id is None``) money KPIs must never collapse mixed
    currencies into one blended scalar - there is no single base currency
    to convert into. Mirrors the cross-project rollup in
    ``projects.router.analytics_overview``:

        * the headline ``value`` is the DOMINANT currency's subtotal (the
          bucket with the largest absolute amount) so the tile still shows
          a real, attributable figure rather than an em-dash or a
          meaningless sum;
        * ``breakdown.currency`` carries that dominant bucket's ISO code so
          the UI renders e.g. ``"EUR 1.2M"`` not a bare number;
        * ``breakdown.by_currency`` is the full ``{CODE: amount-string}``
          map so the UI can render every per-currency subtotal;
        * ``breakdown.multi_currency`` is true when more than one currency
          is present, signalling the UI to show the "+ N other" /
          "multi-currency" hint and NOT treat the headline as a portfolio
          total.

    Empty input → ``(Decimal("0"), {"currency": ""})``. Amounts whose
    currency could not be resolved are kept under an explicit ``"UNKNOWN"``
    bucket (mirrors ``analytics_overview``) rather than silently dropped, so
    money never vanishes from the rollup.
    """
    buckets: dict[str, Decimal] = {}
    for code, amount in by_currency.items():
        key = code if code else "UNKNOWN"
        buckets[key] = buckets.get(key, Decimal("0")) + amount
    if not buckets:
        return Decimal("0"), {"currency": ""}
    # Dominant = largest by absolute magnitude; ties broken alphabetically
    # so the headline is deterministic across calls.
    dominant_code = max(
        sorted(buckets),
        key=lambda c: abs(buckets[c]),
    )
    breakdown: dict[str, Any] = {
        "currency": dominant_code,
        "by_currency": {code: str(amount) for code, amount in sorted(buckets.items())},
        "multi_currency": len(buckets) > 1,
    }
    return buckets[dominant_code], breakdown


def _parse_date(value: Any) -> _date | None:
    """Parse a stored date into a ``date``.

    Finance/procurement store dates as ``String(20)`` (ISO ``YYYY-MM-DD`` or
    full ISO timestamps), so a plain ``isinstance(value, date)`` guard treats
    every real row as "no date". Accept ``date`` / ``datetime`` instances and
    ISO strings; return ``None`` on anything unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Trim a time component / timezone if present, keep the date portion.
    candidate = text.replace("Z", "").split("T", 1)[0].split(" ", 1)[0]
    try:
        return _date.fromisoformat(candidate)
    except ValueError:
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None


# ── Financial KPIs ─────────────────────────────────────────────────────


# ── EVM core helpers ───────────────────────────────────────────────────


@dataclass
class EVMSnapshot:
    """The five EVM primitives + counts for any project (or portfolio).

    All Decimal values default to 0 so consumer KPIs can derive without
    re-querying. Returned by :func:`_evm_snapshot`.

    Portfolio mode (``project_id is None``): the scalar primitives still
    carry the cross-project sums for ratio KPIs (CPI/SPI/TCPI are
    currency-neutral so an aggregate ratio is meaningful), but the
    ``*_by_currency`` maps carry the per-currency subtotals so the
    currency-denominated KPIs (CV/SV/EAC/ETC/VAC) can group by ISO code
    instead of blending. In single-project mode the maps are empty and
    consumers use the (base-currency-converted) scalars directly.
    """

    bac: Decimal = Decimal("0")  # Budget at completion
    pv: Decimal = Decimal("0")  # Planned value (BCWS)
    ev: Decimal = Decimal("0")  # Earned value (BCWP)
    ac: Decimal = Decimal("0")  # Actual cost (ACWP)
    record_count: int = 0
    currency: str = ""  # Project base currency for the money primitives
    breakdown: dict[str, Any] = field(default_factory=dict)
    # Portfolio-mode only: each money primitive grouped by the owning
    # project's ISO currency. Empty in single-project mode.
    bac_by_currency: dict[str, Decimal] = field(default_factory=dict)
    pv_by_currency: dict[str, Decimal] = field(default_factory=dict)
    ev_by_currency: dict[str, Decimal] = field(default_factory=dict)
    ac_by_currency: dict[str, Decimal] = field(default_factory=dict)
    is_portfolio: bool = False


async def _evm_snapshot_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> EVMSnapshot:
    """Build the five EVM primitives for ONE project.

    Strategy:
        * BAC: project.budget OR Σ Task.planned_value (whichever is larger)
        * PV:  Σ Task.planned_value
        * EV:  Σ Task.earned_value (calculated upstream as % complete × BAC)
        * AC:  Σ finance.Payment.amount + Σ procurement.PurchaseOrder.amount_total
               (every foreign-currency row converted into the project's base
               currency via ``Project.fx_rates`` before summing - no mixed-
               currency blending).

    Note: there is no ``finance.Expense`` model on this platform; actual
    cost is sourced from settled payments plus committed purchase orders.
    """
    snap = EVMSnapshot()
    base_currency, fx_map = await _project_currency_and_fx(session, project_id)
    snap.currency = base_currency
    seen_codes: set[str] = set()
    # Tasks → PV + EV + count
    try:
        from app.modules.tasks.models import Task  # type: ignore

        stmt = select(Task).where(Task.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            pv = _to_decimal(getattr(row, "planned_value", 0))
            ev = _to_decimal(getattr(row, "earned_value", 0))
            snap.pv += pv
            snap.ev += ev
            snap.record_count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("evm: tasks probe failed", exc_info=True)

    # Project budget → BAC
    try:
        from app.modules.projects.models import Project  # type: ignore

        proj = await session.get(Project, project_id)
        if proj is not None:
            snap.bac = max(
                _to_decimal(getattr(proj, "budget", None)),
                _to_decimal(getattr(proj, "contract_value", None)),
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("evm: project probe failed", exc_info=True)
    # CONN-78: when neither budget nor contract value is set, the cost
    # baseline (BAC) is the priced estimate - the sum of the project's BOQ
    # position totals. This ties the executive cost spine back to the
    # take-off / estimating work instead of collapsing to Σ planned_value.
    # Each position is converted into the project base currency via the
    # same fx_map (mirrors ``boq.service._position_total_in_base``), and the
    # baseline source is recorded so the UI can offer a "View BOQ baseline"
    # drill on the cost tile.
    baseline_source = "budget" if snap.bac > 0 else ""
    if snap.bac == 0:
        boq_baseline = await _boq_baseline_for_project(session, project_id, fx_map, base_currency)
        if boq_baseline > 0:
            snap.bac = boq_baseline
            baseline_source = "boq"
    if snap.bac == 0:
        snap.bac = snap.pv  # Fall back to Σ planned_value
        if snap.bac > 0:
            baseline_source = "planned_value"

    # finance.Payment → AC (settled actual cost)
    try:
        from app.modules.finance.models import Invoice, Payment  # type: ignore

        # Payment has no project_id - it hangs off the Invoice, so scope
        # via the parent invoice's project_id.
        stmt = (
            select(Payment)
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .where(
                Invoice.project_id == project_id,
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            amt = _to_decimal(getattr(row, "amount", 0))
            code = str(getattr(row, "currency_code", "") or "")
            if code:
                seen_codes.add(code.upper())
            snap.ac += _amount_in_base(amt, code, fx_map, base_currency)
            snap.record_count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("evm: finance payment probe failed", exc_info=True)

    # procurement.PurchaseOrder → AC (committed cost)
    try:
        from app.modules.procurement.models import PurchaseOrder  # type: ignore

        stmt = select(PurchaseOrder).where(PurchaseOrder.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            amt = _to_decimal(getattr(row, "amount_total", 0))
            code = str(getattr(row, "currency_code", "") or "")
            if code:
                seen_codes.add(code.upper())
            snap.ac += _amount_in_base(amt, code, fx_map, base_currency)
            snap.record_count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("evm: procurement probe failed", exc_info=True)

    snap.breakdown = {
        "bac": str(snap.bac),
        "pv": str(snap.pv),
        "ev": str(snap.ev),
        "ac": str(snap.ac),
        "currency": base_currency,
        # Where BAC came from: "budget" (project budget/contract value),
        # "boq" (priced estimate fallback - CONN-78) or "planned_value"
        # (Σ task planned_value). "" when there is no baseline at all.
        "baseline_source": baseline_source,
    }
    missing = _missing_fx_codes(seen_codes, fx_map, base_currency)
    if missing:
        snap.breakdown["missing_fx_codes"] = missing
    return snap


async def _boq_baseline_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    fx_map: dict[str, str],
    base_currency: str,
) -> Decimal:
    """Sum a project's priced BOQ position totals in the base currency.

    The cost baseline of last resort (CONN-78): when a project carries no
    budget / contract value, its estimate is the sum of every BOQ
    position's ``total``. Each total is stored in the position's home
    currency (carried on ``metadata_.currency`` / ``position_currency`` /
    ``project_currency``, mirroring ``boq.service._position_currency``);
    foreign rows are converted into the project base currency via the same
    fx_map before summing so mixed-currency estimates never blend.

    Degrades to ``Decimal("0")`` when the BOQ module is absent or any query
    fails - this is purely a read-side fallback.
    """
    total = Decimal("0")
    try:
        from app.modules.boq.models import BOQ, Position  # type: ignore

        stmt = select(Position).join(BOQ, Position.boq_id == BOQ.id).where(BOQ.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            meta = row.metadata_ if isinstance(getattr(row, "metadata_", None), dict) else {}
            code = ""
            for key in ("currency", "position_currency", "project_currency"):
                val = meta.get(key)
                if isinstance(val, str) and val.strip():
                    code = val.strip().upper()
                    break
            amt = _to_decimal(getattr(row, "total", 0))
            total += _amount_in_base(amt, code, fx_map, base_currency)
    except ImportError:
        return Decimal("0")
    except Exception:
        logger.debug("evm: boq baseline probe failed", exc_info=True)
        return Decimal("0")
    return total


async def _evm_snapshot_portfolio(
    session: AsyncSession,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> EVMSnapshot:
    """Aggregate per-project EVM snapshots into a portfolio snapshot.

    Each project's money primitives are computed in its OWN base currency
    (so within-project FX conversion still applies via
    ``_evm_snapshot_for_project``), then bucketed by that project's ISO
    currency - mixed currencies are NEVER summed into one scalar.

    The scalar primitives (``bac/pv/ev/ac``) still carry the raw
    cross-project sums so the currency-neutral ratio KPIs (CPI = EV/AC,
    SPI = EV/PV, TCPI) stay meaningful - a ratio of two same-shaped sums
    is dimensionless even across currencies (it is a blended performance
    index, the standard portfolio EVM reading). The currency-denominated
    KPIs (CV/SV/EAC/ETC/VAC) instead read the ``*_by_currency`` maps and
    group by ISO code.

    ``allowed_project_ids`` scopes the fan-out to the caller's accessible
    projects (IDOR defence): ``None`` aggregates every project (admin),
    a set restricts to those ids, and an empty set yields an empty snapshot.
    """
    snap = EVMSnapshot(is_portfolio=True)
    if allowed_project_ids is not None and not allowed_project_ids:
        # Caller can reach no project - never fall back to "all projects".
        return snap
    try:
        from app.modules.projects.models import Project  # type: ignore

        # Select only the PK column - a full ``select(Project)`` would
        # eager-load ``Project``'s ``lazy="selectin"`` relationships (WBS,
        # team, …), which is both wasteful here and brittle under partial
        # test schemas. We only need each project's id to fan out.
        stmt = select(Project.id)
        if allowed_project_ids is not None:
            stmt = stmt.where(Project.id.in_(allowed_project_ids))
        project_ids = (await session.execute(stmt)).scalars().all()
    except ImportError:
        return snap
    except Exception:
        logger.debug("evm portfolio: project list failed", exc_info=True)
        return snap

    missing_codes: set[str] = set()
    for pid in project_ids:
        per = await _evm_snapshot_for_project(session, pid)
        if per.record_count == 0 and per.bac == 0:
            continue
        code = (per.currency or "").strip().upper() or "UNKNOWN"
        snap.bac += per.bac
        snap.pv += per.pv
        snap.ev += per.ev
        snap.ac += per.ac
        snap.record_count += per.record_count
        snap.bac_by_currency[code] = snap.bac_by_currency.get(code, Decimal("0")) + per.bac
        snap.pv_by_currency[code] = snap.pv_by_currency.get(code, Decimal("0")) + per.pv
        snap.ev_by_currency[code] = snap.ev_by_currency.get(code, Decimal("0")) + per.ev
        snap.ac_by_currency[code] = snap.ac_by_currency.get(code, Decimal("0")) + per.ac
        for mc in per.breakdown.get("missing_fx_codes", []) or []:
            missing_codes.add(mc)

    snap.breakdown = {
        "bac": str(snap.bac),
        "pv": str(snap.pv),
        "ev": str(snap.ev),
        "ac": str(snap.ac),
        "currency": "",
        "multi_currency": len({c for c in snap.ac_by_currency if c} | {c for c in snap.pv_by_currency if c}) > 1,
        "ac_by_currency": {c: str(v) for c, v in sorted(snap.ac_by_currency.items())},
        "pv_by_currency": {c: str(v) for c, v in sorted(snap.pv_by_currency.items())},
        "ev_by_currency": {c: str(v) for c, v in sorted(snap.ev_by_currency.items())},
        "bac_by_currency": {c: str(v) for c, v in sorted(snap.bac_by_currency.items())},
    }
    if missing_codes:
        snap.breakdown["missing_fx_codes"] = sorted(missing_codes)
    return snap


async def _evm_snapshot(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> EVMSnapshot:
    """Build EVM primitives for one project, or aggregate the portfolio.

    Single-project (``project_id`` set): every money row is converted into
    that project's base currency via its ``fx_rates`` table - see
    :func:`_evm_snapshot_for_project`.

    Portfolio (``project_id is None``): per-project snapshots are bucketed
    by each project's own ISO currency, never blended - see
    :func:`_evm_snapshot_portfolio`. ``allowed_project_ids`` scopes the
    portfolio fan-out to the caller's accessible projects (IDOR defence).
    """
    if project_id is None:
        return await _evm_snapshot_portfolio(session, allowed_project_ids)
    return await _evm_snapshot_for_project(session, project_id)


def _evm_currency_result(
    snap: EVMSnapshot,
    *,
    scalar_value: Decimal,
    per_currency: dict[str, Decimal],
    extra_breakdown: dict[str, Any] | None = None,
) -> KPIComputation:
    """Build a currency-unit :class:`KPIComputation` from an EVM snapshot.

    Single-project mode → headline value is ``scalar_value`` (already in
    the project base currency) and ``breakdown.currency`` is that base.

    Portfolio mode → headline value is the dominant currency's subtotal and
    ``breakdown`` carries the ``by_currency`` map + ``multi_currency`` flag,
    so the UI groups by ISO code instead of presenting the blended scalar.
    """
    extra = dict(extra_breakdown or {})
    if not snap.is_portfolio:
        breakdown = {**snap.breakdown, **extra}
        return KPIComputation(
            value=scalar_value,
            unit="currency",
            source_record_count=snap.record_count,
            breakdown=breakdown,
        )
    value, money_breakdown = _portfolio_money_breakdown(per_currency)
    breakdown = {**snap.breakdown, **money_breakdown, **extra}
    return KPIComputation(
        value=value,
        unit="currency",
        source_record_count=snap.record_count,
        breakdown=breakdown,
    )


@register_kpi(
    "cpi",
    name="Cost Performance Index",
    unit="ratio",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    target_default=Decimal("1.0"),
    description="EV / AC (PMBOK). > 1.0 = under budget; < 1.0 = over budget.",
)
async def cpi_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Cost Performance Index = EV / AC."""
    snap = await _evm_snapshot(session, project_id, allowed_project_ids)
    value = _safe_div(snap.ev, snap.ac) if snap.ac > 0 else Decimal("0")
    return KPIComputation(
        value=value,
        unit="ratio",
        source_record_count=snap.record_count,
        breakdown=snap.breakdown,
    )


@register_kpi(
    "spi",
    name="Schedule Performance Index",
    unit="ratio",
    category="schedule",
    source_modules=["tasks"],
    target_default=Decimal("1.0"),
    description="EV / PV (PMBOK). > 1.0 = ahead of schedule.",
)
async def spi_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Schedule Performance Index = EV / PV."""
    snap = await _evm_snapshot(session, project_id, allowed_project_ids)
    value = _safe_div(snap.ev, snap.pv) if snap.pv > 0 else Decimal("0")
    return KPIComputation(
        value=value,
        unit="ratio",
        source_record_count=snap.record_count,
        breakdown=snap.breakdown,
    )


# ── Additional EVM KPIs (per PMBOK 7) ──────────────────────────────────


@register_kpi(
    "cv",
    name="Cost Variance",
    unit="currency",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    target_default=Decimal("0"),
    description="EV - AC. Negative = over budget.",
)
async def cv_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id, allowed_project_ids)
    per_currency = {
        code: snap.ev_by_currency.get(code, Decimal("0")) - snap.ac_by_currency.get(code, Decimal("0"))
        for code in set(snap.ev_by_currency) | set(snap.ac_by_currency)
    }
    return _evm_currency_result(
        snap,
        scalar_value=snap.ev - snap.ac,
        per_currency=per_currency,
    )


@register_kpi(
    "sv",
    name="Schedule Variance",
    unit="currency",
    category="schedule",
    source_modules=["tasks", "projects"],
    target_default=Decimal("0"),
    description="EV - PV. Negative = behind schedule.",
)
async def sv_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id, allowed_project_ids)
    per_currency = {
        code: snap.ev_by_currency.get(code, Decimal("0")) - snap.pv_by_currency.get(code, Decimal("0"))
        for code in set(snap.ev_by_currency) | set(snap.pv_by_currency)
    }
    return _evm_currency_result(
        snap,
        scalar_value=snap.ev - snap.pv,
        per_currency=per_currency,
    )


# Pure helper shared by the EAC / ETC / VAC KPI formulas below. NOT a
# registered KPI itself - the ``@register_kpi("eac", ...)`` decorator lives on
# ``eac_kpi``, which the registry invokes with ``(session, project_id=...,
# allowed_project_ids=..., **)``. This helper takes only the four EVM
# primitives, so it must stay undecorated.
def _eac_from_primitives(bac: Decimal, pv: Decimal, ev: Decimal, ac: Decimal) -> Decimal:
    """EAC = AC + (BAC - EV) / (CPI * SPI). Falls back to BAC when a
    performance index is undefined (no actuals / no progress yet)."""
    if ac == 0 or ev == 0 or pv == 0:
        return bac
    cpi = _safe_div(ev, ac)
    spi = _safe_div(ev, pv)
    denom = cpi * spi
    if denom == 0:
        return ac
    return ac + _safe_div(bac - ev, denom)


@register_kpi(
    "eac",
    name="Estimate at Completion",
    unit="currency",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    description=("AC + (BAC - EV) / (CPI * SPI) - assumes both perf indices persist (common in construction)."),
)
async def eac_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id, allowed_project_ids)
    scalar_eac = _eac_from_primitives(snap.bac, snap.pv, snap.ev, snap.ac)
    cpi = _safe_div(snap.ev, snap.ac) if snap.ac > 0 else Decimal("0")
    spi = _safe_div(snap.ev, snap.pv) if snap.pv > 0 else Decimal("0")
    # Portfolio: EAC is non-linear, so compute it per-currency from each
    # bucket's own primitives rather than from the blended scalars.
    per_currency = {
        code: _eac_from_primitives(
            snap.bac_by_currency.get(code, Decimal("0")),
            snap.pv_by_currency.get(code, Decimal("0")),
            snap.ev_by_currency.get(code, Decimal("0")),
            snap.ac_by_currency.get(code, Decimal("0")),
        )
        for code in (
            set(snap.bac_by_currency) | set(snap.pv_by_currency) | set(snap.ev_by_currency) | set(snap.ac_by_currency)
        )
    }
    return _evm_currency_result(
        snap,
        scalar_value=scalar_eac,
        per_currency=per_currency,
        extra_breakdown={"cpi": str(cpi), "spi": str(spi)},
    )


@register_kpi(
    "etc",
    name="Estimate to Complete",
    unit="currency",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    description="EAC - AC. Money still needed to finish.",
)
async def etc_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id, allowed_project_ids)
    scalar_eac = _eac_from_primitives(snap.bac, snap.pv, snap.ev, snap.ac)
    # ETC = EAC - AC, per currency in portfolio mode.
    per_currency = {
        code: _eac_from_primitives(
            snap.bac_by_currency.get(code, Decimal("0")),
            snap.pv_by_currency.get(code, Decimal("0")),
            snap.ev_by_currency.get(code, Decimal("0")),
            snap.ac_by_currency.get(code, Decimal("0")),
        )
        - snap.ac_by_currency.get(code, Decimal("0"))
        for code in (
            set(snap.bac_by_currency) | set(snap.pv_by_currency) | set(snap.ev_by_currency) | set(snap.ac_by_currency)
        )
    }
    return _evm_currency_result(
        snap,
        scalar_value=scalar_eac - snap.ac,
        per_currency=per_currency,
        extra_breakdown={"eac": str(scalar_eac)},
    )


@register_kpi(
    "vac",
    name="Variance at Completion",
    unit="currency",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    description="BAC - EAC. Negative = expected to finish over budget.",
)
async def vac_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id, allowed_project_ids)
    scalar_eac = _eac_from_primitives(snap.bac, snap.pv, snap.ev, snap.ac)
    # VAC = BAC - EAC, per currency in portfolio mode.
    per_currency = {
        code: snap.bac_by_currency.get(code, Decimal("0"))
        - _eac_from_primitives(
            snap.bac_by_currency.get(code, Decimal("0")),
            snap.pv_by_currency.get(code, Decimal("0")),
            snap.ev_by_currency.get(code, Decimal("0")),
            snap.ac_by_currency.get(code, Decimal("0")),
        )
        for code in (
            set(snap.bac_by_currency) | set(snap.pv_by_currency) | set(snap.ev_by_currency) | set(snap.ac_by_currency)
        )
    }
    return _evm_currency_result(
        snap,
        scalar_value=snap.bac - scalar_eac,
        per_currency=per_currency,
        extra_breakdown={"eac": str(scalar_eac)},
    )


@register_kpi(
    "tcpi",
    name="To-Complete Performance Index",
    unit="ratio",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    description="(BAC - EV) / (BAC - AC). CPI required for the remaining work.",
)
async def tcpi_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id, allowed_project_ids)
    denom = snap.bac - snap.ac
    if denom <= 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="ratio",
            source_record_count=snap.record_count,
            breakdown=snap.breakdown,
        )
    value = _safe_div(snap.bac - snap.ev, denom)
    return KPIComputation(
        value=value,
        unit="ratio",
        source_record_count=snap.record_count,
        breakdown=snap.breakdown,
    )


@register_kpi(
    "procurement_savings",
    name="Procurement Savings",
    unit="percent",
    category="financial",
    source_modules=["procurement"],
    description="(Budgeted - actual) / budgeted on POs.",
)
async def procurement_savings_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Procurement savings = (budgeted - actual) / budgeted.

    Actual is the committed PO value (``PurchaseOrder.amount_total``).
    Budgeted is the pre-order estimate carried on the linked material
    requisition lines (``MaterialRequisitionItem.extended_cost``) - the
    requisition is the baseline a PO is raised against. All amounts are
    converted into the project base currency via ``Project.fx_rates``
    before the savings ratio is taken so mixed-currency POs never blend.
    """
    budgeted = Decimal("0")
    actual = Decimal("0")
    count = 0
    base_currency, fx_map = await _project_currency_and_fx(session, project_id)
    seen_codes: set[str] = set()
    # Map requisition.po_id → Σ requisition item extended_cost (the budget
    # baseline the PO was raised against), converted to base currency.
    budget_by_po: dict[Any, Decimal] = {}
    try:
        from app.modules.procurement.models import (  # type: ignore
            MaterialRequisition,
            MaterialRequisitionItem,
        )

        req_stmt = select(MaterialRequisition).where(MaterialRequisition.po_id.is_not(None))
        if project_id is not None:
            req_stmt = req_stmt.where(MaterialRequisition.project_id == project_id)
        req_stmt = _scope_portfolio(req_stmt, MaterialRequisition.project_id, project_id, allowed_project_ids)
        reqs = (await session.execute(req_stmt)).scalars().all()
        for req in reqs:
            item_stmt = select(MaterialRequisitionItem).where(
                MaterialRequisitionItem.requisition_id == req.id,
            )
            items = (await session.execute(item_stmt)).scalars().all()
            req_budget = Decimal("0")
            for item in items:
                amt = _to_decimal(getattr(item, "extended_cost", 0))
                code = str(getattr(item, "currency_code", "") or "")
                if code:
                    seen_codes.add(code.upper())
                req_budget += _amount_in_base(amt, code, fx_map, base_currency)
            budget_by_po[req.po_id] = budget_by_po.get(req.po_id, Decimal("0")) + req_budget
    except ImportError:
        pass
    except Exception:
        logger.debug("procurement_savings: requisition probe failed", exc_info=True)

    try:
        from app.modules.procurement.models import PurchaseOrder  # type: ignore

        stmt = select(PurchaseOrder)
        if project_id is not None:
            stmt = stmt.where(PurchaseOrder.project_id == project_id)
        stmt = _scope_portfolio(stmt, PurchaseOrder.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            po_budget = budget_by_po.get(row.id)
            if po_budget is None or po_budget <= 0:
                # No requisition baseline → cannot compute savings for this PO.
                continue
            amt = _to_decimal(getattr(row, "amount_total", 0))
            code = str(getattr(row, "currency_code", "") or "")
            if code:
                seen_codes.add(code.upper())
            actual += _amount_in_base(amt, code, fx_map, base_currency)
            budgeted += po_budget
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("procurement_savings: probe failed", exc_info=True)

    if budgeted <= 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=count,
        )
    pct = (budgeted - actual) / budgeted * Decimal("100")
    breakdown: dict[str, Any] = {
        "budgeted": str(budgeted),
        "actual": str(actual),
        "currency": base_currency,
    }
    missing = _missing_fx_codes(seen_codes, fx_map, base_currency)
    if missing:
        breakdown["missing_fx_codes"] = missing
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=count,
        breakdown=breakdown,
    )


@register_kpi(
    "change_order_ratio",
    name="Change Order Ratio",
    unit="percent",
    category="financial",
    source_modules=["changeorders"],
    description="Total CO value / original contract value.",
)
async def change_order_ratio_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    co_value = Decimal("0")
    count = 0
    base_currency, fx_map = await _project_currency_and_fx(session, project_id)
    seen_codes: set[str] = set()
    try:
        from app.modules.changeorders.models import ChangeOrder  # type: ignore

        stmt = select(ChangeOrder)
        if project_id is not None:
            stmt = stmt.where(ChangeOrder.project_id == project_id)
        stmt = _scope_portfolio(stmt, ChangeOrder.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            # The approved figure is authoritative once a CO is signed off;
            # before that, ``cost_impact`` carries the proposed delta.
            amt = _to_decimal(
                getattr(row, "approved_amount", None)
                if getattr(row, "approved_amount", None) is not None
                else getattr(row, "cost_impact", 0),
            )
            code = str(getattr(row, "currency", "") or "")
            if code:
                seen_codes.add(code.upper())
            co_value += _amount_in_base(amt, code, fx_map, base_currency)
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("change_order_ratio: probe failed", exc_info=True)

    contract_value = Decimal("0")
    try:
        from app.modules.projects.models import Project  # type: ignore

        if project_id is not None:
            proj = await session.get(Project, project_id)
            if proj is not None:
                contract_value = _to_decimal(
                    getattr(proj, "contract_value", None) or getattr(proj, "budget", 0),
                )
    except ImportError:
        pass
    except Exception:
        logger.debug("change_order_ratio: project probe failed", exc_info=True)

    if contract_value <= 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=count,
        )
    pct = co_value / contract_value * Decimal("100")
    breakdown: dict[str, Any] = {
        "change_order_total": str(co_value),
        "contract_value": str(contract_value),
        "currency": base_currency,
    }
    missing = _missing_fx_codes(seen_codes, fx_map, base_currency)
    if missing:
        breakdown["missing_fx_codes"] = missing
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=count,
        breakdown=breakdown,
    )


@register_kpi(
    "cash_in_30d",
    name="Cash Inflow (30d)",
    unit="currency",
    category="financial",
    source_modules=["finance"],
    description="Projected cash inflow over the next 30 days.",
)
async def cash_in_30d_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Projected receivable cash due within the next 30 days.

    Outstanding = ``Invoice.amount_total`` minus the sum of settled
    ``Payment.amount`` for that invoice. Only ``receivable`` invoices count
    as inflow.

    Single-project mode: foreign-currency invoices are converted into the
    project base currency via ``Project.fx_rates`` before summing.

    Portfolio mode (``project_id is None``): there is no single base
    currency, so amounts are grouped by each invoice's own ``currency_code``
    and the headline ``value`` is the dominant currency's subtotal - never a
    blended cross-currency scalar. The full per-currency map and the
    ``multi_currency`` flag are returned in ``breakdown``.
    """
    total = Decimal("0")
    count = 0
    today = datetime.now(UTC).date()
    horizon = today + timedelta(days=30)
    base_currency, fx_map = await _project_currency_and_fx(session, project_id)
    is_portfolio = project_id is None
    by_currency: dict[str, Decimal] = {}
    seen_codes: set[str] = set()
    try:
        from app.modules.finance.models import Invoice  # type: ignore

        stmt = select(Invoice).where(Invoice.invoice_direction == "receivable")
        if project_id is not None:
            stmt = stmt.where(Invoice.project_id == project_id)
        stmt = _scope_portfolio(stmt, Invoice.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            due = _parse_date(getattr(row, "due_date", None))
            # No due date → due immediately (count it); else only within horizon.
            if due is not None and due > horizon:
                continue
            gross = _to_decimal(getattr(row, "amount_total", 0))
            paid = sum(
                (_to_decimal(getattr(p, "amount", 0)) for p in getattr(row, "payments", []) or []),
                Decimal("0"),
            )
            outstanding = gross - paid
            if outstanding <= 0:
                continue
            code = str(getattr(row, "currency_code", "") or "")
            if code:
                seen_codes.add(code.upper())
            if is_portfolio:
                _add_currency_bucket(by_currency, outstanding, code, "")
            else:
                total += _amount_in_base(outstanding, code, fx_map, base_currency)
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("cash_in_30d: probe failed", exc_info=True)
    if is_portfolio:
        value, breakdown = _portfolio_money_breakdown(by_currency)
    else:
        value = total
        breakdown = {"currency": base_currency}
    missing = _missing_fx_codes(seen_codes, fx_map, base_currency)
    if missing:
        breakdown["missing_fx_codes"] = missing
    return KPIComputation(
        value=value,
        unit="currency",
        source_record_count=count,
        breakdown=breakdown,
    )


@register_kpi(
    "cash_out_30d",
    name="Cash Outflow (30d)",
    unit="currency",
    category="financial",
    source_modules=["finance"],
    description="Projected cash outflow over the next 30 days.",
)
async def cash_out_30d_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Projected cash outflow within the next 30 days.

    There is no ``finance.Expense`` model on this platform, so outflow is
    sourced from outstanding ``payable`` invoices (amount_total minus
    settled payments) plus committed purchase orders falling due within the
    horizon.

    Single-project mode: all amounts are converted into the project base
    currency via ``Project.fx_rates`` before summing.

    Portfolio mode (``project_id is None``): amounts are grouped by each
    row's own ``currency_code`` and the headline ``value`` is the dominant
    currency's subtotal - never a blended cross-currency scalar. The full
    per-currency map and the ``multi_currency`` flag are returned in
    ``breakdown``.
    """
    total = Decimal("0")
    count = 0
    today = datetime.now(UTC).date()
    horizon = today + timedelta(days=30)
    base_currency, fx_map = await _project_currency_and_fx(session, project_id)
    is_portfolio = project_id is None
    by_currency: dict[str, Decimal] = {}
    seen_codes: set[str] = set()

    # Outstanding payable invoices.
    try:
        from app.modules.finance.models import Invoice  # type: ignore

        stmt = select(Invoice).where(Invoice.invoice_direction == "payable")
        if project_id is not None:
            stmt = stmt.where(Invoice.project_id == project_id)
        stmt = _scope_portfolio(stmt, Invoice.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            due = _parse_date(getattr(row, "due_date", None))
            if due is not None and due > horizon:
                continue
            gross = _to_decimal(getattr(row, "amount_total", 0))
            paid = sum(
                (_to_decimal(getattr(p, "amount", 0)) for p in getattr(row, "payments", []) or []),
                Decimal("0"),
            )
            outstanding = gross - paid
            if outstanding <= 0:
                continue
            code = str(getattr(row, "currency_code", "") or "")
            if code:
                seen_codes.add(code.upper())
            if is_portfolio:
                _add_currency_bucket(by_currency, outstanding, code, "")
            else:
                total += _amount_in_base(outstanding, code, fx_map, base_currency)
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("cash_out_30d: invoice probe failed", exc_info=True)

    # Committed purchase orders due within the horizon (not yet completed).
    try:
        from app.modules.procurement.models import PurchaseOrder  # type: ignore

        stmt = select(PurchaseOrder)
        if project_id is not None:
            stmt = stmt.where(PurchaseOrder.project_id == project_id)
        stmt = _scope_portfolio(stmt, PurchaseOrder.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            status_val = (getattr(row, "status", "") or "").lower()
            if status_val in ("completed", "cancelled", "closed", "received"):
                continue
            due = _parse_date(getattr(row, "delivery_date", None)) or _parse_date(
                getattr(row, "issue_date", None),
            )
            if due is not None and due > horizon:
                continue
            amt = _to_decimal(getattr(row, "amount_total", 0))
            if amt <= 0:
                continue
            code = str(getattr(row, "currency_code", "") or "")
            if code:
                seen_codes.add(code.upper())
            if is_portfolio:
                _add_currency_bucket(by_currency, amt, code, "")
            else:
                total += _amount_in_base(amt, code, fx_map, base_currency)
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("cash_out_30d: procurement probe failed", exc_info=True)

    if is_portfolio:
        value, breakdown = _portfolio_money_breakdown(by_currency)
    else:
        value = total
        breakdown = {"currency": base_currency}
    missing = _missing_fx_codes(seen_codes, fx_map, base_currency)
    if missing:
        breakdown["missing_fx_codes"] = missing
    return KPIComputation(
        value=value,
        unit="currency",
        source_record_count=count,
        breakdown=breakdown,
    )


@register_kpi(
    "dso",
    name="Days Sales Outstanding",
    unit="days",
    category="financial",
    source_modules=["finance"],
    description="Average days from invoice issue to payment.",
)
async def dso_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Average days from a receivable invoice date to its last payment.

    The Invoice model has no ``issue_date``/``paid_at`` columns - issue is
    ``invoice_date`` and settlement dates live on the ``Payment`` relation.
    Only ``receivable`` invoices that have at least one payment contribute.
    """
    total_days = Decimal("0")
    count = 0
    try:
        from app.modules.finance.models import Invoice  # type: ignore

        stmt = select(Invoice).where(Invoice.invoice_direction == "receivable")
        if project_id is not None:
            stmt = stmt.where(Invoice.project_id == project_id)
        stmt = _scope_portfolio(stmt, Invoice.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            issued = _parse_date(getattr(row, "invoice_date", None))
            if issued is None:
                continue
            payment_dates = [
                pd
                for p in getattr(row, "payments", []) or []
                if (pd := _parse_date(getattr(p, "payment_date", None))) is not None
            ]
            if not payment_dates:
                continue
            # Settlement = the most recent payment against the invoice.
            settled = max(payment_dates)
            delta = (settled - issued).days
            total_days += Decimal(delta)
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("dso: probe failed", exc_info=True)

    avg = _safe_div(total_days, Decimal(count)) if count > 0 else Decimal("0")
    return KPIComputation(
        value=avg,
        unit="days",
        source_record_count=count,
    )


# ── Quality KPIs ───────────────────────────────────────────────────────


@register_kpi(
    "first_pass_yield",
    name="First Pass Yield",
    unit="percent",
    category="quality",
    source_modules=["inspections", "ncr"],
    target_default=Decimal("95"),
    description="Passed inspections / total inspections.",
)
async def first_pass_yield_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    total = 0
    passed = 0
    try:
        from app.modules.inspections.models import QualityInspection  # type: ignore

        stmt = select(QualityInspection)
        if project_id is not None:
            stmt = stmt.where(QualityInspection.project_id == project_id)
        stmt = _scope_portfolio(stmt, QualityInspection.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total += 1
            # "Passed" reads from the dedicated ``result`` field first (the
            # inspection outcome), falling back to ``status`` for rows that
            # never recorded a separate result.
            outcome = (getattr(row, "result", "") or getattr(row, "status", "") or "").lower()
            if outcome in ("passed", "pass", "approved", "completed", "ok"):
                passed += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("first_pass_yield: probe failed", exc_info=True)

    if total == 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=0,
        )
    pct = Decimal(passed) / Decimal(total) * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=total,
        breakdown={"passed": passed, "total": total},
    )


@register_kpi(
    "copq",
    name="Cost of Poor Quality",
    unit="currency",
    category="quality",
    source_modules=["ncr"],
    description="Sum of NCR cost impact.",
)
async def copq_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Sum of NCR cost impact, currency-honest in both modes.

    ``NCR.cost_impact`` is recorded in the owning project's currency (the
    model has no per-row currency column).

    Single-project mode: the sum is wholly in that project's base currency,
    so the headline ``value`` is that sum and ``breakdown.currency`` is its
    ISO code.

    Portfolio mode (``project_id is None``): NCRs from projects in different
    currencies must NOT be blended into one scalar. We group ``cost_impact``
    by each project's own base currency; the headline ``value`` is the
    dominant currency's subtotal and ``breakdown`` carries the full
    ``by_currency`` map plus a ``multi_currency`` flag so the UI groups by
    ISO code instead of presenting a meaningless sum.
    """
    count = 0
    base_currency, _fx_unused = await _project_currency_and_fx(session, project_id)
    is_portfolio = project_id is None
    single_total = Decimal("0")
    # Portfolio mode: group by each project's own currency.
    by_currency: dict[str, Decimal] = {}
    project_currency_cache: dict[uuid.UUID, str] = {}
    try:
        from app.modules.ncr.models import NCR  # type: ignore
        from app.modules.projects.models import Project  # type: ignore

        stmt = select(NCR)
        if project_id is not None:
            stmt = stmt.where(NCR.project_id == project_id)
        stmt = _scope_portfolio(stmt, NCR.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            amt = _to_decimal(getattr(row, "cost_impact", None))
            count += 1
            if is_portfolio:
                pid = getattr(row, "project_id", None)
                code = ""
                if pid is not None:
                    code = project_currency_cache.get(pid, "")
                    if not code:
                        proj = await session.get(Project, pid)
                        code = str(getattr(proj, "currency", "") or "").strip().upper() if proj else ""
                        project_currency_cache[pid] = code
                _add_currency_bucket(by_currency, amt, code, "")
            else:
                single_total += amt
    except ImportError:
        pass
    except Exception:
        logger.debug("copq: probe failed", exc_info=True)

    if is_portfolio:
        value, breakdown = _portfolio_money_breakdown(by_currency)
    else:
        value = single_total
        breakdown = {"currency": base_currency}
    return KPIComputation(
        value=value,
        unit="currency",
        source_record_count=count,
        breakdown=breakdown,
    )


@register_kpi(
    "punch_close_rate",
    name="Punch List Close Rate",
    unit="percent",
    category="quality",
    source_modules=["punchlist"],
    description="Closed punch items / total.",
)
async def punch_close_rate_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    total = 0
    closed = 0
    try:
        from app.modules.punchlist.models import PunchItem  # type: ignore

        stmt = select(PunchItem)
        if project_id is not None:
            stmt = stmt.where(PunchItem.project_id == project_id)
        stmt = _scope_portfolio(stmt, PunchItem.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total += 1
            status_val = (getattr(row, "status", "") or "").lower()
            if status_val in ("closed", "resolved", "completed", "verified"):
                closed += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("punch_close_rate: probe failed", exc_info=True)

    if total == 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=0,
        )
    pct = Decimal(closed) / Decimal(total) * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=total,
        breakdown={"closed": closed, "total": total},
    )


@register_kpi(
    "rfi_close_avg_days",
    name="RFI Close Avg Days",
    unit="days",
    category="quality",
    source_modules=["rfi"],
    description="Average days from RFI open to close.",
)
async def rfi_close_avg_days_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    total_days = Decimal("0")
    count = 0
    try:
        from app.modules.rfi.models import RFI  # type: ignore

        stmt = select(RFI)
        if project_id is not None:
            stmt = stmt.where(RFI.project_id == project_id)
        stmt = _scope_portfolio(stmt, RFI.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            opened = getattr(row, "created_at", None) or getattr(
                row,
                "opened_at",
                None,
            )
            closed = getattr(row, "closed_at", None) or getattr(
                row,
                "responded_at",
                None,
            )
            if opened is None or closed is None:
                continue
            try:
                if isinstance(opened, datetime):
                    opened_d = opened.date()
                else:
                    opened_d = opened
                if isinstance(closed, datetime):
                    closed_d = closed.date()
                else:
                    closed_d = closed
                delta = (closed_d - opened_d).days
                total_days += Decimal(max(0, delta))
                count += 1
            except Exception:
                continue
    except ImportError:
        pass
    except Exception:
        logger.debug("rfi_close_avg_days: probe failed", exc_info=True)

    avg = _safe_div(total_days, Decimal(count)) if count > 0 else Decimal("0")
    return KPIComputation(value=avg, unit="days", source_record_count=count)


# ── Safety KPIs ────────────────────────────────────────────────────────


@register_kpi(
    "safety_trir",
    name="Total Recordable Incident Rate",
    unit="ratio",
    category="safety",
    source_modules=["safety"],
    target_default=Decimal("0"),
    description="(Recordable incidents × 200000) / hours worked.",
)
async def safety_trir_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    incidents = 0
    hours_worked = Decimal("200000")  # Industry-standard normaliser
    try:
        from app.modules.safety.models import Incident  # type: ignore

        stmt = select(Incident)
        if project_id is not None:
            stmt = stmt.where(Incident.project_id == project_id)
        stmt = _scope_portfolio(stmt, Incident.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            # Recordable = not "first_aid_only"
            severity = (getattr(row, "severity", "") or "").lower()
            if severity in (
                "minor",
                "major",
                "fatal",
                "lost_time",
                "recordable",
                "medical_treatment",
            ):
                incidents += 1
        # Try to find actual hours-worked records - gracefully fall back
        try:
            from app.modules.safety.models import WorkHours  # type: ignore

            stmt2 = select(WorkHours)
            if project_id is not None:
                stmt2 = stmt2.where(WorkHours.project_id == project_id)
            stmt2 = _scope_portfolio(stmt2, WorkHours.project_id, project_id, allowed_project_ids)
            wh_rows = (await session.execute(stmt2)).scalars().all()
            total_hours = sum(
                (_to_decimal(getattr(r, "hours", 0)) for r in wh_rows),
                Decimal("0"),
            )
            if total_hours > 0:
                hours_worked = total_hours
        except Exception:
            pass
    except ImportError:
        pass
    except Exception:
        logger.debug("safety_trir: probe failed", exc_info=True)

    trir = Decimal(incidents) * Decimal("200000") / hours_worked if hours_worked > 0 else Decimal("0")
    return KPIComputation(
        value=trir,
        unit="ratio",
        source_record_count=incidents,
        breakdown={
            "incidents": incidents,
            "hours_worked": str(hours_worked),
        },
    )


# ── Sustainability ─────────────────────────────────────────────────────


@register_kpi(
    "embodied_carbon_per_m2",
    name="Embodied Carbon per m2",
    unit="ratio",
    category="sustainability",
    source_modules=["carbon", "projects"],
    description="Total Scope 3 emissions / project gross floor area.",
)
async def embodied_carbon_per_m2_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    total_emissions = Decimal("0")
    project_area = Decimal("0")
    count = 0
    try:
        from app.modules.carbon.models import (  # type: ignore
            CarbonInventory,
        )

        stmt = select(CarbonInventory)
        if project_id is not None:
            stmt = stmt.where(CarbonInventory.project_id == project_id)
        stmt = _scope_portfolio(stmt, CarbonInventory.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total_emissions += _to_decimal(
                getattr(row, "scope3_kgco2e", None) or getattr(row, "kgco2e", 0),
            )
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("embodied_carbon_per_m2: carbon probe failed", exc_info=True)

    try:
        from app.modules.projects.models import Project  # type: ignore

        if project_id is not None:
            proj = await session.get(Project, project_id)
            if proj is not None:
                project_area = _to_decimal(
                    getattr(proj, "gross_floor_area_m2", None) or getattr(proj, "area_m2", 0),
                )
    except ImportError:
        pass
    except Exception:
        logger.debug("embodied_carbon_per_m2: project probe failed", exc_info=True)

    value = _safe_div(total_emissions, project_area)
    return KPIComputation(
        value=value,
        unit="ratio",
        source_record_count=count,
        breakdown={
            "total_kgco2e": str(total_emissions),
            "area_m2": str(project_area),
        },
    )


# ── Operational ────────────────────────────────────────────────────────


@register_kpi(
    "equipment_utilization",
    name="Equipment Utilization",
    unit="percent",
    category="operational",
    source_modules=["equipment"],
    description="hours_used / hours_available.",
)
async def equipment_utilization_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    used = Decimal("0")
    available = Decimal("0")
    count = 0
    try:
        from app.modules.equipment.models import Equipment  # type: ignore

        stmt = select(Equipment)
        if project_id is not None:
            stmt = stmt.where(Equipment.project_id == project_id)
        stmt = _scope_portfolio(stmt, Equipment.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            used += _to_decimal(getattr(row, "hours_used", 0))
            available += _to_decimal(
                getattr(row, "hours_available", None) or getattr(row, "total_hours", 0),
            )
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("equipment_utilization: probe failed", exc_info=True)

    if available <= 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=count,
        )
    pct = used / available * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=count,
        breakdown={"hours_used": str(used), "hours_available": str(available)},
    )


@register_kpi(
    "subcontractor_avg_rating",
    name="Subcontractor Avg Rating",
    unit="ratio",
    category="operational",
    source_modules=["subcontractors"],
    description="Average of SubcontractorRating.score.",
)
async def subcontractor_avg_rating_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    total = Decimal("0")
    count = 0
    try:
        from app.modules.subcontractors.models import (  # type: ignore
            SubcontractorRating,
        )

        stmt = select(SubcontractorRating)
        if project_id is not None:
            stmt = stmt.where(SubcontractorRating.project_id == project_id)
        stmt = _scope_portfolio(stmt, SubcontractorRating.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total += _to_decimal(getattr(row, "score", 0))
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("subcontractor_avg_rating: probe failed", exc_info=True)

    avg = _safe_div(total, Decimal(count)) if count > 0 else Decimal("0")
    return KPIComputation(value=avg, unit="ratio", source_record_count=count)


@register_kpi(
    "bid_win_rate",
    name="Bid Win Rate",
    unit="percent",
    category="operational",
    source_modules=["bid_management", "tendering"],
    description="Won bids / submitted bids.",
)
async def bid_win_rate_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Won bids / submitted bids.

    Sourced from ``tendering.TenderBid`` (its ``status`` distinguishes
    won/awarded/accepted from pending/rejected). TenderBid has no direct
    ``project_id`` - it hangs off ``TenderPackage`` - so a project scope is
    applied by joining the package. When the tendering module is absent we
    fall back to ``bid_management``: a win is a ``BidAward`` (one per
    package) and total is the number of ``BidSubmission`` envelopes.

    Portfolio mode restricts to the caller's ``allowed_project_ids`` (when
    not ``None``) by joining the owning package, so a non-admin never counts
    bids on projects they cannot access.
    """
    won = 0
    total = 0
    won_status = ("won", "awarded", "accepted")
    # In portfolio mode we still need the package join to scope by project.
    scope_portfolio = project_id is None and allowed_project_ids is not None

    # Primary source: tendering.TenderBid
    try:
        from app.modules.tendering.models import TenderBid, TenderPackage  # type: ignore

        stmt = select(TenderBid)
        if project_id is not None:
            stmt = stmt.join(
                TenderPackage,
                TenderBid.package_id == TenderPackage.id,
            ).where(TenderPackage.project_id == project_id)
        elif scope_portfolio:
            stmt = stmt.join(
                TenderPackage,
                TenderBid.package_id == TenderPackage.id,
            )
            stmt = (
                stmt.where(false())
                if not allowed_project_ids
                else stmt.where(TenderPackage.project_id.in_(allowed_project_ids))
            )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total += 1
            status_val = (getattr(row, "status", "") or "").lower()
            if status_val in won_status:
                won += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("bid_win_rate: tendering probe failed", exc_info=True)

    # Fallback: bid_management (awards vs submissions) when no tender bids.
    if total == 0:
        try:
            from app.modules.bid_management.models import (  # type: ignore
                BidAward,
                Bidder,
                BidPackage,
                BidSubmission,
            )

            # Total submissions for the scope.
            sub_stmt = select(BidSubmission)
            award_stmt = select(BidAward)
            if project_id is not None:
                # BidSubmission → Bidder → BidPackage(project_id)
                sub_stmt = (
                    sub_stmt.join(Bidder, BidSubmission.bidder_id == Bidder.id)
                    .join(BidPackage, Bidder.package_id == BidPackage.id)
                    .where(BidPackage.project_id == project_id)
                )
                award_stmt = award_stmt.join(
                    BidPackage,
                    BidAward.package_id == BidPackage.id,
                ).where(BidPackage.project_id == project_id)
            elif scope_portfolio:
                # Portfolio mode: restrict to the caller's accessible projects
                # via the owning package.
                sub_stmt = sub_stmt.join(Bidder, BidSubmission.bidder_id == Bidder.id).join(
                    BidPackage, Bidder.package_id == BidPackage.id
                )
                award_stmt = award_stmt.join(BidPackage, BidAward.package_id == BidPackage.id)
                if not allowed_project_ids:
                    sub_stmt = sub_stmt.where(false())
                    award_stmt = award_stmt.where(false())
                else:
                    sub_stmt = sub_stmt.where(BidPackage.project_id.in_(allowed_project_ids))
                    award_stmt = award_stmt.where(BidPackage.project_id.in_(allowed_project_ids))
            total = len((await session.execute(sub_stmt)).scalars().all())
            won = len((await session.execute(award_stmt)).scalars().all())
        except ImportError:
            pass
        except Exception:
            logger.debug("bid_win_rate: bid_management probe failed", exc_info=True)

    if total == 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=0,
        )
    pct = Decimal(won) / Decimal(total) * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=total,
        breakdown={"won": won, "total": total},
    )


@register_kpi(
    "project_count_active",
    name="Active Project Count",
    unit="count",
    category="operational",
    source_modules=["projects"],
    description="Count of projects with status='active' or similar.",
)
async def project_count_active_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    count = 0
    if allowed_project_ids is not None and not allowed_project_ids:
        # Non-admin caller with no accessible project counts zero.
        return KPIComputation(value=Decimal("0"), unit="count", source_record_count=0)
    try:
        from app.modules.projects.models import Project  # type: ignore

        stmt = select(Project)
        if project_id is not None:
            stmt = stmt.where(Project.id == project_id)
        elif allowed_project_ids is not None:
            stmt = stmt.where(Project.id.in_(allowed_project_ids))
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            status_val = (getattr(row, "status", "") or "").lower()
            if status_val in ("active", "in_progress", "construction", ""):
                count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("project_count_active: probe failed", exc_info=True)

    return KPIComputation(
        value=Decimal(count),
        unit="count",
        source_record_count=count,
    )


# ── Project-controls spine KPIs (feature 09) ───────────────────────────
# Six cross-module KPIs that complete the executive controls spine (risk,
# quality, safety, changes, schedule). Each registers into the shared
# registry so the BI dashboards, alert engine and the project-controls
# snapshot all gain them at once. Every formula follows the established
# graceful-degradation + currency-honest contract.

# Statuses that mean a register entry is no longer "open" / live.
_RISK_CLOSED_STATUSES = {"closed", "mitigated", "accepted", "resolved", "retired"}
_NCR_CLOSED_STATUSES = {"closed", "resolved", "verified", "cancelled", "void"}
_HIGH_SEVERITY = {"high", "very_high", "critical", "severe", "catastrophic"}
# Variation statuses that are still pending a decision (not yet approved/rejected).
_VARIATION_PENDING_STATUSES = {"draft", "submitted", "under_review", "pending", "in_review"}


@register_kpi(
    "risk_open_exposure",
    name="Open Risk Exposure",
    unit="currency",
    category="risk",
    source_modules=["risk", "projects"],
    description="Sum of impact_cost over open (not closed/mitigated/accepted) risks.",
)
async def risk_open_exposure_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Total cost exposure of open risks, currency-honest.

    Within a single project every risk's ``impact_cost`` is converted into
    the project base currency via ``Project.fx_rates``; across the portfolio
    the amounts are bucketed by each project's ISO currency and never blended.
    The breakdown also carries a probability-weighted exposure variant
    (``Σ impact_cost × probability``) as a secondary signal.
    """
    base_currency, fx_map = await _project_currency_and_fx(session, project_id)
    seen_codes: set[str] = set()
    by_currency: dict[str, Decimal] = {}
    scalar_exposure = Decimal("0")
    weighted = Decimal("0")
    count = 0
    # Resolve each row's owning-project base currency in portfolio mode so the
    # per-currency bucketing is correct without re-querying every project.
    fx_cache: dict[uuid.UUID, tuple[str, dict[str, str]]] = {}
    try:
        from app.modules.risk.models import RiskItem  # type: ignore

        stmt = select(RiskItem)
        if project_id is not None:
            stmt = stmt.where(RiskItem.project_id == project_id)
        stmt = _scope_portfolio(stmt, RiskItem.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            status_val = (getattr(row, "status", "") or "").strip().lower()
            if status_val in _RISK_CLOSED_STATUSES:
                continue
            amt = _to_decimal(getattr(row, "impact_cost", 0))
            code = str(getattr(row, "currency", "") or "").strip().upper()
            prob = _to_decimal(getattr(row, "probability", 0))
            count += 1
            if project_id is None:
                pid = getattr(row, "project_id", None)
                row_base, row_fx = base_currency, fx_map
                if pid is not None:
                    if pid not in fx_cache:
                        fx_cache[pid] = await _project_currency_and_fx(session, pid)
                    row_base, row_fx = fx_cache[pid]
                bucket_code = code or row_base or "UNKNOWN"
                converted = _amount_in_base(amt, code, row_fx, row_base)
                _add_currency_bucket(by_currency, converted, bucket_code, row_base)
                scalar_exposure += converted
                weighted += converted * prob
            else:
                if code:
                    seen_codes.add(code)
                converted = _amount_in_base(amt, code, fx_map, base_currency)
                scalar_exposure += converted
                weighted += converted * prob
    except ImportError:
        return KPIComputation(value=Decimal("0"), unit="currency", source_record_count=0)
    except Exception:
        logger.debug("risk_open_exposure: probe failed", exc_info=True)

    if project_id is None:
        value, breakdown = _portfolio_money_breakdown(by_currency)
        breakdown["open_risk_count"] = count
        breakdown["weighted_exposure"] = str(weighted)
        return KPIComputation(
            value=value,
            unit="currency",
            source_record_count=count,
            breakdown=breakdown,
        )
    breakdown = {
        "currency": base_currency,
        "open_risk_count": count,
        "weighted_exposure": str(weighted),
    }
    missing = _missing_fx_codes(seen_codes, fx_map, base_currency)
    if missing:
        breakdown["missing_fx_codes"] = missing
    return KPIComputation(
        value=scalar_exposure,
        unit="currency",
        source_record_count=count,
        breakdown=breakdown,
    )


@register_kpi(
    "risk_high_unmitigated_count",
    name="High Unmitigated Risks",
    unit="count",
    category="risk",
    source_modules=["risk"],
    description="Count of open high/critical risks with no mitigation strategy.",
)
async def risk_high_unmitigated_count_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """High/critical risks that are still open and carry no mitigation.

    Severity comes from ``impact_severity`` (falling back to ``risk_tier``);
    a risk counts as unmitigated when ``mitigation_strategy`` is empty and no
    ``mitigation_actions`` are recorded. Mirrors the ``project_intelligence``
    collector's risk-gap signal.
    """
    count = 0
    total = 0
    try:
        from app.modules.risk.models import RiskItem  # type: ignore

        stmt = select(RiskItem)
        if project_id is not None:
            stmt = stmt.where(RiskItem.project_id == project_id)
        stmt = _scope_portfolio(stmt, RiskItem.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            status_val = (getattr(row, "status", "") or "").strip().lower()
            if status_val in _RISK_CLOSED_STATUSES:
                continue
            total += 1
            severity = (getattr(row, "impact_severity", "") or "").strip().lower()
            tier = (getattr(row, "risk_tier", "") or "").strip().lower()
            if severity not in _HIGH_SEVERITY and tier not in _HIGH_SEVERITY:
                continue
            strategy = (getattr(row, "mitigation_strategy", "") or "").strip()
            actions = getattr(row, "mitigation_actions", None) or []
            if not strategy and not actions:
                count += 1
    except ImportError:
        return KPIComputation(value=Decimal("0"), unit="count", source_record_count=0)
    except Exception:
        logger.debug("risk_high_unmitigated_count: probe failed", exc_info=True)

    return KPIComputation(
        value=Decimal(count),
        unit="count",
        source_record_count=count,
        breakdown={"open_risk_count": total},
    )


@register_kpi(
    "ncr_open_count",
    name="Open NCRs",
    unit="count",
    category="quality",
    source_modules=["ncr"],
    description="Count of NCRs not yet closed/resolved/verified.",
)
async def ncr_open_count_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Open Non-Conformance Reports - the live quality-defect backlog."""
    count = 0
    total = 0
    try:
        from app.modules.ncr.models import NCR  # type: ignore

        stmt = select(NCR)
        if project_id is not None:
            stmt = stmt.where(NCR.project_id == project_id)
        stmt = _scope_portfolio(stmt, NCR.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total += 1
            status_val = (getattr(row, "status", "") or "").strip().lower()
            if status_val not in _NCR_CLOSED_STATUSES:
                count += 1
    except ImportError:
        return KPIComputation(value=Decimal("0"), unit="count", source_record_count=0)
    except Exception:
        logger.debug("ncr_open_count: probe failed", exc_info=True)

    return KPIComputation(
        value=Decimal(count),
        unit="count",
        source_record_count=count,
        breakdown={"total_ncr_count": total},
    )


@register_kpi(
    "incident_count",
    name="Safety Incidents",
    unit="count",
    category="safety",
    source_modules=["safety"],
    description="Count of safety incidents in the period (complements TRIR).",
)
async def incident_count_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    period_start: _date | None = None,
    period_end: _date | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Raw incident count, optionally windowed by ``incident_date``.

    Uses the real ``SafetyIncident`` model (the ``safety_trir`` formula
    imports a non-existent ``Incident`` alias and so silently counts zero;
    this KPI is the working count surface).
    """
    count = 0
    try:
        from app.modules.safety.models import SafetyIncident  # type: ignore

        stmt = select(SafetyIncident)
        if project_id is not None:
            stmt = stmt.where(SafetyIncident.project_id == project_id)
        stmt = _scope_portfolio(stmt, SafetyIncident.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            when = _parse_date(getattr(row, "incident_date", None))
            if period_start is not None and (when is None or when < period_start):
                continue
            if period_end is not None and (when is None or when > period_end):
                continue
            count += 1
    except ImportError:
        return KPIComputation(value=Decimal("0"), unit="count", source_record_count=0)
    except Exception:
        logger.debug("incident_count: probe failed", exc_info=True)

    return KPIComputation(
        value=Decimal(count),
        unit="count",
        source_record_count=count,
    )


@register_kpi(
    "pending_variation_value",
    name="Pending Variation Value",
    unit="currency",
    category="changes",
    source_modules=["variations", "projects"],
    description="Sum of estimated_cost_impact over variation requests awaiting a decision.",
)
async def pending_variation_value_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Value of variation requests still pending (draft/submitted/under review).

    Distinct from ``change_order_ratio`` which measures signed/approved change
    orders against the contract. Currency-honest: within-project FX convert,
    portfolio per-currency bucketing, never blended.
    """
    base_currency, fx_map = await _project_currency_and_fx(session, project_id)
    seen_codes: set[str] = set()
    by_currency: dict[str, Decimal] = {}
    scalar_value = Decimal("0")
    count = 0
    fx_cache: dict[uuid.UUID, tuple[str, dict[str, str]]] = {}
    try:
        from app.modules.variations.models import VariationRequest  # type: ignore

        stmt = select(VariationRequest)
        if project_id is not None:
            stmt = stmt.where(VariationRequest.project_id == project_id)
        stmt = _scope_portfolio(stmt, VariationRequest.project_id, project_id, allowed_project_ids)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            status_val = (getattr(row, "status", "") or "").strip().lower()
            if status_val not in _VARIATION_PENDING_STATUSES:
                continue
            amt = _to_decimal(getattr(row, "estimated_cost_impact", 0))
            code = str(getattr(row, "currency", "") or "").strip().upper()
            count += 1
            if project_id is None:
                pid = getattr(row, "project_id", None)
                row_base, row_fx = base_currency, fx_map
                if pid is not None:
                    if pid not in fx_cache:
                        fx_cache[pid] = await _project_currency_and_fx(session, pid)
                    row_base, row_fx = fx_cache[pid]
                bucket_code = code or row_base or "UNKNOWN"
                converted = _amount_in_base(amt, code, row_fx, row_base)
                _add_currency_bucket(by_currency, converted, bucket_code, row_base)
                scalar_value += converted
            else:
                if code:
                    seen_codes.add(code)
                scalar_value += _amount_in_base(amt, code, fx_map, base_currency)
    except ImportError:
        return KPIComputation(value=Decimal("0"), unit="currency", source_record_count=0)
    except Exception:
        logger.debug("pending_variation_value: probe failed", exc_info=True)

    if project_id is None:
        value, breakdown = _portfolio_money_breakdown(by_currency)
        breakdown["pending_count"] = count
        return KPIComputation(
            value=value,
            unit="currency",
            source_record_count=count,
            breakdown=breakdown,
        )
    breakdown = {"currency": base_currency, "pending_count": count}
    missing = _missing_fx_codes(seen_codes, fx_map, base_currency)
    if missing:
        breakdown["missing_fx_codes"] = missing
    return KPIComputation(
        value=scalar_value,
        unit="currency",
        source_record_count=count,
        breakdown=breakdown,
    )


async def _active_baseline_finishes(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> dict[str, _date]:
    """Map activity-id / wbs-code → baselined finish date for one project.

    The baseline ``snapshot_data`` is a caller-defined JSON blob. We accept
    the common shapes defensively: a top-level ``activities`` list, or a bare
    list, where each entry carries an id (``id``/``activity_id``) and/or a
    ``wbs_code`` plus a finish date (``end_date``/``finish``/``baseline_finish``).
    The most recent active baseline wins.
    """
    finishes: dict[str, _date] = {}
    try:
        from app.modules.schedule.models import ScheduleBaseline  # type: ignore

        stmt = (
            select(ScheduleBaseline)
            .where(ScheduleBaseline.project_id == project_id)
            .where(ScheduleBaseline.is_active.is_(True))
        )
        rows = (await session.execute(stmt)).scalars().all()
        # Prefer the latest baseline_date when several are active.
        rows = sorted(rows, key=lambda r: str(getattr(r, "baseline_date", "") or ""))
        for row in rows:
            data = getattr(row, "snapshot_data", None)
            entries: list[Any] = []
            if isinstance(data, dict):
                raw = data.get("activities")
                if isinstance(raw, list):
                    entries = raw
            elif isinstance(data, list):
                entries = data
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                finish = _parse_date(
                    entry.get("end_date")
                    or entry.get("finish")
                    or entry.get("baseline_finish")
                    or entry.get("baseline_end"),
                )
                if finish is None:
                    continue
                for key in (entry.get("id"), entry.get("activity_id"), entry.get("wbs_code")):
                    if key:
                        finishes[str(key)] = finish
    except ImportError:
        return {}
    except Exception:
        logger.debug("milestone_slippage: baseline probe failed", exc_info=True)
    return finishes


@register_kpi(
    "milestone_slippage_days",
    name="Milestone Slippage",
    unit="days",
    category="schedule",
    source_modules=["schedule"],
    description="Max positive delta between an activity's current finish and its baseline finish.",
)
async def milestone_slippage_days_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    **_: Any,
) -> KPIComputation:
    """Worst-case schedule slip: the largest number of days any activity's
    current finish has moved past its baselined finish.

    Pure ISO-string date arithmetic via ``_parse_date`` (schedule dates are
    ``String`` columns). Region-neutral. Returns 0 when no baseline exists or
    nothing has slipped.

    Portfolio mode restricts the fan-out to the caller's
    ``allowed_project_ids`` (IDOR defence): an empty set yields zero.
    """
    max_slip = 0
    slipped = 0
    total = 0
    if project_id is None and allowed_project_ids is not None and not allowed_project_ids:
        return KPIComputation(value=Decimal("0"), unit="days", source_record_count=0)
    try:
        from app.modules.schedule.models import Activity, Schedule  # type: ignore

        # Resolve which project owns each schedule (Activity has no
        # project_id - it hangs off Schedule).
        sched_stmt = select(Schedule.id, Schedule.project_id)
        if project_id is None and allowed_project_ids is not None:
            sched_stmt = sched_stmt.where(Schedule.project_id.in_(allowed_project_ids))
        sched_rows = (await session.execute(sched_stmt)).all()
        sched_to_project = {sid: pid for sid, pid in sched_rows}

        target_pids = [project_id] if project_id is not None else sorted({p for p in sched_to_project.values() if p})
        baselines: dict[uuid.UUID, dict[str, _date]] = {}
        for pid in target_pids:
            baselines[pid] = await _active_baseline_finishes(session, pid)

        act_stmt = select(Activity)
        if project_id is not None:
            scoped_schedule_ids = [sid for sid, pid in sched_to_project.items() if pid == project_id]
            if not scoped_schedule_ids:
                return KPIComputation(value=Decimal("0"), unit="days", source_record_count=0)
            act_stmt = act_stmt.where(Activity.schedule_id.in_(scoped_schedule_ids))
        rows = (await session.execute(act_stmt)).scalars().all()
        for row in rows:
            owning_project = sched_to_project.get(getattr(row, "schedule_id", None))
            if owning_project is None:
                continue
            baseline = baselines.get(owning_project, {})
            if not baseline:
                continue
            current = _parse_date(getattr(row, "end_date", None))
            if current is None:
                continue
            base_finish = baseline.get(str(getattr(row, "id", ""))) or baseline.get(str(getattr(row, "wbs_code", "")))
            if base_finish is None:
                continue
            total += 1
            slip = (current - base_finish).days
            if slip > 0:
                slipped += 1
                max_slip = max(max_slip, slip)
    except ImportError:
        return KPIComputation(value=Decimal("0"), unit="days", source_record_count=0)
    except Exception:
        logger.debug("milestone_slippage_days: probe failed", exc_info=True)

    return KPIComputation(
        value=Decimal(max_slip),
        unit="days",
        source_record_count=total,
        breakdown={"activities_compared": total, "activities_slipped": slipped},
    )


# ── Bootstrap ──────────────────────────────────────────────────────────


def list_system_kpis() -> list[dict[str, Any]]:
    """Return metadata for every registered system KPI."""
    return [dict(meta) for meta in SYSTEM_KPI_META.values()]


# ── Drill-down record providers ─────────────────────────────────────────
# A KPI's "drill-down" returns the underlying rows that fed the aggregate -
# e.g. for ``cpi`` we return task earned-value rows plus the finance
# payments / purchase orders that make up actual cost. Each provider is
# registered against a KPI code and returns a list of dicts, capped at
# ``limit``. Providers are called as
# ``(session, project_id, limit, allowed_project_ids)``; the last arg
# scopes a portfolio drill-down to the caller's accessible projects (IDOR
# defence) and defaults to ``None`` (unrestricted) for direct callers.

KPIRecordProvider = Callable[..., Awaitable[list[dict[str, Any]]]]
KPI_RECORD_PROVIDERS: dict[str, KPIRecordProvider] = {}


def register_kpi_records(code: str) -> Callable[[KPIRecordProvider], KPIRecordProvider]:
    """Decorator registering a drill-down record provider for a KPI."""

    def decorator(fn: KPIRecordProvider) -> KPIRecordProvider:
        KPI_RECORD_PROVIDERS[code] = fn
        return fn

    return decorator


async def _evm_drilldown_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Shared drill-down implementation for every EVM KPI.

    Returns one row per task with its PV/EV plus the matching finance
    expenses (joined logically via project_id only - strict task-expense
    linking is upstream).
    """
    records: list[dict[str, Any]] = []
    try:
        from app.modules.tasks.models import Task  # type: ignore

        stmt = select(Task)
        if project_id is not None:
            stmt = stmt.where(Task.project_id == project_id)
        stmt = _scope_portfolio(stmt, Task.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "task",
                    "id": str(row.id),
                    "name": getattr(row, "name", ""),
                    "planned_value": str(_to_decimal(getattr(row, "planned_value", 0))),
                    "earned_value": str(_to_decimal(getattr(row, "earned_value", 0))),
                    "project_id": str(getattr(row, "project_id", "")),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("evm drilldown: tasks probe failed", exc_info=True)
    # Actual cost rows: settled payments (joined to the invoice for project
    # scope) - there is no finance.Expense model on this platform.
    try:
        from app.modules.finance.models import Invoice, Payment  # type: ignore

        stmt = select(Payment, Invoice).join(Invoice, Payment.invoice_id == Invoice.id)
        if project_id is not None:
            stmt = stmt.where(Invoice.project_id == project_id)
        stmt = _scope_portfolio(stmt, Invoice.project_id, project_id, allowed_project_ids).limit(limit)
        for payment, invoice in (await session.execute(stmt)).all():
            records.append(
                {
                    "kind": "payment",
                    "id": str(payment.id),
                    "amount": str(_to_decimal(getattr(payment, "amount", 0))),
                    "currency": str(getattr(payment, "currency_code", "") or ""),
                    "project_id": str(getattr(invoice, "project_id", "") or ""),
                    "invoice_id": str(getattr(payment, "invoice_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("evm drilldown: finance probe failed", exc_info=True)
    # Committed cost rows: purchase orders.
    try:
        from app.modules.procurement.models import PurchaseOrder  # type: ignore

        stmt = select(PurchaseOrder)
        if project_id is not None:
            stmt = stmt.where(PurchaseOrder.project_id == project_id)
        stmt = _scope_portfolio(stmt, PurchaseOrder.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "purchase_order",
                    "id": str(row.id),
                    "po_number": getattr(row, "po_number", "") or "",
                    "amount": str(_to_decimal(getattr(row, "amount_total", 0))),
                    "currency": str(getattr(row, "currency_code", "") or ""),
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("evm drilldown: procurement probe failed", exc_info=True)
    return records


for _evm_code in ("cpi", "spi", "cv", "sv", "eac", "etc", "vac", "tcpi"):
    KPI_RECORD_PROVIDERS[_evm_code] = _evm_drilldown_records


@register_kpi_records("safety_trir")
async def _safety_trir_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        from app.modules.safety.models import Incident  # type: ignore

        stmt = select(Incident)
        if project_id is not None:
            stmt = stmt.where(Incident.project_id == project_id)
        stmt = _scope_portfolio(stmt, Incident.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "incident",
                    "id": str(row.id),
                    "severity": getattr(row, "severity", "") or "",
                    "occurred_at": str(getattr(row, "occurred_at", "") or ""),
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("safety_trir drilldown: probe failed", exc_info=True)
    return records


@register_kpi_records("project_count_active")
async def _projects_active_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        from app.modules.projects.models import Project  # type: ignore

        stmt = select(Project)
        if project_id is not None:
            stmt = stmt.where(Project.id == project_id)
        elif allowed_project_ids is not None:
            stmt = stmt.where(false()) if not allowed_project_ids else stmt.where(Project.id.in_(allowed_project_ids))
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "project",
                    "id": str(row.id),
                    "name": getattr(row, "name", "") or "",
                    "status": getattr(row, "status", "") or "",
                    "budget": str(_to_decimal(getattr(row, "budget", 0))),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("project_count_active drilldown: probe failed", exc_info=True)
    return records


# ── Project-controls spine drill-down providers (feature 09) ────────────


async def _risk_drilldown_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Open risks behind ``risk_open_exposure`` / ``risk_high_unmitigated_count``."""
    records: list[dict[str, Any]] = []
    try:
        from app.modules.risk.models import RiskItem  # type: ignore

        stmt = select(RiskItem)
        if project_id is not None:
            stmt = stmt.where(RiskItem.project_id == project_id)
        stmt = _scope_portfolio(stmt, RiskItem.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            status_val = (getattr(row, "status", "") or "").strip().lower()
            if status_val in _RISK_CLOSED_STATUSES:
                continue
            records.append(
                {
                    "kind": "risk",
                    "id": str(row.id),
                    "code": getattr(row, "code", "") or "",
                    "title": getattr(row, "title", "") or "",
                    "status": getattr(row, "status", "") or "",
                    "impact_severity": getattr(row, "impact_severity", "") or "",
                    "impact_cost": str(_to_decimal(getattr(row, "impact_cost", 0))),
                    "currency": getattr(row, "currency", "") or "",
                    "mitigation_strategy": (getattr(row, "mitigation_strategy", "") or "")[:200],
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("risk drilldown: probe failed", exc_info=True)
    return records


KPI_RECORD_PROVIDERS["risk_open_exposure"] = _risk_drilldown_records
KPI_RECORD_PROVIDERS["risk_high_unmitigated_count"] = _risk_drilldown_records


@register_kpi_records("ncr_open_count")
async def _ncr_open_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        from app.modules.ncr.models import NCR  # type: ignore

        stmt = select(NCR)
        if project_id is not None:
            stmt = stmt.where(NCR.project_id == project_id)
        stmt = _scope_portfolio(stmt, NCR.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            status_val = (getattr(row, "status", "") or "").strip().lower()
            if status_val in _NCR_CLOSED_STATUSES:
                continue
            records.append(
                {
                    "kind": "ncr",
                    "id": str(row.id),
                    "ncr_number": getattr(row, "ncr_number", "") or "",
                    "title": getattr(row, "title", "") or "",
                    "severity": getattr(row, "severity", "") or "",
                    "status": getattr(row, "status", "") or "",
                    "cost_impact": str(getattr(row, "cost_impact", "") or ""),
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("ncr_open_count drilldown: probe failed", exc_info=True)
    return records


@register_kpi_records("incident_count")
async def _incident_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        from app.modules.safety.models import SafetyIncident  # type: ignore

        stmt = select(SafetyIncident)
        if project_id is not None:
            stmt = stmt.where(SafetyIncident.project_id == project_id)
        stmt = _scope_portfolio(stmt, SafetyIncident.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "incident",
                    "id": str(row.id),
                    "incident_number": getattr(row, "incident_number", "") or "",
                    "severity": getattr(row, "severity", "") or "",
                    "incident_date": str(getattr(row, "incident_date", "") or ""),
                    "status": getattr(row, "status", "") or "",
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("incident_count drilldown: probe failed", exc_info=True)
    return records


@register_kpi_records("pending_variation_value")
async def _pending_variation_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        from app.modules.variations.models import VariationRequest  # type: ignore

        stmt = select(VariationRequest)
        if project_id is not None:
            stmt = stmt.where(VariationRequest.project_id == project_id)
        stmt = _scope_portfolio(stmt, VariationRequest.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            status_val = (getattr(row, "status", "") or "").strip().lower()
            if status_val not in _VARIATION_PENDING_STATUSES:
                continue
            records.append(
                {
                    "kind": "variation_request",
                    "id": str(row.id),
                    "code": getattr(row, "code", "") or "",
                    "status": getattr(row, "status", "") or "",
                    "estimated_cost_impact": str(_to_decimal(getattr(row, "estimated_cost_impact", 0))),
                    "currency": getattr(row, "currency", "") or "",
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("pending_variation_value drilldown: probe failed", exc_info=True)
    return records


@register_kpi_records("milestone_slippage_days")
async def _milestone_slippage_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Activities whose current finish has slipped past their baseline finish."""
    records: list[dict[str, Any]] = []
    if project_id is None and allowed_project_ids is not None and not allowed_project_ids:
        return records
    try:
        from app.modules.schedule.models import Activity, Schedule  # type: ignore

        sched_stmt = select(Schedule.id, Schedule.project_id)
        if project_id is None and allowed_project_ids is not None:
            sched_stmt = sched_stmt.where(Schedule.project_id.in_(allowed_project_ids))
        sched_rows = (await session.execute(sched_stmt)).all()
        sched_to_project = {sid: pid for sid, pid in sched_rows}
        target_pids = [project_id] if project_id is not None else sorted({p for p in sched_to_project.values() if p})
        baselines: dict[uuid.UUID, dict[str, _date]] = {}
        for pid in target_pids:
            baselines[pid] = await _active_baseline_finishes(session, pid)

        act_stmt = select(Activity)
        if project_id is not None:
            scoped = [sid for sid, pid in sched_to_project.items() if pid == project_id]
            if not scoped:
                return records
            act_stmt = act_stmt.where(Activity.schedule_id.in_(scoped))
        rows = (await session.execute(act_stmt)).scalars().all()
        for row in rows:
            owning_project = sched_to_project.get(getattr(row, "schedule_id", None))
            if owning_project is None:
                continue
            baseline = baselines.get(owning_project, {})
            base_finish = baseline.get(str(getattr(row, "id", ""))) or baseline.get(str(getattr(row, "wbs_code", "")))
            current = _parse_date(getattr(row, "end_date", None))
            if base_finish is None or current is None:
                continue
            slip = (current - base_finish).days
            if slip <= 0:
                continue
            records.append(
                {
                    "kind": "activity",
                    "id": str(row.id),
                    "name": getattr(row, "name", "") or "",
                    "wbs_code": getattr(row, "wbs_code", "") or "",
                    "baseline_finish": base_finish.isoformat(),
                    "current_finish": current.isoformat(),
                    "slip_days": slip,
                    "project_id": str(owning_project),
                },
            )
            if len(records) >= limit:
                break
    except ImportError:
        pass
    except Exception:
        logger.debug("milestone_slippage_days drilldown: probe failed", exc_info=True)
    return records


# ── Quality / change drill-downs (CONN-77: 4 previously dead tiles) ──────
# first_pass_yield, copq, rfi_close_avg_days and change_order_ratio sit on
# the Project Controls spine but had no registered record provider, so the
# drill drawer opened empty (dead end). Each now returns the underlying rows
# that feed its aggregate, deep-linked back to the owning module.


@register_kpi_records("first_pass_yield")
async def _first_pass_yield_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Inspections behind ``first_pass_yield`` (passed / total)."""
    records: list[dict[str, Any]] = []
    try:
        from app.modules.inspections.models import QualityInspection  # type: ignore

        stmt = select(QualityInspection)
        if project_id is not None:
            stmt = stmt.where(QualityInspection.project_id == project_id)
        stmt = _scope_portfolio(stmt, QualityInspection.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "inspection",
                    "id": str(row.id),
                    "inspection_number": getattr(row, "inspection_number", "") or "",
                    "title": getattr(row, "title", "") or "",
                    "inspection_type": getattr(row, "inspection_type", "") or "",
                    "status": getattr(row, "status", "") or "",
                    "result": getattr(row, "result", "") or "",
                    "inspection_date": str(getattr(row, "inspection_date", "") or ""),
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("first_pass_yield drilldown: probe failed", exc_info=True)
    return records


@register_kpi_records("copq")
async def _copq_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """NCRs behind ``copq`` (cost of poor quality = Σ NCR cost impact)."""
    records: list[dict[str, Any]] = []
    try:
        from app.modules.ncr.models import NCR  # type: ignore

        stmt = select(NCR)
        if project_id is not None:
            stmt = stmt.where(NCR.project_id == project_id)
        stmt = _scope_portfolio(stmt, NCR.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "ncr",
                    "id": str(row.id),
                    "ncr_number": getattr(row, "ncr_number", "") or "",
                    "title": getattr(row, "title", "") or "",
                    "severity": getattr(row, "severity", "") or "",
                    "status": getattr(row, "status", "") or "",
                    "cost_impact": str(getattr(row, "cost_impact", "") or ""),
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("copq drilldown: probe failed", exc_info=True)
    return records


@register_kpi_records("rfi_close_avg_days")
async def _rfi_close_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """RFIs behind ``rfi_close_avg_days`` (open-to-close turnaround)."""
    records: list[dict[str, Any]] = []
    try:
        from app.modules.rfi.models import RFI  # type: ignore

        stmt = select(RFI)
        if project_id is not None:
            stmt = stmt.where(RFI.project_id == project_id)
        stmt = _scope_portfolio(stmt, RFI.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "rfi",
                    "id": str(row.id),
                    "rfi_number": getattr(row, "rfi_number", "") or "",
                    "subject": getattr(row, "subject", "") or "",
                    "status": getattr(row, "status", "") or "",
                    "priority": getattr(row, "priority", "") or "",
                    "responded_at": str(getattr(row, "responded_at", "") or ""),
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("rfi_close_avg_days drilldown: probe failed", exc_info=True)
    return records


@register_kpi_records("change_order_ratio")
async def _change_order_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Change orders behind ``change_order_ratio`` (Σ CO value / contract value)."""
    records: list[dict[str, Any]] = []
    try:
        from app.modules.changeorders.models import ChangeOrder  # type: ignore

        stmt = select(ChangeOrder)
        if project_id is not None:
            stmt = stmt.where(ChangeOrder.project_id == project_id)
        stmt = _scope_portfolio(stmt, ChangeOrder.project_id, project_id, allowed_project_ids).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            amount = getattr(row, "approved_amount", None)
            if amount is None:
                amount = getattr(row, "cost_impact", 0)
            records.append(
                {
                    "kind": "change_order",
                    "id": str(row.id),
                    "code": getattr(row, "code", "") or "",
                    "title": getattr(row, "title", "") or "",
                    "status": getattr(row, "status", "") or "",
                    "cost_impact": str(_to_decimal(amount)),
                    "currency": getattr(row, "currency", "") or "",
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("change_order_ratio drilldown: probe failed", exc_info=True)
    return records


async def drilldown(
    code: str,
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    limit: int = 100,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Return underlying records for a KPI, capped at ``limit``.

    Returns ``[]`` if no provider is registered or the probe fails.

    ``allowed_project_ids`` scopes a portfolio drill-down
    (``project_id is None``) to the caller's accessible projects (IDOR
    defence): ``None`` is unrestricted (admin / already-gated single
    project), a set restricts to those ids, and an empty set returns no
    rows. Each provider applies it through the shared :func:`_scope_portfolio`.
    """
    provider = KPI_RECORD_PROVIDERS.get(code)
    if provider is None:
        return []
    try:
        return await provider(session, project_id, limit, allowed_project_ids)
    except Exception:
        logger.exception("drilldown: provider for %s raised", code)
        return []


# ── Benchmark (portfolio median) ────────────────────────────────────────


async def benchmark(
    code: str,
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Return ``{value, median, percentile}`` comparing the project's KPI
    to the portfolio median computed across all active projects.

    Skipped when:
        * ``project_id`` is None (caller already at portfolio level)
        * No other projects exist
    """
    if project_id is None:
        return {}
    try:
        from app.modules.projects.models import Project  # type: ignore

        rows = (await session.execute(select(Project))).scalars().all()
    except ImportError:
        return {}
    except Exception:
        logger.debug("benchmark: project list failed", exc_info=True)
        return {}

    project_values: list[Decimal] = []
    target_value: Decimal | None = None
    for proj in rows:
        try:
            result = await compute(code, session, project_id=proj.id)
        except Exception:
            continue
        if result.source_record_count == 0:
            continue
        project_values.append(result.value)
        if proj.id == project_id:
            target_value = result.value
    if not project_values or target_value is None:
        return {}
    project_values.sort()
    n = len(project_values)
    median = (
        (project_values[n // 2 - 1] + project_values[n // 2]) / Decimal("2") if n % 2 == 0 else project_values[n // 2]
    )
    rank = sum(1 for v in project_values if v <= target_value)
    percentile = Decimal(rank) * Decimal("100") / Decimal(n)
    return {
        "value": str(target_value),
        "median": str(median),
        "percentile": str(percentile.quantize(Decimal("0.01"))),
        "portfolio_size": n,
    }


async def compute(
    code: str,
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    period_start: _date | None = None,
    period_end: _date | None = None,
    filters: dict[str, Any] | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
) -> KPIComputation:
    """Invoke a registered KPI safely.

    Returns a zero-value :class:`KPIComputation` when the code is unknown
    or when the formula raises - never bubble up to API callers, this
    module is purely consumer code.

    ``allowed_project_ids`` is forwarded to every formula so a portfolio
    call (``project_id is None``) only aggregates over the caller's
    accessible projects (IDOR defence). ``None`` means no restriction
    (admin / single-project, which is already access-checked). Formulas
    that have no portfolio fan-out ignore it via their ``**_`` catch-all.
    """
    fn = KPI_FORMULAS.get(code)
    if fn is None:
        logger.debug("compute: unknown KPI code=%s", code)
        return KPIComputation()
    try:
        return await fn(
            session,
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
            filters=filters or {},
            allowed_project_ids=allowed_project_ids,
        )
    except Exception:
        logger.exception("compute: KPI %s formula raised", code)
        return KPIComputation()


__all__ = [
    "EVMSnapshot",
    "KPIComputation",
    "KPIFormula",
    "KPIRecordProvider",
    "KPI_FORMULAS",
    "KPI_RECORD_PROVIDERS",
    "SYSTEM_KPI_META",
    "benchmark",
    "compute",
    "drilldown",
    "list_system_kpis",
    "register_kpi",
    "register_kpi_records",
]
