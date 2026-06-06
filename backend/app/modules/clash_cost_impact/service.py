# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Pure cost-rollup service for the clash cost-impact module.

The service is deliberately read-only - no ORM writes, no transactional
side-effects - because the cost-impact column is a derived view over
state that the upstream clash + BOQ modules already own. Keeping the
arithmetic in ``Decimal`` until the final ``float`` narrowing matches
the BOQ module's wire convention (``feedback_no_orjson_default.md`` -
floats only at the response boundary, never inside the rollup).

Formula (per clash)
    ``cost_impact = rework_subtotal + labour_subtotal``
    * ``rework_subtotal = sum(affected_positions.total) × rework_factor``
    * ``labour_subtotal = trade_pair_hours × blended_rate``

Where ``rework_factor`` defaults to 0.10 (10 %), ``blended_rate``
defaults to 50.0 currency units per hour and ``trade_pair_hours`` is
the symmetric lookup in :data:`TRADE_PAIR_HOURS` below.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.clash.models import ClashResult, ClashRun
from app.modules.clash.schemas import OPEN_STATUSES
from app.modules.projects.models import Project

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────

#: Default rework factor applied to the affected BOQ positions subtotal.
#: 10 % is the conservative QS rule-of-thumb for rework on a discovered
#: clash - defensible against most cost-estimating handbooks. Override
#: per-project via ``Project.metadata_.clash_cost_impact.rework_factor``.
DEFAULT_REWORK_FACTOR = Decimal("0.10")

#: Default blended labour rate per hour in the project's native currency.
#: 50.0 is a deliberately round, geography-agnostic placeholder (the architecture guide
#: §"No country-specific standards in default UI / marketing"). Override
#: per-project via ``Project.metadata_.clash_cost_impact.blended_rate``.
DEFAULT_BLENDED_RATE = Decimal("50.0")

#: Symmetric discipline-pair labour-hours lookup. Keys are written
#: ``(min, max)`` alphabetic so the lookup is symmetric on the pair:
#: ``(arch, struct)`` and ``(struct, arch)`` both normalise to the same
#: tuple via :func:`_pair_key`. Values come from a coordination-engineer
#: rule-of-thumb table; they are conservative averages - the QS still
#: has the affected-positions list for the real story.
TRADE_PAIR_HOURS: dict[tuple[str, str], int] = {
    # The four classical coordination axes - Structural ↔ MEP is the
    # textbook example (a beam through a duct) and carries the highest
    # rework hours; architectural ↔ structural usually only needs paint /
    # finish rework, so it is lighter.
    ("architectural", "structural"): 4,
    ("architectural", "mechanical"): 6,
    ("architectural", "electrical"): 4,
    ("architectural", "plumbing"): 4,
    ("mechanical", "structural"): 8,
    ("electrical", "structural"): 6,
    ("plumbing", "structural"): 6,
    # MEP ↔ MEP cross - every duct/pipe/cable-tray reroute is a few
    # hours of coordination + the field rework itself.
    ("electrical", "mechanical"): 4,
    ("mechanical", "plumbing"): 4,
    ("electrical", "plumbing"): 3,
    # Civil / site coordination cross - captures landscape/utilities vs
    # the building envelope. Light because typically the answer is a
    # site-plan adjustment, not a rebuild.
    ("architectural", "civil"): 3,
    ("civil", "structural"): 4,
    # Same-discipline fallback (e.g. two ducts on the same trade) - when
    # only one of the elements has a discipline label or both are equal.
    ("architectural", "architectural"): 2,
    ("structural", "structural"): 2,
    ("mechanical", "mechanical"): 2,
    ("electrical", "electrical"): 2,
    ("plumbing", "plumbing"): 2,
}

#: Fallback labour hours when the pair has no explicit row above. Picked
#: as the median of the table so a "miss" never artificially inflates
#: the rollup - the surveyor still gets a number, but a modest one.
DEFAULT_TRADE_PAIR_HOURS = 4


# ── Helpers ────────────────────────────────────────────────────────────────


def _normalise_discipline(value: str | None) -> str:
    """Collapse a free-text discipline label to a canonical lookup key.

    Handles the common variants the BIM importers produce
    (``"Structural"``, ``"struct"``, ``"STRUCT"``, ``"Structure"``, …)
    by lower-casing + stripping whitespace + mapping a small alias
    dictionary. Unknown labels pass through lower-cased so the
    ``unknown`` cell of the lookup table can still match.
    """
    if not value:
        return "unknown"
    raw = value.strip().lower()
    aliases = {
        "arch": "architectural",
        "architecture": "architectural",
        "struct": "structural",
        "structure": "structural",
        "mep": "mechanical",  # blanket MEP rolls up to mechanical
        "hvac": "mechanical",
        "mech": "mechanical",
        "elec": "electrical",
        "elect": "electrical",
        "pl": "plumbing",
        "plumb": "plumbing",
        "site": "civil",
        "landscape": "civil",
    }
    return aliases.get(raw, raw)


def _pair_key(a: str | None, b: str | None) -> tuple[str, str]:
    """Sorted symmetric pair key - ``(arch, struct)`` == ``(struct, arch)``."""
    da, db = _normalise_discipline(a), _normalise_discipline(b)
    return (da, db) if da <= db else (db, da)


def trade_pair_hours(a: str | None, b: str | None) -> int:
    """Lookup the labour hours for a discipline pair (symmetric)."""
    key = _pair_key(a, b)
    return TRADE_PAIR_HOURS.get(key, DEFAULT_TRADE_PAIR_HOURS)


def _to_decimal(value: Any) -> Decimal:
    """Coerce a Position numeric string into ``Decimal`` (matches BOQ svc).

    BOQ stores money as ``String`` to dodge SQLite's REAL precision loss
    (see ``backend/app/modules/boq/models.py`` - same convention here).
    """
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _money_quantise(value: Decimal) -> Decimal:
    """Quantise to 2 dp with conventional half-up money rounding.

    Decimal's default rounding is ROUND_HALF_EVEN ("banker's rounding"),
    which is wrong for money totals - a QS expects 0.125 → 0.13, not 0.12.
    Internal arithmetic stays exact; this is only applied at the boundary.
    """
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money_round(value: Decimal) -> float:
    """Round to 2 dp at the wire boundary; internal arithmetic stays exact."""
    return float(_money_quantise(value))


def _project_cost_config(project: Project) -> tuple[Decimal, Decimal]:
    """Pull per-project rework_factor + blended_rate from metadata.

    The two knobs live under ``Project.metadata_["clash_cost_impact"]`` so
    we never need a migration for a v1 ship. The shape is:

        {
            "clash_cost_impact": {
                "rework_factor": "0.12",   // or 12 - both accepted
                "blended_rate":  "65.0"
            }
        }

    Strings are parsed via :class:`Decimal`; bad values fall back to the
    defaults rather than 500ing the rollup endpoint.
    """
    factor = DEFAULT_REWORK_FACTOR
    rate = DEFAULT_BLENDED_RATE
    meta = getattr(project, "metadata_", None) or {}
    cfg = meta.get("clash_cost_impact") if isinstance(meta, dict) else None
    if isinstance(cfg, dict):
        raw_factor = cfg.get("rework_factor")
        if raw_factor is not None:
            try:
                parsed = Decimal(str(raw_factor))
                # Accept either decimal (0.10) or percent (10).
                if parsed > Decimal("1"):
                    parsed = parsed / Decimal("100")
                if Decimal("0") <= parsed <= Decimal("1"):
                    factor = parsed
            except (InvalidOperation, ValueError, TypeError):
                logger.debug(
                    "Bad rework_factor %r on project %s - using default",
                    raw_factor,
                    project.id,
                )
        raw_rate = cfg.get("blended_rate")
        if raw_rate is not None:
            try:
                parsed_rate = Decimal(str(raw_rate))
                if parsed_rate >= Decimal("0"):
                    rate = parsed_rate
            except (InvalidOperation, ValueError, TypeError):
                logger.debug(
                    "Bad blended_rate %r on project %s - using default",
                    raw_rate,
                    project.id,
                )
    return factor, rate


# ── Core service ───────────────────────────────────────────────────────────


class ClashCostImpactService:
    """Read-only cost rollup over clashes + BOQ positions.

    Construct one per request via the FastAPI session dependency; it
    holds the session by reference and issues SELECTs only (no flush,
    no commit, no events fired).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Loaders ────────────────────────────────────────────────────────────

    async def _load_clash(self, clash_id: uuid.UUID) -> ClashResult | None:
        return await self.session.get(ClashResult, clash_id)

    async def _load_run(self, run_id: uuid.UUID) -> ClashRun | None:
        return await self.session.get(ClashRun, run_id)

    async def project_id_for_clash(self, clash_id: uuid.UUID) -> uuid.UUID | None:
        """Resolve owning project id for a clash without computing impact.

        Used by the router to run the IDOR access check *before* doing
        the (relatively expensive) impact computation - and before any
        404 branching, so 404 vs 403 cannot be distinguished by timing.
        """
        clash = await self._load_clash(clash_id)
        if clash is None:
            return None
        run = await self._load_run(clash.run_id)
        if run is None:
            return None
        return run.project_id

    async def _load_project(self, project_id: uuid.UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    async def _positions_for_project(self, project_id: uuid.UUID) -> list[Position]:
        """All BOQ positions whose owning BOQ belongs to ``project_id``.

        We deliberately fetch every position once and filter in Python on
        ``cad_element_ids`` - the JSON list is opaque to the SQLite
        backend (cross-dialect ``json_each`` is not portable across the
        test SQLite + prod Postgres pair we ship), and a single project's
        BOQ count is in the 10² range, well within memory.
        """
        stmt = select(Position).join(BOQ, BOQ.id == Position.boq_id).where(BOQ.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _open_clashes_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status_filter: str = "open",
    ) -> list[ClashResult]:
        """Every clash for ``project_id`` matching ``status_filter``.

        ``status_filter='open'`` resolves to the ``OPEN_STATUSES`` tuple
        from the clash schemas (``new``/``active``/``reviewed``); any
        other value is passed through verbatim for the rare "rollup all"
        case. Closed/ignored clashes are excluded by default - they no
        longer carry a rework risk.
        """
        stmt = (
            select(ClashResult)
            .join(ClashRun, ClashRun.id == ClashResult.run_id)
            .where(ClashRun.project_id == project_id)
        )
        if status_filter == "open":
            stmt = stmt.where(ClashResult.status.in_(OPEN_STATUSES))
        elif status_filter and status_filter != "all":
            stmt = stmt.where(ClashResult.status == status_filter)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Cost-impact for a single clash ─────────────────────────────────────

    def _affected_positions(
        self,
        clash: ClashResult,
        positions: list[Position],
    ) -> list[Position]:
        """Subset of ``positions`` whose ``cad_element_ids`` overlap the clash.

        The match is done on the stable element ids
        (``a_stable_id`` / ``b_stable_id``) - these are snapshotted on
        every ``ClashResult`` so the link survives a model re-import
        (the model element's row id may change, the stable id will not).
        """
        wanted = {
            (clash.a_stable_id or "").strip(),
            (clash.b_stable_id or "").strip(),
        } - {""}
        if not wanted:
            return []
        out: list[Position] = []
        for pos in positions:
            ids = pos.cad_element_ids or []
            # ``cad_element_ids`` is a JSON column; defend against the
            # rare bad row that stored a non-list (older importer bugs
            # have shipped strings / dicts in this slot). Iterating a
            # string would otherwise match by-character against the
            # ``wanted`` set and silently corrupt the rework subtotal.
            if not isinstance(ids, list) or not ids:
                continue
            for raw in ids:
                if str(raw).strip() in wanted:
                    out.append(pos)
                    break
        return out

    def _compute_impact(
        self,
        clash: ClashResult,
        project: Project,
        affected: list[Position],
    ) -> tuple[dict[str, Any], Decimal]:
        """Pure arithmetic kernel - no I/O, easy to unit-test.

        Returns ``(payload, total_decimal)`` where ``payload`` is the
        Pydantic-ready response dict (floats at the boundary, matching
        the BOQ wire convention) and ``total_decimal`` is the exact
        ``Decimal`` total before the 2-dp narrowing. The rollup loop
        uses ``total_decimal`` so per-clash rounding does NOT accumulate
        into the project-level total (otherwise the rollup is off by up
        to ``0.005 × clash_count`` currency units, which is real money
        on a 10⁴-clash mega-project).
        """
        rework_factor, blended_rate = _project_cost_config(project)

        rework_total = sum((_to_decimal(p.total) for p in affected), Decimal("0"))
        rework_subtotal = rework_total * rework_factor

        has_guids = bool((clash.a_stable_id or "").strip() or (clash.b_stable_id or "").strip())
        if has_guids:
            labour_hours_int = trade_pair_hours(clash.a_discipline, clash.b_discipline)
        else:
            labour_hours_int = 0
        labour_hours = Decimal(labour_hours_int)
        labour_subtotal = labour_hours * blended_rate

        total = rework_subtotal + labour_subtotal

        # Confidence ladder (spec):
        #   high   - ≥1 affected BOQ position (real rework money)
        #   medium - labour estimate only (no BOQ overlap)
        #   low    - no element GUIDs at all OR both subtotals zero
        if affected:
            confidence = "high"
        elif has_guids and labour_subtotal > Decimal("0"):
            confidence = "medium"
        else:
            confidence = "low"

        payload: dict[str, Any] = {
            # ``project.currency`` is the authoritative source of truth;
            # falling back to a hard-coded "EUR" would silently mislabel
            # a project that was created without a currency set (per
            # ``v3_db_eur_defaults_killed.md`` - no DB-level EUR defaults).
            "currency": project.currency or "",
            "components": {
                "rework_positions_total": _money_round(rework_total),
                "rework_factor_pct": float(_money_quantise(rework_factor * Decimal("100"))),
                "rework_subtotal": _money_round(rework_subtotal),
                "labour_hours": float(labour_hours),
                "blended_rate": float(_money_quantise(blended_rate)),
                "labour_subtotal": _money_round(labour_subtotal),
            },
            "total_estimate": _money_round(total),
            "confidence": confidence,
            "affected_positions": [
                {
                    "position_id": p.id,
                    # ``boq_id`` lets the UI deep-link straight to the owning
                    # BOQ editor (``/boq/{boq_id}?highlight={position_id}``);
                    # the position id alone is not routable without it.
                    "boq_id": p.boq_id,
                    "ordinal": p.ordinal or "",
                    "description": p.description or "",
                    "total": _money_round(_to_decimal(p.total)),
                }
                for p in affected
            ],
        }
        return payload, total

    async def impact_for_clash(self, clash_id: uuid.UUID) -> tuple[dict[str, Any] | None, uuid.UUID | None]:
        """Resolve a single clash → cost-impact payload + owning project id.

        Returns ``(None, None)`` when the clash row is missing - the
        router maps that to a 404. The second tuple slot is the project
        id (so the router can run the IDOR guard against the actual
        owning project rather than trusting the URL).
        """
        clash = await self._load_clash(clash_id)
        if clash is None:
            return None, None
        run = await self._load_run(clash.run_id)
        if run is None:
            return None, None
        project = await self._load_project(run.project_id)
        if project is None:
            return None, None

        positions = await self._positions_for_project(run.project_id)
        affected = self._affected_positions(clash, positions)
        payload, _ = self._compute_impact(clash, project, affected)
        payload["clash_id"] = clash.id
        return payload, run.project_id

    # ── Project rollup ─────────────────────────────────────────────────────

    async def rollup_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status_filter: str = "open",
    ) -> dict[str, Any] | None:
        """Sum of every (filtered) clash's cost impact for ``project_id``.

        Returns ``None`` when the project itself is missing (→ 404 on
        the router). Closed projects are still rolled up - coordination
        debt does not magically clear when the project status flips.
        """
        project = await self._load_project(project_id)
        if project is None:
            return None

        clashes = await self._open_clashes_for_project(project_id, status_filter=status_filter)
        if not clashes:
            return {
                "project_id": project.id,
                "currency": project.currency or "",
                "total_open_impact": 0.0,
                "clash_count": 0,
                "by_trade_pair": [],
            }

        # Fetch BOQ positions ONCE for the whole project rollup so we
        # do not N+1 over every clash.
        positions = await self._positions_for_project(project_id)

        total = Decimal("0")
        by_pair_total: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
        by_pair_count: dict[tuple[str, str], int] = defaultdict(int)

        for clash in clashes:
            affected = self._affected_positions(clash, positions)
            # Use the EXACT Decimal total (not the rounded float) so
            # per-clash 2-dp rounding does not accumulate into the
            # project rollup. Otherwise a 10⁴-clash mega-project drifts
            # by up to ``0.005 × N`` currency units - real money.
            _, clash_total = self._compute_impact(clash, project, affected)
            total += clash_total
            key = _pair_key(clash.a_discipline, clash.b_discipline)
            by_pair_total[key] += clash_total
            by_pair_count[key] += 1

        # Emit in a stable order - total desc, then alphabetical pair -
        # so the UI table is deterministic across page renders / tests.
        by_trade_pair = [
            {
                "pair": list(key),
                "count": by_pair_count[key],
                "total": _money_round(by_pair_total[key]),
            }
            for key in sorted(
                by_pair_total.keys(),
                key=lambda k: (-by_pair_total[k], k),
            )
        ]

        return {
            "project_id": project.id,
            "currency": project.currency or "",
            "total_open_impact": _money_round(total),
            "clash_count": len(clashes),
            "by_trade_pair": by_trade_pair,
        }
