"""Phase and project-type filters for cross-project views (#567).

Mirrors ``frontend/src/shared/lib/projectFacets.ts``: absent or ``all`` keeps
everything, ``__unset__`` keeps projects with no value, anything else must match.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

FACET_ALL = "all"
FACET_UNSET = "__unset__"


def _matches(value: str | None, flt: str | None) -> bool:
    # A non-string is FastAPI's Query default when the route function is called directly.
    if not isinstance(flt, str) or not flt or flt == FACET_ALL:
        return True
    own = (value or "").strip()
    if flt == FACET_UNSET:
        return own == ""
    return own == flt


def filter_by_facets(projects: Iterable[Any], phase: str | None, project_type: str | None) -> list[Any]:
    """Keep the projects whose phase and project type match the given filters."""
    return [
        p
        for p in projects
        if _matches(getattr(p, "phase", None), phase) and _matches(getattr(p, "project_type", None), project_type)
    ]
