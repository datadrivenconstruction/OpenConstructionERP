# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A comment saying two shapes must stay in sync does not keep them in sync.

``bim_hub.schemas.RequirementBrief`` is a hand-written subset of
``requirements.schemas.RequirementResponse``, defined locally so bim_hub does
not have to import requirements and create a cycle. That is a reasonable
trade. What was not reasonable is that the only thing holding the two together
was a sentence in a docstring: "the two shapes MUST stay in sync". Nothing ran.

The failure mode is quiet in the direction that matters. Rename or drop a field
in the requirements schema and the brief keeps declaring it, so pydantic fills
it from a default and the BIM viewer renders a plausible wrong value forever.
Nobody sees a stack trace, because ``from_attributes`` reading a name the ORM
no longer has is exactly the case a default exists for.

So the test is one-directional on purpose. The brief is allowed to be smaller,
that is its whole reason for existing, but every name it does carry has to
still mean the same thing on the other side. Adding a field to the requirements
schema is not a failure here; removing one that the brief still claims is.
"""

from __future__ import annotations

from app.modules.bim_hub.schemas import RequirementBrief
from app.modules.requirements.models import Requirement
from app.modules.requirements.schemas import RequirementResponse


def _annotation(model: type, name: str) -> object:
    """The declared type of one field, without pydantic's wrapping."""
    return model.model_fields[name].annotation


class TestTheBriefIsASubsetAndStaysOne:
    def test_every_field_on_the_brief_exists_on_the_response(self) -> None:
        """The brief may be smaller. It may not name something that is gone."""
        brief = set(RequirementBrief.model_fields)
        full = set(RequirementResponse.model_fields)
        missing = sorted(brief - full)
        assert not missing, (
            "RequirementBrief declares fields that RequirementResponse no longer has: "
            f"{missing}. Either the field was renamed or dropped in "
            "app/modules/requirements/schemas.py and the brief was not followed, or "
            "the brief invented a name. Pydantic will not complain about either, "
            "it will serve a default to the BIM viewer."
        )

    def test_the_shared_fields_declare_the_same_type(self) -> None:
        """A str that quietly became a list would deserialise into nonsense.

        Kept separate from the name check because the two fail for different
        reasons and the fix differs: a missing name is a rename to follow, a
        changed type is a decision about whether the brief should carry the
        field at all.
        """
        shared = sorted(set(RequirementBrief.model_fields) & set(RequirementResponse.model_fields))
        mismatched = [
            name for name in shared if _annotation(RequirementBrief, name) != _annotation(RequirementResponse, name)
        ]
        assert not mismatched, (
            f"RequirementBrief and RequirementResponse disagree on the type of: {mismatched}. "
            "The brief is read out of the same ORM rows, so a divergent type is a "
            "wrong value rather than an error."
        )

    def test_the_brief_is_genuinely_smaller(self) -> None:
        """If it ever equals the full response, the copy has lost its excuse.

        The duplication is paid for by keeping the BIM element payload light.
        A brief that carries everything is just a second copy of a schema, and
        at that point the circular import is the cheaper problem to solve.
        """
        brief = set(RequirementBrief.model_fields)
        full = set(RequirementResponse.model_fields)
        assert brief < full, (
            "RequirementBrief is no longer a proper subset of RequirementResponse. "
            "It is embedded in every element of a model response, so it exists to "
            "be small."
        )


class TestTheBuilderCanActuallyFillIt:
    def test_every_brief_field_is_readable_off_the_orm_row(self) -> None:
        """The schema is only half the contract, the builder is the other half.

        ``BIMHubService.list_elements_with_links`` fills the brief with
        ``getattr(req, name)`` for each of its fields. A name the ORM row does
        not carry reads as ``None``, gets dropped, and the field arrives at the
        viewer as its default. That is the same silent-default failure the
        schema check above guards against, one layer down, and it is why the
        brief was previously written out by hand and could not gain a field.
        """
        unreadable = sorted(name for name in RequirementBrief.model_fields if not hasattr(Requirement, name))
        assert not unreadable, (
            f"RequirementBrief declares fields that a Requirement row cannot answer: {unreadable}. "
            "The BIM element brief is built by reading each field name off the ORM row, so "
            "these would ship as defaults on every element without any error."
        )


class TestTheCycleAnswersReachTheViewer:
    def test_the_brief_carries_when_and_how(self) -> None:
        """Phase and verification method are what make a requirement actionable.

        Standing in front of an element, the two questions are whether this
        applies at the current stage and how it would be proven. Both are short
        neutral keys, so carrying them costs nothing and leaving them out means
        the viewer can only say that some constraint exists.
        """
        assert "phase" in RequirementBrief.model_fields
        assert "verification_method" in RequirementBrief.model_fields

    def test_the_prose_answers_stay_out(self) -> None:
        """Rationale and originator are deliberately absent, not forgotten.

        Written down because the obvious reading of the test above is "add the
        rest too". These are free text of unbounded length and the brief is
        repeated per element, so they belong on the requirement's own screen.
        """
        assert "rationale" not in RequirementBrief.model_fields
        assert "originator" not in RequirementBrief.model_fields
