# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every seeded letter must name a party the demo actually has a contact for.

The correspondence seeds carry the counterparty as a role on the seed tuple.
The writer turns that role into a contact id, so a role with no matching
contact produces a letter linked to nobody, which is the state this change was
made to end. Three of the ten letters are with a permitting body, the notice of
commencement, its acknowledgement and the inspection report, and the generated
contact list had no authority in it at all.

The role deliberately is not read back out of the subject line. The subjects do
name the party and parsing them is the obvious shortcut, but they are English
prose written to be read on a screen and they get reworded; a parser keyed on
the word "Authority" would keep producing rows after a rewording, pointing at
the wrong contact or at none, with nothing to notice. That makes the pairing
between the two lists a thing worth asserting rather than deriving.

What this does not cover: the resolution itself lives in the seeding writer and
needs a database to reach, so the direction rule (an outgoing letter fills
to_contact_ids, an incoming one fills from_contact_id) is not exercised here.
This file checks the half reachable without one, which is that every role named
is a role the demo seeds.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data

# Read from the checkout rather than from the module's __file__, so the file
# under test is the one this commit changes whatever the install layout is.
_SOURCE = Path(__file__).resolve().parents[2] / "app" / "core" / "demo_projects.py"


def _curated(name: str) -> ast.Dict:
    """The hand-curated seed dict of that name, as source.

    ``_CONTACTS`` and ``_CORRESPONDENCE`` are locals inside the seeding
    function and it needs a database to reach, so they are read statically.
    ``_CORRESPONDENCE`` is not even a literal, its dates are computed, which is
    why this returns the syntax tree rather than a value.
    """
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and isinstance(node.value, ast.Dict)
        ):
            return node.value
    raise AssertionError(f"{name} is no longer an annotated dict literal in {_SOURCE.name}")


def _curated_contact_roles() -> dict[str, set[str]]:
    """Roles in each hand-curated contact list, by demo."""
    out: dict[str, set[str]] = {}
    for key, value in zip(_curated("_CONTACTS").keys, _curated("_CONTACTS").values, strict=True):
        roles: set[str] = set()
        for entry in value.elts:
            for k, v in zip(entry.keys, entry.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == "contact_type":
                    roles.add(v.value)
        out[key.value] = roles
    return out


def _demos_with_curated_letters() -> set[str]:
    return {k.value for k in _curated("_CORRESPONDENCE").keys}


def _generated(demo_id: str) -> dict:
    return _generate_module_data(
        DEMO_TEMPLATES[demo_id],
        project_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        demo_id=demo_id,
        base=datetime(2026, 1, 15, tzinfo=UTC),
    )


def _letters_linked_to_nobody(letters: list[dict], seeded_roles: set[str]) -> list[str]:
    """References of the letters whose party the demo seeds no contact for.

    Both tests below go through here, so the failing case exercises the same
    code the passing case does rather than a restatement of it.
    """
    return [
        letter["reference_number"]
        for letter in letters
        if not letter.get("party") or letter["party"] not in seeded_roles
    ]


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_every_letter_is_with_a_party_the_demo_seeds(demo_id: str) -> None:
    data = _generated(demo_id)
    letters = data.get("correspondence", [])
    assert letters, f"{demo_id} generated no correspondence at all"

    seeded_roles = {c["contact_type"] for c in data.get("contacts", [])}
    unlinked = _letters_linked_to_nobody(letters, seeded_roles)
    assert not unlinked, (
        f"{demo_id} seeds {len(unlinked)} letters with a party it has no contact for: "
        f"{unlinked}; it seeds {sorted(seeded_roles)}"
    )


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_the_permitting_body_letters_have_something_to_point_at(demo_id: str) -> None:
    """The same check narrowed onto the case that was actually broken.

    A regression here names the authority rather than only failing somewhere in
    the loop above, which is the difference between a report you can act on and
    one you have to go and read the seed list to understand.
    """
    data = _generated(demo_id)
    letters = [c for c in data.get("correspondence", []) if c.get("party") == "authority"]
    assert letters, f"{demo_id} seeds no authority correspondence"

    roles = {c["contact_type"] for c in data.get("contacts", [])}
    assert "authority" in roles, (
        f"{demo_id} writes {len(letters)} letters to or from a permitting body and seeds no authority contact for them"
    )


def test_a_curated_contact_list_covers_the_letters_it_is_paired_with() -> None:
    """The pair that reaches the database is not always a pair one demo produced.

    The writer picks the two lists independently, curated first and generated
    as the fallback, for contacts and for letters separately. So a demo with a
    hand-curated contact list and no curated correspondence is seeded with
    curated contacts and generated letters, a combination the generator never
    produces on its own and the tests above therefore never see. If that
    curated list happens to omit a role the generated letters name, those
    letters resolve to nobody, which is the defect this change exists to fix
    surviving in the hand-curated demos, the ones most likely to be shown.

    Only retail-market-heilbronn is in that position today and it does carry
    all four roles. This asserts it, so adding a curated contact list to
    another demo has to face the question rather than quietly reopen it.
    """
    generated_parties = {letter["party"] for letter in _generated(sorted(DEMO_TEMPLATES)[0])["correspondence"]}
    curated_letters = _demos_with_curated_letters()

    for demo_id, roles in sorted(_curated_contact_roles().items()):
        if demo_id in curated_letters:
            continue  # curated letters carry no role, so there is nothing to resolve
        missing = sorted(generated_parties - roles)
        assert not missing, (
            f"{demo_id} is seeded with its own contacts but generated letters, and its "
            f"contact list has no {missing}; those letters would link to nobody"
        )


def test_the_check_above_reports_a_party_with_no_contact() -> None:
    """Without this the file could pass by asserting nothing."""
    seeded_roles = {"client", "consultant", "authority", "subcontractor"}
    planted = [
        {"reference_number": "OUT-2026-900", "party": "insurer"},
        {"reference_number": "IN-2026-901", "party": None},
        {"reference_number": "OUT-2026-902", "party": "client"},
    ]
    assert _letters_linked_to_nobody(planted, seeded_roles) == [
        "OUT-2026-900",
        "IN-2026-901",
    ]
