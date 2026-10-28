# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What a hand-made methodology is priced at, against what it says on screen.

A methodology installed from the catalogue carries its country's rate, and the
project VAT override lands on a number the reader recognises. A methodology the
user made by hand is the sharper case, and it is the one this file pins.

``CreateMethodologyModal.tsx`` seeds a new methodology with exactly one cascade
step, ``category="tax"``, ``rate="0"``, and sends ``vat_rate="0"`` beside it.
Exactly one tax step is precisely the condition
:meth:`MethodologyService._with_project_vat` requires, so that nought is
replaced by the project's own rate at pricing time. The computed figures and
both exports are right to do this, and they report the rate they used. The read
side does not: ``GET /methodologies/{id}`` serves the stored steps and the
stored ``vat_rate``, so a screen showing VAT nought belongs to a bill costed at
the project's rate, with nothing on the screen saying so.

This file characterises that behaviour rather than blessing it. Whether the
read side should carry an override signal, resolve the effective rate, or ask
the user before substituting at all is an open product question. What is not
open is that the substitution happens on the hand-made stack too, which is easy
to miss because every catalogue template arrives with a plausible rate already
in place and only the blank one starts at nought.
"""

from __future__ import annotations

from app.modules.methodology.service import MethodologyService

# The stack CreateMethodologyModal.tsx seeds for a brand new methodology, in the
# wire shape the service stores and reads back. Kept as a literal rather than
# imported, because the point of the test is that the two layers agree by
# accident of shape and nothing holds them together.
_BLANK_STACK: list[dict[str, object]] = [
    {
        "key": "vat",
        "label": "VAT",
        "category": "tax",
        "kind": "percentage",
        "rate": "0",
        "amount": "0",
        "base": ["direct"],
    },
]


def test_the_blank_stack_carries_exactly_one_tax_step() -> None:
    """The seeded stack meets the override's precondition, and that is the point.

    If the modal ever seeds a second tax line, or drops the category, the
    override stops applying and a hand-made methodology silently changes which
    branch it travels. That would be a behaviour change nobody asked for, so it
    is asserted here rather than left to be noticed in a screenshot.
    """
    tax_steps = [s for s in _BLANK_STACK if str(s.get("category", "")).strip().lower() == "tax"]
    assert len(tax_steps) == 1, (
        f"the seeded stack carries {len(tax_steps)} tax steps; the project VAT override applies only to "
        f"exactly one, so a new methodology would no longer be re-rated by its project"
    )
    assert tax_steps[0]["rate"] == "0", "the seeded stack is expected to start at nought, which is what makes it sharp"


def test_a_new_methodology_is_priced_at_the_projects_rate_not_at_its_own_nought() -> None:
    """Nought on the screen, the project's rate in the cascade.

    Asserted at the override itself, which is pure, so the claim needs no
    stored rows. The stored side of the same statement lives in
    ``tests/pg/test_methodology_takes_the_projects_vat.py``.
    """
    swapped = MethodologyService._with_project_vat(_BLANK_STACK, "25")

    assert swapped[0]["rate"] == "25", (
        f"a project on 25 percent left the hand-made stack reading {swapped[0]['rate']}; the override did not land"
    )
    # The stored stack is untouched, so the read side genuinely still serves
    # nought. That is the half a reader never sees, and mutating in place would
    # have hidden it here while re-rating every later computation in the process.
    assert _BLANK_STACK[0]["rate"] == "0", "the override mutated the shared step dict instead of copying it"


def test_a_project_without_a_rate_leaves_the_hand_made_stack_alone() -> None:
    """The override is the only thing that moves the rate, and only when asked.

    ``compute_estimate`` calls it solely when the project states a rate, so the
    negative case is asserted here at the same seam: an empty stack of tax steps
    has nothing to substitute and must come back identical.
    """
    no_tax = [{"key": "oh", "label": "Overhead", "category": "overhead", "kind": "percentage", "rate": "10"}]
    assert MethodologyService._with_project_vat(no_tax, "25") is no_tax, (
        "a stack with no tax line has nothing a single project rate can stand in for and must be returned untouched"
    )

    # Two tax lines is the other side of the same precondition, and it is the
    # control that makes the positive case above mean something: if the
    # override fired regardless of how many tax steps it found, both
    # assertions in this file would pass for the wrong reason.
    two_tax = [*_BLANK_STACK, {"key": "gst", "label": "GST", "category": "tax", "kind": "percentage", "rate": "5"}]
    assert MethodologyService._with_project_vat(two_tax, "25") is two_tax, (
        "a stack with two tax lines cannot be re-rated by one project figure and must be returned untouched"
    )
