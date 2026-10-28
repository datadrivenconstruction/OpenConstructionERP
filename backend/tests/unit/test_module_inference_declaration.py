# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# What a module says it does with inference, and the three states that are easy
# to collapse into each other.
#
# The register this feeds answers the question "which of these modules performs
# inference, and on what". It is only worth answering if a module that has never
# been read is distinguishable from one that was read and found to do nothing,
# and if a claim that something is not an AI system has to carry its reason. Both
# are properties of the declaration type rather than of any module, so they are
# pinned here rather than in a gate over the tree.

from __future__ import annotations

import pytest

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest


def _manifest(**kwargs: object) -> ModuleManifest:
    return ModuleManifest(name="oe_probe", version="1.0.0", display_name="Probe", **kwargs)  # type: ignore[arg-type]


def test_a_module_that_says_nothing_is_undeclared_and_not_declared_empty() -> None:
    """The default has to be absent, because silence is not a statement."""
    assert _manifest().inference is None


def test_declaring_none_is_a_different_state_from_saying_nothing() -> None:
    """Someone looked and found nothing. That is a fact and it reads as one."""
    declared = _manifest(inference=InferenceDeclaration(role=InferenceRole.NONE))

    assert declared.inference is not None
    assert declared.inference.role is InferenceRole.NONE
    assert declared.inference.gaps() == []


def test_a_role_outside_the_vocabulary_fails_where_it_was_written() -> None:
    """A typo is a wrong statement, so it raises rather than being collected."""
    with pytest.raises(ValueError, match="llm"):
        InferenceDeclaration(role="llm")  # type: ignore[arg-type]


def test_the_spelling_people_will_actually_write_is_accepted() -> None:
    """A manifest carries `role="calls_model"`, not an imported enum member."""
    declared = InferenceDeclaration(role="calls_model", what="cost text against a catalogue")  # type: ignore[arg-type]

    assert declared.role is InferenceRole.CALLS_MODEL


def test_claiming_the_exclusion_without_a_ground_is_reported_not_accepted() -> None:
    """`rule_based` is an argument, and an argument with no reason is evasion."""
    bare = InferenceDeclaration(role=InferenceRole.RULE_BASED)

    assert bare.gaps(), "a rule_based claim with no basis must not read as complete"
    assert "basis" in bare.gaps()[0]

    grounded = InferenceDeclaration(
        role=InferenceRole.RULE_BASED,
        what="colours elements by user-written rules",
        basis="hard-coded predicates over element fields, no model of any kind is loaded",
    )
    assert grounded.gaps() == []


@pytest.mark.parametrize("role", [InferenceRole.CALLS_MODEL, InferenceRole.CONSUMES_RESULT])
def test_a_role_about_a_model_has_to_say_what_it_infers(role: InferenceRole) -> None:
    """Knowing that a module calls a model, and not what for, answers nobody."""
    assert InferenceDeclaration(role=role).gaps()
    assert InferenceDeclaration(role=role, what="a supplier invoice into a booking draft").gaps() == []


def test_an_incomplete_declaration_does_not_take_the_module_off_the_air() -> None:
    """A missing sentence must not cost a module its endpoints.

    The loader logs and skips a manifest that raises on import, so a manifest
    that validated by raising would turn a documentation defect into every
    endpoint in that module answering 404. The gaps are returned instead, and
    the gate is what reads them.
    """
    manifest = _manifest(inference=InferenceDeclaration(role=InferenceRole.CALLS_MODEL))

    assert manifest.inference is not None
    assert manifest.inference.gaps() != []


def test_the_declaration_cannot_be_edited_after_a_manifest_states_it() -> None:
    """A register whose entries can be rewritten in place is not a record."""
    declared = InferenceDeclaration(role=InferenceRole.NONE)

    with pytest.raises(Exception, match="assign"):
        declared.role = InferenceRole.CALLS_MODEL  # type: ignore[misc]


def test_one_declaration_reads_back_as_one_declaration() -> None:
    """The common case must not cost the author a one-element tuple."""
    declared = _manifest(inference=InferenceDeclaration(role=InferenceRole.NONE))

    assert declared.inference_declarations() == (InferenceDeclaration(role=InferenceRole.NONE),)
    assert _manifest().inference_declarations() == ()


def test_a_module_whose_answer_depends_on_the_call_can_give_both_answers() -> None:
    """The shape a single role records wrongly for most of an endpoint's calls.

    One matcher, one endpoint, three modes, and the mode arrives as a request
    parameter. A field that can hold only one role has to pick between saying
    that a string comparison is a model and saying that an encoder is not.
    """
    declared = _manifest(
        inference=(
            InferenceDeclaration(
                role=InferenceRole.RULE_BASED,
                when="mode='lexical'",
                what="a description into catalogue candidates",
                basis="a fixed string ratio and two constant bonuses, all written in the file",
            ),
            InferenceDeclaration(
                role=InferenceRole.CALLS_MODEL,
                when="mode='semantic' or mode='hybrid'",
                what="the same ranking, by embedding both sides",
            ),
        )
    )

    roles = [d.role for d in declared.inference_declarations()]

    assert roles == [InferenceRole.RULE_BASED, InferenceRole.CALLS_MODEL]
    assert declared.inference_gaps() == []


def test_two_declarations_that_do_not_say_when_are_a_gap_not_two_facts() -> None:
    """Unconditional twice is a contradiction, and neither entry is quotable."""
    declared = _manifest(
        inference=(
            InferenceDeclaration(role=InferenceRole.NONE),
            InferenceDeclaration(role=InferenceRole.CALLS_MODEL, what="something"),
        )
    )

    gaps = declared.inference_gaps()

    assert len(gaps) == 2
    assert all("`when`" in gap for gap in gaps)


def test_two_declarations_claiming_the_same_condition_are_a_gap() -> None:
    """A register asked for the answer under this condition gets two."""
    declared = _manifest(
        inference=(
            InferenceDeclaration(role=InferenceRole.NONE, when="mode='lexical'"),
            InferenceDeclaration(role=InferenceRole.CALLS_MODEL, when="mode='lexical'", what="something"),
        )
    )

    assert any("both claim" in gap for gap in declared.inference_gaps())


def test_a_single_declaration_does_not_have_to_say_when() -> None:
    """Requiring it everywhere would fill 190 manifests with the word always."""
    declared = _manifest(inference=InferenceDeclaration(role=InferenceRole.NONE))

    assert declared.inference_gaps() == []
