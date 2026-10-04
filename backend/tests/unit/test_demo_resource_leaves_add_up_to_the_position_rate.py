# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every seeded resource buildup must add up to the position's own unit rate.

The BOQ grid derives its resource columns by summing ``quantity * unit_rate``
over a position's leaves: the labour / material / plant columns on the German
preset, the equivalent cost-element columns on the Chinese one. When the leaves
do not add up to the rate beside them the columns are wrong in a way nobody can
see, because each column on its own still looks plausible.

Both readings are asserted, because the two consumers do not read the same
field. The grid computes from ``quantity * unit_rate`` and never looks at a
leaf's ``total`` (``columnDefs.ts``), while ``_resource_breakdown_rollup``
prefers ``total``. Pinning only one would leave two nearly-equal truths in the
data and let them drift apart again.

The population is every position of every registered demo template rather than
a sample, and that is the point of the test. The defect it pins was a rounding
effect that only bit where the unit rate was small: a labour share of a rate
under one unit of currency divided by an hourly crew rate rounded to zero
hours, so the leaf carried no money and the grid showed a position as pure
material with no crew time on it. A sample would have missed it, and the money
identity would have gone on failing quietly on hundreds of rows.

Scope. This covers ``_make_resources``, the buildup behind
``_enrich_position_metadata`` that every demo template goes through. The
separate ``_resources_for_position`` helper has its own remainder logic and a
single call site and is not exercised here.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app.core import demo_projects

SOURCE = Path(demo_projects.__file__)

#: How many offenders to name before the message stops being readable.
_SHOWN = 6


@lru_cache(maxsize=1)
def _positions() -> tuple[tuple[str, str, Decimal, tuple[dict, ...]], ...]:
    """Every priced position of every registered demo template, with its leaves."""
    rows: list[tuple[str, str, Decimal, tuple[dict, ...]]] = []
    for key, template in demo_projects.DEMO_TEMPLATES.items():
        for _ordinal, _title, _section_class, items in template.sections:
            for item in items:
                description, unit, unit_rate, classification = item[1], item[2], item[4], item[5]
                rate = Decimal(str(unit_rate))
                if rate <= 0:
                    continue
                # Called the way the installer calls it, so a pack's
                # hand-written build-up is held to the same identities.
                meta = demo_projects._enrich_position_metadata(
                    description=description,
                    unit=unit,
                    unit_rate=unit_rate,
                    classification=classification,
                    locale=template.locale,
                    explicit_resources=template.position_resources.get(item[0]),
                )
                leaves = meta.get("resources") or []
                if leaves:
                    rows.append((str(key), str(description), rate, tuple(leaves)))
    return tuple(rows)


def _grid_money(leaf: dict) -> Decimal:
    """What the grid adds up for this leaf."""
    return Decimal(str(leaf.get("quantity") or 0)) * Decimal(str(leaf.get("unit_rate") or 0))


def _stored_money(leaf: dict) -> Decimal:
    """What the rollup adds up for this leaf."""
    return Decimal(str(leaf.get("total") or 0))


def _absorbing_leaves(leaves: tuple[dict, ...]) -> list[dict]:
    """Leaves priced in money rather than hours, so able to carry a remainder.

    An hourly leaf holds a quantized quantity against a fixed crew rate, so the
    money it can express is a multiple of that rate. Only a leaf carrying its
    money directly in ``unit_rate`` can take an arbitrary remainder.
    """
    return [leaf for leaf in leaves if leaf.get("unit") != "hr"]


def test_the_census_reaches_the_population_it_claims_to_read() -> None:
    """A census that walks nothing passes for the wrong reason.

    Stated first because every assertion below is over this set, and an empty
    or truncated walk would certify the whole population green without looking
    at any of it.
    """
    rows = _positions()
    assert len(demo_projects.DEMO_TEMPLATES) >= 30, (
        f"expected the demo templates to be registered, found {len(demo_projects.DEMO_TEMPLATES)}"
    )
    assert len(rows) >= 4000, f"only {len(rows)} priced positions found across the demo templates"
    assert len({key for key, _desc, _rate, _leaves in rows}) >= 30, "positions came from too few templates"


def test_every_buildup_sums_to_its_position_unit_rate() -> None:
    """Both readings, exactly, on every position."""
    offenders: list[str] = []
    for key, description, rate, leaves in _positions():
        grid = sum((_grid_money(leaf) for leaf in leaves), Decimal("0"))
        stored = sum((_stored_money(leaf) for leaf in leaves), Decimal("0"))
        if grid != rate or stored != rate:
            offenders.append(f"{key}: {description[:40]!r} rate {rate} grid {grid} stored {stored}")
    assert not offenders, (
        f"{len(offenders)} of {len(_positions())} buildups do not sum to their unit rate: "
        + "; ".join(offenders[:_SHOWN])
    )


def test_every_buildup_has_a_leaf_that_can_absorb_the_remainder() -> None:
    """The structural reason the sum above is reachable at all.

    Without this the sum test still fails, but it fails as a number mismatch
    and says nothing about why. A branch added with only hourly leaves has no
    way to land on the rate, and this names that directly.
    """
    offenders = [
        f"{key}: {description[:40]!r}"
        for key, description, _rate, leaves in _positions()
        if not _absorbing_leaves(leaves)
    ]
    assert not offenders, (
        f"{len(offenders)} buildups have no leaf priced in money, so nothing can carry the remainder: "
        + "; ".join(offenders[:_SHOWN])
    )


def test_the_absorbing_leaf_never_goes_negative() -> None:
    """The remainder must not be so large it drives its own leaf through zero.

    Nobody asked for this one. It is the failure mode that would turn a
    correct-looking total into a negative material line, and it is cheap to
    rule out.
    """
    offenders = [
        f"{key}: {description[:40]!r} -> {_grid_money(_absorbing_leaves(leaves)[0])}"
        for key, description, _rate, leaves in _positions()
        if _absorbing_leaves(leaves) and _grid_money(_absorbing_leaves(leaves)[0]) <= 0
    ]
    assert not offenders, f"{len(offenders)} absorbing leaves are not positive: " + "; ".join(offenders[:_SHOWN])


def test_no_hourly_leaf_is_rounded_out_of_existence() -> None:
    """An hourly leaf must carry money, not a quantity that rounded to zero.

    This is the defect the buildup had: on a cheap position the crew time came
    to a few thousandths of an hour, was stored to two decimal places, and
    became 0.00 hours. The money identity can hold with the labour leaf priced
    at nothing, so this cannot be folded into the sum assertion.
    """
    offenders = [
        f"{key}: {description[:40]!r} {leaf.get('name')!r} qty {leaf.get('quantity')}"
        for key, description, _rate, leaves in _positions()
        for leaf in leaves
        if leaf.get("unit") == "hr" and _grid_money(leaf) <= 0
    ]
    assert not offenders, (
        f"{len(offenders)} hourly leaves carry no money because their quantity rounded away: "
        + "; ".join(offenders[:_SHOWN])
    )


def test_every_branch_declares_a_composition_that_adds_up() -> None:
    """The source must not declare one split while the code produces another.

    Read off the source rather than the built objects, because after the
    absorbing leaf has taken the remainder every buildup adds up by
    construction and a short declaration would no longer show. Two branches
    declared shares summing to 0.95 and the absorbing leaf silently made up the
    difference, so the shipped composition was five points heavier on material
    than the source said.
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    offenders: list[str] = []
    call_sites = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_make_resources"):
            continue
        if len(node.args) < 4 or not isinstance(node.args[3], ast.List):
            continue
        call_sites += 1
        ref = node.args[2].value if isinstance(node.args[2], ast.Constant) else "?"
        declared = Decimal("0")
        for element in node.args[3].elts:
            if isinstance(element, ast.Tuple) and len(element.elts) >= 3 and isinstance(element.elts[2], ast.Constant):
                declared += Decimal(str(element.elts[2].value))
        if declared != Decimal("1"):
            offenders.append(f"{ref} declares {declared}")
    assert call_sites >= 70, f"only {call_sites} buildup call sites parsed; the scan missed most of them"
    assert not offenders, "branches whose shares do not sum to 1.00: " + "; ".join(offenders[:_SHOWN])
