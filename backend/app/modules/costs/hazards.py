# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Hazardous-material markers on cost items.

Cost databases carry items built from materials that are banned or restricted
in many jurisdictions, asbestos-cement sheets above all. They stay in the data,
since an estimator pricing removal or refurbishment work needs them, but a
search for "frame walls" should not offer a chrysotile wall as its top hit, and
a row that does appear should say what it is.

The words that mark a hazard live in ``hazard_terms.json``, keyed by hazard id
and covering the languages the cost databases ship in. :func:`hazards_in`
names the hazards a text mentions; :func:`hazard_sql_flag` is the same test as
an SQL expression, so a relevance search can rank those rows after the rest.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import and_, case, not_, or_

_TERMS_FILE = Path(__file__).with_name("hazard_terms.json")


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    return json.loads(_TERMS_FILE.read_text(encoding="utf-8"))


def _cleaned(section: str) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for hazard_id, terms in (_raw().get(section) or {}).items():
        # Longest first, so "asbestos-free" is stripped before "asbestos free".
        cleaned = tuple(
            sorted({str(t).casefold().strip() for t in terms if str(t).strip()}, key=lambda t: (-len(t), t))
        )
        if cleaned:
            out[str(hazard_id)] = cleaned
    return out


@lru_cache(maxsize=1)
def hazard_terms() -> dict[str, tuple[str, ...]]:
    """``{hazard_id: terms}``, casefolded, read once from the data file."""
    return _cleaned("hazards")


@lru_cache(maxsize=1)
def hazard_exclusions() -> dict[str, tuple[str, ...]]:
    """``{hazard_id: phrases}`` that deny the hazard ("asbestos-free")."""
    return _cleaned("exclude")


def _mentions(folded: str, hazard_id: str, terms: tuple[str, ...]) -> bool:
    for phrase in hazard_exclusions().get(hazard_id, ()):
        folded = folded.replace(phrase, " ")
    return any(term in folded for term in terms)


def hazards_in(texts: Iterable[str | None]) -> list[str]:
    """The hazard ids any of ``texts`` mentions, in a stable order.

    A phrase that denies the hazard ("asbestos-free", "sans amiante") is
    removed first, so a safe product carries no marker while a text that
    also names the material elsewhere still does.
    """
    folded = " ".join(t.casefold() for t in texts if isinstance(t, str) and t)
    if not folded:
        return []
    return [hid for hid, terms in sorted(hazard_terms().items()) if _mentions(folded, hid, terms)]


def _case_variants(term: str) -> set[str]:
    # PostgreSQL folds case per the database's ctype. A cluster initialised
    # with the C locale folds ASCII only, so LOWER()/ILIKE would miss a
    # capitalised Cyrillic or Greek word. Matching the spellings a description
    # actually uses (lower, capitalised, upper) with plain LIKE works under
    # every locale.
    return {term, term[:1].upper() + term[1:], term.upper()}


def _any_like(column: Any, terms: Iterable[str]) -> Any:
    patterns = sorted({v for t in terms for v in _case_variants(t)})
    return or_(*[column.like(f"%{p}%") for p in patterns])


def hazard_sql_flag(column: Any) -> Any:
    """``1`` when ``column`` mentions a hazard, else ``0``, as SQL.

    A row that carries a denying phrase ("asbestos-free") is not flagged.
    Unlike :func:`hazards_in` this does not look for a second, undenied
    mention in the same text; such a row only loses its demotion, it still
    shows the badge.
    """
    exclusions = hazard_exclusions()
    conditions = []
    for hazard_id, terms in hazard_terms().items():
        cond = _any_like(column, terms)
        if exclusions.get(hazard_id):
            cond = and_(cond, not_(_any_like(column, exclusions[hazard_id])))
        conditions.append(cond)
    if not conditions:
        return case((column.is_(None), 0), else_=0)
    return case((or_(*conditions), 1), else_=0)


def query_names_a_hazard(q: str | None) -> bool:
    """True when the search text itself asks for a hazardous material."""
    return bool(q) and bool(hazards_in([q]))
