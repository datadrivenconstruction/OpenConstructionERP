# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure compute-orchestration for forensic delay analysis (T2.2).

This sits between the persistence layer (the stored ``DelayAnalysis`` /
``DelayEvent`` / ``Fragnet`` rows) and the pure :mod:`delay_engine`. It maps
stored specs (plain dicts, exactly as the ORM/JSON columns hold them) into
engine objects, dispatches the chosen forensic method, and returns an
exhibit-ready ``result_json`` dict.

It is intentionally pure and DB-free (mirrors :mod:`cpm_report` and
:mod:`schedule.snapshot_envelope`) so the whole compute path is unit-testable
on the local interpreter; the service layer only loads activity rows + the
stored specs, calls :func:`run_analysis`, and persists the windows + the
returned dict.
"""

from __future__ import annotations

from typing import Any

from .cpm import Activity, TaskNetwork, critical_path
from .delay_engine import (
    DelayEvent,
    Fragnet,
    RewireOp,
    apply_fragnets,
    attribute,
    project_finish,
    run_apvab,
    run_cab,
    run_iap,
    run_tia,
    run_windows,
)

__all__ = [
    "build_engine_event",
    "build_engine_fragnet",
    "run_analysis",
]

# Method codes accepted by :func:`run_analysis` (stored on DelayAnalysis.method).
_METHODS = (
    "tia",
    "windows",
    "as_planned_vs_as_built",
    "impacted_as_planned",
    "collapsed_as_built",
)


def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build_engine_fragnet(d: dict[str, Any]) -> Fragnet:
    """Map a stored fragnet dict into an engine :class:`delay_engine.Fragnet`."""
    rewires = tuple(
        RewireOp(
            successor_id=rw["successor_id"],
            pred_id=rw["pred_id"],
            op=rw.get("op", "redirect_from_host"),
            dep_type=rw.get("dep_type", "FS"),
            lag=int(rw.get("lag", 0)),
        )
        for rw in (d.get("rewires") or [])
        if isinstance(rw, dict) and "successor_id" in rw and "pred_id" in rw
    )
    new_activities = tuple(d.get("fragnet_activities") or ())
    return Fragnet(
        insert_mode=d.get("insert_mode", "lengthen_activity"),
        host_id=d.get("host_id") or d.get("insert_at_activity_ref"),
        added_duration_days=int(d.get("added_duration_days", 0) or 0),
        new_activities=new_activities,
        rewires=rewires,
    )


def build_engine_event(d: dict[str, Any]) -> DelayEvent:
    """Map a stored event dict into an engine :class:`delay_engine.DelayEvent`."""
    fragnets = tuple(build_engine_fragnet(f) for f in (d.get("fragnets") or []) if isinstance(f, dict))
    insert_at = d.get("insert_at")
    if insert_at is None and fragnets:
        insert_at = fragnets[0].host_id
    return DelayEvent(
        id=d.get("id"),
        insert_at=insert_at,
        responsibility=d.get("responsibility", "employer"),
        is_concurrent=bool(d.get("is_concurrent", False)),
        is_pacing=bool(d.get("is_pacing", False)),
        event_start=_int_or_none(d.get("event_start")),
        event_end=_int_or_none(d.get("event_end")),
        fragnets=fragnets,
    )


def _all_fragnets(events: list[DelayEvent], *, responsibilities: tuple[str, ...] | None = None) -> list[Fragnet]:
    out: list[Fragnet] = []
    for e in events:
        if responsibilities is not None and e.responsibility not in responsibilities:
            continue
        out.extend(e.fragnets)
    return out


def _attr_dict(a: Any) -> dict[str, int]:
    return {
        "employer_days": a.employer_days,
        "contractor_days": a.contractor_days,
        "neutral_days": a.neutral_days,
        "concurrent_days": a.concurrent_days,
        "net_entitlement_days": a.net_entitlement_days,
    }


def _concurrency(result: dict[str, Any]) -> dict[str, Any]:
    """Concurrent employer/contractor delay in one place, for a plain-words note in the exhibit."""
    if result.get("windows"):
        days = sum(int(w.get("concurrent_days") or 0) for w in result["windows"])
    else:
        days = int((result.get("attribution") or {}).get("concurrent_days") or 0)
    return {"present": days > 0, "days": days, "apportionment": result.get("apportionment")}


def run_analysis(
    method: str,
    *,
    baseline_activities: list[Activity] | None = None,
    asbuilt_activities: list[Activity] | None = None,
    events: list[dict[str, Any]] | None = None,
    apportionment: str = "malmaison",
    snapshots: list[list[Activity]] | None = None,
    window_bounds: list[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Run the chosen forensic method and return an exhibit-ready result dict.

    Args:
        method: One of ``tia``, ``windows``, ``as_planned_vs_as_built``,
            ``impacted_as_planned``, ``collapsed_as_built``.
        baseline_activities: The as-planned network (TIA/IAP/APvAB).
        asbuilt_activities: The as-built network (APvAB/CAB).
        events: Stored event specs (dicts) with their fragnets.
        apportionment: Apportionment method for concurrent critical events.
        snapshots: Ordered dated activity lists for the Windows method.
        window_bounds: Optional explicit ``(open, close)`` work-day bounds per
            window (Windows method).

    Returns:
        A JSON-serialisable dict (the cached ``result_json`` / exhibit payload).

    Raises:
        ValueError: on an unknown method.
        cpm.CycleError: if a spliced network contains a logic cycle.
    """
    if method not in _METHODS:
        raise ValueError(f"Unknown delay-analysis method: {method!r}")

    engine_events = [build_engine_event(e) for e in (events or [])]
    base = list(baseline_activities or [])
    built = list(asbuilt_activities or [])

    result: dict[str, Any] = {"method": method, "apportionment": apportionment}

    if method == "tia":
        finish0 = project_finish(TaskNetwork(base)) if base else 0
        all_frag = _all_fragnets(engine_events)
        impacted_net = apply_fragnets(base, all_frag) if base else TaskNetwork([])
        finish1 = project_finish(impacted_net) if base else 0
        crit0 = set(critical_path(TaskNetwork(base))) if base else set()
        crit1 = set(critical_path(impacted_net)) if base else set()
        gross = max(0, finish1 - finish0)
        attr = attribute(gross, engine_events, impacted_net, method=apportionment)
        per_event = []
        for e in engine_events:
            r = run_tia(base, e) if base else None
            per_event.append(
                {
                    "event_id": e.id,
                    "responsibility": e.responsibility,
                    "entitlement_days": (r.entitlement_days if r else 0),
                    "critical_path_impact": (r.critical_path_impact if r else False),
                    "drove_completion": (r.drove_completion if r else False),
                }
            )
        result.update(
            {
                "baseline_finish": finish0,
                "impacted_finish": finish1,
                "total_entitlement_days": attr.net_entitlement_days,
                "gross_slip_days": gross,
                "attribution": _attr_dict(attr),
                "baseline_critical": sorted(map(str, crit0)),
                "impacted_critical": sorted(map(str, crit1)),
                "newly_critical": sorted(map(str, crit1 - crit0)),
                "events": per_event,
            }
        )

    elif method == "impacted_as_planned":
        emp_frag = _all_fragnets(engine_events, responsibilities=("employer",))
        r = run_iap(base, emp_frag)
        result.update(
            {
                "baseline_finish": r.reference_finish,
                "impacted_finish": r.modelled_finish,
                "total_entitlement_days": r.entitlement_days,
            }
        )

    elif method == "collapsed_as_built":
        emp_frag = _all_fragnets(engine_events, responsibilities=("employer",))
        r = run_cab(built, emp_frag)
        result.update(
            {
                "asbuilt_finish": r.reference_finish,
                "collapsed_finish": r.modelled_finish,
                "total_entitlement_days": r.entitlement_days,
            }
        )

    elif method == "as_planned_vs_as_built":
        net_slip, attr = run_apvab(base, built, engine_events, method=apportionment)
        result.update(
            {
                "baseline_finish": project_finish(TaskNetwork(base)) if base else 0,
                "asbuilt_finish": project_finish(TaskNetwork(built)) if built else 0,
                "net_slip_days": net_slip,
                "total_entitlement_days": attr.net_entitlement_days,
                "attribution": _attr_dict(attr),
            }
        )

    else:  # windows
        wins = run_windows(snapshots or [], engine_events, method=apportionment, window_bounds=window_bounds)
        result.update(
            {
                "total_entitlement_days": wins.total_entitlement_days,
                "total_gross_slip_days": wins.total_gross_slip_days,
                "window_count": len(wins.windows),
                "windows": [
                    {
                        "sequence_order": w.sequence_order,
                        "finish_at_open": w.finish_at_open,
                        "finish_at_close": w.finish_at_close,
                        "gross_slip_days": w.gross_slip_days,
                        "employer_days": w.employer_days,
                        "contractor_days": w.contractor_days,
                        "neutral_days": w.neutral_days,
                        "concurrent_days": w.concurrent_days,
                        "net_entitlement_days": w.net_entitlement_days,
                        "driving_event_ids": [str(i) for i in w.driving_event_ids],
                    }
                    for w in wins.windows
                ],
            }
        )

    result["concurrency"] = _concurrency(result)
    return result
