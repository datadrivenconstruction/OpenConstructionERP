# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for saved searches: the persistence behind the Find Records history.

Three layers, in the order a failure is worth reading:

* the pure signature / facet helpers, which decide what counts as the same
  search and therefore whether a re-save updates or duplicates;
* the rule set, including the reachability check that the engine actually
  resolves ``retrieval_saved_search`` to rules - a rule set nothing registers
  produces a clean report having checked nothing, which reads exactly like a
  valid pin;
* the service against PostgreSQL: create, re-save, rename, replay, evict,
  delete, and the owner scoping that keeps one user's pins out of another's.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import Severity, rule_registry
from app.modules.projects.models import Project
from app.modules.retrieval.repository import SAVED_SEARCH_LIMIT, SavedSearchRepository
from app.modules.retrieval.saved_search_logic import (
    date_window_ordered,
    describe_facets,
    facet_signature,
    is_iso_date,
    is_meaningful,
    normalize_facets,
)
from app.modules.retrieval.service import SavedSearchInvalid, SavedSearchService
from app.modules.retrieval.validators import (
    RETRIEVAL_SAVED_SEARCH_RULE_SET,
    register_retrieval_rules,
)
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest.fixture(autouse=True)
def _rules() -> None:
    """Register the module's rules for every test in this file.

    Nothing calls the module ``on_startup`` hook in the test process, so
    without this the rule set resolves to nothing and every save reports a
    clean result having examined nothing at all.
    """
    register_retrieval_rules()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _seed(session: AsyncSession) -> tuple[User, Project]:
    user = User(
        email=f"saved-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Saved",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Saved {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return user, proj


# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_signature_ignores_key_order_and_surrounding_space() -> None:
    a = normalize_facets({"text": " rebar ", "party": "acme"})
    b = normalize_facets({"party": " acme", "text": "rebar"})
    assert facet_signature(a) == facet_signature(b)


def test_signature_separates_searches_that_differ_in_one_facet() -> None:
    a = normalize_facets({"text": "rebar", "record_type": "document"})
    b = normalize_facets({"text": "rebar", "record_type": "change_order"})
    assert facet_signature(a) != facet_signature(b)


def test_signature_cannot_be_forged_by_moving_a_value_between_facets() -> None:
    # Without a separator between fields, {"text": "ab", "party": ""} and
    # {"text": "a", "party": "b"} would hash the same string.
    a = normalize_facets({"text": "ab"})
    b = normalize_facets({"text": "a", "party": "b"})
    assert facet_signature(a) != facet_signature(b)


def test_normalize_drops_keys_the_search_endpoint_does_not_accept() -> None:
    facets = normalize_facets({"text": "rebar", "sort": "date", "limit": 10})
    assert set(facets) == {"text", "party", "record_type", "date_from", "date_to", "entity"}


def test_empty_query_is_not_meaningful_but_a_single_facet_is() -> None:
    assert not is_meaningful(normalize_facets({}))
    assert not is_meaningful(normalize_facets({"text": "   "}))
    assert is_meaningful(normalize_facets({"entity": "CO-7"}))


def test_iso_date_and_window_ordering() -> None:
    assert is_iso_date("2026-06-20")
    assert is_iso_date("")
    assert not is_iso_date("20/06/2026")
    assert date_window_ordered("2026-06-01", "2026-06-30")
    assert date_window_ordered("", "2026-06-30")
    assert not date_window_ordered("2026-06-30", "2026-06-01")


def test_describe_falls_back_to_the_facets_when_there_is_no_text() -> None:
    assert describe_facets(normalize_facets({"text": "rebar"})) == "rebar"
    described = describe_facets(normalize_facets({"party": "acme", "date_from": "2026-06-01"}))
    assert "acme" in described
    assert "2026-06-01" in described
    assert describe_facets(normalize_facets({})) == "All records"


# ── The rule set ─────────────────────────────────────────────────────────────


def test_the_engine_actually_resolves_the_saved_search_rule_set() -> None:
    """The set the service passes must resolve to the rules this module wrote.

    A rule set nobody registers resolves to zero rules, and the engine then
    returns a report with no findings - indistinguishable from a valid pin.
    """
    rules = rule_registry.get_rules_for_sets([RETRIEVAL_SAVED_SEARCH_RULE_SET])
    ids = [r.rule_id for r in rules if r.enabled]
    assert ids.count("retrieval_saved_search.label_present") == 1
    assert ids.count("retrieval_saved_search.has_facet") == 1
    assert ids.count("retrieval_saved_search.date_window_sane") == 1
    assert ids.count("retrieval_saved_search.known_record_type") == 1


def test_only_the_record_type_rule_is_a_warning() -> None:
    """The indexed-type check must not block a save, the other three must."""
    by_id = {r.rule_id: r for r in rule_registry.get_rules_for_sets([RETRIEVAL_SAVED_SEARCH_RULE_SET])}
    assert by_id["retrieval_saved_search.known_record_type"].severity == Severity.WARNING
    assert by_id["retrieval_saved_search.label_present"].severity == Severity.ERROR
    assert by_id["retrieval_saved_search.has_facet"].severity == Severity.ERROR
    assert by_id["retrieval_saved_search.date_window_sane"].severity == Severity.ERROR


# ── The service ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_saving_a_search_persists_the_facets_and_passes_validation(
    session: AsyncSession,
) -> None:
    user, proj = await _seed(session)
    saved = await SavedSearchService(session).save(
        user.id,
        proj.id,
        label="Rebar letters",
        raw_facets={"text": "rebar", "record_type": "correspondence"},
    )
    assert saved.label == "Rebar letters"
    assert saved.text == "rebar"
    assert saved.record_type == "correspondence"
    assert saved.validation_status == "passed"
    assert saved.validation_findings == []
    assert saved.use_count == 0
    assert saved.last_used_at is None


@pytest.mark.asyncio
async def test_resaving_the_same_facets_renames_the_pin_instead_of_duplicating(
    session: AsyncSession,
) -> None:
    user, proj = await _seed(session)
    service = SavedSearchService(session)
    first = await service.save(user.id, proj.id, label="Rebar", raw_facets={"text": "rebar"})
    second = await service.save(
        user.id,
        proj.id,
        label="Rebar, renamed",
        raw_facets={"text": " rebar "},
    )
    assert second.id == first.id
    assert second.label == "Rebar, renamed"
    assert len(await service.list_saved(user.id, proj.id)) == 1


@pytest.mark.asyncio
async def test_a_search_with_no_facets_is_refused(session: AsyncSession) -> None:
    user, proj = await _seed(session)
    with pytest.raises(SavedSearchInvalid) as exc:
        await SavedSearchService(session).save(
            user.id,
            proj.id,
            label="Everything",
            raw_facets={},
        )
    assert any(f["rule_id"] == "retrieval_saved_search.has_facet" for f in exc.value.findings)
    assert await SavedSearchRepository(session).count_for_owner(user.id, proj.id) == 0


@pytest.mark.asyncio
async def test_a_backwards_date_window_is_refused(session: AsyncSession) -> None:
    user, proj = await _seed(session)
    with pytest.raises(SavedSearchInvalid) as exc:
        await SavedSearchService(session).save(
            user.id,
            proj.id,
            label="Backwards",
            raw_facets={"text": "rebar", "date_from": "2026-06-30", "date_to": "2026-06-01"},
        )
    rule_ids = {f["rule_id"] for f in exc.value.findings}
    assert "retrieval_saved_search.date_window_sane" in rule_ids


@pytest.mark.asyncio
async def test_a_non_iso_date_is_refused(session: AsyncSession) -> None:
    user, proj = await _seed(session)
    with pytest.raises(SavedSearchInvalid):
        await SavedSearchService(session).save(
            user.id,
            proj.id,
            label="Slashes",
            raw_facets={"text": "rebar", "date_from": "20/06/2026"},
        )


@pytest.mark.asyncio
async def test_an_unindexed_record_type_warns_but_still_saves(session: AsyncSession) -> None:
    user, proj = await _seed(session)
    saved = await SavedSearchService(session).save(
        user.id,
        proj.id,
        label="Future type",
        raw_facets={"text": "rebar", "record_type": "rfi"},
    )
    assert saved.validation_status == "warnings"
    assert [f["rule_id"] for f in saved.validation_findings] == ["retrieval_saved_search.known_record_type"]


@pytest.mark.asyncio
async def test_a_missing_label_falls_back_to_a_description_of_the_facets(
    session: AsyncSession,
) -> None:
    user, proj = await _seed(session)
    saved = await SavedSearchService(session).save(
        user.id,
        proj.id,
        label="   ",
        raw_facets={"text": "rebar"},
    )
    assert saved.label == "rebar"
    assert saved.validation_status == "passed"


@pytest.mark.asyncio
async def test_replaying_a_pin_moves_it_to_the_top_of_the_list(session: AsyncSession) -> None:
    user, proj = await _seed(session)
    service = SavedSearchService(session)
    older = await service.save(user.id, proj.id, label="Older", raw_facets={"text": "concrete"})
    await service.save(user.id, proj.id, label="Newer", raw_facets={"text": "rebar"})

    # Newest-created leads while nothing has been replayed.
    assert [s.label for s in await service.list_saved(user.id, proj.id)] == ["Newer", "Older"]

    await service.record_use(older)
    listed = await service.list_saved(user.id, proj.id)
    assert [s.label for s in listed] == ["Older", "Newer"]
    assert listed[0].use_count == 1
    assert listed[0].last_used_at is not None


@pytest.mark.asyncio
async def test_renaming_keeps_the_facets_and_repointing_changes_the_signature(
    session: AsyncSession,
) -> None:
    user, proj = await _seed(session)
    service = SavedSearchService(session)
    saved = await service.save(user.id, proj.id, label="Rebar", raw_facets={"text": "rebar"})
    original_signature = saved.signature

    renamed = await service.update(saved, label="Rebar claims", raw_facets=None)
    assert renamed.text == "rebar"
    assert renamed.signature == original_signature

    repointed = await service.update(renamed, label=None, raw_facets={"text": "concrete"})
    assert repointed.text == "concrete"
    assert repointed.signature != original_signature


@pytest.mark.asyncio
async def test_a_full_list_evicts_its_least_used_pin_rather_than_refusing(
    session: AsyncSession,
) -> None:
    user, proj = await _seed(session)
    service = SavedSearchService(session)
    for i in range(SAVED_SEARCH_LIMIT):
        await service.save(user.id, proj.id, label=f"Search {i}", raw_facets={"text": f"term{i}"})
    assert await SavedSearchRepository(session).count_for_owner(user.id, proj.id) == (SAVED_SEARCH_LIMIT)

    await service.save(user.id, proj.id, label="One more", raw_facets={"text": "overflow"})
    labels = [s.label for s in await service.list_saved(user.id, proj.id)]
    assert "One more" in labels
    # The oldest never-replayed pin is the one that dropped off.
    assert "Search 0" not in labels
    assert await SavedSearchRepository(session).count_for_owner(user.id, proj.id) == (SAVED_SEARCH_LIMIT)


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_one_users_pin_is_invisible_to_another(session: AsyncSession) -> None:
    owner, proj = await _seed(session)
    intruder = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Other",
        role="admin",
    )
    session.add(intruder)
    await session.flush()

    saved = await SavedSearchService(session).save(
        owner.id,
        proj.id,
        label="Rebar",
        raw_facets={"text": "rebar"},
    )
    repo = SavedSearchRepository(session)
    assert await repo.get_owned(saved.id, owner.id) is not None
    assert await repo.get_owned(saved.id, intruder.id) is None
    assert await SavedSearchService(session).list_saved(intruder.id, proj.id) == []


@pytest.mark.asyncio
async def test_the_same_facets_on_two_projects_are_two_pins(session: AsyncSession) -> None:
    user, proj = await _seed(session)
    other = Project(name=f"Other {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(other)
    await session.flush()

    service = SavedSearchService(session)
    first = await service.save(user.id, proj.id, label="Rebar", raw_facets={"text": "rebar"})
    second = await service.save(user.id, other.id, label="Rebar", raw_facets={"text": "rebar"})
    assert first.id != second.id
    assert len(await service.list_saved(user.id, proj.id)) == 1
    assert len(await service.list_saved(user.id, other.id)) == 1


@pytest.mark.asyncio
async def test_deleting_a_pin_removes_it_from_the_list(session: AsyncSession) -> None:
    user, proj = await _seed(session)
    service = SavedSearchService(session)
    saved = await service.save(user.id, proj.id, label="Rebar", raw_facets={"text": "rebar"})
    await service.delete(saved)
    assert await service.list_saved(user.id, proj.id) == []
