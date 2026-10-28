"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An AIA payment application prints figures in the contract's own units.

The G702 face and the G703 continuation sheet were both formatted by one
helper, and that helper was handed the currency code, printed the code next to
the figure on the face, and still quantised to a ``Decimal("0.01")`` literal.

Eligibility for this form is gated on the project's country, US, CA or AU, and
not on the contract's currency, which is a free ISO code the contract carries.
So the reachable case is a US project running a contract denominated in
something other than dollars, which is narrower than a tender letter but is not
closed, and the document goes to an owner and an architect who certify the
figure on it.

The continuation sheet is the half that could have been missed. Its columns are
too narrow to repeat the code on every row, so it called the helper with no
currency at all, and a repair that only fixed the code-carrying calls would
have left the sheet quoting cents underneath a face quoting whole units. Both
are asserted here, from one rendered document, so they cannot drift apart.
"""

from __future__ import annotations

import io
from typing import Any

import pypdf
import pytest

from app.core.money import CURRENCIES, minor_units
from app.modules.contracts.aia_pdf import _amount, _money, render_aia_application_pdf

#: One amount with a different non-zero digit at every place the platform can
#: print, so rounding it to 0, 2 or 3 decimals gives three strings that differ
#: as strings. A rounder probe would read the same at every digit count and let
#: a currency-blind renderer pass the whole table.
PROBE = "1234567.891"


# ── the helper ────────────────────────────────────────────────────────────────


def test_the_probe_amount_can_tell_the_digit_counts_apart() -> None:
    """Without this the table below could be green and measuring nothing."""
    rendered = {places: _amount(PROBE, code) for places, code in ((0, "HUF"), (2, "USD"), (3, "KWD"))}
    assert len(set(rendered.values())) == 3, f"the probe cannot distinguish digit counts: {rendered}"


def test_the_registry_still_carries_currencies_of_every_kind() -> None:
    """And a registry that had lost its 0 and 3 entries would do the same."""
    counts = {minor_units(code) for code in CURRENCIES}
    assert {0, 2, 3} <= counts, f"registry no longer spans the digit counts under test: {sorted(counts)}"


@pytest.mark.parametrize(
    ("currency", "expected"),
    [
        # No subunit at all. Two digits here are not a finer forint, they are a
        # pair of digits no payment can carry.
        ("HUF", "1,234,568"),
        ("IDR", "1,234,568"),
        ("JPY", "1,234,568"),
        # Two, which is what the old literal assumed, so these rows are the
        # control and have to come out byte-identical to the old renderer. USD
        # and CAD and AUD are the currencies this form was written for.
        ("USD", "1,234,567.89"),
        ("CAD", "1,234,567.89"),
        ("AUD", "1,234,567.89"),
        # Three. The Gulf and Tunisian dinars are subdivided into thousandths
        # and the third digit is a real fils a real certificate carries.
        ("BHD", "1,234,567.891"),
        ("KWD", "1,234,567.891"),
        ("TND", "1,234,567.891"),
    ],
)
def test_an_amount_is_written_with_the_digits_its_currency_has(currency: str, expected: str) -> None:
    assert _amount(PROBE, currency) == expected


def test_the_face_writes_the_same_figure_with_its_code_in_front() -> None:
    """The two helpers are one decision, so the face cannot drift from the sheet."""
    for code in ("HUF", "USD", "KWD"):
        assert _money(PROBE, code) == f"{code} {_amount(PROBE, code)}"


def test_a_currency_with_no_subunit_gets_no_separator_either() -> None:
    """A trailing "1,234," reads as a truncated number rather than a whole one."""
    written = _amount(PROBE, "HUF")
    assert "." not in written, f"a forint was written with a decimal separator: {written!r}"
    assert written == "1,234,568"


def test_the_renderer_takes_its_digit_count_from_the_one_registry() -> None:
    """Every code in the registry, so a currency added tomorrow is covered."""
    disagreements = {}
    for code in CURRENCIES:
        _, _, frac = _amount(PROBE, code).partition(".")
        if len(frac) != minor_units(code):
            disagreements[code] = (_amount(PROBE, code), minor_units(code))
    assert not disagreements, f"the renderer disagrees with the registry: {disagreements}"


@pytest.mark.parametrize("code", ["", "ZZZ", "zzz"])
def test_a_code_the_registry_does_not_carry_keeps_the_two_decimal_default(code: str) -> None:
    """Not a guess made here: it is the registry's own documented default.

    A contract carries a blank currency until somebody sets one, and the
    renderer must not invent a code. It asks the registry and takes whatever
    the registry says about a code it does not know.
    """
    assert _amount(PROBE, code) == "1,234,567.89"


def test_a_missing_or_unparseable_figure_still_reads_as_zero() -> None:
    """Unchanged, and asserted so the currency argument cannot have moved it."""
    assert _amount(None, "USD") == "0.00"
    assert _amount("not a number", "USD") == "0.00"
    assert _amount(None, "HUF") == "0"


# ── the document ──────────────────────────────────────────────────────────────

#: Chosen so the two spellings differ in the integer part as well: half a forint
#: rounds up. An amount ending in .00 would print "250,000" either way and the
#: assertion would be satisfied by the code being replaced.
AMOUNT = "250000.50"
IN_FORINT = "250,001"
IN_CENTS = "250,000.50"


def _application(currency: str) -> dict[str, Any]:
    """A payment application carrying the same figure on the face and the sheet."""
    return {
        "application_number": "APP-014",
        "claim_date": "2026-04-15",
        "period_end": "2026-04-30",
        "currency": currency,
        "certification": {
            "architect_certified_by": "Ortega Architects",
            "architect_certified_at": "2026-05-01",
            "owner_certified_by": "Harbour Estates",
            "owner_certified_at": "2026-05-02",
            "certified_amount": AMOUNT,
        },
        "summary": {
            "original_contract_sum": AMOUNT,
            "contract_sum_to_date": AMOUNT,
            "total_completed_stored": AMOUNT,
            "current_payment_due": AMOUNT,
            "balance_to_finish": "0.00",
            "retainage": "0.00",
        },
        "lines": [
            {
                "item_number": "01",
                "description": "Substructure",
                "scheduled_value": AMOUNT,
                "previous_value": "0.00",
                "this_period_value": AMOUNT,
                "materials_stored": "0.00",
                "total_completed_stored": AMOUNT,
                "percent_complete": "100",
                "balance_to_finish": "0.00",
                "retainage": "0.00",
            }
        ],
    }


def _drawn_runs(data: bytes) -> list[str]:
    """Every non-empty text run the page actually draws."""
    runs: list[str] = []
    for page in pypdf.PdfReader(io.BytesIO(data)).pages:
        page.extract_text(visitor_text=lambda text, cm, tm, font, size: runs.append(text))
    return [run.strip() for run in runs if run.strip()]


def test_a_forint_application_is_certified_in_whole_forint() -> None:
    """The face carries the code, so its figure is asserted with the code."""
    runs = _drawn_runs(render_aia_application_pdf(_application("HUF")))

    assert f"HUF {IN_FORINT}" in runs, f"the face does not certify whole forint: {runs[:24]}"
    assert not [r for r in runs if IN_CENTS in r], f"the application still carries cents: {runs}"


def test_the_continuation_sheet_agrees_with_the_face_it_supports() -> None:
    """The sheet prints the figure bare, and it has to be the same figure.

    This is the half a partial repair would have missed: the sheet's calls
    carried no currency code at all, because its columns are too narrow to
    repeat one, so fixing only the code-carrying calls on the face would have
    left an owner certifying whole forint above a schedule of values quoting
    fillér. One document, both parts, asserted together.
    """
    runs = _drawn_runs(render_aia_application_pdf(_application("HUF")))

    bare = [r for r in runs if r == IN_FORINT]
    assert bare, f"the continuation sheet does not carry the bare figure: {runs}"
    assert f"HUF {IN_FORINT}" in runs, f"the face lost its figure: {runs[:24]}"


def test_a_dollar_application_is_unchanged() -> None:
    """The control. This form's own three countries all keep two decimals."""
    runs = _drawn_runs(render_aia_application_pdf(_application("USD")))

    assert f"USD {IN_CENTS}" in runs, f"the dollar face lost its cents: {runs[:24]}"
    assert IN_CENTS in runs, f"the dollar sheet lost its cents: {runs}"
