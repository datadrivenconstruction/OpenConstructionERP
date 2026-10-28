# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resolving a seed row's party must fail to nothing, never to the wrong party.

Five registers link to a contact through ``_seeded_party_id``. The PG tests
prove the links reach the database; this pins the rule that decides what happens
when they cannot, which is the part a reader is most likely to 'tidy up'.

The registers seed more rows than there are firms with a contact. Falling back
to the first contact of the role would give every one of those rows a link, and
each would be wrong: a purchase order whose note names one company while its
vendor link points at another looks correct on every screen that shows it, and
nothing downstream can tell. An empty cell is visibly empty. So an index past
the end resolves to nothing on purpose, and this file is where that is written
down as a decision rather than an oversight.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core import demo_projects
from app.core.demo_projects import (
    DEMO_TEMPLATES,
    _contacts_for_project,
    _generate_module_data,
    _seeded_party_id,
    _uuid_or_none,
)

_SEEDED = {
    "contractor": ["c-0"],
    "subcontractor": ["s-0", "s-1", "s-2"],
    "consultant": ["k-0", "k-1"],
}


@pytest.mark.parametrize(
    ("role", "index", "expected"),
    [
        ("contractor", 0, "c-0"),
        ("subcontractor", 0, "s-0"),
        ("subcontractor", 1, "s-1"),
        ("subcontractor", 2, "s-2"),
        ("consultant", 1, "k-1"),
    ],
)
def test_a_position_inside_the_role_picks_that_contact(role: str, index: int, expected: str) -> None:
    """The nth subcontract is the nth firm's, not the first firm's repeated."""
    assert _seeded_party_id(_SEEDED, role, index) == expected


@pytest.mark.parametrize("index", [3, 4, 99])
def test_a_position_past_the_end_resolves_to_nothing(index: int) -> None:
    """The decision this file exists for. A wrong link outranks a missing one in damage."""
    assert _seeded_party_id(_SEEDED, "subcontractor", index) is None


@pytest.mark.parametrize("index", [-1, -3])
def test_a_negative_position_resolves_to_nothing(index: int) -> None:
    """Python would read -1 as the last contact, which is a different firm again."""
    assert _seeded_party_id(_SEEDED, "subcontractor", index) is None


@pytest.mark.parametrize("role", ["authority", "supplier", "", None])
def test_a_role_the_demo_did_not_seed_resolves_to_nothing(role: str | None) -> None:
    """A register may name a party this demo has no contact for; that is not an error."""
    assert _seeded_party_id(_SEEDED, role) is None


def test_no_contacts_at_all_resolves_to_nothing() -> None:
    """The contacts block is fail-soft, so every caller must survive it seeding none."""
    assert _seeded_party_id({}, "contractor") is None


def test_the_id_is_returned_as_stored_for_the_text_columns() -> None:
    """Some columns take the id as text and some as a UUID; only one of them converts."""
    ids = {"contractor": [str(uuid.uuid4())]}
    resolved = _seeded_party_id(ids, "contractor")
    assert resolved == ids["contractor"][0]
    assert isinstance(resolved, str)
    assert _uuid_or_none(resolved) == uuid.UUID(ids["contractor"][0])
    assert _uuid_or_none(None) is None


# ── The other side of the same rule ──────────────────────────────────────
#
# Everything above pins what happens when a role cannot be resolved. That is the
# right behaviour for the lookup and a defect in the seed: a row pointing at a
# role the project never seeded is silently linkless, and the screen shows an
# empty cell that looks like data rather than a mistake. Measured on the five
# hand-written projects that named no main contractor while the punchlist
# assigned to one by default and both contract signature blocks named one.

_ROLES_THE_SEED_POINTS_AT = ("client", "contractor", "subcontractor", "consultant")


def _hand_written_contacts() -> dict[str, list[dict]]:
    """``_CONTACTS`` read out of the source, because it is a local variable.

    It lives inside ``_seed_module_data`` and cannot be imported. Only constant
    keys and values are taken, which is all this needs: the roles.
    """
    source = Path(demo_projects.__file__).read_text(encoding="utf-8")
    out: dict[str, list[dict]] = {}
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_CONTACTS"):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=False):
            if isinstance(key, ast.Constant) and isinstance(value, ast.List):
                out[key.value] = [
                    {
                        k.value: v.value
                        for k, v in zip(entry.keys, entry.values, strict=False)
                        if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
                    }
                    for entry in value.elts
                    if isinstance(entry, ast.Dict)
                ]
    return out


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_every_project_seeds_a_contact_for_every_role_its_rows_name(demo_id: str) -> None:
    generated = _generate_module_data(
        DEMO_TEMPLATES[demo_id],
        project_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        demo_id=demo_id,
        base=datetime(2026, 1, 15, tzinfo=UTC),
    ).get("contacts", [])
    contacts = _contacts_for_project(_hand_written_contacts().get(demo_id), generated)
    seeded = {c.get("contact_type") for c in contacts}
    missing = [role for role in _ROLES_THE_SEED_POINTS_AT if role not in seeded]
    assert not missing, f"{demo_id} seeds rows pointing at {missing}, but has no contact holding that role"


def test_the_repair_only_fires_when_a_main_contractor_is_absent() -> None:
    """It must fill a hole, not append a second contractor to a list that has one."""
    generated = [{"contact_type": "contractor", "company_name": "Generated"}]
    already = [{"contact_type": "client"}, {"contact_type": "contractor", "company_name": "Hand written"}]
    assert [c.get("company_name") for c in _contacts_for_project(already, generated)] == [None, "Hand written"]

    filled = _contacts_for_project([{"contact_type": "client"}], generated)
    assert [c["contact_type"] for c in filled] == ["client", "contractor"]
    assert filled[1]["company_name"] == "Generated"

    # No hand-written list at all is the ordinary path, and it must pass through
    # unchanged rather than gaining a duplicate of a row it already holds.
    assert _contacts_for_project(None, generated) == generated
    assert _contacts_for_project([], generated) == generated
