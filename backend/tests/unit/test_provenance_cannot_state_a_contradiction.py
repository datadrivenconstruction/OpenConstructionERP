"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The provenance type must refuse to describe the defects it was built for.

Every assertion here that a construction *succeeds* would also pass against a
plain dataclass with no validation at all, so those carry no weight on their
own. The load-bearing tests are the ones that assert a raise, and each is
written from a defect that actually shipped:

* a config endpoint answering "these are CA's phone rules" about the generic
  ones, which is ``DECLARED`` with the requested and used codes differing;
* a calendar endpoint labelling a Canadian project "Standard", which is the same
  lie with the fields swapped;
* a holiday calculation raising, being swallowed into an empty set, and every
  day of the year becoming a working day, which is ``UNAVAILABLE`` being treated
  as an answer.
"""

from __future__ import annotations

import pytest

from app.core.provenance import (
    Provenance,
    Source,
    declared,
    fell_back,
    unavailable,
    weakest,
)

# ── The contradictions, which are the point of the type ─────────────────────


def test_a_declared_answer_cannot_name_a_different_thing_as_its_source() -> None:
    """The phone-rules defect, in the exact shape it shipped."""
    with pytest.raises(ValueError, match="that is a fallback"):
        Provenance(axis="jurisdiction", source=Source.DECLARED, requested="CA", used="DEFAULT")


@pytest.mark.parametrize("source", [Source.DECLARED, Source.PROJECT, Source.PLATFORM])
def test_no_answered_source_may_contradict_itself(source: Source) -> None:
    """All three answered sources carry the invariant, not only the first."""
    with pytest.raises(ValueError):
        Provenance(axis="jurisdiction", source=source, requested="CA", used="DEFAULT")


def test_a_fallback_cannot_claim_it_used_what_it_was_asked_for() -> None:
    """The same lie the other way round: a real row dressed as a default."""
    with pytest.raises(ValueError, match="cannot have used the very thing"):
        Provenance(axis="jurisdiction", source=Source.FALLBACK, requested="DE", used="DE")


def test_a_fallback_must_name_what_answered_instead() -> None:
    """The hole a careful adopter falls into without trying.

    ``fell_back(axis, code, table.get(code, ""))`` looks reasonable and produces
    a fallback naming nothing as the stand-in, which still reports ``usable``.
    A caller is then told it may compute with a value whose origin the record
    does not carry, which is the condition this module exists to prevent.

    Found by an adopting module rather than by this test file, which is why it
    is here: four modules took this type up on the same day.
    """
    with pytest.raises(ValueError, match="must name what answered"):
        Provenance(axis="jurisdiction", source=Source.FALLBACK, requested="AT")


def test_a_fallback_that_names_a_token_is_accepted() -> None:
    """The control for the test above: the honest shape must still construct.

    Without this, the constraint could be satisfied by refusing every fallback,
    and the test above would pass against a type nobody can use.
    """
    p = Provenance(axis="jurisdiction", source=Source.FALLBACK, requested="AT", used="INTERNATIONAL")
    assert p.usable is True
    assert p.answered is False


def test_nothing_answering_is_unavailable_rather_than_a_nameless_fallback() -> None:
    """The escape route the refusal points at has to exist.

    An adopter told a nameless fallback is illegal needs somewhere to put the
    case where genuinely nothing answered, and that is UNAVAILABLE, which is
    the one source allowed to leave *used* empty.
    """
    p = unavailable("jurisdiction", "AT", detail="no table and no default")
    assert p.used == ""
    assert p.usable is False


def test_an_unavailable_cannot_have_used_anything() -> None:
    """The swallowed-exception defect: nothing answered, so nothing was used."""
    with pytest.raises(ValueError, match="nothing answered"):
        Provenance(axis="calendar", source=Source.UNAVAILABLE, requested="CA", used="DEFAULT")


def test_a_provenance_must_name_its_axis() -> None:
    """An axis-less provenance is the wrapper this module refused to be."""
    with pytest.raises(ValueError, match="name the axis"):
        Provenance(axis="", source=Source.DECLARED)


# ── The honest shapes still construct ───────────────────────────────────────


def test_the_shapes_that_are_true_are_accepted() -> None:
    assert declared("jurisdiction", "DE").used == "DE"
    assert fell_back("jurisdiction", "CA", "INTERNATIONAL").requested == "CA"
    assert unavailable("calendar", "CA", detail="holiday table raised").used == ""


def test_an_unknown_request_may_still_be_declared_when_nothing_was_asked() -> None:
    """A resolution with no request is not a contradiction, only uninformative.

    Guarding on both fields being non-empty is deliberate: a helper that has no
    request to record must not be forced to invent one, and inventing one is the
    failure this module exists to prevent.
    """
    assert Provenance(axis="language", source=Source.DECLARED, used="pt-BR").answered is True


# ── answered and usable are different questions ─────────────────────────────


@pytest.mark.parametrize(
    ("source", "answered", "usable"),
    [
        (Source.DECLARED, True, True),
        (Source.PROJECT, True, True),
        (Source.PLATFORM, True, True),
        (Source.FALLBACK, False, True),
        (Source.UNAVAILABLE, False, False),
    ],
)
def test_answered_and_usable_split_where_the_plan_says_they_split(source: Source, answered: bool, usable: bool) -> None:
    """Amber is a working state: a fallback is not answered and is still usable.

    The row that matters is FALLBACK, where the two verdicts differ. A test that
    only checked the ends would pass against an implementation where the two
    properties are the same function.

    Each source is built in the only shape it is allowed to take, because the
    constructor rejects the others. Writing one shape for all five and expecting
    it to construct is a test of the fixture rather than of the properties.
    """
    if source is Source.UNAVAILABLE:
        p = Provenance(axis="jurisdiction", source=source, requested="CA")
    elif source is Source.FALLBACK:
        p = Provenance(axis="jurisdiction", source=source, requested="CA", used="INTERNATIONAL")
    else:
        p = Provenance(axis="jurisdiction", source=source, requested="CA", used="CA")
    assert p.answered is answered
    assert p.usable is usable


def test_answered_and_usable_are_not_the_same_property() -> None:
    """The negative control for the parametrised table above."""
    p = fell_back("jurisdiction", "CA", "INTERNATIONAL")
    assert p.answered is not p.usable


# ── weakest ─────────────────────────────────────────────────────────────────


def test_weakest_finds_the_worst_axis_wherever_it_sits() -> None:
    """Argument order must not decide the answer.

    Run both ways round, because an implementation that returned the first or
    the last argument would pass either call on its own.
    """
    good = declared("jurisdiction", "DE")
    bad = fell_back("effective_date", "2026-01-01", "latest")
    assert weakest(good, bad) is bad
    assert weakest(bad, good) is bad


def test_an_honest_jurisdiction_does_not_rescue_a_silent_second_axis() -> None:
    """The tax engine, which is honest on one axis and opaque on the other.

    This is the case a single wrapper keyed on jurisdiction would have painted
    green, and it is why provenance is per axis.
    """
    verdict = weakest(
        declared("jurisdiction", "DE"),
        unavailable("effective_date", "2019-06-30", detail="no rate in force on that date"),
    )
    assert verdict.source is Source.UNAVAILABLE
    assert verdict.axis == "effective_date"


def test_weakest_of_one_is_that_one() -> None:
    p = declared("language", "en-US")
    assert weakest(p) is p


def test_weakest_refuses_to_judge_nothing() -> None:
    """An empty call would have to invent a verdict, which is the whole defect."""
    with pytest.raises(ValueError, match="at least one"):
        weakest()


# ── Strength relations, pinned pairwise rather than as a list ───────────────


@pytest.mark.parametrize(
    ("stronger", "weaker"),
    [
        (Source.DECLARED, Source.PROJECT),
        (Source.PROJECT, Source.PLATFORM),
        (Source.PLATFORM, Source.FALLBACK),
        (Source.FALLBACK, Source.UNAVAILABLE),
    ],
)
def test_each_source_is_weaker_than_the_one_before_it(stronger: Source, weaker: Source) -> None:
    """Pinned as pairs, not as the whole member list.

    A test asserting the exact tuple of members breaks the day somebody adds a
    legitimate sixth source, which trains people to edit the test rather than
    read it. These pairs are the relations ``weakest`` actually depends on, and
    they survive a new member being inserted at its true strength.
    """
    a = Provenance(axis="x", source=stronger, requested="q", used="q" if stronger is not Source.FALLBACK else "r")
    b = Provenance(
        axis="x",
        source=weaker,
        requested="q",
        used="" if weaker is Source.UNAVAILABLE else ("r" if weaker is Source.FALLBACK else "q"),
    )
    assert weakest(a, b) is b
    assert weakest(b, a) is b


def test_the_source_values_are_the_tokens_the_plan_names() -> None:
    """The wire format, which reaches an API response and a UI label.

    Values rather than names, because these are what a client branches on, and
    renaming one silently is a breaking change that no type checker sees.
    """
    assert Source.DECLARED.value == "declared"
    assert Source.FALLBACK.value == "fallback"
    assert Source.UNAVAILABLE.value == "unavailable"
