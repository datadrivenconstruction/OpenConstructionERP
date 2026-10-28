# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠CPM under explicit scheduling options (a scheduling profile).

The plain pass in :func:`app.core.cpm.calculate_cpm` plans: it knows no data
date, no actuals, lags run in elapsed days and every activity without a
successor is bound to the project finish. A progressed programme needs the
choices a planner makes explicitly, and this pass honours them:

* ``progress_mode`` - how a started activity's remaining work is placed:
  ``retained_logic`` (remaining work still waits for open predecessors),
  ``progress_override`` (remaining work runs from the data date, open
  predecessor logic is ignored for it) or ``actual_dates`` (the planned
  duration runs from the actual start, the data date is not consulted);
* ``lag_calendar`` - which calendar a lag is counted on: ``elapsed`` (calendar
  days, the plain pass's rule), the ``predecessor``'s, the ``successor``'s or
  the ``project`` calendar;
* ``open_ends`` - an activity without a successor is bound to the
  ``project_finish``, or to its ``own_finish`` (zero float, so a dangling end
  shows up as critical instead of hiding behind project float);
* ``critical_rule`` - ``total_float`` (float at or below a threshold, in
  working days) or ``longest_path`` (the driving chain to the latest finish).

Offsets are calendar days from the project origin, as in the plain pass, and
the same day-stepping helpers are used, so a profile with every option at its
default and no progress gives the plain pass's early dates for FS and SS
links. FF and SF links count the successor's duration in working days here,
where the plain pass subtracts it in calendar days. Float is reported in
working days of the activity's own calendar, which is what a threshold means
to a planner. Pure and stateless.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from app.core.cpm import (
    _add_working_days,
    _parse_exceptions,
    _parse_work_days,
    _snap_to_working_day,
    _sub_working_days,
    _working_days_between,
)

PROGRESS_MODES: tuple[str, ...] = ("retained_logic", "progress_override", "actual_dates")
LAG_CALENDARS: tuple[str, ...] = ("elapsed", "predecessor", "successor", "project")
OPEN_END_RULES: tuple[str, ...] = ("project_finish", "own_finish")
CRITICAL_RULES: tuple[str, ...] = ("total_float", "longest_path")

_Calendar = tuple[set[int], set[date]]


@dataclass(frozen=True)
class ActivityStatus:
    """Progress of one activity as of the data date.

    Attributes:
        actual_start: Offset of the day work actually started.
        actual_finish: Offset of the last day worked (inclusive).
        percent_complete: 0..100, used for the remaining duration when
            ``remaining_duration`` is not given.
        remaining_duration: Remaining working days, wins over the percent.
    """

    actual_start: int | None = None
    actual_finish: int | None = None
    percent_complete: float = 0.0
    remaining_duration: int | None = None

    @property
    def finished(self) -> bool:
        return self.actual_finish is not None or self.percent_complete >= 100.0

    @property
    def started(self) -> bool:
        return self.actual_start is not None or self.finished or self.percent_complete > 0.0


@dataclass(frozen=True)
class SchedulingOptions:
    """The settings of one scheduling profile plus the status to apply."""

    progress_mode: str = "retained_logic"
    lag_calendar: str = "elapsed"
    open_ends: str = "project_finish"
    critical_rule: str = "total_float"
    critical_float_threshold: int = 0
    data_date: int | None = None
    status: Mapping[str, ActivityStatus] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, allowed in (
            ("progress_mode", PROGRESS_MODES),
            ("lag_calendar", LAG_CALENDARS),
            ("open_ends", OPEN_END_RULES),
            ("critical_rule", CRITICAL_RULES),
        ):
            if getattr(self, name) not in allowed:
                raise ValueError(f"{name} must be one of {allowed}, got {getattr(self, name)!r}")


def remaining_working_days(status: ActivityStatus | None, duration: int) -> int:
    """Remaining working days, clamped to ``[0, duration]``."""
    if status is None:
        return duration
    if status.finished:
        return 0
    if status.remaining_duration is not None:
        return max(0, min(duration, int(status.remaining_duration)))
    pct = max(0.0, min(100.0, float(status.percent_complete)))
    return max(0, min(duration, round(duration * (1.0 - pct / 100.0))))


def _signed_working_days(start: int, end: int, cal: _Calendar, origin: date) -> int:
    if end >= start:
        return _working_days_between(start, end, cal[0], cal[1], origin)
    return -_working_days_between(end, start, cal[0], cal[1], origin)


class _Engine:
    """One run of the profile pass; holds the parsed network."""

    def __init__(
        self,
        activities: list[dict],
        relationships: list[dict],
        calendar: dict | None,
        origin: date,
        options: SchedulingOptions,
    ) -> None:
        self.origin = origin
        self.options = options
        self.project_cal: _Calendar = (_parse_work_days(calendar), _parse_exceptions(calendar))
        self.acts: dict[str, dict] = {}
        for act in activities:
            aid = str(act["id"])
            if aid in self.acts:
                continue
            own = act.get("calendar")
            cal = (_parse_work_days(own), _parse_exceptions(own)) if own else self.project_cal
            self.acts[aid] = {
                "id": aid,
                "name": act.get("name", ""),
                "duration": max(int(act.get("duration", 0) or 0), 0),
                "start_offset": max(int(act.get("start_offset", 0) or 0), 0),
                "cal": cal,
            }
        self.preds: dict[str, list[dict]] = defaultdict(list)
        self.succs: dict[str, list[dict]] = defaultdict(list)
        for rel in relationships:
            pred_id = str(rel.get("predecessor_id", ""))
            succ_id = str(rel.get("successor_id", ""))
            if pred_id not in self.acts or succ_id not in self.acts or pred_id == succ_id:
                continue
            link = {
                "pred": pred_id,
                "succ": succ_id,
                "type": str(rel.get("type", rel.get("relationship_type", "FS")) or "FS").upper(),
                "lag": int(rel.get("lag", rel.get("lag_days", 0)) or 0),
            }
            self.preds[succ_id].append(link)
            self.succs[pred_id].append(link)

    # ── Calendar helpers ──────────────────────────────────────────────────

    def _snap(self, offset: int, cal: _Calendar) -> int:
        return _snap_to_working_day(offset, cal[0], cal[1], self.origin)

    def _add(self, start: int, days: int, cal: _Calendar) -> int:
        return _add_working_days(start, days, cal[0], cal[1], self.origin)

    def _sub(self, end: int, days: int, cal: _Calendar) -> int:
        return _sub_working_days(end, days, cal[0], cal[1], self.origin)

    def _lag_cal(self, link: dict) -> _Calendar | None:
        rule = self.options.lag_calendar
        if rule == "predecessor":
            return self.acts[link["pred"]]["cal"]
        if rule == "successor":
            return self.acts[link["succ"]]["cal"]
        if rule == "project":
            return self.project_cal
        return None

    def _shift(self, anchor: int, link: dict) -> int:
        """Apply a link's lag forward on the lag calendar."""
        lag = link["lag"]
        cal = self._lag_cal(link)
        if cal is None or lag == 0:
            return anchor + lag
        if lag > 0:
            return self._add(self._snap(anchor, cal), lag, cal)
        return self._sub(anchor, -lag, cal)

    def _unshift(self, anchor: int, link: dict) -> int:
        """Remove a link's lag backward, the mirror of :meth:`_shift`."""
        lag = link["lag"]
        cal = self._lag_cal(link)
        if cal is None or lag == 0:
            return anchor - lag
        if lag > 0:
            return self._sub(anchor, lag, cal)
        return self._add(self._snap(anchor, cal), -lag, cal)

    # ── Passes ────────────────────────────────────────────────────────────

    def topo_order(self) -> list[str]:
        in_degree = {aid: len(self.preds[aid]) for aid in self.acts}
        queue = sorted(aid for aid, deg in in_degree.items() if deg == 0)
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            released = []
            for link in self.succs[current]:
                in_degree[link["succ"]] -= 1
                if in_degree[link["succ"]] == 0:
                    released.append(link["succ"])
            queue = sorted(queue + released)
        if len(order) < len(self.acts):
            order.extend(aid for aid in self.acts if aid not in set(order))
        return order

    def run(self) -> list[dict]:
        opts = self.options
        dd = opts.data_date
        order = self.topo_order()
        res: dict[str, dict] = {}
        drivers: dict[str, list[str]] = {}

        for aid in order:
            act = self.acts[aid]
            cal, dur = act["cal"], act["duration"]
            st = opts.status.get(aid)
            logic_es = act["start_offset"]
            candidates: list[tuple[str, int]] = []
            for link in self.preds[aid]:
                if link["pred"] not in res:
                    continue
                pred = res[link["pred"]]
                kind = link["type"]
                if kind == "SS":
                    cand = self._shift(pred["early_start"], link)
                elif kind == "FF":
                    cand = self._sub(self._shift(pred["early_finish"], link), dur, cal)
                elif kind == "SF":
                    cand = self._sub(self._shift(pred["early_start"], link), dur, cal)
                else:
                    cand = self._shift(pred["early_finish"], link)
                candidates.append((link["pred"], cand))
                logic_es = max(logic_es, cand)

            finished = st is not None and st.finished
            started = st is not None and st.started
            rem = remaining_working_days(st, dur)
            binding = logic_es

            if finished:
                assert st is not None
                if st.actual_finish is not None:
                    ef = self._snap(st.actual_finish + 1, cal)
                elif dd is not None:
                    ef = dd
                else:
                    ef = self._add(self._snap(logic_es, cal), dur, cal)
                es = st.actual_start if st.actual_start is not None else self._sub(ef, dur, cal)
                binding = None
            elif started:
                assert st is not None
                es = st.actual_start if st.actual_start is not None else (dd if dd is not None else logic_es)
                if opts.progress_mode == "actual_dates":
                    ef = self._add(self._snap(es, cal), dur, cal)
                    binding = None
                elif opts.progress_mode == "progress_override":
                    rem_start = dd if dd is not None else es
                    ef = self._add(self._snap(rem_start, cal), rem, cal)
                    binding = None
                else:
                    floor = dd if dd is not None else es
                    rem_start = max(floor, logic_es)
                    ef = self._add(self._snap(rem_start, cal), rem, cal)
                    if rem_start != logic_es:
                        binding = None
                ef = max(ef, es)
            else:
                start = logic_es if dd is None else max(logic_es, dd)
                if start != logic_es:
                    binding = None
                es = max(self._snap(start, cal), 0)
                ef = self._add(es, dur, cal)

            drivers[aid] = [pid for pid, cand in candidates if binding is not None and cand == binding]
            res[aid] = {
                "id": aid,
                "name": act["name"],
                "duration": dur,
                "early_start": es,
                "early_finish": ef,
                "completed": finished,
                "started": started and not finished,
                "remaining_duration": rem,
                "out_of_sequence": False,
                "open_start": not self.preds[aid],
                "open_finish": not self.succs[aid],
            }

        for aid in order:
            st = opts.status.get(aid)
            if st is None or not st.started:
                continue
            for link in self.preds[aid]:
                if link["type"] not in ("FS", "SF"):
                    continue
                pst = opts.status.get(link["pred"])
                if pst is None or not pst.finished:
                    res[aid]["out_of_sequence"] = True
                    break

        project_finish = max((r["early_finish"] for r in res.values() if not r["completed"]), default=0)
        if not any(not r["completed"] for r in res.values()):
            project_finish = max((r["early_finish"] for r in res.values()), default=0)

        for aid in reversed(order):
            act, r = self.acts[aid], res[aid]
            cal = act["cal"]
            if r["completed"]:
                r["late_start"], r["late_finish"] = r["early_start"], r["early_finish"]
                continue
            work = r["remaining_duration"] if r["started"] else act["duration"]
            bounds: list[int] = []
            for link in self.succs[aid]:
                succ = res[link["succ"]]
                if succ["completed"] or "late_start" not in succ:
                    continue
                kind = link["type"]
                if kind == "SS":
                    bounds.append(self._add(self._snap(self._unshift(succ["late_start"], link), cal), work, cal))
                elif kind == "FF":
                    bounds.append(self._unshift(succ["late_finish"], link))
                elif kind == "SF":
                    bounds.append(self._add(self._snap(self._unshift(succ["late_finish"], link), cal), work, cal))
                else:
                    bounds.append(self._unshift(succ["late_start"], link))
            if bounds:
                lf = min(bounds)
            elif opts.open_ends == "own_finish" and not self.succs[aid]:
                lf = r["early_finish"]
            else:
                lf = project_finish
            r["late_finish"] = lf
            r["late_start"] = self._sub(lf, work, cal)

        for aid in order:
            act, r = self.acts[aid], res[aid]
            cal = act["cal"]
            if r["completed"]:
                r["total_float"] = 0
                r["free_float"] = 0
                continue
            if r["started"]:
                r["total_float"] = _signed_working_days(r["early_finish"], r["late_finish"], cal, self.origin)
            else:
                r["total_float"] = _signed_working_days(r["early_start"], r["late_start"], cal, self.origin)
            slacks: list[int] = []
            for link in self.succs[aid]:
                succ = res[link["succ"]]
                if succ["completed"]:
                    continue
                kind = link["type"]
                if kind == "SS":
                    slacks.append(
                        _signed_working_days(self._shift(r["early_start"], link), succ["early_start"], cal, self.origin)
                    )
                elif kind == "FF":
                    slacks.append(
                        _signed_working_days(
                            self._shift(r["early_finish"], link), succ["early_finish"], cal, self.origin
                        )
                    )
                elif kind == "SF":
                    slacks.append(
                        _signed_working_days(
                            self._shift(r["early_start"], link), succ["early_finish"], cal, self.origin
                        )
                    )
                else:
                    slacks.append(
                        _signed_working_days(
                            self._shift(r["early_finish"], link), succ["early_start"], cal, self.origin
                        )
                    )
            r["free_float"] = max(min(slacks), 0) if slacks else max(r["total_float"], 0)

        longest: set[str] = set()
        seeds = [aid for aid in order if not res[aid]["completed"] and res[aid]["early_finish"] == project_finish]
        stack = list(seeds)
        while stack:
            aid = stack.pop()
            if aid in longest:
                continue
            longest.add(aid)
            stack.extend(p for p in drivers.get(aid, []) if not res[p]["completed"])

        for aid in order:
            r = res[aid]
            r["on_longest_path"] = aid in longest
            r["driving_predecessors"] = drivers.get(aid, [])
            if r["completed"]:
                r["is_critical"] = False
            elif opts.critical_rule == "longest_path":
                r["is_critical"] = aid in longest
            else:
                r["is_critical"] = r["total_float"] <= opts.critical_float_threshold
        return [res[aid] for aid in self.acts]


def calculate_cpm_with_options(
    activities: list[dict],
    relationships: list[dict],
    *,
    calendar: dict | None,
    project_start: date,
    options: SchedulingOptions,
) -> list[dict]:
    """Run the forward and backward pass under ``options``.

    Takes the activity and relationship dicts of
    :func:`app.core.cpm.calculate_cpm`. Returns one dict per activity, in input
    order, with the plain pass's keys (offsets, ``total_float``,
    ``free_float``, ``is_critical``) plus ``completed``, ``started``,
    ``remaining_duration``, ``out_of_sequence``, ``open_start``,
    ``open_finish``, ``on_longest_path`` and ``driving_predecessors``.
    """
    if not activities:
        return []
    return _Engine(activities, relationships, calendar, project_start, options).run()
