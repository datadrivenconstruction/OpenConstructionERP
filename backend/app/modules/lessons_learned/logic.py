# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure matching of lessons to a situation (trade, cost code, risk category).

A lesson matches when any tag given in the query agrees with the lesson's tag: trade and risk category
case-insensitively and exactly, cost codes when one is a prefix of the other (so a lesson on ``330`` is seen
from ``331.10``). The result counts distinct projects, never lessons, so one busy project cannot inflate it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

IMPACTS = ("low", "medium", "high")
_IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}


def norm(value: str | None) -> str:
    """Normalise a free-text tag for comparison."""
    return (value or "").strip().casefold()


def code_related(a: str | None, b: str | None) -> bool:
    """True when one cost code is a (non-empty) prefix of the other."""
    x, y = norm(a).replace(" ", ""), norm(b).replace(" ", "")
    return bool(x) and bool(y) and (x.startswith(y) or y.startswith(x))


def matched_tags(lesson: Any, trade: str | None, cost_code: str | None, risk_category: str | None) -> list[str]:
    """Names of the query tags this lesson agrees with (empty list = no match)."""
    hits: list[str] = []
    if norm(trade) and norm(trade) == norm(lesson.trade):
        hits.append("trade")
    if code_related(cost_code, lesson.cost_code):
        hits.append("cost_code")
    if norm(risk_category) and norm(risk_category) == norm(lesson.risk_category):
        hits.append("risk_category")
    return hits


@dataclass
class SeenOn:
    """Outcome of a lookup: distinct projects, lessons and the top few lessons to show."""

    projects: int
    lessons: int
    top: list[tuple[Any, list[str]]]


def seen_on(
    lessons: Iterable[Any],
    *,
    trade: str | None = None,
    cost_code: str | None = None,
    risk_category: str | None = None,
    exclude_project_id: Any = None,
    top_n: int = 3,
) -> SeenOn:
    """Match confirmed lessons from other projects. With no tag in the query every lesson matches."""
    untagged = not (norm(trade) or norm(cost_code) or norm(risk_category))
    found: list[tuple[Any, list[str]]] = []
    for lesson in lessons:
        if lesson.status != "confirmed" or lesson.project_id == exclude_project_id:
            continue
        hits = matched_tags(lesson, trade, cost_code, risk_category)
        if hits or untagged:
            found.append((lesson, hits))
    found.sort(key=lambda p: (-len(p[1]), _IMPACT_RANK.get(p[0].impact, 1), p[0].title.casefold()))
    return SeenOn(
        projects=len({str(le.project_id) for le, _ in found}),
        lessons=len(found),
        top=found[:top_n],
    )
