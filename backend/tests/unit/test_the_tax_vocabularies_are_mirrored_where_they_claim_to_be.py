# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Two vocabularies in this module are copied by hand and say so in a comment.

``schemas.py`` carries a ``Literal`` that mirrors ``TAX_COMBINATIONS`` in
models.py and another that mirrors ``ResolutionStatus`` in tax_rules.py. Both
comments say "Mirrors". Nothing made either of them true.

Why it matters, in the direction that hurts. ``TaxResolutionStatus`` is what
the response model validates against, so a status added to the resolver and
not to the schema does not degrade - it turns the countries the new status was
written for into failed requests. That is worse than the answer it replaced,
and no test over ``resolve()`` can see it, because ``resolve()`` is right.
This was live while ``default_rate_not_in_force`` was being added and the only
thing that caught it was somebody reading the second file.

The sibling case is the one this file is built around rather than the pair.
A gate that checks the two mirrors we have today is blind to the third one
somebody writes next month, which is the same defect wearing the next
costume: a scope written as a name cannot see a sibling holding the same
thing. So the mirrors are discovered from the source comment that claims the
mirroring, and a claim with no entry in the table below is itself a failure.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

from app.modules.i18n_foundation import models, schemas, tax_rules

#: Each mirror in ``schemas.py`` and the vocabulary it copies. The value is
#: read from its own module rather than restated here: a table that carried
#: its own copy of the members would be a third mirror needing a fourth check.
MIRRORS: dict[str, tuple[str, tuple[str, ...]]] = {
    "TaxCombination": ("models.TAX_COMBINATIONS", models.TAX_COMBINATIONS),
    "TaxResolutionStatus": ("tax_rules.ResolutionStatus", get_args(tax_rules.ResolutionStatus)),
}

#: ``#: Mirrors ``NAME`` in module.py`` followed, after any further comment
#: lines, by the ``Literal`` it introduces. Matching the comment rather than
#: the assignment is deliberate: the claim is what has to be checked, and the
#: claim is written in the comment.
_MIRROR_CLAIM = re.compile(
    r"^#: Mirrors ``(?P<source>\w+)`` in (?P<module>\w+)\.py\b.*\n(?:#:.*\n)*(?P<name>\w+) = Literal\[",
    re.MULTILINE,
)


def _claims_in_schemas() -> dict[str, str]:
    """Every mirror ``schemas.py`` claims, read out of its own source."""
    text = Path(schemas.__file__).read_text(encoding="utf-8")
    return {m.group("name"): f"{m.group('module')}.{m.group('source')}" for m in _MIRROR_CLAIM.finditer(text)}


def test_every_literal_that_claims_to_mirror_something_is_checked_here() -> None:
    """A third mirror must join this table rather than quietly not be checked.

    This is the assertion that stops the file ageing into a gate for two
    specific names. It reads the claims out of the source, so a Literal
    written next month with the same comment style is compared from the day
    it is written, and one written without the comment fails here as a claim
    nobody can check rather than passing as a thing nobody looked at.
    """
    claimed = _claims_in_schemas()

    assert claimed, (
        "no mirror claims found in schemas.py at all. Either the comment style changed "
        "or the module was reorganised; this file is now checking nothing, which is the "
        "vacuous pass it exists to prevent."
    )
    assert set(claimed) == set(MIRRORS), (
        f"schemas.py claims to mirror {sorted(claimed)} and this table checks "
        f"{sorted(MIRRORS)}. A Literal that says it mirrors something and is not in the "
        "table is unchecked: add it to MIRRORS with the vocabulary it copies."
    )
    for name, source in claimed.items():
        assert MIRRORS[name][0] == source, (
            f"{name} says it mirrors {source} and this table compares it against "
            f"{MIRRORS[name][0]}. One of the two is out of date."
        )


@pytest.mark.parametrize("name", sorted(MIRRORS))
def test_a_mirrored_vocabulary_holds_the_same_members_as_its_source(name: str) -> None:
    """The members must match exactly, in both directions.

    Both directions, not just one. A member in the source and not in the
    mirror is the failure that turns a request into a 500. A member in the
    mirror and not in the source is a value the API will accept and nothing
    can ever produce, which reads to a client as a state that exists.
    """
    source_name, source_members = MIRRORS[name]
    mirror_members = get_args(getattr(schemas, name))

    missing = sorted(set(source_members) - set(mirror_members))
    extra = sorted(set(mirror_members) - set(source_members))

    assert not missing, (
        f"{source_name} has {missing} and schemas.{name} does not. The response model "
        f"validates against schemas.{name}, so this is not a degraded answer - it is a "
        f"failed request on exactly the cases the new member was written for. Add "
        f"{missing} to schemas.{name}."
    )
    assert not extra, (
        f"schemas.{name} has {extra} and {source_name} does not. Nothing can produce "
        f"those, so they are a state the API advertises and never returns."
    )


def test_every_resolved_status_is_a_status() -> None:
    """``RESOLVED_STATUSES`` may only name members of ``ResolutionStatus``.

    A typo here fails silently and in the direction that looks fine: the
    misspelt entry matches nothing, so a status that carries a rate reports
    ``resolved`` false and the rate is withheld. No number is ever wrong, so
    nothing red appears; the platform simply stops answering for one status.
    """
    statuses = set(get_args(tax_rules.ResolutionStatus))
    strays = sorted(set(tax_rules.RESOLVED_STATUSES) - statuses)

    assert not strays, (
        f"RESOLVED_STATUSES names {strays}, which are not members of ResolutionStatus. "
        "Each one matches nothing, so any resolution carrying it would report resolved "
        "false and withhold a rate it actually has."
    )
    assert len(set(tax_rules.RESOLVED_STATUSES)) == len(tax_rules.RESOLVED_STATUSES), (
        "RESOLVED_STATUSES lists a status twice, which means one of them was meant to be a different status."
    )


def test_every_subnational_combination_is_a_combination() -> None:
    """``SUBNATIONAL_COMBINATIONS`` may only name members of ``TAX_COMBINATIONS``.

    The subnational tuple decides which rows require a ``subdivision_code``
    and which forbid it, and the table's check constraint is written from the
    same members. A name in here that is not a real combination describes a
    rule for rows that cannot exist, and the rule it was meant to describe is
    not applied to anything.
    """
    strays = sorted(set(models.SUBNATIONAL_COMBINATIONS) - set(models.TAX_COMBINATIONS))

    assert not strays, (
        f"SUBNATIONAL_COMBINATIONS names {strays}, which are not in TAX_COMBINATIONS. "
        "Those describe a subdivision rule for a combination no row can hold."
    )
