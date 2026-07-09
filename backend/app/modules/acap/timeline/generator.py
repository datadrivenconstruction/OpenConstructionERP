# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""ACAP construction-timeline generator — deterministic, NO LLM.

Duration of each work item is derived straight from the AHSP labour
coefficients (man-days) and the SAME take-off quantities the RAB uses:

    man_days      = qty(element)  x  Σ labour-OH(kode)          # person-days
    duration_days = ceil(man_days / crew_size)                 # calendar days

Sequencing is a STATIC finish-to-start DAG in ``data/task_sequence.yaml``
(``ponytail:`` template, not a CPM solver — see that file). Each stage's
earliest start = max end of its ``depends_on`` stages; stages that share a
dependency but not each other run in parallel. Output is Gantt JSON.

Quantities are imported from :mod:`app.modules.acap.rab.generator` on purpose:
a project's schedule must be built from the EXACT geometry as its RAB, so if
the take-off formula changes the timeline follows automatically — no second
copy to drift.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.acap.layout.schema import FloorPlan
from app.modules.acap.rab.generator import (
    ELEMENT_KODE_MAP,
    _dec,
    _load_coefficient,
    _qty_by_element,
)
from app.modules.acap.takeoff import aggregate

_SEQUENCE_PATH = Path(__file__).parent.parent / "data" / "task_sequence.yaml"


@dataclass(frozen=True)
class StageSpec:
    """One construction stage: its crew, fixed lead days, ordered work
    elements, and the stages that must finish before it may start."""

    name: str
    depends_on: tuple[str, ...]
    crew: int
    lead_days: int
    elements: tuple[str, ...]


def _load_task_sequence(path: Path = _SEQUENCE_PATH) -> list[StageSpec]:
    """Parse ``task_sequence.yaml`` into ordered :class:`StageSpec`s."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs: list[StageSpec] = []
    for stage in doc["stages"]:
        specs.append(
            StageSpec(
                name=stage["name"],
                depends_on=tuple(stage.get("depends_on", []) or ()),
                crew=int(stage["crew"]),
                lead_days=int(stage.get("lead_days", 0)),
                elements=tuple(stage.get("elements", []) or ()),
            )
        )
    return specs


# Loaded once — a static config, same lifecycle as ELEMENT_KODE_MAP.
TASK_SEQUENCE: list[StageSpec] = _load_task_sequence()


def _duration_days(man_days: Decimal, crew: int) -> int:
    """Calendar days for *man_days* of work by a *crew*-person crew.

    Rounds UP (a partial crew-day still occupies a whole calendar day) and
    never rounds a real (>0) task down to 0. Zero work -> zero days (the task
    is dropped, never shown as a phantom 1-day bar).
    """
    if man_days <= 0:
        return 0
    return max(1, math.ceil(man_days / Decimal(crew)))


@dataclass
class Schedule:
    """Pure scheduling result: per-stage (start, end) windows and per-task
    bars, in whole days from project start (day 0)."""

    stage_windows: dict[str, tuple[int, int]]
    tasks: list[dict[str, Any]]
    total_days: int


def build_schedule(specs: list[StageSpec], task_durations: dict[str, int]) -> Schedule:
    """Resolve the finish-to-start DAG to earliest-start windows.

    *task_durations* maps element -> whole-day duration (0 = no work). A
    stage's duration = ``lead_days`` + Σ its present tasks' durations (the
    crew works its tasks in listed order); a stage's start = max end of its
    ``depends_on`` stages. Zero-duration tasks are dropped from the bars but a
    zero-duration stage still forwards its start to dependants.

    Raises:
        ValueError: dependency cycle, or a stage names an unknown dependency.
    """
    by_name = {s.name: s for s in specs}
    windows: dict[str, tuple[int, int]] = {}
    resolving: set[str] = set()

    def stage_duration(spec: StageSpec) -> int:
        return spec.lead_days + sum(task_durations.get(e, 0) for e in spec.elements)

    def resolve(name: str) -> None:
        if name in windows:
            return
        if name in resolving:
            raise ValueError(f"Dependency cycle at stage: {name}")
        if name not in by_name:
            raise ValueError(f"Unknown stage dependency: {name}")
        resolving.add(name)
        spec = by_name[name]
        start = 0
        for dep in spec.depends_on:
            resolve(dep)
            start = max(start, windows[dep][1])
        windows[name] = (start, start + stage_duration(spec))
        resolving.discard(name)

    for spec in specs:
        resolve(spec.name)

    tasks: list[dict[str, Any]] = []
    for spec in specs:
        cursor = windows[spec.name][0] + spec.lead_days
        for element in spec.elements:
            dur = task_durations.get(element, 0)
            if dur <= 0:
                continue
            tasks.append(
                {
                    "element": element,
                    "stage": spec.name,
                    "crew": spec.crew,
                    "duration_days": dur,
                    "start_day": cursor,
                    "end_day": cursor + dur,
                    "depends_on": list(spec.depends_on),
                }
            )
            cursor += dur

    total_days = max((end for _, end in windows.values()), default=0)
    return Schedule(stage_windows=windows, tasks=tasks, total_days=total_days)


@dataclass
class TimelineResult:
    """Gantt-ready timeline. ``tasks`` carry kode/uraian/man_days on top of the
    pure schedule bars; ``stages`` are the (start, end) windows for grouping."""

    tasks: list[dict[str, Any]]
    stages: list[dict[str, Any]]
    total_days: int
    not_covered: list[str] = field(default_factory=list)


async def labor_oh_for_kode(session: AsyncSession, kode: str) -> Decimal:
    """Total labour man-days per unit for *kode* = Σ koef over its ``tenaga``
    resources (pekerja + tukang + kepala + mandor).

    Supervisory trades (kepala/mandor) are small and included as the AHSP
    states them; the per-stage crew size absorbs the mix.

    Raises:
        ValueError: *kode* not in the coefficient DB (seed/programming error).
    """
    coeff = await _load_coefficient(session, kode)
    if coeff is None:
        raise ValueError(f"AHSP kode not found: {kode}")
    return sum((_dec(r.koef) for r in coeff.resources if r.tipe == "tenaga"), Decimal("0"))


async def generate_timeline(session: AsyncSession, plan: FloorPlan) -> TimelineResult:
    """Build the construction timeline for *plan*.

    Reuses the RAB take-off quantities (:func:`_qty_by_element`) so the
    schedule is derived from the exact geometry as the bill of quantities.
    Every element in the static sequence that has a quantity AND a seeded AHSP
    kode becomes a Gantt task; an element with no quantity (e.g. no wet room ->
    no sanitair) contributes 0 days and is dropped.
    """
    qty_by_element = _qty_by_element(aggregate(plan))

    task_durations: dict[str, int] = {}
    task_meta: dict[str, dict[str, Any]] = {}
    for spec in TASK_SEQUENCE:
        for element in spec.elements:
            kode = ELEMENT_KODE_MAP.get(element)
            qty = qty_by_element.get(element, Decimal("0"))
            if kode is None or qty <= 0:
                task_durations[element] = 0
                continue
            coeff = await _load_coefficient(session, kode)
            if coeff is None:
                raise ValueError(f"AHSP kode not found: {kode}")
            oh = sum((_dec(r.koef) for r in coeff.resources if r.tipe == "tenaga"), Decimal("0"))
            man_days = qty * oh
            task_durations[element] = _duration_days(man_days, spec.crew)
            task_meta[element] = {
                "kode": kode,
                "uraian": coeff.uraian,
                "unit": coeff.satuan,
                "quantity": qty,
                "labor_oh_per_unit": oh,
                "man_days": man_days,
            }

    schedule = build_schedule(TASK_SEQUENCE, task_durations)

    for task in schedule.tasks:
        task.update(task_meta[task["element"]])

    stages = [
        {"stage": spec.name, "start_day": windows[0], "end_day": windows[1],
         "duration_days": windows[1] - windows[0], "depends_on": list(spec.depends_on)}
        for spec in TASK_SEQUENCE
        if (windows := schedule.stage_windows[spec.name])[1] - windows[0] > 0
    ]

    return TimelineResult(
        tasks=schedule.tasks,
        stages=stages,
        total_days=schedule.total_days,
    )
