# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The assembly picker has to find what an estimator types.

Issue #406 was reported against a Swiss civil-works catalogue and the
reporter supplied the five positions his estimator picks between, plus the
two queries the man actually types. Both are in here verbatim, and they are
what makes these tests worth having: the five names share a long head and
differ only at the tail, so a filter that matched on the head would pass a
test built from invented names and still fail the day it shipped.

``grue tour`` is the case a whole-query LIKE cannot serve at any level of
effort. The stored text reads "grue a tour", so the typed string is not a
substring of it, and no amount of case folding changes that. ``acces
difficile`` is the accent case: he types on a laptop keyboard without
accents, the catalogue carries them.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.core.text_search import fold_text, free_text_filter, search_terms
from app.modules.assemblies.models import Assembly
from app.modules.assemblies.repository import AssemblyRepository
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()

# The reporter's catalogue, as he pasted it into the issue.
POSITIONS = [
    "Installation de chantier - petit chantier, accès direct",
    "Installation de chantier - petit chantier, accès difficile",
    "Installation de chantier - chantier moyen, grue mobile",
    "Installation de chantier - chantier moyen, grue à tour",
    "Installation de chantier - grand chantier, grue à tour + baraquements",
]


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def catalogue(session):
    """The five positions, stored the way the picker would have stored them."""
    for i, name in enumerate(POSITIONS):
        session.add(
            Assembly(
                code=f"NPK-{i:03d}",
                name=name,
                description="",
                unit="pce",
                owner_id=OWNER_ID,
                is_active=True,
            )
        )
    await session.flush()
    return session


async def names_for(session, query: str) -> list[str]:
    repo = AssemblyRepository(session)
    rows, _total = await repo.list_all(q=query, owner_id=OWNER_ID, limit=50)
    return [a.name for a in rows]


# ── The two queries the estimator types ──────────────────────────────────


@pytest.mark.asyncio
async def test_finds_the_position_when_a_word_between_the_terms_is_skipped(catalogue):
    """ "grue tour" has to find "grue à tour". This is the report, in one line."""
    found = await names_for(catalogue, "grue tour")

    assert found, "typing the two words that distinguish the entry found nothing"
    assert sorted(found) == sorted(
        [
            "Installation de chantier - chantier moyen, grue à tour",
            "Installation de chantier - grand chantier, grue à tour + baraquements",
        ]
    )
    # "grue mobile" is a grue and is not a tour. Widening recall is only
    # useful while it still narrows to an answer.
    assert "Installation de chantier - chantier moyen, grue mobile" not in found


@pytest.mark.asyncio
async def test_finds_the_accented_position_from_an_unaccented_query(catalogue):
    found = await names_for(catalogue, "acces difficile")

    assert found == ["Installation de chantier - petit chantier, accès difficile"]


@pytest.mark.asyncio
async def test_the_accent_folds_in_both_directions(catalogue):
    """Typed with the accent, stored with the accent, still one row."""
    assert await names_for(catalogue, "accès difficile") == [
        "Installation de chantier - petit chantier, accès difficile"
    ]


# ── The head is not an answer ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_shared_head_still_returns_every_position(catalogue):
    """Typing the common prefix cannot narrow anything, and must not pretend to."""
    found = await names_for(catalogue, "Installation de chantier")

    assert len(found) == len(POSITIONS)


@pytest.mark.asyncio
async def test_terms_may_be_typed_in_any_order(catalogue):
    """He reads the tail and types it back in the order he noticed it."""
    assert await names_for(catalogue, "tour grue") == await names_for(catalogue, "grue tour")


@pytest.mark.asyncio
async def test_every_term_has_to_appear(catalogue):
    """Terms are ANDed. Matching any one of them would return the whole list."""
    found = await names_for(catalogue, "grue baraquements")

    assert found == ["Installation de chantier - grand chantier, grue à tour + baraquements"]


@pytest.mark.asyncio
async def test_a_term_no_position_carries_finds_nothing(catalogue):
    assert await names_for(catalogue, "grue helicoptere") == []


@pytest.mark.asyncio
async def test_trailing_punctuation_on_a_term_is_not_matched_literally(catalogue):
    """Typed "moyen," from reading the row. The comma is not part of the word."""
    found = await names_for(catalogue, "chantier moyen, grue")

    assert len(found) == 2


# ── LIKE metacharacters ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_percent_sign_is_literal_text(catalogue):
    """Unescaped, this returned the entire catalogue as if nothing was typed."""
    assert await names_for(catalogue, "%") == []


@pytest.mark.asyncio
async def test_an_underscore_is_literal_text(catalogue):
    """Unescaped, LIKE reads it as "any single character"."""
    assert await names_for(catalogue, "grue _ tour") == []


@pytest.mark.asyncio
async def test_a_blank_query_does_not_filter(catalogue):
    assert len(await names_for(catalogue, "   ")) == len(POSITIONS)


# ── The pieces, without a database ───────────────────────────────────────


def test_folding_leaves_alone_what_translate_cannot_map():
    """A fold that changes the character count is not applied, on either side.

    The SQL fold is a character-to-character ``translate()`` and cannot emit
    two characters for one, so "ß" stays "ß" in the query as well. Folding it
    in Python only would build a pattern the column can never match.
    """
    assert fold_text("Grue à Tour") == "grue a tour"
    assert fold_text("Straße") == "straße"
    assert fold_text("ACCÈS") == "acces"


def test_terms_drop_punctuation_but_keep_the_word():
    assert search_terms("chantier moyen, grue") == ["chantier", "moyen", "grue"]
    assert search_terms("  ") == []
    assert search_terms("...") == []


def test_a_query_with_no_term_yields_no_filter():
    """``None`` means do not filter, which is what an absent query does."""
    assert free_text_filter("", [Assembly.name]) is None
    assert free_text_filter("  ,  ", [Assembly.name]) is None
    assert free_text_filter("grue", []) is None
