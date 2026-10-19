# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How a holiday answer was arrived at, not only what it was.

``_get_holidays`` used to collapse four situations into one ``frozenset``:
covered and complete, covered but outside a curated window, not covered at all,
and a computation that raised. The last was swallowed into an empty set by a
bare ``except Exception``, and since ``is_working_day`` turns the set into a
``bool``, a broken holiday computation made every weekday a working day with a
log line as the only trace. A log is not something a caller can branch on.

Three empty sets, three meanings. A jurisdiction with genuinely no holidays is
an answer. A jurisdiction nothing covers is a weaker answer, the international
default. A jurisdiction whose holidays could not be computed is not an answer at
all. The old code produced identical bytes for all three.

The two axes are asserted separately on purpose. China in a year past its
curated table is the case that matters: the country is fully covered and the
year is not, so a single flag keyed on the country would report it green. That
is why :func:`app.core.provenance.weakest` exists and why it is tested here.

Coverage answers whether rows are present, and does not absorb accuracy. A
holiday whose date is computed but whose length is a stand-in is a third axis,
not a hole in the first two, so it is a fallback on ``holiday_extent`` while
jurisdiction and year both stay declared. Bending ``partial`` to carry it would
have made one slot answer two questions resolved two different ways. See
``_EXTENT_STANDINS`` for why the axis and its tokens are named for the
mechanism: absence has to mean "no stand-in we know of" and never "verified",
because nothing in this module has been verified.

Mutation matrix, measured across this file, ``test_calendar.py`` and
``test_calendar_nigeria_bulgaria.py``, which is the whole of what reads the
holiday tables:

    baseline                                       152 passed
    restore the swallow (except -> empty set)        9 failed, 143 passed
    raise but still cache an empty answer            5 failed, 147 passed
    treat a curated-window miss as complete          4 failed, 148 passed
    call every shared table a synonym (AT as DE)     1 failed, 151 passed
    forget the synonym table (GB falls back to UK)   1 failed, 151 passed
    call an uncovered country declared               4 failed, 148 passed
    drop one Gulf country from the span registry     3 failed, 149 passed
    call every uncomputed extent a computed one      8 failed, 144 passed
    restore the hijri swallow (out of range -> [])   5 failed, 147 passed
    stop enforcing the japanese formula window       3 failed, 149 passed
    drop Nigeria from the hijri-dependent set        2 failed, 150 passed
    restored                                       152 passed

The source was restored to a byte-identical sha256 after every mutation. The
kill counts differ from each other on purpose: a uniform number across eleven
mutations would mean everything fires on any change, and would look just as
green.

Two of these come in opposed pairs on purpose. A shared holiday function can be
wrongly called a synonym or wrongly called a fallback, and an empty set can be
wrongly called an answer or wrongly called nothing; a guard that is only hard in
one direction leaves the other as the way in.

The second mutation is the one a partial fix would produce: the first call
raises and every later one returns a plausible empty set from the cache. It is
caught only because the failure paths are asserted twice rather than once, at
both the resolver and the ``is_working_day`` level.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest

from app.core import calendar as cal
from app.core.calendar import (
    AXIS_EFFECTIVE_YEAR,
    AXIS_JURISDICTION,
    HolidayCalculationError,
    holiday_provenance,
    resolve_holidays,
)
from app.core.provenance import Provenance, Source, weakest

# Test-only codes. Real ones would tie these assertions to shipped data and make
# them fail for reasons that have nothing to do with provenance.
_EMPTY_CC = "ZZ"  # a jurisdiction with genuinely no holidays
_BROKEN_CC = "QQ"  # a jurisdiction whose computation raises


@pytest.fixture(autouse=True)
def _isolate_calendar_state() -> Iterator[None]:
    """Keep injected functions and memoised answers out of other tests.

    The cache is module-level, so a single poisoned entry would make unrelated
    tests order-dependent - which is exactly the failure the no-memoising rule
    below exists to prevent.
    """
    saved = dict(cal._HOLIDAY_FUNCS)
    cal._holiday_cache.clear()
    yield
    cal._HOLIDAY_FUNCS.clear()
    cal._HOLIDAY_FUNCS.update(saved)
    cal._holiday_cache.clear()


def _install_empty() -> None:
    cal._HOLIDAY_FUNCS[_EMPTY_CC] = lambda _y: set()


def _install_broken() -> None:
    def boom(_year: int) -> set[date]:
        raise ValueError("ephemeris unavailable")

    cal._HOLIDAY_FUNCS[_BROKEN_CC] = boom


# ── The three empty sets the old code could not tell apart ────────────────────


@pytest.mark.unit
def test_holiday_free_and_uncovered_and_failed_are_three_different_things() -> None:
    """All three produced an empty frozenset before, which is why none was safe.

    This asserts they are now distinguishable at all, which is the whole point
    of the change. The finer assertions live in the tests below; this one is the
    statement of the defect.
    """
    _install_empty()
    _install_broken()

    free = resolve_holidays(_EMPTY_CC, 2026)
    uncovered = resolve_holidays("XX", 2026)

    assert free["dates"] == uncovered["dates"] == frozenset()
    # Same dates, different provenance. That is the entire fix.
    assert free[AXIS_JURISDICTION].source is not uncovered[AXIS_JURISDICTION].source

    with pytest.raises(HolidayCalculationError):
        resolve_holidays(_BROKEN_CC, 2026)


@pytest.mark.unit
def test_a_holiday_free_jurisdiction_is_declared_rather_than_a_fallback() -> None:
    """Zero holidays is an answer found on the country's own terms."""
    _install_empty()
    prov = resolve_holidays(_EMPTY_CC, 2026)[AXIS_JURISDICTION]
    assert prov.source is Source.DECLARED
    assert prov.answered is True
    assert prov.usable is True


@pytest.mark.unit
def test_an_uncovered_country_falls_back_to_the_international_default() -> None:
    """Not covered is a weaker answer, not the absence of one.

    It stays usable: an uncovered jurisdiction runs on a working week with no
    public holidays and says so, rather than refusing to schedule anything.
    """
    prov = resolve_holidays("XX", 2026)[AXIS_JURISDICTION]
    assert prov.source is Source.FALLBACK
    assert prov.requested == "XX"
    assert prov.used == cal.NO_PUBLIC_HOLIDAYS
    assert prov.answered is False
    assert prov.usable is True


@pytest.mark.unit
def test_a_failed_computation_raises_and_carries_unavailable_provenance() -> None:
    """The defect surfaces as a defect, and brings the vocabulary with it.

    A caller that catches this should not have to rebuild the provenance by
    hand, because rebuilding it by hand is how it ends up recorded as a
    fallback - which would say an answer was found.
    """
    _install_broken()
    with pytest.raises(HolidayCalculationError) as excinfo:
        resolve_holidays(_BROKEN_CC, 2026)

    exc = excinfo.value
    assert exc.country_code == _BROKEN_CC
    assert exc.year == 2026
    assert isinstance(exc.__cause__, ValueError)
    assert exc.provenance.source is Source.UNAVAILABLE
    assert exc.provenance.usable is False
    assert exc.provenance.used == "", "nothing answered, so nothing was used"


@pytest.mark.unit
def test_a_failure_is_never_memoised() -> None:
    """A cached failure would raise once and then answer emptily forever after.

    Asserting the failure twice is what separates this from a partial fix. One
    call cannot tell a raise-and-do-not-cache from a raise-and-cache.
    """
    _install_broken()
    for _ in range(2):
        with pytest.raises(HolidayCalculationError):
            resolve_holidays(_BROKEN_CC, 2026)
    assert (_BROKEN_CC, 2026) not in cal._holiday_cache


@pytest.mark.unit
def test_is_working_day_propagates_a_failed_computation() -> None:
    """The bool-returning caller must not invent a working year out of a failure.

    Called twice on purpose. A fix that raises but still memoises the empty set
    would satisfy the first call and hand the second a year in which every
    weekday is a working day, which is the original defect wearing a raise.
    """
    _install_broken()
    _install_empty()
    for _ in range(2):
        with pytest.raises(HolidayCalculationError):
            cal.is_working_day(date(2026, 6, 3), _BROKEN_CC)
    # Control: a country with no holidays still answers normally, so the raise
    # above is about the failure and not about having an empty set.
    assert cal.is_working_day(date(2026, 6, 3), _EMPTY_CC) is True


# ── Curated windows: the second axis ──────────────────────────────────────────


@pytest.mark.unit
def test_the_curated_tables_are_populated() -> None:
    """Population floor: the window tests below pass vacuously over empty tables."""
    assert cal._CURATED_TABLES
    for code, (table, omitted) in cal._CURATED_TABLES.items():
        assert table, f"{code} curated table is empty"
        assert omitted, f"{code} names nothing it omits"


@pytest.mark.unit
def test_the_curated_set_names_every_year_keyed_table_in_the_module() -> None:
    """Ratchet: a new lunisolar table added and not registered would lie.

    A table left out of ``_CURATED_TABLES`` reports every year complete,
    including years it does not cover, which is the defect this file exists to
    prevent. Counting the module's year-keyed tables is a property of the module
    rather than a restatement of the list being checked.
    """
    year_keyed = {
        name
        for name, value in vars(cal).items()
        if name.isupper() and isinstance(value, dict) and value and all(isinstance(k, int) for k in value)
    }
    registered = {id(table) for table, _ in cal._CURATED_TABLES.values()}
    unregistered = {name for name in year_keyed if id(vars(cal)[name]) not in registered}
    assert not unregistered, f"year-keyed tables not registered in _CURATED_TABLES: {sorted(unregistered)}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("country", "expected_omission"),
    [("CN", "Spring Festival"), ("IN", "Diwali")],
)
def test_a_year_outside_a_curated_table_falls_back_on_the_year_axis_alone(
    country: str,
    expected_omission: str,
) -> None:
    """The country is covered and the year is not. One flag would miss this.

    ``_holidays_cn`` already knew exactly what it was dropping and said so in a
    warning. Only the channel was missing.
    """
    far_future = 2099
    assert far_future not in cal._CURATED_TABLES[country][0], "pick a year the table really does not cover"

    result = resolve_holidays(country, far_future)
    assert result[AXIS_JURISDICTION].source is Source.DECLARED, "the country itself is fully covered"
    assert result[AXIS_EFFECTIVE_YEAR].source is Source.FALLBACK
    assert result[AXIS_EFFECTIVE_YEAR].used == cal.GREGORIAN_ONLY
    assert expected_omission in result["omitted"]
    assert expected_omission in result[AXIS_EFFECTIVE_YEAR].detail
    assert result["dates"], "the fixed Gregorian days are still returned"


@pytest.mark.unit
@pytest.mark.parametrize("country", ["CN", "IN"])
def test_a_year_inside_the_curated_table_is_declared_on_both_axes(country: str) -> None:
    """Control for the partial case: inside the window nothing is omitted."""
    covered_year = max(cal._CURATED_TABLES[country][0])
    result = resolve_holidays(country, covered_year)
    assert result[AXIS_JURISDICTION].source is Source.DECLARED
    assert result[AXIS_EFFECTIVE_YEAR].source is Source.DECLARED
    assert result["omitted"] == ()


@pytest.mark.unit
def test_the_weaker_axis_is_the_verdict() -> None:
    """A fully covered country in an uncovered year is not a covered answer.

    This is the case a single jurisdiction-keyed flag paints green, so it is
    asserted through the helper a caller would actually reach for.
    """
    verdict = holiday_provenance("CN", 2099)
    assert verdict.source is Source.FALLBACK
    assert verdict.axis == AXIS_EFFECTIVE_YEAR

    inside = holiday_provenance("CN", max(cal._CURATED_TABLES["CN"][0]))
    assert inside.source is Source.DECLARED


# ── Which country actually answered ───────────────────────────────────────────


@pytest.mark.unit
def test_at_least_one_shipped_code_is_served_by_another_countrys_function() -> None:
    """Population floor for the alias test: without an alias it proves nothing."""
    by_func: dict[Any, list[str]] = {}
    for code, func in cal._HOLIDAY_FUNCS.items():
        by_func.setdefault(func, []).append(code)
    assert any(len(codes) > 1 for codes in by_func.values())


@pytest.mark.unit
def test_a_country_served_by_another_countrys_table_reports_a_fallback() -> None:
    """Austria is not Germany, and a caller is entitled to know which answered.

    The table's own comment calls Austrian holidays a close mirror of Germany's.
    A close mirror is an approximation, so it is a fallback and says so.
    """
    prov = resolve_holidays("AT", 2026)[AXIS_JURISDICTION]
    assert prov.source is Source.FALLBACK
    assert prov.requested == "AT"
    assert prov.used == "DE"
    assert prov.answered is False


@pytest.mark.unit
@pytest.mark.parametrize("code", ["GB", "UK"])
def test_two_spellings_of_one_state_are_not_a_fallback(code: str) -> None:
    """GB and UK share a function because they are the same country.

    The counterpart to the Austria test, and the reason the two cannot be told
    apart by "do these share a function". Reporting Britain as falling back to
    itself would be a false alarm, and false alarms are how a provenance field
    stops being read.
    """
    prov = resolve_holidays(code, 2026)[AXIS_JURISDICTION]
    assert prov.source is Source.DECLARED
    assert prov.answered is True


@pytest.mark.unit
@pytest.mark.parametrize("code", ["DE", "CA", "US", "CH"])
def test_a_country_answered_by_its_own_table_is_declared(code: str) -> None:
    """Controls, including CH whose function is a lambda naming no country."""
    prov = resolve_holidays(code, 2026)[AXIS_JURISDICTION]
    assert prov.source is Source.DECLARED
    assert prov.requested == prov.used == code


# ── The type is doing work, not just carrying strings ─────────────────────────


@pytest.mark.unit
def test_the_shape_of_this_defect_cannot_be_written_down() -> None:
    """An unavailable that claims something answered is refused by the type.

    This is the shape the old swallow would have had to take to be recorded:
    nothing answered, yet a country named as having answered. Asserting it here
    keeps the guarantee visible from the module that needed it.
    """
    with pytest.raises(ValueError, match="nothing answered"):
        Provenance(axis=AXIS_JURISDICTION, source=Source.UNAVAILABLE, requested="DE", used="DE")


@pytest.mark.unit
def test_weakest_of_the_two_axes_prefers_the_worse_one() -> None:
    """Guards the ordering the verdict depends on."""
    strong = resolve_holidays("DE", 2026)[AXIS_JURISDICTION]
    weak = resolve_holidays("XX", 2026)[AXIS_JURISDICTION]
    assert weakest(strong, weak) is weak
    assert weakest(weak, strong) is weak


# ── Present rows, uncomputed extent ───────────────────────────────────────────


@pytest.mark.unit
def test_the_placeholder_span_registry_is_populated() -> None:
    """Population floor: the tests below pass vacuously over an empty registry."""
    assert cal._PLACEHOLDER_SPANS
    for code, names in cal._PLACEHOLDER_SPANS.items():
        assert names, f"{code} is registered as having a placeholder span but names none"


@pytest.mark.unit
def test_every_country_served_by_the_shared_eid_spans_is_registered() -> None:
    """Ratchet: derived from the source, not from the list being checked.

    ``_gcc_eids`` is where the placeholder lives, so the countries affected are
    the ones whose function calls it. A seventh Gulf country added without a
    registry entry would silently claim a computed span, which is the whole
    thing this field exists to prevent.
    """
    served = {
        code
        for code, func in cal._HOLIDAY_FUNCS.items()
        if getattr(func, "__name__", "").startswith("_holidays_") and "_gcc_eids(" in inspect.getsource(func)
    }
    assert served, "no function calls _gcc_eids; this test is checking nothing"
    unsourced = {code for code, spans in cal._EID_SPANS.items() if not spans.sourced}
    assert served <= set(cal._EID_SPANS), f"served without a span row: {sorted(served - set(cal._EID_SPANS))}"
    assert unsourced == set(cal._PLACEHOLDER_SPANS), (
        f"unsourced spans and registered placeholders differ: {sorted(unsourced ^ set(cal._PLACEHOLDER_SPANS))}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("country", ["AE", "QA", "KW", "BH", "OM"])
def test_a_placeholder_span_is_reported_without_downgrading_coverage(country: str) -> None:
    """The rows are present, so coverage is complete, and that is a true sentence.

    Coverage answers presence and does not absorb accuracy. The country and the
    year both answered on their own terms; what did not happen is the length
    being worked out, and that is the third axis rather than a hole in the
    first two.
    """
    result = resolve_holidays(country, 2026)
    assert result[AXIS_JURISDICTION].source is Source.DECLARED
    assert result[AXIS_EFFECTIVE_YEAR].source is Source.DECLARED
    assert result["omitted"] == (), "nothing is missing; the extent is the issue"
    assert result["placeholder_spans"] == cal._GCC_PLACEHOLDER_SPANS


@pytest.mark.unit
@pytest.mark.parametrize(
    ("country", "token"),
    [
        ("AE", cal.SHARED_GCC_EID_SPAN),
        ("QA", cal.SHARED_GCC_EID_SPAN),
        ("KW", cal.SHARED_GCC_EID_SPAN),
        ("BH", cal.SHARED_GCC_EID_SPAN),
        ("OM", cal.SHARED_GCC_EID_SPAN),
        ("CH", cal.THREE_FIXED_DAYS),
    ],
)
def test_an_uncomputed_extent_is_a_fallback_naming_what_stood_in(country: str, token: str) -> None:
    """A stand-in is an answer, so it is a fallback and it names itself.

    Switzerland is here beside the Gulf because a hardcoded three-date roster is
    as uncomputed as a hardcoded span. Marking one and not the other would make
    the absence of the mark mean less than it should.
    """
    prov = resolve_holidays(country, 2026)[cal.AXIS_HOLIDAY_EXTENT]
    assert prov.source is Source.FALLBACK
    assert prov.requested == country
    assert prov.used == token
    assert prov.usable is True, "the dates are still an answer and can be computed with"
    assert prov.detail, "a stand-in has to be able to explain itself to a human"


@pytest.mark.unit
@pytest.mark.parametrize("country", ["DE", "US", "CN", "IN", "JP", "NG", "BG", "SA", "EG"])
def test_a_country_with_no_known_stand_in_is_declared_on_the_extent_axis(country: str) -> None:
    """Absence means no stand-in we know of, not an extent anybody verified.

    Nobody has checked the German roster. The whole reason the axis is named for
    the mechanism is so that this row can be silent without claiming otherwise.
    """
    assert resolve_holidays(country, 2026)[cal.AXIS_HOLIDAY_EXTENT].source is Source.DECLARED


@pytest.mark.unit
def test_the_verdict_goes_amber_for_a_country_whose_span_was_never_computed() -> None:
    """The live consequence, asserted where a consumer would actually hit it.

    Nothing publishes as jurisdiction specific while a dimension it uses falls
    back, and that rule reads the verdict. Before the third axis Saudi Arabia
    answered fully covered on a span its own source says runs short, so the rule
    read the answer and never saw the caveat.
    """
    verdict = holiday_provenance("QA", 2026)
    assert verdict.source is Source.FALLBACK
    assert verdict.axis == cal.AXIS_HOLIDAY_EXTENT
    assert verdict.answered is False

    # Control: a country with none of the three weaknesses still reads clean.
    assert holiday_provenance("DE", 2026).source is Source.DECLARED


@pytest.mark.unit
def test_every_country_with_a_placeholder_span_also_declares_a_stand_in() -> None:
    """The two registries cannot drift apart without this going red.

    ``placeholder_spans`` is the data and ``holiday_extent`` is the provenance.
    A country in the first and not the second would carry the names of holidays
    nobody computed while reporting the axis clean, which is the worse half of
    the pair to lose.
    """
    assert set(cal._PLACEHOLDER_SPANS) <= set(cal._EXTENT_STANDINS), (
        f"has placeholder spans but no stand-in on the extent axis: "
        f"{sorted(set(cal._PLACEHOLDER_SPANS) - set(cal._EXTENT_STANDINS))}"
    )
    for token in cal._EXTENT_STANDINS.values():
        assert token in cal._EXTENT_DETAIL, f"{token} has no detail text"


@pytest.mark.unit
@pytest.mark.parametrize("country", ["DE", "US", "CA", "CN", "JP"])
def test_a_country_with_no_known_placeholder_reports_none(country: str) -> None:
    """Absence means no placeholder we know of, not a span anybody verified.

    The field is named for the mechanism for exactly this reason. Nothing here
    asserts that Germany's holiday lengths were checked, because they were not,
    and a field called "approximate" would have made every quiet country claim
    they had been.
    """
    assert resolve_holidays(country, 2026)["placeholder_spans"] == ()


@pytest.mark.unit
def test_an_omitted_holiday_and_a_placeholder_span_are_independent() -> None:
    """Two different facts in two slots, which is the point of the second slot.

    China past its curated table has omissions and no placeholder spans. Saudi
    Arabia used to have the reverse; Qatar still does. One field carrying both
    would have had to call these the same thing.
    """
    china = resolve_holidays("CN", 2099)
    qatar = resolve_holidays("QA", 2026)

    assert china["omitted"] and not china["placeholder_spans"]
    assert qatar["placeholder_spans"] and not qatar["omitted"]


# ── Windows that the code states and used to not enforce ──────────────────────


@pytest.mark.unit
def test_the_hijri_dependent_set_is_derived_from_the_source() -> None:
    """Ratchet, and the one that already earned its keep.

    ``_HIJRI_DEPENDENT`` is hand-written, so it is held to the functions that
    actually reach the converter. Nigeria joined that set the day it was added
    and is not one of the countries anybody would list from memory as "the Gulf
    ones", which is exactly the drift this catches. Equality rather than subset:
    a country registered here that does not use the converter would report a
    window fallback it is not subject to.
    """

    def _source(func) -> str:
        # A country whose function applies announced moves to a statutory
        # roster (Egypt) computes the roster in a ``_statutory`` companion.
        companion = getattr(cal, f"{func.__name__}_statutory", None)
        return inspect.getsource(func) + (inspect.getsource(companion) if companion else "")

    reaching = {
        code
        for code, func in cal._HOLIDAY_FUNCS.items()
        if getattr(func, "__name__", "").startswith("_holidays_")
        and any(call in _source(func) for call in ("_gcc_eids(", "_eid_days(", "_hijri_dates_in_gregorian_year("))
    }
    assert reaching, "nothing reaches the Hijri converter; this test is checking nothing"
    assert reaching == set(cal._HIJRI_DEPENDENT), (
        f"registered but not reaching: {sorted(set(cal._HIJRI_DEPENDENT) - reaching)}; "
        f"reaching but not registered: {sorted(reaching - set(cal._HIJRI_DEPENDENT))}. "
        "Add the country to _HIJRI_DEPENDENT, or take it out if it no longer converts. "
        "Do not relax this to a subset check: both directions are defects, one reports "
        "a window limit the country is not subject to and the other hides the limit it is."
    )


@pytest.mark.unit
@pytest.mark.parametrize("country", ["AE", "SA", "NG"])
def test_a_year_past_the_hijri_window_is_unavailable_rather_than_shorter(country: str) -> None:
    """The cardinal failure, one call below where it was fixed this morning.

    Past 2077 every Islamic holiday used to vanish and the year reported itself
    fully covered, so ``is_working_day`` counted Eid al-Fitr as a working day.
    The reason a raise beats an empty result is not that empty is sometimes a
    legitimate answer. It never is: measured across the converter's window a
    fixed Hijri date lands once or twice in every year and never zero, so every
    empty list this ever produced was the defect. See
    ``test_an_in_range_year_always_has_at_least_one_occurrence``.
    """
    with pytest.raises(HolidayCalculationError) as excinfo:
        resolve_holidays(country, 2100)
    assert excinfo.value.provenance.source is Source.UNAVAILABLE
    assert isinstance(excinfo.value.__cause__, cal.HijriRangeError)

    with pytest.raises(HolidayCalculationError):
        cal.is_working_day(date(2100, 6, 3), country)


@pytest.mark.unit
@pytest.mark.parametrize("country", ["AE", "SA", "NG"])
def test_the_year_that_straddles_the_window_says_so(country: str) -> None:
    """2077 is the year that was already wrong and looked healthy.

    The converter's window ends on 16 November 2077, so that year answers on
    1 January and fails on 31 December. The UAE reported twelve holidays for it
    against a healthy thirteen, and twelve sits inside the band that ordinary
    lunar drift produces, so counting could never have found it.
    """
    result = resolve_holidays(country, 2077)
    assert result[AXIS_EFFECTIVE_YEAR].source is Source.FALLBACK
    assert result[AXIS_EFFECTIVE_YEAR].used == cal.HIJRI_WINDOW_EDGE
    assert result[AXIS_JURISDICTION].source is Source.DECLARED, "the country is covered; the year is the problem"
    assert result["dates"], "the reachable part of the year still answered"


@pytest.mark.unit
@pytest.mark.parametrize("year", [2026, 2050, 2070])
def test_a_year_inside_the_hijri_window_is_declared(year: int) -> None:
    """Control for the two above: inside the window nothing falls back."""
    assert resolve_holidays("AE", year)[AXIS_EFFECTIVE_YEAR].source is Source.DECLARED


@pytest.mark.unit
@pytest.mark.parametrize("year", [1979, 2100, 2500])
def test_a_japanese_year_outside_the_fitted_range_falls_back(year: int) -> None:
    """A stated range that nothing enforced is a promise with no keeper.

    ``_equinox_day`` carries "accurate for the years 1980-2099" and the formula
    corrects leap years with ``offset // 4``, which treats 2100 as a leap year
    where Gregorian does not. So the boundary is earned rather than copied, and
    outside it the equinox days are extrapolated. Before 1980 the modern roster
    is applied to a year that did not have it, which is the same lie at the
    other end.
    """
    prov = resolve_holidays("JP", year)[AXIS_EFFECTIVE_YEAR]
    assert prov.source is Source.FALLBACK
    assert prov.used == cal.EXTRAPOLATED_EQUINOX


@pytest.mark.unit
@pytest.mark.parametrize("year", [1980, 2026, 2099])
def test_a_japanese_year_inside_the_fitted_range_is_declared(year: int) -> None:
    """Control, and it pins both edges of the window rather than the middle."""
    assert resolve_holidays("JP", year)[AXIS_EFFECTIVE_YEAR].source is Source.DECLARED


@pytest.mark.unit
def test_the_two_japanese_defects_stay_two_clauses() -> None:
    """One token covers two defects, and the detail must not blend them.

    Extrapolated equinoxes and a modern roster applied to a year that predates
    it are separate faults that happen to share an axis. A detail string that
    runs them together reads as one fault with a long explanation, and the
    reader loses the ability to tell which one their year actually has.

    They are not symmetric either. The extrapolation applies at both ends of
    the window; the roster is only wrong below it. Carrying the roster clause
    on a year above the window would be a true sentence about the wrong year,
    which is the quiet way a detail string stops being evidence.

    This is a test rather than a comment because the failure mode is somebody
    tidying two clauses into one, and prose does not survive that.
    """
    below = resolve_holidays("JP", 1979)[AXIS_EFFECTIVE_YEAR].detail
    above = resolve_holidays("JP", 2100)[AXIS_EFFECTIVE_YEAR].detail

    for detail in (below, above):
        assert "extrapolated" in detail, "both ends run the formula outside the range it was fitted to"

    assert "roster" in below, "1979 predates the modern roster and the detail has to say so"
    assert "roster" not in above, "2100 does not predate the roster; claiming it would be a wrong-year fact"
    assert below.count(";") >= 1, "the two defects must stay separable rather than run together"


@pytest.mark.unit
def test_a_window_limit_does_not_leak_onto_countries_that_have_none() -> None:
    """The negative control that would catch a limit applied too widely.

    Germany and the United States are subject to neither window, so a year that
    breaks Japan and the Gulf must leave them untouched. Without this, checking
    a limit is applied says nothing about whether it is applied only where it
    belongs.
    """
    for country in ("DE", "US", "BG"):
        assert resolve_holidays(country, 2100)[AXIS_EFFECTIVE_YEAR].source is Source.DECLARED


# ── The accessor keeps its shape ──────────────────────────────────────────────


@pytest.mark.unit
def test_get_holidays_still_returns_a_frozenset_of_dates() -> None:
    """Guards a trap: ``assert _get_holidays(cc, y)`` is a live assertion elsewhere.

    ``tests/unit/core/test_calendar.py`` asserts truthiness of this return to
    prove Bahrain and Oman have holidays at all. Had the accessor started
    returning the provenance mapping, that assertion would have passed on a
    non-empty dict while the dates inside it were empty.
    """
    holidays = cal._get_holidays("DE", 2026)
    assert isinstance(holidays, frozenset)
    assert all(isinstance(d, date) for d in holidays)
    assert holidays == resolve_holidays("DE", 2026)["dates"]


@pytest.mark.unit
def test_a_lower_case_code_resolves_the_same_as_upper() -> None:
    """The code is normalised once, in the resolver, rather than at each caller."""
    assert resolve_holidays("de", 2026)["dates"] == resolve_holidays("DE", 2026)["dates"]
    assert resolve_holidays("de", 2026)[AXIS_JURISDICTION].requested == "DE"
