# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A bill seeded for a project that names no country must not be a German bill.

``BOQService.apply_default_markups`` used to demand a region from its caller,
and the endpoint's default was the neutral international stack. From this
release the region is derived from the owning project's country when the
caller names none, so a Hungarian project gets Hungarian site overheads,
Hungarian profit and 27 percent afa without anybody picking a dropdown.

That derivation is only safe because ``Project.country_code`` became nullable
in revision ``v3319``. Before it the column was ``NOT NULL DEFAULT 'DE'`` while
the API accepted the field as optional, so "nobody chose a country" and
"somebody chose Germany" were the same stored row. Deriving a markup region
from that column in that state would have quoted every unstated market with
German overheads, German profit and German VAT, and nothing on the screen
would have said a country had been assumed. The wrong answer would have looked
exactly like a right one, which is why it needs a test rather than a comment.

So this file gates three things that are only correct together:

* the column can hold "unknown" at all,
* "unknown" resolves to the neutral stack and specifically not to DACH,
* and the service actually asks, rather than owning a correct helper it never
  calls.

Every check is on a pure function or on source, so the file needs no database.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from app.modules.boq.markup_templates import (
    DEFAULT_MARKUP_TEMPLATES,
    REGION_BY_COUNTRY,
    region_key_for_country,
)
from app.modules.projects.models import Project

#: The markets the country packs are being built out for. They are named
#: individually because a population floor alone would stay green while any one
#: of them silently dropped out of the table.
PRIORITY_MARKETS = ("HU", "CN", "GB", "US", "DE", "ES", "IT", "RU", "BR")

#: A well-formed alpha-2 that is not assigned to any country. It stands for
#: every market the table states no convention for.
UNASSIGNED = "ZZ"


def test_the_country_column_can_hold_unknown() -> None:
    """Nullable, and with no server default putting a country back.

    Both halves matter and only one of them is obvious. Dropping NOT NULL while
    leaving ``server_default='DE'`` would keep a bare INSERT writing Germany,
    making the nullability cosmetic: the ORM would report a nullable column,
    every test here would pass, and rows created without a country would still
    arrive as German. That is the same defect in a quieter form.
    """
    column = Project.__table__.c.country_code
    assert column.nullable is True, (
        "Project.country_code is NOT NULL again. Every project that names no "
        "country is being stored as a German one, and apply_default_markups "
        "will price it with the DACH stack."
    )
    assert column.server_default is None, (
        "Project.country_code has a server default again "
        f"({column.server_default!r}). The column is nullable in name only: a "
        "bare INSERT still writes a country nobody chose."
    )


def test_an_unstated_country_resolves_to_the_neutral_stack() -> None:
    """NULL, empty and blank all mean unknown, and unknown is not Germany."""
    for unstated in (None, "", "   "):
        resolved = region_key_for_country(unstated)
        assert resolved == "DEFAULT", (
            f"country {unstated!r} resolved to {resolved!r}. A project that "
            "names no country must be quoted with the neutral international "
            "method."
        )
        assert resolved != "DACH", (
            f"country {unstated!r} resolved to the German stack. This is the "
            "exact failure v3319 exists to make impossible."
        )


def test_an_unassigned_country_is_not_given_a_neighbour() -> None:
    """A market the table does not cover gets the neutral stack, not a guess.

    The markup table's own header says a country's absence from it is an
    answer rather than an oversight: we ship the neutral international method
    for that market and say so. Resolving an unknown country to the nearest
    covered one would replace an honest neutral stack with a national stack
    that is confidently wrong.
    """
    assert UNASSIGNED not in REGION_BY_COUNTRY, (
        f"{UNASSIGNED} is now a mapped country, so it can no longer stand for "
        "an uncovered market here. Pick another unassigned alpha-2."
    )
    assert region_key_for_country(UNASSIGNED) == "DEFAULT"


@pytest.mark.parametrize("country", PRIORITY_MARKETS)
def test_a_priority_market_resolves_to_a_real_stack(country: str) -> None:
    """Each named market maps, and maps to a region that can be seeded."""
    region = region_key_for_country(country)
    assert region != "DEFAULT", (
        f"{country} fell out of REGION_BY_COUNTRY and is being quoted with the neutral international method again."
    )
    assert region in DEFAULT_MARKUP_TEMPLATES, (
        f"{country} maps to region {region!r}, which has no template. Seeding a bill for this country raises KeyError."
    )


def test_case_and_whitespace_do_not_change_the_answer() -> None:
    """The column is not validated on the way in, so the reader normalises."""
    assert region_key_for_country("hu") == region_key_for_country("HU")
    assert region_key_for_country(" gb ") == region_key_for_country("GB")


def test_every_mapped_country_has_a_template() -> None:
    """No country may point at a region that does not exist.

    ``region_lines_for_country`` and this resolver share the same table, and a
    dangling region key here is a 500 on the seeding path rather than a wrong
    number, so it is worth the whole-table sweep.
    """
    dangling = {
        country: region for country, region in REGION_BY_COUNTRY.items() if region not in DEFAULT_MARKUP_TEMPLATES
    }
    assert not dangling, f"countries pointing at regions with no template: {dangling}"


def test_the_table_still_covers_the_markets_it_claims_to() -> None:
    """A population floor, printed with its denominator.

    The floor is not a target. It exists so that a refactor that quietly
    shrinks the table cannot leave the checks above passing on a handful of
    survivors.
    """
    covered = len(REGION_BY_COUNTRY)
    regions = len(DEFAULT_MARKUP_TEMPLATES)
    print(f"REGION_BY_COUNTRY covers {covered} countries across {regions} regions")
    assert covered >= 27, f"only {covered} countries are mapped to a national stack"
    assert regions >= 20, f"only {regions} regions are defined"


def _apply_default_markups_source() -> str:
    """The service method's source, read from the live function object."""
    from app.modules.boq.service import BOQService

    return inspect.getsource(BOQService.apply_default_markups)


def test_the_service_asks_the_project_when_no_region_is_named() -> None:
    """The helper being right is worthless if the seeding path never calls it.

    A test of the resolver alone stays green when the service keeps demanding a
    region, or keeps its own copy of the mapping that drifts from this one. So
    this reads the method: its ``region`` parameter must accept None, and the
    body must reach the shared resolver.
    """
    source = _apply_default_markups_source()
    tree = ast.parse(textwrap.dedent(source))
    func = tree.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)

    region_arg = next((a for a in func.args.args if a.arg == "region"), None)
    assert region_arg is not None, "apply_default_markups no longer takes a region"
    assert region_arg.annotation is not None
    annotation = ast.unparse(region_arg.annotation)
    assert "None" in annotation, (
        f"region is annotated {annotation!r}. It has to accept None, which is "
        "how a caller says 'derive it from the project'."
    )

    called = {ast.unparse(node.func) for node in ast.walk(func) if isinstance(node, ast.Call)}
    assert "region_key_for_country" in called, (
        "apply_default_markups does not call region_key_for_country. Either it "
        "no longer derives the region, or it derives it from a second copy of "
        "the country table that nothing keeps in step with this one."
    )


def test_the_migration_that_makes_this_safe_is_present() -> None:
    """The nullability has to survive a fresh database, not just this model.

    ``create_all`` builds a new install from the model, so the model alone is
    enough there and the checks above would pass. An existing install only
    changes when a revision changes it, and without one every deployed database
    keeps NOT NULL DEFAULT 'DE' while the code above happily assumes otherwise.
    """
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    revision = versions / "v3319_project_country_code_nullable.py"
    assert revision.is_file(), (
        "the revision making country_code nullable is gone. Existing databases "
        "still store an unchosen country as Germany."
    )
    body = revision.read_text(encoding="utf-8")
    assert "oe_projects_project" in body
    assert "nullable=True" in body
