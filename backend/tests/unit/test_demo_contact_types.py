# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every contact the demo seeds must be a contact the API would accept.

The seeder builds ``Contact`` rows through the ORM, so ``contact_type`` never
meets ``ContactCreate`` on the way in. It wrote "contractor" on the generated
path, which reaches every generated demo, and "authority" in the hand-built
German project. Neither was in the schema's allowed set, so the product shipped
records its own create endpoint would refuse. Nothing crashed, which is why it
went unreported; the tell was the edit form, where the contact type is required
and its chip is selected by matching the stored value, so those rows opened with
nothing chosen and picking a chip silently rewrote the party's role.

This is the same failure as the variation-order vocabulary, from the same cause,
which is why there are two files rather than one broad "seeder is valid" test:
each names the field it guards.

Two tests do the work because the two blocks are reachable in different ways.
The generator can be called directly, so its contacts are validated as real
objects. The hand-built block is a local inside the seeding function and needs a
database to reach, so it is covered by reading the literals out of the source.
The third test keeps the file honest: it feeds a value the schema rejects
through the same assertion and requires it to fail.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data
from app.modules.contacts.schemas import CONTACT_TYPES, ContactCreate

# Matches the literal role in every seeded contact dict, in both the generated
# block and the hand-built one.
_TYPE_LITERAL = re.compile(r'"contact_type":\s*"([a-z_]+)"')

# Read from the checkout rather than from demo_projects.__file__, so the file
# under test is the one this commit changes whatever the install layout is.
_SOURCE = Path(__file__).resolve().parents[2] / "app" / "core" / "demo_projects.py"

# Seeded contacts today. A floor rather than an equality because adding demo
# parties is normal; the point is that the pattern keeps finding all of them.
# A scan for source literals narrows silently: hold the role in a variable, move
# a block into a helper, rename the key, and those rows leave the scan while a
# non-empty result still looks healthy. Only a count notices.
# If you deliberately removed a seeded contact, lower this and say so.
_SEEDED_CONTACTS = 55


def _generated_contacts(demo_id: str) -> list[dict]:
    """Contact rows the generator would seed for one demo template."""
    template = DEMO_TEMPLATES[demo_id]
    data = _generate_module_data(
        template,
        project_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        demo_id=demo_id,
        base=datetime(2026, 1, 15, tzinfo=UTC),
    )
    return data.get("contacts", [])


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_every_generated_contact_is_one_the_api_would_create(demo_id: str) -> None:
    contacts = _generated_contacts(demo_id)
    assert contacts, f"{demo_id} generated no contacts at all"
    for contact in contacts:
        # The whole row, not just the role: if the seeder ever writes a country
        # code or an address that the API refuses, that is the same bug wearing
        # a different field.
        ContactCreate(**contact)


def test_no_hand_built_contact_names_a_role_the_schema_rejects() -> None:
    """Covers the curated block, which only a full seeding run can reach."""
    assert _SOURCE.is_file(), f"cannot find the demo source at {_SOURCE}"
    found = _TYPE_LITERAL.findall(_SOURCE.read_text(encoding="utf-8"))
    assert len(found) >= _SEEDED_CONTACTS, (
        f"the pattern found {len(found)} seeded contacts, expected at least "
        f"{_SEEDED_CONTACTS}; it has drifted from the source and the rows it no "
        f"longer sees are unchecked"
    )
    roles = sorted(set(found))
    unknown = [r for r in roles if r not in CONTACT_TYPES]
    assert not unknown, f"demo seeds roles the API refuses: {unknown}"


@pytest.mark.parametrize("role", ["contractor_", "Authority", "vendor", ""])
def test_the_assertion_above_rejects_a_role_that_is_not_in_the_set(role: str) -> None:
    """Without this the file could pass by asserting nothing."""
    assert role not in CONTACT_TYPES
    with pytest.raises(ValidationError):
        ContactCreate(contact_type=role, company_name="Example Works")
