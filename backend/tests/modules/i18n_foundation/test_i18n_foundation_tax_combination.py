"""Combined tax rates: does the shipped data say how two rates add up?

These tests read ``seed_data/tax_configurations.json`` directly rather than a
database, because the seed file is what a new installation gets and it is the
thing that has to be right. They exist to stop one specific bug.

Canada levies a federal rate and, in most provinces, a provincial one, and the
two combine in two opposite ways. A harmonised rate REPLACES the federal rate,
so Ontario is 13 % and not 5 + 13. A separate provincial rate STACKS on it, so
British Columbia is 5 + 7. Before the ``combination`` column, nothing in a row
said which, and the obvious implementation - federal plus my province - gives
the right answer in British Columbia and an 18 % invoice in Ontario. A bug that
is correct in the province you happened to test in is a bug that ships.

The rule that decides replace-versus-stack is therefore read out of the data,
never written here. The resolver branches on ``combination`` and on nothing
else; it does not know that HST is harmonised, and if every row were mislabelled
it would happily return the wrong numbers. That is deliberate: these tests are a
check on the data, so the data has to be able to fail them.
``test_marking_ontario_as_stacking_breaks_the_published_figure`` proves it can.

Two things changed with v3307, and both close what this file used to record as
weaknesses.

The province is now a column. It used to live in ``tax_code`` as a naming
convention that differed between countries and that nothing enforced, so this
file parsed it. ``_jurisdiction_from_tax_code`` still parses it, but only to
assert that the convention and the new ``subdivision_code`` agree on all eleven
rows - which makes the old weakness into a free check on the backfill.

And the arithmetic is no longer written here. It used to be a private
``_combined_rate`` in this file, which meant the figures below were checked
against a second implementation that no user ever ran. It now calls the
resolver the API serves, so this file checks the shipped *data* and
``test_tax_subdivision_resolver.py`` checks the same function against rows in a
real database. Two instruments, one subject: the data being right proves
nothing about a resolver that ignores the province, and vice versa.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.i18n_foundation.models import SUBNATIONAL_COMBINATIONS, TAX_COMBINATIONS
from app.modules.i18n_foundation.subdivisions import CANADA_SUBDIVISIONS, normalize_subdivision
from app.modules.i18n_foundation.tax_rules import resolve, row_from_mapping, validate_tax_row

_SEED = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "i18n_foundation"
    / "seed_data"
    / "tax_configurations.json"
)

# Published combined rates a quantity surveyor would recognise, by jurisdiction.
# Federal 5 % is Excise Tax Act s.165(1); the harmonised provinces come from the
# statutory instruments that prescribe their rates (SOR/2016-119 for New
# Brunswick and Newfoundland, SOR/2016-212 for Prince Edward Island, SOR/2025-77
# for the Nova Scotia cut to 14 % on 2025-04-01); the separate provincial rates
# come from the three provincial finance ministries and, for Quebec, from
# Ministere des Finances du Quebec information bulletin 2012-4.
#
# Alberta and the three territories appear because a jurisdiction with no
# provincial tax is the case a "federal plus provincial" implementation gets
# right by accident. They prove nothing on their own, and they are here to keep
# the federal row honest - and because "correctly 5 %" and "we do not know" have
# to be different answers, which is what the resolver's status says.
_CANADA_PUBLISHED = {
    "CA-ON": Decimal("13"),
    "CA-NS": Decimal("14"),
    "CA-NB": Decimal("15"),
    "CA-NL": Decimal("15"),
    "CA-PE": Decimal("15"),
    "CA-QC": Decimal("14.975"),
    "CA-BC": Decimal("12"),
    "CA-SK": Decimal("11"),
    "CA-MB": Decimal("12"),
    "CA-AB": Decimal("5"),
    "CA-YT": Decimal("5"),
    "CA-NT": Decimal("5"),
    "CA-NU": Decimal("5"),
}


def _rows() -> list[dict]:
    return json.loads(_SEED.read_text(encoding="utf-8"))


def _jurisdiction_from_tax_code(row: dict) -> str | None:
    """The subdivision a row's ``tax_code`` implies, by the old convention.

    Kept, but demoted. This used to be how the province was found, and the
    docstring called it the weak point: the table had no jurisdiction column,
    so the only place a province had ever been recorded was inside
    ``tax_code``, and the convention differed by country. Canada writes the tax
    first (``HST_ON``, ``PST_BC``), the United States writes the state first
    (``CA_SALES``), and nothing enforced either.

    ``subdivision_code`` is now the answer. This function survives as the
    independent second reading that the backfill is checked against - see
    ``test_the_subdivision_column_agrees_with_the_old_naming_convention``.
    """
    code = row["tax_code"] or ""
    if row["combination"] not in SUBNATIONAL_COMBINATIONS:
        return None
    if row["country_code"] == "CA":
        return f"CA-{code.rsplit('_', 1)[-1]}"
    if row["country_code"] == "US":
        return f"US-{code.split('_', 1)[0]}"
    if row["country_code"] == "PK":
        # Pakistan names the provincial revenue authority, not the province.
        return {"PRA_ST": "PK-PB", "SRB_ST": "PK-SD", "KPRA_ST": "PK-KP"}.get(code)
    raise AssertionError(f"no jurisdiction convention for country {row['country_code']!r}")


def _combined_rate(rows: list[dict], country: str, jurisdiction: str, on_date: str) -> Decimal:
    """Total rate payable in one jurisdiction, as the API would report it.

    Delegates to the shipped resolver rather than reimplementing it. A private
    copy here would let the two drift, and the figures below would then be
    checked against an implementation nobody runs.
    """
    resolution = resolve([row_from_mapping(r) for r in rows], country, jurisdiction, on_date)
    assert resolution.combined_rate_pct is not None, (
        f"{country}/{jurisdiction} on {on_date}: {resolution.status} - {resolution.reason}"
    )
    return Decimal(resolution.combined_rate_pct)


# ── The field exists and every row states it ────────────────────────────────


def test_every_row_states_how_it_combines() -> None:
    """No row is allowed to stay silent; silence is the defect being fixed."""
    rows = _rows()

    missing = [r for r in rows if not r.get("combination")]

    assert missing == [], f"{len(missing)} rows carry no combination"


def test_no_row_invents_a_combination_the_model_does_not_know() -> None:
    rows = _rows()

    unknown = sorted({r["combination"] for r in rows} - set(TAX_COMBINATIONS))

    assert unknown == []


def test_a_country_has_at_most_one_federal_rate() -> None:
    """Two federal rows would make the stacking arithmetic ambiguous."""
    counts: dict[str, int] = {}
    for row in _rows():
        if row["combination"] == "federal" and row["effective_to"] is None:
            counts[row["country_code"]] = counts.get(row["country_code"], 0) + 1

    assert [cc for cc, n in counts.items() if n > 1] == []


def test_a_stacking_or_replacing_row_has_a_federal_row_to_refer_to() -> None:
    """``stacks_on_federal`` in a country with no federal row means nothing."""
    rows = _rows()
    federal_countries = {r["country_code"] for r in rows if r["combination"] == "federal"}

    orphans = sorted(
        {
            f"{r['country_code']}/{r['tax_code']}"
            for r in rows
            if r["combination"] in SUBNATIONAL_COMBINATIONS and r["country_code"] not in federal_countries
        }
    )

    assert orphans == []


def test_no_row_that_names_a_subdivision_calls_itself_country_wide() -> None:
    """Row eighty-one, which the seed file can still get wrong on its own.

    The write rules refuse this shape through the API and through the seed
    loader, and the table's check constraint refuses it in the database. What
    none of those watch is somebody hand-editing the JSON: the loader would
    reject it at boot, which is loud, but a test that names the offending row
    at review time is better than a stack trace on a customer's first start.

    The rule is the naming convention itself: in Canada and the United States,
    an underscore in ``tax_code`` is how a subdivision has always been written.
    Elsewhere it means a rate tier (``VAT_RED``), so the check is scoped to the
    two countries where the structure exists.
    """
    offenders = sorted(
        f"{r['country_code']}/{r['tax_code']}"
        for r in _rows()
        if r["country_code"] in ("CA", "US")
        and "_" in (r["tax_code"] or "")
        and r["combination"] not in SUBNATIONAL_COMBINATIONS
    )

    assert offenders == [], (
        f"{offenders} name a subdivision but claim to be country-wide. A row like that "
        f"is invisible to the combined-rate arithmetic rather than wrong in it."
    )


# ── The subdivision axis, as shipped ────────────────────────────────────────


def test_every_subnational_row_names_the_subdivision_it_belongs_to() -> None:
    """The invisible row, checked against the file that ships it.

    A provincial rate with no ``subdivision_code`` matches no per-province
    lookup, so the province answers with the federal rate and nothing reports
    that a rate was missed.
    """
    silent = sorted(
        f"{r['country_code']}/{r['tax_code']}"
        for r in _rows()
        if r["combination"] in SUBNATIONAL_COMBINATIONS and not r.get("subdivision_code")
    )

    assert silent == []


def test_no_country_wide_row_carries_a_subdivision() -> None:
    """The other direction of the same invariant the table constrains."""
    mislabelled = sorted(
        f"{r['country_code']}/{r['tax_code']}"
        for r in _rows()
        if r["combination"] not in SUBNATIONAL_COMBINATIONS and r.get("subdivision_code")
    )

    assert mislabelled == []


def test_the_subdivision_column_agrees_with_the_old_naming_convention() -> None:
    """Two independent readings of where a row belongs, and they must match.

    ``subdivision_code`` was backfilled from ``tax_code``, so checking one
    against the other is checking the backfill by the only other evidence that
    ever existed. A row where they disagree is a row the migration got wrong,
    and it would resolve into the wrong province rather than failing.
    """
    disagreements = [
        (row["country_code"], row["tax_code"], row.get("subdivision_code"), _jurisdiction_from_tax_code(row))
        for row in _rows()
        if row["combination"] in SUBNATIONAL_COMBINATIONS
        and normalize_subdivision(row.get("subdivision_code")) != _jurisdiction_from_tax_code(row)
    ]

    assert disagreements == []


def test_every_shipped_row_passes_the_write_rules() -> None:
    """The seed loader validates each row at boot; this fails at review instead.

    Same function, called on the same file. The difference is when it speaks.
    """
    for row in _rows():
        validate_tax_row(
            row["country_code"],
            row["combination"],
            normalize_subdivision(row.get("subdivision_code")),
        )


def test_every_canadian_subdivision_has_a_published_figure() -> None:
    """The registry and the published table below cannot drift apart.

    Thirteen jurisdictions, thirteen expected totals. A territory quietly
    dropped from the parametrize list would otherwise never be missed.
    """
    assert set(_CANADA_PUBLISHED) == set(CANADA_SUBDIVISIONS)


# ── The arithmetic, against published figures ───────────────────────────────


@pytest.mark.parametrize(("province", "published"), sorted(_CANADA_PUBLISHED.items()))
def test_the_combined_canadian_rate_matches_the_published_figure(province: str, published: Decimal) -> None:
    """Ontario 13, British Columbia 12, Quebec 14.975, Alberta 5."""
    combined = _combined_rate(_rows(), "CA", province, "2026-08-23")

    assert combined == published, f"{province}: computed {combined}, published {published}"


def test_nova_scotia_reads_the_rate_that_was_correct_before_the_cut() -> None:
    """The closed period is load-bearing: 15 % until 2025-03-31, 14 % after."""
    rows = _rows()

    assert _combined_rate(rows, "CA", "CA-NS", "2025-03-31") == Decimal("15")
    assert _combined_rate(rows, "CA", "CA-NS", "2025-04-01") == Decimal("14")


def test_the_california_combined_rate_adds_to_a_zero_federal_layer() -> None:
    """The United States has a federal row of 0 %, which is what a state adds to."""
    combined = _combined_rate(_rows(), "US", "US-CA", "2026-08-23")

    assert combined == Decimal("7.25")


# ── The control: prove the data can fail these tests ────────────────────────


def test_marking_ontario_as_stacking_breaks_the_published_figure() -> None:
    """Mutate the field and the arithmetic must convict.

    If this passes with Ontario marked as stacking, then ``combination`` is
    decorative and the tests above are only re-reading numbers somebody typed.
    18 % is the exact wrong answer the field exists to prevent, so it is
    asserted rather than merely being asserted as "not 13".
    """
    rows = _rows()
    ontario = [r for r in rows if r["tax_code"] == "HST_ON"]
    assert len(ontario) == 1
    ontario[0]["combination"] = "stacks_on_federal"

    combined = _combined_rate(rows, "CA", "CA-ON", "2026-08-23")

    assert combined == Decimal("18")
    assert combined != _CANADA_PUBLISHED["CA-ON"]


def test_dropping_the_federal_row_breaks_every_stacking_province() -> None:
    """The other half of the control: replacing provinces must not move."""
    rows = [r for r in _rows() if r["combination"] != "federal"]

    assert _combined_rate(rows, "CA", "CA-BC", "2026-08-23") == Decimal("7")
    assert _combined_rate(rows, "CA", "CA-ON", "2026-08-23") == Decimal("13")


def test_marking_british_columbia_as_compounding_moves_the_total() -> None:
    """The fifth combination is load-bearing, not a synonym for the fourth.

    British Columbia charges its 7 % PST on the pre-GST amount, so the total is
    12 %. Charged on the GST-included amount instead, the same 7 % would do the
    work of 7.35 % and the total would be 12.35 %. If this mutation leaves the
    figure at 12, ``compounds_on_federal`` is dead code and the model still
    cannot express the ordering of two taxes.

    No Canadian jurisdiction compounds today - Quebec was the last and stopped
    on 2013-01-01 - so this is the only place the shipped data can exercise it,
    by mutation.
    """
    rows = _rows()
    bc = [r for r in rows if r["tax_code"] == "PST_BC"]
    assert len(bc) == 1
    bc[0]["combination"] = "compounds_on_federal"

    combined = _combined_rate(rows, "CA", "CA-BC", "2026-08-23")

    assert combined == Decimal("12.35")
    assert combined != _CANADA_PUBLISHED["CA-BC"]
