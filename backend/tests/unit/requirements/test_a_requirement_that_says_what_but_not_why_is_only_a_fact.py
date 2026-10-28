"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A requirement stored as an EAC triplet says what. It does not say why.

Nor who asked for it, at which phase it applies, how anyone would prove it was
met, or which priced work it governs. These pin the five answers the triplet was
missing, and the two properties that make the vocabulary switch safe: both
wordings carry the same concepts, and a stage system is allowed to have no name
for a phase rather than being forced to invent one.

Pure unit tests. Nothing here touches a database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.requirements.intl import PRIORITY_ALIASES, PRIORITY_LABELS, priority_label, priority_rank
from app.modules.requirements.lifecycle import (
    CYCLE_QUESTIONS,
    DEFAULT_VOCABULARY,
    ORIGINATOR_ROLE_LABELS,
    ORIGINATOR_ROLES,
    PHASE_LABELS,
    PHASE_SPINE,
    PHASE_SYSTEMS,
    VERIFICATION_LABELS,
    VERIFICATION_METHODS,
    VOCABULARIES,
    VOCABULARY_TERMS,
    base_language,
    cycle_completeness,
    phase_in_system,
    phase_rank,
    resolve_label,
    unanswered_questions,
    vocabulary_term,
)
from app.modules.requirements.models import Requirement
from app.modules.requirements.schemas import RequirementCreate, RequirementResponse, RequirementSetCreate
from app.modules.requirements.service import _requirement_from_create

# ── The vocabulary switch ───────────────────────────────────────────────────


@pytest.mark.parametrize("vocabulary", sorted(VOCABULARIES))
def test_every_vocabulary_answers_every_term(vocabulary: str) -> None:
    """Switching wording must rename concepts, never drop one.

    A project that flips to the standard's wording and finds one field suddenly
    unlabelled has lost information by pressing a toggle.
    """
    assert set(VOCABULARIES[vocabulary]) == set(VOCABULARY_TERMS)


@pytest.mark.parametrize("vocabulary", sorted(VOCABULARIES))
def test_every_term_has_english(vocabulary: str) -> None:
    """English is the last link of the fallback chain, so it cannot be missing."""
    for term, per_lang in VOCABULARIES[vocabulary].items():
        assert per_lang.get("en"), f"{vocabulary}.{term} has no English label"


def test_the_two_vocabularies_actually_differ() -> None:
    """Otherwise the switch is a control that changes nothing.

    Not every term has to differ - "Phase" is "Phase" either way - but if none
    of them did, the feature would be a lie told by a dropdown.
    """
    iso = VOCABULARIES["iso19650"]
    neutral = VOCABULARIES["neutral"]
    differing = [t for t in VOCABULARY_TERMS if iso[t]["en"] != neutral[t]["en"]]
    assert len(differing) >= 5


def test_an_unknown_vocabulary_falls_back_rather_than_raising() -> None:
    """A row carrying a value from a future release still renders words."""
    assert vocabulary_term("requirement", "some_future_standard") == vocabulary_term("requirement", DEFAULT_VOCABULARY)


def test_an_unknown_term_is_returned_as_itself() -> None:
    assert vocabulary_term("no_such_term") == "no_such_term"


# ── The fallback chain ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("locale", "expected"),
    [("es-CL", "es"), ("es_MX", "es"), ("PT-br", "pt"), ("de", "de"), ("zh-Hant-TW", "zh")],
)
def test_base_language_strips_the_region(locale: str, expected: str) -> None:
    assert base_language(locale) == expected


def test_a_regional_locale_uses_its_base_language_before_english() -> None:
    """The reason this chain exists at all.

    The platform ships es-CL, es-CO, es-MX and pt-BR. No catalog in this module
    is keyed by region, so without the middle step every one of those readers
    would skip a perfectly good Spanish or Portuguese label and be shown
    English instead.
    """
    catalog = {"en": "Client", "es": "Cliente"}

    assert resolve_label(catalog, "es-CL") == "Cliente"
    assert resolve_label(catalog, "es") == "Cliente"
    # A language with no entry still lands somewhere readable.
    assert resolve_label(catalog, "ja") == "Client"


def test_an_exact_regional_entry_wins_over_the_base_language() -> None:
    catalog = {"en": "Formwork", "es": "encofrado", "es-CO": "formaleta"}

    assert resolve_label(catalog, "es-CO") == "formaleta"
    assert resolve_label(catalog, "es-CL") == "encofrado"


# ── Wann: the phase spine ───────────────────────────────────────────────────


@pytest.mark.parametrize("system", sorted(PHASE_SYSTEMS))
def test_every_stage_system_has_an_entry_for_every_spine_phase(system: str) -> None:
    """An entry, which may be ``None``. A missing key is a lookup that crashes."""
    assert set(PHASE_SYSTEMS[system]) == set(PHASE_SPINE)


def test_a_system_may_have_no_name_for_a_phase() -> None:
    """The property the whole mapping is built around.

    RIBA has no separate permit stage and HOAI does not pay for a strategic
    one. Forcing each spine phase into every system would put an equivalence in
    front of an architect that their own standard does not make.
    """
    assert phase_in_system("approval", "riba") is None
    assert phase_in_system("strategy", "hoai") is None
    # And the ones that do exist are named.
    assert phase_in_system("approval", "hoai") == "LP 4 Genehmigungsplanung"
    assert phase_in_system("strategy", "riba") == "Stage 0 Strategic Definition"


def test_an_unknown_system_answers_none_rather_than_raising() -> None:
    assert phase_in_system("detail", "no_such_system") is None


def test_the_hoai_titles_match_the_ones_the_dach_pack_already_ships() -> None:
    """Cross-module consistency, not a restatement of the same list.

    A German user meets Leistungsphasen in the fee schedule and again on a
    requirement. If the two modules spelled them differently, the platform
    would look like it was describing two different standards.
    """
    from app.modules.dach_pack.config import PACK_CONFIG

    hoai = next(s for s in PACK_CONFIG["standards"] if s["code"] == "HOAI")
    pack_titles = {f"LP {p['lp']} {p['title']}" for p in hoai["service_phases"]}

    for phase, name in PHASE_SYSTEMS["hoai"].items():
        if name is None:
            continue
        # LP 8 covers both construction and handover here, and the pack spells
        # it with its full "Objektüberwachung - Bauüberwachung" title.
        assert any(title.startswith(name) for title in pack_titles), f"{phase} -> {name!r} is not a DACH pack title"


def test_the_spine_is_ordered_earliest_first() -> None:
    assert phase_rank("strategy") < phase_rank("design") < phase_rank("construction") < phase_rank("operation")


def test_an_unknown_phase_sorts_last_rather_than_first() -> None:
    """A row from an import must not float to the top of a phase-sorted list."""
    assert phase_rank("no_such_phase") > phase_rank("operation")


@pytest.mark.parametrize("phase", PHASE_SPINE)
def test_every_spine_phase_has_a_neutral_label(phase: str) -> None:
    """For the majority of projects that run neither HOAI nor RIBA."""
    assert PHASE_LABELS[phase]["en"]


# ── Wie and Wer ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method", VERIFICATION_METHODS)
def test_every_verification_method_has_words(method: str) -> None:
    """Otherwise a German screen offers the reader ``document_review``."""
    assert VERIFICATION_LABELS[method]["en"]
    assert VERIFICATION_LABELS[method]["de"]


@pytest.mark.parametrize("role", ORIGINATOR_ROLES)
def test_every_party_role_has_words(role: str) -> None:
    assert ORIGINATOR_ROLE_LABELS[role]["en"]
    assert ORIGINATOR_ROLE_LABELS[role]["de"]


# ── The cycle ───────────────────────────────────────────────────────────────


def test_the_cycle_is_six_questions() -> None:
    assert [question for question, _field in CYCLE_QUESTIONS] == [
        "what",
        "why",
        "who",
        "when",
        "how",
        "with_what",
    ]


def test_a_bare_triplet_answers_only_what() -> None:
    answers = {"entity": "exterior_wall", "rationale": "", "originator": "", "phase": "", "verification_method": ""}

    assert unanswered_questions(answers) == ("why", "who", "when", "how", "with_what")
    assert cycle_completeness(answers) == pytest.approx(16.67)


def test_an_empty_collection_is_unanswered_but_a_zero_is_an_answer() -> None:
    """A count of zero is a statement. An empty list of links is not.

    Treating them the same would either mark every unlinked requirement
    complete or mark a legitimately zero-valued field incomplete.
    """
    assert "with_what" in unanswered_questions({"position_links": []})
    assert "with_what" not in unanswered_questions({"position_links": [uuid.uuid4()]})
    assert "why" not in unanswered_questions({"rationale": 0})
    assert "why" not in unanswered_questions({"rationale": False})


# ── The priority spelling that rendered as a raw key ────────────────────────


def test_the_legacy_priority_spelling_has_a_label_in_every_catalogued_language() -> None:
    """``may`` was accepted by this API long before the label catalog existed.

    Without an entry it rendered as the English word "may" to a reader in any
    of the platform's languages, because the fallback had nothing to fall back
    from.
    """
    assert PRIORITY_LABELS["may"]["de"] == PRIORITY_LABELS["could"]["de"]
    assert priority_label("may", "ru") == priority_label("could", "ru")


def test_the_legacy_spelling_sorts_where_the_word_it_means_sorts() -> None:
    """Otherwise one priority splits into two groups in a sorted list."""
    assert PRIORITY_ALIASES["may"] == "could"
    assert priority_rank("may") == priority_rank("could")


# ── The three hand-written column lists ─────────────────────────────────────


def test_every_field_the_create_schema_validates_reaches_a_column() -> None:
    """The durable form of a bug this module had three times over.

    Two service constructors and one response builder each named the columns
    themselves, and none of them could notice a field the others had. A field
    added to the schema was validated, accepted, and then dropped - silently,
    with a default in its place and nothing failing.
    """
    columns = {c.name for c in Requirement.__table__.columns}
    schema_fields = set(RequirementCreate.model_fields)

    assert not schema_fields - columns, f"validated but unstorable: {sorted(schema_fields - columns)}"


def test_the_only_field_the_builder_has_to_rename_is_the_one_it_renames() -> None:
    """``metadata`` is the column name but not the attribute name.

    SQLAlchemy's declarative base owns ``metadata``, so the ORM exposes the
    column as ``metadata_``. That is the single rename the builder applies, and
    a second one appearing without being added to the map would pass the
    column-name check above and then fail at construction.
    """
    from app.modules.requirements.service import _CREATE_RENAMES

    assert _CREATE_RENAMES == {"metadata": "metadata_"}
    for schema_name, orm_name in _CREATE_RENAMES.items():
        assert hasattr(Requirement, orm_name), f"builder renames to {orm_name}, which the model does not have"
        assert not hasattr(Requirement, schema_name) or orm_name != schema_name


def test_the_create_builder_carries_the_five_new_answers_onto_the_row() -> None:
    data = RequirementCreate(
        entity="exterior_wall",
        attribute="fire_rating",
        constraint_value="F90",
        rationale="Musterbauordnung 30",
        originator="Bauamt Frankfurt",
        originator_role="authority",
        phase="detail",
        verification_method="model_check",
    )

    row = _requirement_from_create(uuid.uuid4(), data, "user-1")

    assert row.rationale == "Musterbauordnung 30"
    assert row.originator == "Bauamt Frankfurt"
    assert row.originator_role == "authority"
    assert row.phase == "detail"
    assert row.verification_method == "model_check"


def test_the_confidence_float_is_stored_as_its_text() -> None:
    """The one genuine conversion the builder still has to make by hand."""
    data = RequirementCreate(entity="e", attribute="a", constraint_value="v", confidence=0.87)

    assert _requirement_from_create(uuid.uuid4(), data, "").confidence == "0.87"


def test_the_response_carries_every_answer_back_out() -> None:
    fields = set(RequirementResponse.model_fields)

    assert {"rationale", "originator", "originator_role", "phase", "verification_method"} <= fields
    assert {"linked_position_ids", "unanswered_questions", "cycle_completeness"} <= fields


@pytest.mark.parametrize(("stored", "expected"), [("0.5", 0.5), ("not-a-number", None), (None, None), ("", None)])
def test_an_unreadable_confidence_does_not_refuse_the_whole_requirement(
    stored: str | None, expected: float | None
) -> None:
    """One malformed historic value must not hide the twenty fields beside it.

    Asserted through the model rather than by calling the validator directly,
    because what matters is that serialising the requirement succeeds.
    """
    now = datetime(2026, 8, 11, tzinfo=UTC)
    response = RequirementResponse.model_validate(
        {
            "id": uuid.uuid4(),
            "requirement_set_id": uuid.uuid4(),
            "entity": "exterior_wall",
            "attribute": "fire_rating",
            "constraint_type": "equals",
            "constraint_value": "F90",
            "confidence": stored,
            "created_at": now,
            "updated_at": now,
        }
    )

    assert response.confidence == expected
    assert response.entity == "exterior_wall"


# ── The patterns are generated, not retyped ─────────────────────────────────


@pytest.mark.parametrize("phase", PHASE_SPINE)
def test_the_schema_accepts_every_phase_on_the_spine(phase: str) -> None:
    """The pattern is built from the spine, so this can only fail if one of
    them stops being a valid regex alternation member."""
    assert RequirementCreate(entity="e", attribute="a", constraint_value="v", phase=phase).phase == phase


@pytest.mark.parametrize("method", VERIFICATION_METHODS)
def test_the_schema_accepts_every_verification_method(method: str) -> None:
    created = RequirementCreate(entity="e", attribute="a", constraint_value="v", verification_method=method)
    assert created.verification_method == method


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase", "detailed_design"),
        ("verification_method", "smell_test"),
        ("originator_role", "project_manager"),
        ("priority", "urgent"),
    ],
)
def test_a_value_outside_the_vocabulary_is_refused(field: str, value: str) -> None:
    """A free-text phase would make the whole point of a key vocabulary moot."""
    with pytest.raises(ValueError):
        RequirementCreate(entity="e", attribute="a", constraint_value="v", **{field: value})


def test_a_set_defaults_to_the_neutral_wording() -> None:
    """The standard's wording is precise for projects that run it and opaque
    for the ones that do not, and most do not."""
    created = RequirementSetCreate(project_id=uuid.uuid4(), name="Fire requirements")

    assert created.vocabulary == "neutral"
