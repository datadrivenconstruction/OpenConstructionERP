# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Free-text matching for catalogue pickers.

A picker filter built as one ``ILIKE '%<whole query>%'`` answers a question
nobody asks. Estimators type the words that tell entries apart, not a prefix
of the stored string, and in a structured catalogue those words sit at the
tail of the position text and are separated by words the typist skips. A
Swiss civil-works catalogue reported in issue #406 has five positions whose
common head is "Installation de chantier" and whose tails are "chantier
moyen, grue a tour" and friends; typing ``grue tour`` matched nothing at all,
because that substring does not occur in ``grue a tour``.

Two rules fix that, and both have to hold on the database side. Matching a
single term is useless if the row was already filtered out.

Word order and adjacency
    The query is split into terms and every term has to appear somewhere in
    the row, in any order and with anything in between. A row containing the
    whole query as a phrase satisfies that too, so this only ever widens what
    the picker finds.

Accents
    Catalogue text carries them, laptop typists skip them. Both sides are
    folded to their unaccented base, so ``acces`` finds ``accès`` and the
    other way round. The fold is applied in SQL with ``translate()`` rather
    than by an extension so nothing has to be installed into the database.

Only foldings that keep the character count are applied, which is the same
rule the picker's client-side highlighter uses. That is deliberate: the two
have to agree, or the server would return a row the client then declines to
mark, which reads as a bug in the marking. It is also forced by
``translate()``, whose mapping is character to character, so a fold such as
``ß`` to ``ss`` cannot be expressed. Those characters are left alone on both
sides and match themselves.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from sqlalchemy import ColumnElement, String, and_, func, or_

# Latin-1 Supplement through Latin Extended-B. Everything a European
# construction catalogue writes its position texts in lives in here.
_FOLDABLE = range(0x00C0, 0x0250)

# Trailing punctuation a typed term picks up from a position text. Stripped
# from the term, never from the row: "moyen," has to find "moyen".
_TERM_TRIM = " \t\r\n.,;:!?()[]{}<>\"'`«»„“”‘’-–—/\\|*+&"


def _build_fold_map() -> dict[str, str]:
    """Accented character to its unaccented base, for single-character folds."""
    mapping: dict[str, str] = {}
    for code in _FOLDABLE:
        char = chr(code).lower()
        if len(char) != 1:
            continue
        base = "".join(c for c in unicodedata.normalize("NFD", char) if not unicodedata.combining(c)).lower()
        if len(base) == 1 and base != char:
            mapping[char] = base
    return mapping


_FOLD_MAP = _build_fold_map()

# The two arguments ``translate()`` takes, aligned by position.
FOLD_FROM = "".join(_FOLD_MAP)
FOLD_TO = "".join(_FOLD_MAP.values())

# LIKE metacharacters in a typed term are literal text. Escaping them is not
# only correctness: an unescaped ``%`` matched every row in the catalogue.
_LIKE_ESCAPE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


def fold_text(text: str) -> str:
    """Lowercase `text` and strip the accents ``translate()`` can strip.

    Kept in step with the SQL side by construction: both read `_FOLD_MAP`.
    """
    return "".join(_FOLD_MAP.get(c, c) for c in text.lower())


def search_terms(query: str) -> list[str]:
    """Split a typed query into the terms every row has to contain."""
    return [term for term in (raw.strip(_TERM_TRIM) for raw in query.split()) if term]


def folded_column(column: ColumnElement[str]) -> ColumnElement[str]:
    """The SQL expression that folds a column the way `fold_text` folds a term."""
    return func.translate(func.lower(column), FOLD_FROM, FOLD_TO, type_=String)


def free_text_filter(
    query: str | None,
    columns: Sequence[ColumnElement[str]],
) -> ColumnElement[bool] | None:
    """Build the picker filter for `query` over `columns`.

    Args:
        query: What the user typed. Blank or punctuation-only yields no filter.
        columns: Text columns a term may match in. A term matching any one of
            them counts for the row, so a term in the name and a term in the
            description together still match.

    Returns:
        A clause requiring every term to appear somewhere in the row, or
        ``None`` when the query carries no term to match on. ``None`` means
        "do not filter", the same as an absent query.
    """
    terms = search_terms(query or "")
    if not terms or not columns:
        return None

    folded = [folded_column(column) for column in columns]
    return and_(
        *(
            or_(*(expr.like(f"%{fold_text(term).translate(_LIKE_ESCAPE)}%", escape="\\") for expr in folded))
            for term in terms
        )
    )
