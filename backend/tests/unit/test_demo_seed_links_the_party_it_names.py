# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A seeded record must link to the firm it names, on every demo project.

The purchase orders used to fail this in two different ways, and only one of
them was visible. Sixteen orders linked to nothing and printed an empty vendor
cell, which a reader notices. Thirty-nine more named one company in the note
and pointed at another, which no reader can notice and no other test asks
about: the note was written in the generator from the template's tender firms,
the link was resolved in the writer from the seeded contacts, and those two
lists differ in order and in length on every hand-written pack. The trade
subcontracts had the same split between title and counterparty.

The fix makes one choice serve both, so this reads the objects the writer
builds and asserts they agree. It does not re-implement the choice: a test that
recomputes the vendor the same way the writer does would agree with itself
whatever either of them said.

There is a second reason to run the writer rather than inspect it. Every module
block in ``_seed_module_data`` is wrapped in ``try / except Exception`` so that
a module the deployment does not carry cannot break the rest of the seed. A
NameError in the block would land in the same handler, the block would silently
write nothing, and no test that does not install a project would go red. So the
presence of each block's key in the returned summary is asserted too.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core import demo_projects


class _Result:
    """Empty query result: this seed runs against a database with no rows."""

    def all(self) -> list:
        return []

    def scalars(self) -> _Result:
        return self

    def scalar_one_or_none(self) -> None:
        return None

    def scalar(self) -> None:
        return None

    def first(self) -> None:
        return None

    def __iter__(self):
        return iter(())


class _RecordingSession:
    """Collects what the writer would persist, without a database."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    def add_all(self, objs) -> None:
        self.added.extend(objs)

    async def flush(self) -> None:
        return None

    async def execute(self, *_args, **_kwargs) -> _Result:
        return _Result()

    async def commit(self) -> None:
        return None


def _seed(demo_id: str) -> tuple[dict, list]:
    session = _RecordingSession()
    template = demo_projects.DEMO_TEMPLATES[demo_id]
    results = asyncio.run(demo_projects._seed_module_data(session, uuid.uuid4(), uuid.uuid4(), demo_id, template))
    return results, session.added


def _by_class(added: list, name: str) -> list:
    return [obj for obj in added if type(obj).__name__ == name]


def _companies(added: list) -> dict[str, str]:
    return {str(c.id): str(c.company_name or "").strip() for c in _by_class(added, "Contact")}


@pytest.mark.parametrize("demo_id", sorted(demo_projects.DEMO_TEMPLATES))
def test_every_purchase_order_links_to_the_vendor_its_note_names(demo_id: str) -> None:
    results, added = _seed(demo_id)
    assert "procurement" in results, "the procurement block raised and was swallowed by its except"

    companies = _companies(added)
    for po in _by_class(added, "PurchaseOrder"):
        assert po.vendor_contact_id, f"{po.po_number} has no vendor, the register prints an empty cell"
        named = companies.get(str(po.vendor_contact_id))
        assert named is not None, f"{po.po_number} links to something that is not a seeded contact"
        if named:
            assert named in str(po.notes or ""), (
                f"{po.po_number} says {po.notes!r} and links to {named!r}: "
                "the note and the link disagree, which no reader can see"
            )


@pytest.mark.parametrize("demo_id", sorted(demo_projects.DEMO_TEMPLATES))
def test_every_contract_links_to_a_seeded_counterparty(demo_id: str) -> None:
    results, added = _seed(demo_id)
    assert "contracts" in results, "the contracts block raised and was swallowed by its except"

    companies = _companies(added)
    for contract in _by_class(added, "Contract"):
        assert contract.counterparty_id, f"contract {contract.code} has no counterparty"
        assert str(contract.counterparty_id) in companies, (
            f"contract {contract.code} links to something that is not a seeded contact"
        )

    for party in _by_class(added, "ContractParty"):
        assert str(party.display_name or "").strip(), (
            f"a {party.party_role} party on {demo_id} would be listed with no name at all"
        )
        assert party.party_id is not None, f"the {party.party_role} party on {demo_id} names a firm it cannot open"
