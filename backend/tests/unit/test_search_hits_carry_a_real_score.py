"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unified search hits carry a relevance score, and it ranks them.

Every result the global search returned scored 0%. The query path was
fine - results came back - but ``_hit_from_row`` in the search service
took ``rank_score: float = 0.0`` and nothing ever filled it in, so every
SQL-track hit reached the frontend at exactly zero and the modal drew
``Math.round(0 * 100)`` for all of them. On a stock install the SQL
track is the only track (``lancedb`` and ``fastembed`` live in the
optional ``[vector]`` extra), so that was every result a reader saw.

The response schema was never at fault: ``score`` is declared, and
``ge=0.0`` makes 0.0 valid, so serialisation had nothing to catch.

Two things are pinned here, because a score that is merely non-zero is
no better than the zero was:

* a matching hit scores above zero, and
* the better of two matches scores strictly higher, so the number
  carries relevance rather than a rank position or a constant.

The vector track is stubbed out rather than skipped, so these tests
describe the configuration the defect was reported in: no embedding
model installed, SQL recall only.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector_index import COLLECTION_BOQ, COLLECTION_TASKS, VectorHit
from app.modules.projects.models import Project
from app.modules.search import service as search_service
from app.modules.search.service import (
    _LEXICAL_FLOOR,
    _hit_from_row,
    _lexical_score,
    _sql_search_collection,
    _sql_search_collection_raw,
    unified_search_service,
)
from app.modules.tasks.models import Task
from app.modules.users.models import User

# The exact-title task and the one that only mentions the phrase in a
# long body. "Better match" is not a matter of taste here: one row is
# the query, the other buries it in a sentence.
EXACT_TITLE = "Concrete wall"
BURIED_TITLE = "Weekly site walk"
BURIED_BODY = "Walk the south block and check the concrete wall pour against the pour schedule before Friday."


class _SharedSession:
    """Hand the service the test's transaction instead of a fresh session.

    ``unified_search_service`` opens its own session through
    ``async_session_factory``; a transaction-isolated fixture rolls its
    seed back, so a second session would find an empty database.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


async def _no_vector_track(*_args: object, **_kwargs: object) -> list[VectorHit]:
    """The vector track on an install without the ``[vector]`` extra."""
    return []


@pytest_asyncio.fixture
async def seeded(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """A transaction-isolated session holding two tasks of unequal match quality."""
    from tests._pg import transactional_session

    project_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    async with transactional_session() as session:
        owner = User(
            id=owner_id,
            email="ranker@test.io",
            hashed_password="x",
            full_name="Test Owner",
        )
        session.add(owner)
        await session.flush()

        session.add(Project(id=project_id, name="Ranking Project", description="", owner_id=owner_id))
        await session.flush()

        session.add_all(
            [
                Task(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    task_type="general",
                    title=EXACT_TITLE,
                    description="",
                    checklist=[],
                    persons_involved=[],
                    bim_element_ids=[],
                ),
                Task(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    task_type="general",
                    title=BURIED_TITLE,
                    description=BURIED_BODY,
                    checklist=[],
                    persons_involved=[],
                    bim_element_ids=[],
                ),
            ]
        )
        await session.flush()

        monkeypatch.setattr(search_service, "async_session_factory", lambda: _SharedSession(session))
        monkeypatch.setattr(search_service, "search_collection", _no_vector_track)
        yield session


# ── The reported defect ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_matching_hit_scores_above_zero(seeded: AsyncSession) -> None:
    """The reproduction: search a term that certainly matches, read the scores."""
    response = await unified_search_service(EXACT_TITLE, types=["tasks"])

    assert response.total >= 2
    assert all(hit.score > 0.0 for hit in response.hits), [(h.title, h.score) for h in response.hits]


@pytest.mark.asyncio
async def test_the_better_match_scores_strictly_higher(seeded: AsyncSession) -> None:
    """A non-zero constant would satisfy the test above. This one it would not.

    The phrase is the whole title of one task and one clause of another's
    description. If the score means relevance, the first outranks the
    second; if it means rank position or a fixed value, it does not.
    """
    response = await unified_search_service(EXACT_TITLE, types=["tasks"])
    by_title = {hit.title: hit.score for hit in response.hits}

    assert set(by_title) == {EXACT_TITLE, BURIED_TITLE}
    assert by_title[EXACT_TITLE] > by_title[BURIED_TITLE]


@pytest.mark.asyncio
async def test_the_score_drives_the_order_of_the_list(seeded: AsyncSession) -> None:
    """The best match is also the first row, not merely the best-numbered one."""
    response = await unified_search_service(EXACT_TITLE, types=["tasks"])

    assert response.hits[0].title == EXACT_TITLE


@pytest.mark.asyncio
async def test_the_sql_track_hands_fusion_a_scored_list(seeded: AsyncSession) -> None:
    """The score is set before fusion, so any consumer of the track sees it."""
    hits = await _sql_search_collection(seeded, COLLECTION_TASKS, EXACT_TITLE, limit=10)

    assert len(hits) == 2
    assert all(hit.score > 0.0 for hit in hits)
    assert hits[0].score > hits[1].score


@pytest.mark.asyncio
async def test_the_recall_query_is_where_the_zero_came_from(seeded: AsyncSession) -> None:
    """The baseline, so the assertions above are known to discriminate.

    ``_sql_search_collection_raw`` is the shipped query, unchanged: it
    finds the same rows and hands every one of them back at 0.0, because
    an ILIKE has no relevance to report. Ranking is the wrapper's job,
    and this test fails the moment that stops being true - at which point
    the tests above would be passing for a reason nobody chose.
    """
    raw = await _sql_search_collection_raw(seeded, COLLECTION_TASKS, EXACT_TITLE, limit=10)

    assert len(raw) == 2
    assert [hit.score for hit in raw] == [0.0, 0.0]


# ── The scorer on its own, no database ─────────────────────────────────


def _hit(title: str, snippet: str, *, payload: dict[str, str] | None = None) -> VectorHit:
    return _hit_from_row(
        row_id=uuid.uuid4(),
        title=title,
        snippet=snippet,
        collection=COLLECTION_BOQ,
        payload=payload or {"title": title},
    )


def test_a_title_match_outranks_a_body_match() -> None:
    in_title = _lexical_score("concrete wall", _hit("Concrete wall 240mm", "Concrete wall 240mm"))
    in_body = _lexical_score("concrete wall", _hit("Section 3 notes", BURIED_BODY))

    assert in_title > in_body


def test_a_short_title_matched_whole_outranks_the_phrase_buried_in_a_long_one() -> None:
    """Coverage: the same phrase says more about a title it fills than one it dots."""
    whole = _lexical_score("concrete wall", _hit("Concrete wall", "Concrete wall"))
    dotted = _lexical_score(
        "concrete wall",
        _hit(
            "Concrete wall to grid line F including formwork, reinforcement and finishing",
            "Concrete wall to grid line F including formwork, reinforcement and finishing",
        ),
    )

    assert whole > dotted


def test_a_partly_covered_query_outranks_nothing_but_scores_below_a_full_one() -> None:
    both_terms = _lexical_score("concrete wall", _hit("Reinforced concrete wall", "Reinforced concrete wall"))
    one_term = _lexical_score("concrete wall", _hit("Concrete slab C30/37", "Concrete slab C30/37"))

    assert both_terms > one_term > 0.0


def test_a_perfect_match_is_the_top_of_the_scale() -> None:
    """The title is the query, so the modal draws 100% - and only then."""
    perfect = _lexical_score("concrete wall", _hit("Concrete wall", "Concrete wall"))
    partial = _lexical_score("concrete wall", _hit("Concrete wall to grid F", "Concrete wall to grid F"))

    assert perfect == pytest.approx(1.0)
    assert partial < 1.0


def test_a_match_outside_the_visible_text_still_scores_as_a_match() -> None:
    """An ordinal or code hit shows no phrase in the title or the snippet.

    It is still a row Postgres matched, so it must not be handed back at
    zero - a reader would take that for "not relevant" rather than for
    "matched somewhere you cannot see".
    """
    by_ordinal = _hit("Concrete wall", "Concrete wall", payload={"title": "Concrete wall", "ordinal": "03.02.001"})

    assert _lexical_score("03.02.001", by_ordinal) == pytest.approx(_LEXICAL_FLOOR)
    assert _LEXICAL_FLOOR > 0.0


def test_an_empty_query_scores_nothing() -> None:
    assert _lexical_score("   ", _hit("Concrete wall", "Concrete wall")) == 0.0
