"""Estimate rules applied to revisions (R6).

One BOQ per project, one position per rule. ``model`` positions are bound to the revision's elements through the ERP
quantity link (``oe_boq_quantity_link``): the element set is re-selected on every revision and the quantity is
computed by the ERP's own ``_compute_link_quantity``. ``derived`` positions evaluate a formula over aggregates.

A quantity a person changed (position quantity differs from what the rules last wrote) is an override: it is kept, the
model value is stored beside it and the position is flagged. A rule that matches nothing in a revision is flagged
``no_match`` and its quantity drops to zero unless overridden; the position is never deleted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core import cost_scope

from . import benchmarks, rules
from .models import DesignEstimate, DesignEstimateBinding, DesignEstimateRule, DesignRevision

DEPTH_PRICED = ("D3", "D4", "D5")  # from here positions priced from the ERP cost base replace the benchmark
ZERO = Decimal(0)


def _svc(session):
    from app.modules.boq.service import BOQService

    return BOQService(session)


def q4(value: Any) -> Decimal:
    from app.modules.boq.service import _quantize_money_str, _to_decimal

    return _to_decimal(_quantize_money_str(_to_decimal(value)))


def _round_currency(value: Any) -> Decimal:
    from app.modules.boq.service import _round_currency as rc

    return rc(value)


def dstr(value: Any) -> str:
    from app.modules.boq.service import _quantize_money_str

    return _quantize_money_str(value)


# ── rule sets ────────────────────────────────────────────────────────────────


async def install_rules(session, project_id: uuid.UUID, doc: dict[str, Any], user_id: uuid.UUID) -> DesignEstimate:
    """Store a validated rule document for the project (replacing rules of the same code, keeping bindings)."""
    rules.validate_document(doc)
    if not benchmarks.available(doc["country"], doc["use"]):
        # Rules without benchmarks are fine, but the range report would have nothing to show.
        pass
    est = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == project_id))
    ).scalar_one_or_none()
    if est is None:
        from app.modules.boq.schemas import BOQCreate

        boq = await _svc(session).create_boq(
            BOQCreate(
                project_id=project_id, name="Design estimate", description="Computed from model revisions by rules"
            )
        )
        est = DesignEstimate(
            project_id=project_id,
            boq_id=boq.id,
            country=doc["country"],
            use=doc["use"],
            aggregates=doc.get("aggregates") or {},
        )
        session.add(est)
    else:
        est.country, est.use, est.aggregates = doc["country"], doc["use"], doc.get("aggregates") or {}
    existing = {
        r.code: r
        for r in (
            await session.execute(select(DesignEstimateRule).where(DesignEstimateRule.project_id == project_id))
        ).scalars()
    }
    for i, body in enumerate(doc["rules"]):
        row = existing.get(body["id"])
        if row is None:
            session.add(
                DesignEstimateRule(project_id=project_id, code=body["id"], kind=body["kind"], body=body, sort_order=i)
            )
        else:
            row.kind, row.body, row.sort_order = body["kind"], body, i
    await session.flush()
    return est


# ── evaluation ──────────────────────────────────────────────────────────────


@dataclass
class Computed:
    quantity: Decimal
    element_keys: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    unit_rate: Decimal | None = None  # derived rules only, when a source gives one


async def load_elements(session, model_id: uuid.UUID) -> list[rules.Element]:
    from app.modules.bim_hub.models import BIMElement

    out: list[rules.Element] = []
    result = await session.stream_scalars(select(BIMElement).where(BIMElement.model_id == model_id))
    async for e in result:
        out.append(rules.Element.of(e))
    return out


def eval_aggregates(aggs: dict[str, Any], elements: list[rules.Element]) -> dict[str, dict[str, Any]]:
    out = {}
    for name, a in aggs.items():
        sel = rules.select(elements, a["select"])
        vals = [v for v in (rules.read_field(e, a["field"]) for e in sel) if v is not None]
        out[name] = {
            "value": rules.aggregate(vals, a["aggregation"]),
            "elements": len(sel),
            "assumption": a["assumption"],
            "label": a.get("label", name),
        }
    return out


async def eval_model_rule(
    session, body: dict[str, Any], elements: list[rules.Element], model_id: uuid.UUID
) -> Computed:
    sel = rules.select(elements, body["select"])
    keys = [e.key for e in sel]
    q = body["quantity"]
    prov = {"select": body["select"], "quantity": q, "elements": len(keys)}
    if not keys:
        return Computed(ZERO, [], ["no_match"], prov)
    value, _, missing = await _svc(session)._compute_link_quantity(
        model_id=model_id,
        stable_ids=keys,
        quantity_field=q.get("field") or "",
        aggregation=q.get("aggregation", "sum"),
        projection_mode="formula" if q.get("formula") else "field",
        formula=q.get("formula"),
    )
    flags: list[str] = []
    if missing:
        prov["elements_without_quantity"] = len(missing)
        flags.append("quantity_missing")
    return Computed(value, keys, flags, prov)


def eval_derived_rule(
    body: dict[str, Any], aggs: dict[str, dict[str, Any]], band: benchmarks.Band | None, wfl_basis: bool
) -> Computed:
    from app.modules.boq.quantity_formula import evaluate_formula

    variables: dict[str, Decimal] = {n: a["value"] for n, a in aggs.items()}
    prov: dict[str, Any] = {
        "formula": body["formula"],
        "aggregates": {
            n: {"value": str(a["value"]), "assumption": a["assumption"]}
            for n, a in aggs.items()
            if n in body["formula"]
        },
    }
    flags: list[str] = []
    for name, inp in (body.get("inputs") or {}).items():
        if inp["value"] is None:
            flags.append("input_missing")
        else:
            variables[name] = Decimal(str(inp["value"]))
            prov.setdefault("inputs", {})[name] = inp
    rate = body.get("rate")
    unit_rate: Decimal | None = None
    if rate is None:
        flags.append("rate_missing")
        prov["missing"] = body.get("missing", "")
        prov["missing_code"] = "rate_missing"
    elif "benchmark" in rate:
        if band is None:
            flags.append("rate_missing")
            prov["missing"] = "No sourced benchmark row with low, mid and high for this cost group."
            prov["missing_code"] = "benchmark_missing"
        else:
            unit_rate = band.mid
            prov["benchmark"] = {
                "low": str(band.low),
                "mid": str(band.mid),
                "high": str(band.high),
                "unit": band.unit,
                **band.source(),
            }
    else:
        unit_rate = Decimal(str(rate["value"]))
        prov["rate"] = rate
    if "input_missing" in flags:
        prov["missing"] = "An input of the formula has no published source."
        prov["missing_code"] = "input_missing"
        return Computed(ZERO, [], flags, prov, unit_rate)
    qty = evaluate_formula(body["formula"], variables)
    if qty == 0:
        flags.append("no_match")
    return Computed(qty, [], flags, prov, unit_rate)


async def evaluate(
    session, est: DesignEstimate, rule_rows: list[DesignEstimateRule], model_id: uuid.UUID
) -> tuple[dict[str, Computed], dict[str, dict[str, Any]]]:
    elements = await load_elements(session, model_id)
    aggs = eval_aggregates(est.aggregates or {}, elements)
    out: dict[str, Computed] = {}
    for r in rule_rows:
        if not r.enabled or r.kind == "manual":
            continue
        if r.kind == "model":
            out[r.code] = await eval_model_rule(session, r.body, elements, model_id)
        else:
            rate = r.body.get("rate") or {}
            band = None
            if "benchmark" in rate:
                b = rate["benchmark"]
                band = benchmarks.band(est.country, est.use, b["cost_group"], b["basis"])
            out[r.code] = eval_derived_rule(r.body, aggs, band, True)
    return out, aggs


# ── unit rates from the ERP cost database ───────────────────────────────────

COST_MIN_SCORE = 0.5  # lexical score below this is no match; a person can still pick any item
_UNIT_ALIAS = {
    "pcs": "pcs",
    "pc": "pcs",
    "stk": "pcs",
    "stk.": "pcs",
    "st": "pcs",
    "ea": "pcs",
    "each": "pcs",
    "stück": "pcs",
    "stueck": "pcs",
    "m²": "m2",
    "m³": "m3",
    "qm": "m2",
    "cbm": "m3",
}


def _unit_key(unit: str) -> str:
    u = (unit or "").strip().casefold()
    return _UNIT_ALIAS.get(u, u)


def cost_query(body: dict[str, Any], lang: str) -> str | None:
    q = body.get("cost_query")
    if isinstance(q, str):
        return q.strip() or None
    if isinstance(q, dict) and q:
        return (q.get(lang) or q.get("en") or next(iter(q.values())) or "").strip() or None
    return None


async def cost_regions(session, country: str, project_region: str | None) -> list[str]:
    """Regions of the loaded ERP cost databases that serve the estimate country (DE -> DE_BERLIN, DE_MUNICH, ...)."""
    from app.modules.costs.models import CostItem

    rows = (
        (
            await session.execute(
                select(CostItem.region).where(CostItem.is_active.is_(True), CostItem.region.isnot(None)).distinct()
            )
        )
        .scalars()
        .all()
    )
    loaded = sorted(r for r in rows if r)
    if project_region and project_region in loaded:
        return [project_region]
    c = country.upper()
    return [r for r in loaded if r.upper() == c or r.upper().startswith(c + "_")]


async def cost_provenance(session, item, *, auto: bool, score: float | None = None) -> dict[str, Any]:
    """What a person needs to see about a cost item: id, code, database, price date."""
    from app.modules.costs.models import CostCatalog

    name = None
    if item.catalog_id is not None:
        cat = await session.get(CostCatalog, item.catalog_id)
        name = cat.name if cat is not None else None
    md = item.metadata_ or {}
    version = md.get("version") or md.get("catalog_version") or md.get("db_version")
    out = {
        "cost_item_id": str(item.id),
        "code": item.code,
        "currency": item.currency,
        "unit": item.unit,
        "database": name or f"{item.source}:{item.region or '-'}",
        "source": item.source,
        "region": item.region,
        "version": str(version) if version else None,
        "price_date": item.price_as_of.isoformat() if item.price_as_of else None,
        "auto": auto,
    }
    if score is not None:
        out["score"] = round(score, 3)
    return out


async def resolve_cost_rate(
    session, project, est: DesignEstimate, body: dict[str, Any], unit: str
) -> tuple[Decimal, dict[str, Any]] | None:
    """Best ERP cost item for a rule in the project's region and currency, or None. Never invents a rate."""
    from app.core.match_service.region_language import language_for
    from app.modules.costs.matcher import match_cwicr_items

    currency = (getattr(project, "currency", None) or "").strip().upper()
    if not currency:
        return None
    best: tuple[float, Any] | None = None
    for region in await cost_regions(session, est.country, getattr(project, "region", None)):
        query = cost_query(body, language_for(region) or "en")
        if not query:
            return None
        for m in await match_cwicr_items(
            session, query, unit=unit, lang=language_for(region), top_k=8, mode="lexical", region=region, source=None
        ):
            if m.score < COST_MIN_SCORE or _unit_key(m.unit) != _unit_key(unit):
                continue
            if (m.currency or "").strip().upper() != currency or q4(m.unit_rate) <= 0:
                continue
            if best is None or m.score > best[0]:
                best = (m.score, m)
    if best is None:
        return None
    item = await cost_scope.get_cost_item(session, best[1].cost_item_id)
    if item is None or item.mass_basis:  # mass-priced items need the per-length conversion: pick by hand
        return None
    return q4(item.rate), await cost_provenance(session, item, auto=True, score=best[0])


# ── positions and bindings ──────────────────────────────────────────────────


async def _rule_rows(session, project_id: uuid.UUID) -> list[DesignEstimateRule]:
    return list(
        (
            await session.execute(
                select(DesignEstimateRule)
                .where(DesignEstimateRule.project_id == project_id, DesignEstimateRule.enabled.is_(True))
                .order_by(DesignEstimateRule.sort_order)
            )
        ).scalars()
    )


async def _bindings(session, project_id: uuid.UUID) -> dict[str, DesignEstimateBinding]:
    rows = (
        await session.execute(select(DesignEstimateBinding).where(DesignEstimateBinding.project_id == project_id))
    ).scalars()
    return {b.rule_code: b for b in rows}


async def _ensure_binding(session, est: DesignEstimate, rule: DesignEstimateRule, n: int) -> DesignEstimateBinding:
    from app.modules.boq.schemas import PositionCreate

    body = rule.body
    pos = await _svc(session).add_position(
        PositionCreate(
            boq_id=est.boq_id,
            ordinal=f"{body['cost_group']}.{n:03d}",
            description=body["label"],
            unit=body["unit"],
            quantity=0,
            unit_rate=Decimal(0),
            classification={est_classification(est): body["cost_group"]},
            source="cad_import",
            metadata={"design_rule": rule.code, "design_rule_kind": rule.kind},
        )
    )
    b = DesignEstimateBinding(
        project_id=est.project_id,
        rule_code=rule.code,
        kind=rule.kind,
        boq_id=est.boq_id,
        position_id=pos.id,
        element_keys=[],
        flags=[],
        provenance={},
    )
    session.add(b)
    await session.flush()
    return b


def _project_currency(project) -> str:
    return (getattr(project, "currency", None) or "").strip().upper()


def _drop_foreign_benchmark(est: DesignEstimate, project, c: Computed) -> None:
    """A benchmark in another currency than the project's is never written as a rate: no conversion is guessed."""
    if c.unit_rate is None or "benchmark" not in c.provenance:
        return
    cur, bench = _project_currency(project), (benchmarks.currency(est.country, est.use) or "").upper()
    if not cur or not bench or cur == bench:
        return
    c.unit_rate = None
    c.flags.append("rate_missing")
    c.provenance["missing"] = f"The benchmark is in {bench}, the project is in {cur}."
    c.provenance["missing_code"] = "currency_mismatch"


def est_classification(est: DesignEstimate) -> str:
    return "din276" if est.country == "DE" else "classification"


def _flags(computed: Computed, *, override: bool, unit_rate: Any) -> list[str]:
    flags = list(computed.flags)
    if override:
        flags.append("override")
    if q4(unit_rate) == 0 and "rate_missing" not in flags:
        flags.append("unpriced")
    return sorted(set(flags))


@dataclass
class Row:
    binding: DesignEstimateBinding
    rule: DesignEstimateRule
    position: Any
    computed: Computed
    override: bool = False


def _overridden(pos, b: DesignEstimateBinding, new_model: Decimal) -> bool:
    """A person set the quantity: it differs from what the rules wrote and from what they compute now."""
    if b.last_applied_quantity is None:
        return False
    cur = q4(pos.quantity)
    if b.model_quantity is not None and cur == q4(b.model_quantity):
        return False  # typed back to the model value it had: follows the model again
    return cur != q4(b.last_applied_quantity) and cur != q4(new_model)


def _live_override(pos, b: DesignEstimateBinding) -> bool:
    """A quantity edited after the last run counts at once, not only after the next run."""
    if b.model_quantity is None:
        return "override" in (b.flags or [])
    return _overridden(pos, b, Decimal(str(b.model_quantity)))


def _rate_edited(pos, b: DesignEstimateBinding) -> bool:
    """A unit rate a person typed: no rule or cost item wrote it, or it differs from what was written."""
    if b.kind == "manual" or q4(pos.unit_rate) == 0:
        return False
    dr = (pos.metadata_ or {}).get("design_rate")
    if not isinstance(dr, dict):
        return True
    applied = dr.get("applied")
    return applied is not None and q4(applied) != q4(pos.unit_rate)


def _live_flags(b: DesignEstimateBinding, override: bool, rate_edited: bool = False) -> list[str]:
    flags = [f for f in (b.flags or []) if f not in ("override", "rate_override")]
    return [*(["override"] if override else []), *(["rate_override"] if rate_edited else []), *flags]


async def recompute(
    session, project_id: uuid.UUID, rev_id: uuid.UUID, model_id: uuid.UUID, user_id: uuid.UUID
) -> list[Row]:
    """Make the positions follow the model of ``model_id`` (a revision): create, re-select, apply, flag."""
    est = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == project_id))
    ).scalar_one_or_none()
    if est is None:
        return []
    svc = _svc(session)
    rule_rows = await _rule_rows(session, project_id)
    bindings = await _bindings(session, project_id)
    computed, aggs = await evaluate(session, est, rule_rows, model_id)
    est.aggregate_values = {n: str(a["value"]) for n, a in aggs.items()}
    positions = {p.id: p for p in await svc.position_repo.list_by_ids([b.position_id for b in bindings.values()])}
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    counter: dict[str, int] = {}
    rows: list[Row] = []
    to_apply: list[Row] = []
    for rule in rule_rows:
        group = rule.body["cost_group"]
        counter[group] = counter.get(group, 0) + 1
        b = bindings.get(rule.code)
        if b is None:
            b = await _ensure_binding(session, est, rule, counter[group])
            positions[b.position_id] = await svc.position_repo.get_by_id(b.position_id)
        if rule.kind == "manual":
            continue
        pos, c = positions.get(b.position_id), computed[rule.code]
        _drop_foreign_benchmark(est, project, c)
        if pos is None:  # deleted in the BOQ module: not recreated, kept as a flagged binding
            b.model_quantity, b.element_keys, b.revision_id = dstr(c.quantity), c.element_keys, rev_id
            b.flags = ["position_deleted"]
            continue
        await _apply_cost_rate(session, svc, project, est, rule, pos, c)
        row = Row(b, rule, pos, c, _overridden(pos, b, c.quantity))
        rows.append(row)
        await _stamp_source(svc, pos, rule, rev_id, c, override=row.override)
        b.model_quantity, b.element_keys, b.revision_id, b.provenance = (
            dstr(c.quantity),
            c.element_keys,
            rev_id,
            c.provenance,
        )
        if rule.kind == "model" and c.element_keys:
            await _sync_link(svc, b, model_id, c, rule.body["quantity"], user_id)
            if not row.override:
                to_apply.append(row)
            continue
        if rule.kind == "model" and b.link_id is not None:
            await svc.quantity_link_repo.update_fields(b.link_id, element_stable_ids=[], status="broken")
        if not row.override:
            await _write_quantity(svc, b, pos, c.quantity)
            await _provenance(svc, pos, b, c)
            if c.unit_rate is not None and q4(pos.unit_rate) == 0:
                await _write_rate(svc, pos, c.unit_rate, c.provenance)
    if to_apply:
        res = await svc.apply_quantity_links(est.boq_id, [r.binding.link_id for r in to_apply], applied_by=user_id)
        skipped = [r for r in res.results if not r.applied]
        if skipped:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, f"Estimate links were not applied: {skipped[0].message}"
            )
        for r in to_apply:
            pos = await svc.position_repo.get_by_id(r.binding.position_id)
            await session.refresh(pos)
            r.position = pos
            r.binding.last_applied_quantity = dstr(pos.quantity)
    est.revision_id = rev_id
    for r in rows:
        r.binding.flags = _flags(r.computed, override=r.override, unit_rate=r.position.unit_rate)
    await session.flush()
    return rows


async def _apply_cost_rate(
    session, svc, project, est: DesignEstimate, rule: DesignEstimateRule, pos, c: Computed
) -> None:
    """Price an unpriced position from the ERP cost database; keep what is there; flag what is not found."""
    if q4(pos.unit_rate) == 0 and c.unit_rate is None:
        hit = await resolve_cost_rate(session, project, est, rule.body, pos.unit)
        if hit is None:
            c.flags.append("cost_no_match")
            return
        await _write_rate(svc, pos, hit[0], {"rate": hit[1]})
    dr = (pos.metadata_ or {}).get("design_rate")
    if not (isinstance(dr, dict) and (dr.get("cost_item_id") or dr.get("assembly_id"))):
        return
    c.flags[:] = [f for f in c.flags if f != "rate_missing"]
    for k in ("missing", "missing_code"):
        c.provenance.pop(k, None)
    c.provenance["cost_item"] = dr
    if dr.get("auto") and q4(dr.get("applied")) == q4(pos.unit_rate):
        c.flags.append("cost_auto")


async def _sync_link(
    svc, b: DesignEstimateBinding, model_id: uuid.UUID, c: Computed, q: dict[str, Any], user_id: uuid.UUID
):
    from app.modules.boq.schemas import QuantityLinkCreate

    mode = "formula" if q.get("formula") else "field"
    if b.link_id is None:
        link = await svc.create_quantity_link(
            b.position_id,
            QuantityLinkCreate(
                model_id=model_id,
                element_stable_ids=c.element_keys,
                quantity_field=q.get("field"),
                aggregation=q.get("aggregation", "sum"),
                projection_mode=mode,
                formula=q.get("formula"),
            ),
            created_by=user_id,
        )
        b.link_id = link.id
        return
    await svc.quantity_link_repo.update_fields(
        b.link_id, model_id=model_id, element_stable_ids=c.element_keys, status="stale"
    )


async def _write_quantity(svc, b: DesignEstimateBinding, pos, qty: Decimal) -> None:
    from app.modules.boq.service import _compute_total

    qs = dstr(qty)
    await svc.position_repo.update_fields(pos.id, quantity=qs, total=_compute_total(qs, pos.unit_rate))
    pos.quantity = qs
    b.last_applied_quantity = qs


async def _write_rate(svc, pos, rate: Decimal, prov: dict[str, Any]) -> None:
    from app.modules.boq.service import _compute_total

    rs = dstr(rate)
    meta = dict(pos.metadata_ or {})
    meta["design_rate"] = {**(prov.get("benchmark") or prov.get("rate") or {}), "applied": rs}
    if isinstance(meta.get("source"), dict):
        meta["source"] = {**meta["source"], "rate": meta["design_rate"]}
    await svc.position_repo.update_fields(pos.id, unit_rate=rs, total=_compute_total(pos.quantity, rs), metadata_=meta)
    pos.unit_rate, pos.metadata_ = rs, meta


async def _stamp_source(svc, pos, rule, rev_id, c: Computed, *, override: bool) -> None:
    """Neutral ``metadata.source`` on the position: what every module downstream copies to trace the number."""
    q = rule.body.get("quantity") or {}
    meta = dict(pos.metadata_ or {})
    meta["source"] = {
        "module": "oe_design",
        "revision_id": str(rev_id) if rev_id else None,
        "rule": rule.code,
        "kind": rule.kind,
        "quantity_field": q.get("field") if isinstance(q, dict) else None,
        "formula": (q.get("formula") if isinstance(q, dict) else None) or rule.body.get("formula"),
        "element_count": len(c.element_keys or []),
        "quantity_override": override,
        "rate": meta.get("design_rate"),
    }
    await svc.position_repo.update_fields(pos.id, metadata_=meta)
    pos.metadata_ = meta


async def _provenance(svc, pos, b: DesignEstimateBinding, c: Computed) -> None:
    meta = dict(pos.metadata_ or {})
    meta["design_derivation" if b.kind == "derived" else "design_selection"] = c.provenance
    await svc.position_repo.update_fields(pos.id, metadata_=meta)


async def recompute_on_accept(
    session, project_id: uuid.UUID, revision_id: uuid.UUID, model_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await recompute(session, project_id, revision_id, model_id, user_id)


# ── impact of a pending revision ────────────────────────────────────────────


def _keydiff(before: list[str], after: list[str]) -> dict[str, Any]:
    b, a = set(before), set(after)
    return {
        "before": len(before),
        "after": len(after),
        "added": sorted(a - b)[:20],
        "removed": sorted(b - a)[:20],
        "added_count": len(a - b),
        "removed_count": len(b - a),
    }


async def _diff_by_type(rev: DesignRevision) -> list[Any]:
    """The editor's per-type quantity deltas, when the package carries them (display only)."""
    import json

    from app.core.storage import get_storage_backend

    from .revisions import file_key

    try:
        raw = await get_storage_backend().get(file_key(rev.storage_prefix, "diff.json"))
        return json.loads(raw).get("by_type", [])
    except Exception:  # noqa: BLE001 - first revisions have no diff
        return []


def _impact_rate(position_rate: Any, rule_rate: Decimal | None) -> Decimal:
    """The rate accepting would leave: an unpriced position takes the rule's rate, a priced one keeps its own."""
    current = q4(position_rate or 0)
    return current if current != 0 else q4(rule_rate or 0)


async def impact(session, rev: DesignRevision) -> dict[str, Any]:
    """Position-level delta if ``rev`` were accepted now. Writes nothing."""
    est = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == rev.project_id))
    ).scalar_one_or_none()
    out: dict[str, Any] = {
        "schema": "ddc-impact/1",
        "revision_id": str(rev.id),
        "estimate": est is not None,
        "rows": [],
        "model_delta_by_type": await _diff_by_type(rev),
    }
    if est is None or rev.bim_model_id is None:
        return out
    svc = _svc(session)
    rule_rows = await _rule_rows(session, rev.project_id)
    bindings = await _bindings(session, rev.project_id)
    computed, _ = await evaluate(session, est, rule_rows, rev.bim_model_id)
    from app.modules.projects.models import Project

    project = await session.get(Project, rev.project_id)
    for c in computed.values():
        _drop_foreign_benchmark(est, project, c)
    out["currency"] = _project_currency(project) or None
    positions = {p.id: p for p in await svc.position_repo.list_by_ids([b.position_id for b in bindings.values()])}
    cur_total = new_total = ZERO
    unpriced = 0
    for rule in rule_rows:
        if rule.kind == "manual":
            continue
        b = bindings.get(rule.code)
        pos = positions.get(b.position_id) if b else None
        c = computed[rule.code]
        new_model = q4(c.quantity)
        cur_q = q4(pos.quantity) if pos is not None else ZERO
        override = bool(b and pos is not None and _overridden(pos, b, c.quantity))
        eff = cur_q if override else new_model
        rate = _impact_rate(pos.unit_rate if pos is not None else None, c.unit_rate)
        cur_total += cur_q * rate
        new_total += eff * rate
        if rate == 0:
            unpriced += 1
        out["rows"].append(
            {
                "rule": rule.code,
                "label": rule.body["label"],
                "cost_group": rule.body["cost_group"],
                "unit": rule.body["unit"],
                "position_id": str(pos.id) if pos is not None else None,
                "ordinal": pos.ordinal if pos is not None else None,
                "new_position": pos is None,
                "current_quantity": str(cur_q),
                "model_quantity_now": b.model_quantity if b else None,
                "model_quantity_new": str(new_model),
                "new_quantity": str(eff),
                "quantity_delta": str(eff - cur_q),
                "override": override,
                "override_quantity": str(cur_q) if override else None,
                "unit_rate": str(rate),
                "cost_delta": format((eff - cur_q) * rate, "f"),
                "flags": _flags(c, override=override, unit_rate=rate),
                "elements": _keydiff(b.element_keys if b else [], c.element_keys),
            }
        )
    out["rows"].sort(
        key=lambda r: (
            not r["override"],
            "no_match" not in r["flags"],
            Decimal(r["cost_delta"]) == 0,
            r["cost_group"],
            r["rule"],
        )
    )
    out["totals"] = {
        "current": format(cur_total, "f"),
        "after": format(new_total, "f"),
        "delta": format(new_total - cur_total, "f"),
        "unpriced_positions": unpriced,
    }
    return out


# ── summary with the benchmark range ────────────────────────────────────────

BENCH_GROUPS = ("200", "300+400", "500", "700")


def range_report(
    est: DesignEstimate, items: list[tuple[Any, DesignEstimateBinding, DesignEstimateRule]], depth_level: str | None
) -> dict[str, Any]:
    """Range per benchmark group and in total. Priced positions replace a group only at D3 and deeper."""
    wfl = Decimal(str((est.aggregate_values or {}).get("living_area_m2", "0")))
    by_group: dict[str, list[tuple[Any, DesignEstimateBinding, DesignEstimateRule]]] = {g: [] for g in BENCH_GROUPS}
    for it in items:
        g = benchmarks.group_for_din276(it[2].body["cost_group"])
        if g in by_group:
            by_group[g].append(it)
    groups: dict[str, Any] = {}
    low = mid = high = ZERO
    missing: list[str] = []
    for g in BENCH_GROUPS:
        members = by_group[g]
        covered = bool(members) and all(
            q4(p.unit_rate) > 0 and not ({"rate_missing", "input_missing", "no_match"} & set(b.flags or []))
            for p, b, _ in members
        )
        band = benchmarks.band(est.country, est.use, g, "WFL")
        if covered and depth_level in DEPTH_PRICED:
            tot = sum((q4(p.total) for p, _, _ in members), ZERO)
            groups[g] = {"source": "positions", "low": str(tot), "mid": str(tot), "high": str(tot)}
            low, mid, high = low + tot, mid + tot, high + tot
        elif band is not None and wfl > 0:
            lo, mi, hi = band.times(wfl)
            groups[g] = {
                "source": "benchmark",
                "low": str(lo),
                "mid": str(mi),
                "high": str(hi),
                "basis": f"{band.basis} {wfl} m2",
                "benchmark": band.source(),
            }
            low, mid, high = low + lo, mid + mi, high + hi
        else:
            groups[g] = {"source": None, "reason": "no sourced benchmark row" if band is None else "no living area"}
            missing.append(g)
    years = sorted({g["benchmark"]["price_level_year"] for g in groups.values() if g.get("source") == "benchmark"})
    used = {g["benchmark"]["source_url"] for g in groups.values() if g.get("source") == "benchmark"}
    return {
        "currency": benchmarks.currency(est.country, est.use),
        "basis_living_area_m2": str(wfl),
        "groups": groups,
        "sources_not_used": benchmarks.unused(est.country, est.use, used),
        "missing_groups": missing,
        "total": {"low": str(low), "mid": str(mid), "high": str(high), "complete": not missing},
        "price_level_years": years,
        "not_in_range": ["100", "600"],
        "note": "Cost groups 100 and 600 have no sourced benchmark and are not part of the range.",
    }


async def summary(session, project_id: uuid.UUID) -> dict[str, Any]:
    est = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == project_id))
    ).scalar_one_or_none()
    if est is None:
        return {"estimate": False}
    svc = _svc(session)
    rule_rows = {r.code: r for r in await _rule_rows(session, project_id)}
    bindings = await _bindings(session, project_id)
    positions = {p.id: p for p in await svc.position_repo.list_by_ids([b.position_id for b in bindings.values()])}
    items = [
        (positions[b.position_id], b, rule_rows[c])
        for c, b in bindings.items()
        if c in rule_rows and b.position_id in positions
    ]
    items.sort(key=lambda it: it[0].ordinal)
    from app.modules.projects.models import Project

    proj = await session.get(Project, project_id)
    rev = await session.get(DesignRevision, est.revision_id) if est.revision_id else None
    depth = (rev.depth_level or None) if rev is not None else None  # "" = a wrapped import nobody rated
    total = sum((q4(p.total) for p, _, _ in items), ZERO)
    unpriced = [r.code for p, b, r in items if q4(p.unit_rate) == 0]
    rng = range_report(est, items, depth)
    t = rng["total"]
    currency = _project_currency(proj) or None
    same_currency = not currency or not rng["currency"] or currency == rng["currency"].upper()
    complete = not unpriced and rng["total"]["complete"] and same_currency
    inside: bool | None = None
    if complete:
        inside = Decimal(t["low"]) <= total <= Decimal(t["high"])
    note_code = None if complete else ("unpriced_or_unsourced" if same_currency else "currency_mismatch")
    bt = (await svc.compute_boq_totals([est.boq_id])).get(est.boq_id) or {}
    boq_totals = {
        k: format(_round_currency(bt.get(k)), "f") for k in ("direct_cost", "markups_total", "grand_total")
    } | {"currency": bt.get("base_currency") or currency}
    return {
        "estimate": True,
        "boq_id": str(est.boq_id),
        "revision_id": str(est.revision_id) if est.revision_id else None,
        "depth_level": depth,
        "country": est.country,
        "use": est.use,
        "currency": currency,
        "boq": boq_totals,
        "cost_regions": await cost_regions(session, est.country, getattr(proj, "region", None)),
        "positions": [
            {
                "rule": r.code,
                "kind": r.kind,
                "position_id": str(p.id),
                "ordinal": p.ordinal,
                "description": p.description,
                "cost_group": r.body["cost_group"],
                "unit": p.unit,
                "quantity": p.quantity,
                "unit_rate": p.unit_rate,
                "total": p.total,
                "model_quantity": b.model_quantity,
                "override": (o := _live_override(p, b)),
                "override_quantity": p.quantity if o else None,
                "override_reason": b.override_reason,
                "flags": _live_flags(b, o, _rate_edited(p, b)),
                "elements": len(b.element_keys or []),
                "provenance": b.provenance,
            }
            for p, b, r in items
        ],
        "total": str(total),
        "unpriced_positions": unpriced,
        "range": rng,
        "inside_range": inside,
        "inside_range_note_code": note_code,
        "inside_range_note": None
        if complete
        else (
            "Not comparable: some positions are unpriced or a range group has no sourced benchmark."
            if same_currency
            else "Not comparable: the benchmark range is in another currency than the project."
        ),
    }


# ── edits by people ─────────────────────────────────────────────────────────


async def _binding_of(session, project_id: uuid.UUID, position_id: uuid.UUID) -> DesignEstimateBinding:
    b = (
        await session.execute(
            select(DesignEstimateBinding).where(
                DesignEstimateBinding.project_id == project_id, DesignEstimateBinding.position_id == position_id
            )
        )
    ).scalar_one_or_none()
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position is not bound to a design rule")
    return b


async def set_override_reason(session, project_id: uuid.UUID, position_id: uuid.UUID, reason: str) -> None:
    (await _binding_of(session, project_id, position_id)).override_reason = reason.strip() or None


async def price_position(
    session,
    project_id: uuid.UUID,
    position_id: uuid.UUID,
    *,
    cost_item_id: uuid.UUID | None,
    unit_rate: Decimal | None,
    source_url: str | None,
    price_date: str | None,
    currency: str | None = None,
    assembly_id: uuid.UUID | None = None,
    via: dict[str, Any] | None = None,
) -> None:
    """Price a position from an ERP cost item or assembly, or from an explicit rate that names its source and date.

    ``via`` records how a person got to the item (Cost Match run/result/decision) and is kept in the provenance.

    The rate must be in the project currency: the estimate sums positions, a rate in another currency would be
    added as if it were the same.
    """
    from app.modules.projects.models import Project

    b = await _binding_of(session, project_id, position_id)
    svc = _svc(session)
    pos = await svc.position_repo.get_by_id(position_id)
    project = await session.get(Project, project_id)
    project_currency = (getattr(project, "currency", None) or "").strip().upper()

    def _same_currency(code: str | None) -> None:
        if code and project_currency and code.strip().upper() != project_currency:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"The rate is in {code.strip().upper()}, the project is in {project_currency}",
            )

    if cost_item_id is not None:
        item = await cost_scope.get_cost_item(session, cost_item_id)
        if item is None or not item.is_active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Cost item not found or inactive")
        if item.unit.strip().casefold() != pos.unit.strip().casefold():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Cost item unit '{item.unit}' differs from the position unit '{pos.unit}'",
            )
        _same_currency(item.currency)
        rate, prov = q4(item.rate), await cost_provenance(session, item, auto=False)
        if via:
            prov["via"] = via
    elif assembly_id is not None:
        from app.modules.assemblies.models import Assembly

        asm = await session.get(Assembly, assembly_id)
        if asm is None or not asm.is_active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Assembly not found or inactive")
        if asm.unit.strip().casefold() != pos.unit.strip().casefold():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Assembly unit '{asm.unit}' differs from the position unit '{pos.unit}'",
            )
        if not (asm.currency or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The assembly names no currency")
        _same_currency(asm.currency)
        rate = q4(asm.total_rate)
        if rate <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The assembly has no rate")
        prov = {
            "assembly_id": str(asm.id),
            "code": asm.code,
            "name": asm.name,
            "currency": asm.currency,
            "unit": asm.unit,
            "database": "assemblies",
            "source": "assembly",
            "region": None,
            "version": None,
            "price_date": None,
            "auto": False,
        }
    else:
        if unit_rate is None or not source_url or not price_date:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Give a cost_item_id, or unit_rate with source_url and price_date",
            )
        _same_currency(currency)
        rate, prov = q4(unit_rate), {"source_url": source_url, "price_date": price_date}
    await _write_rate(svc, pos, rate, {"rate": prov})
    if cost_item_id is not None or assembly_id is not None:  # shown at once, not only after the next run
        shown = {k: v for k, v in (b.provenance or {}).items() if k not in ("missing", "missing_code")}
        b.provenance = {**shown, "cost_item": prov}
    b.flags = [f for f in (b.flags or []) if f not in ("unpriced", "rate_missing", "cost_no_match", "cost_auto")]
