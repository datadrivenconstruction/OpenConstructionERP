# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A contacts import must not quietly refile a party as something else.

The row loop of the file import rewrote any contact_type it did not recognise
to supplier and said nothing about it, so a file naming main contractors
imported a register of suppliers and returned success. The two checks either
side of it, the email and the country code, both reject the row and report it.

The resolution now sits in its own function so it can be reached without a
route, a database or an upload, which is the whole reason the branch had no
test before.

The empty cell is a separate case and still defaults. A file exported from an
address book often has no such column at all, and supplier is a fair reading of
saying nothing; the bug was reading a wrong answer as if it were no answer.
"""

from __future__ import annotations

import pytest

from app.modules.contacts.router import _resolve_contact_type
from app.modules.contacts.schemas import CONTACT_TYPES


@pytest.mark.parametrize("role", CONTACT_TYPES)
def test_every_role_the_api_accepts_survives_the_import(role: str) -> None:
    assert _resolve_contact_type(role) == (role, None)


@pytest.mark.parametrize("cell", ["", "   ", None])
def test_an_empty_cell_still_defaults_to_supplier(cell: object) -> None:
    """Saying nothing is not the same as saying something we cannot store."""
    assert _resolve_contact_type(cell) == ("supplier", None)


@pytest.mark.parametrize("cell", [" Client ", "CLIENT", "SubContractor"])
def test_spacing_and_case_are_read_as_the_role_they_name(cell: str) -> None:
    role, error = _resolve_contact_type(cell)
    assert error is None
    assert role == cell.strip().lower()


@pytest.mark.parametrize("cell", ["vendor", "main contractor", "kunde", "supplier2"])
def test_a_role_we_do_not_have_is_reported_rather_than_rewritten(cell: str) -> None:
    role, error = _resolve_contact_type(cell)
    assert role is None, f"{cell!r} was filed as {role!r} instead of being reported"
    assert error is not None
    # The message has to name the value the file gave and the roles on offer,
    # or the person fixing the file has nothing to act on.
    assert cell.lower() in error
    for allowed in CONTACT_TYPES:
        assert allowed in error


def test_the_old_behaviour_would_fail_these_checks() -> None:
    """States plainly what changed, so the file is not read as always-true.

    The previous line was ``if contact_type not in _ALLOWED: contact_type =
    "supplier"``, which returns a role and no error for every input. Under it
    the unknown-role test above fails on its first assertion.
    """
    old = lambda raw: (  # noqa: E731 - the shape being contrasted, not a helper
        str(raw or "").strip().lower() if str(raw or "").strip().lower() in CONTACT_TYPES else "supplier",
        None,
    )
    assert old("vendor") == ("supplier", None)
    assert _resolve_contact_type("vendor")[0] is None
