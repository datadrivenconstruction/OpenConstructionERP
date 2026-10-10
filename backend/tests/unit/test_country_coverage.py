# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the country coverage manifest.

These test the instrument, not the coverage. A country having no payment regime
is a finding for the register and not a failure here; the manifest reporting it
as covered, or reporting a broken probe as a gap, is a failure here.

The one property everything else rests on: **UNRESOLVED must never present as
MISSING.** An instrument that turns "I could not measure this" into "there is
nothing there" hands back a finished-looking answer to an unasked question, and
every count downstream of it is wrong in the comfortable direction.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

from app.core import country_coverage as cc
from app.core import country_registries as registries
from app.modules.payment_clock import data as payment_clock_data

# Countries with enough spread to exercise the verdicts: a large market with
# broad coverage, one known to be partly covered, one Gulf state, two Asian.
_SWEEP = ("US", "CA", "DE", "GB", "AE", "CN", "IN", "BR", "SA", "NL", "JP", "MX")

# The register's working cohort plus the rest of the large markets. Wider than
# _SWEEP on purpose: a probe that answers for one country and goes quiet for its
# neighbour is the failure this file exists to catch, and a narrow list hides it.
_COHORT = (
    "US", "CA", "DE", "BG", "RU", "CN", "IN", "BR", "NG", "GB", "FR", "ES",
    "IT", "NL", "PL", "JP", "KR", "AU", "MX", "SA", "AE", "ZA", "TR",
)  # fmt: skip

_SCHEDULE_SERVICE = "app.modules.schedule.service"


def test_the_manifest_has_probes_and_they_all_have_distinct_names():
    """Floor plus uniqueness: a suite over an empty registry passes vacuously."""
    names = cc.dimensions()
    assert len(names) >= 8, f"only {len(names)} dimensions; the manifest has lost probes"
    assert len(set(names)) == len(names), "two probes share a dimension name, so one report overwrites the other"


def test_every_probe_returns_one_of_the_declared_verdicts():
    known = {*cc.ANSWERED, cc.UNRESOLVED}
    report = cc.country_coverage("CA")
    assert len(report.dimensions) == len(cc.dimensions())
    for d in report.dimensions:
        assert d.verdict in known, f"{d.dimension} invented the verdict {d.verdict!r}"
        assert d.detail, f"{d.dimension} returned {d.verdict} with no explanation"


# --------------------------------------------------------------------------- #
# The load-bearing property
# --------------------------------------------------------------------------- #


def test_a_probe_that_raises_is_unresolved_and_never_missing():
    def broken(_country: str) -> cc.DimensionReport:
        raise RuntimeError("registry moved")

    got = cc._run("demo.broken", broken, "CA")
    assert got.verdict == cc.UNRESOLVED
    assert got.verdict != cc.MISSING
    assert "registry moved" in got.detail, "the reason was swallowed, so nobody can fix the probe"


def test_a_raising_probe_stays_unresolved_through_the_public_entry_point(monkeypatch):
    """The wrapper is only worth anything if the registry actually goes through it."""

    def broken(_country: str) -> cc.DimensionReport:
        raise LookupError("symbol gone")

    monkeypatch.setattr(cc, "_PROBES", [*cc._PROBES, ("demo.broken", broken)])
    report = cc.country_coverage("CA")
    assert report.counts[cc.UNRESOLVED] >= 1
    assert [d.dimension for d in report.by_verdict(cc.UNRESOLVED)].count("demo.broken") == 1
    assert "demo.broken" not in [d.dimension for d in report.by_verdict(cc.MISSING)]


def test_an_empty_population_is_unresolved_rather_than_everyone_missing():
    """A registry that resolved and came back empty has lost its shape, not its rows."""
    got = cc._keyed("demo.empty", "nowhere", set(), "CA")
    assert got.verdict == cc.UNRESOLVED
    assert got.verdict != cc.MISSING


def test_a_populated_registry_without_this_country_is_missing_not_unresolved():
    """The other side of the same control, so the check above is not passing on everything."""
    got = cc._keyed("demo.populated", "nowhere", {"US", "DE"}, "CA")
    assert got.verdict == cc.MISSING
    assert got.population == ("DE", "US")


def test_unresolved_is_kept_out_of_the_answered_arithmetic():
    assert cc.UNRESOLVED not in cc.ANSWERED
    unresolved = cc._keyed("demo.empty", "nowhere", set(), "CA")
    assert not unresolved.answered
    assert cc._keyed("demo.populated", "nowhere", {"CA"}, "CA").answered


# --------------------------------------------------------------------------- #
# Each verdict has to be reachable, or it is decoration
# --------------------------------------------------------------------------- #


def _sweep() -> list[cc.DimensionReport]:
    out: list[cc.DimensionReport] = []
    for code in _SWEEP:
        out.extend(cc.country_coverage(code).dimensions)
    return out


def test_the_schedule_resolver_answers_through_the_import_it_has_here():
    """The probe takes the import path when the import is available, as it is here.

    This test used to say that the probe declines to guess on a laptop with no
    cluster, and it was the whole trouble: that was true, the probe reported
    UNRESOLVED for every country off a database, and this test could never see
    it because pytest boots one. It now asserts the narrower thing it is
    actually able to observe - that where the import works, the import is what
    answered. The case it could not reach is staged explicitly further down.
    """
    got = _one("CA", "calendar.schedule_regions")
    assert got.verdict != cc.UNRESOLVED, f"the resolver was not importable even under the test harness: {got.detail}"
    assert got.method == "import", f"a cluster is up, so the import path should have answered, not {got.method!r}"


@pytest.mark.parametrize("verdict", [cc.COVERED, cc.FALLBACK, cc.MISSING, cc.NOT_KEYED, cc.ABSENT])
def test_each_verdict_actually_occurs_somewhere_in_the_sweep(verdict):
    """A vocabulary nothing ever returns describes an imaginary product."""
    results = _sweep()
    assert len(results) >= len(_SWEEP) * 8, "the sweep collapsed; the floor below would pass on anything"
    assert any(d.verdict == verdict for d in results), f"no dimension in {len(_SWEEP)} countries returned {verdict}"


def test_covered_and_missing_land_on_different_countries_in_the_same_dimension():
    """Proof the manifest discriminates rather than reporting one verdict per dimension."""
    dimension = "payment.prompt_payment_regime"
    verdicts = {c: _one(c, dimension).verdict for c in _SWEEP}
    resolved = {c: v for c, v in verdicts.items() if v != cc.UNRESOLVED}
    assert len(resolved) >= 6, f"too few resolved to compare: {verdicts}"
    assert len(set(resolved.values())) > 1, f"{dimension} gave every country the same answer: {resolved}"


def test_a_missing_payment_regime_carries_a_reason_when_one_is_on_record(monkeypatch):
    """The deliverable: a reader queries three MISSING countries and gets three
    different stories, not the same generic sentence three times.

    BR has a recorded NO_REGIME_DIFFERENT_SHAPE reason, JP is simply
    unresearched, which is the default state for most of the world, and the
    held case is staged rather than named. It used to name CN, which was held
    at the time; CN then earned a row of its own and this test failed for a
    reason that had nothing to do with what it was testing. Membership of
    NO_REGIME_HELD is meant to change - that is what the set is for - so the
    held branch is exercised on a country the test puts there itself, and the
    assertion survives the table being right about the world on any given day.

    JP is read twice on purpose, once staged as held and once in its natural
    unresearched state, and the two produce different sentences: the held
    branch's own wording against _keyed's generic one. That is what keeps the
    three-distinct-stories assertion meaningful with two real countries.

    This is the assertion that would fail if the detail enrichment in
    _payment_regimes were ever deleted and the probe fell back to _keyed's
    generic MISSING sentence for all three alike.
    """
    dimension = "payment.prompt_payment_regime"
    monkeypatch.setattr(payment_clock_data, "NO_REGIME_HELD", frozenset({"JP"}))
    held = _one("JP", dimension)
    monkeypatch.undo()

    br = _one("BR", dimension)
    jp = _one("JP", dimension)
    assert br.verdict == cc.MISSING
    assert held.verdict == cc.MISSING
    assert jp.verdict == cc.MISSING
    assert "different_shape" in br.detail
    assert "held" in held.detail
    details = {br.detail, held.detail, jp.detail}
    assert len(details) == 3, f"expected three distinct stories, got {details}"


@pytest.mark.parametrize("country", ["RU", "CN"])
def test_the_researched_countries_have_a_payment_regime_of_their_own(country):
    """Fails on the tree before the rows were added, which is the point.

    RU and CN sat in NO_REGIME_HELD, so this dimension came back MISSING for
    both. Holding was the honest state while the search had not been run
    against the right instrument; it stops being honest once it has. A country
    that regresses to MISSING here has lost its row, not merely its research.
    """
    got = _one(country, "payment.prompt_payment_regime")
    assert got.verdict == cc.COVERED, f"{country}: {got.detail}"


def _one(country: str, dimension: str) -> cc.DimensionReport:
    report = cc.country_coverage(country)
    found = [d for d in report.dimensions if d.dimension == dimension]
    assert len(found) == 1, f"{dimension} is not in the manifest"
    return found[0]


# --------------------------------------------------------------------------- #
# Calendars are four registries and the manifest must keep them four
# --------------------------------------------------------------------------- #


def test_the_calendar_registries_are_probed_separately_and_from_separate_sources():
    """They were written independently and have disagreed; one row would hide that."""
    cal = [d for d in cc.country_coverage("CA").dimensions if d.dimension.startswith("calendar.")]
    assert len(cal) >= 4, f"expected four calendar registries, found {[d.dimension for d in cal]}"
    sources = [d.source for d in cal]
    assert len(set(sources)) == len(sources), f"two calendar probes read the same source: {sources}"


def test_the_calendar_registries_do_not_all_agree_about_every_country():
    """Records that coverage is uneven across the four.

    If this ever fails because every country resolves the same way in all four,
    that is not a regression: it means the calendars have been unified and this
    manifest should collapse them into one dimension. Read the failure that way.
    """
    disagreements = []
    for code in _SWEEP:
        cal = [d for d in cc.country_coverage(code).dimensions if d.dimension.startswith("calendar.")]
        answered = {d.verdict for d in cal if d.verdict != cc.UNRESOLVED}
        if len(answered) > 1:
            disagreements.append(code)
    assert disagreements, "the four calendar registries agreed everywhere; consider collapsing the dimension"


# --------------------------------------------------------------------------- #
# Reading a registry without executing its module
# --------------------------------------------------------------------------- #


def test_a_renamed_registry_is_unresolved_rather_than_read_from_stale_source():
    with pytest.raises(LookupError, match="not defined at module level"):
        cc._module_level_node("app.modules.boq.service", "_AACE_CLASSES_RENAMED_BY_THIS_TEST")


def test_the_source_reader_refuses_modules_outside_the_app_package():
    with pytest.raises(LookupError, match="outside the app package"):
        cc._source_of("os.path")


def test_the_report_says_which_method_answered():
    """A source parse is weaker evidence than an import and has to be labelled."""
    for d in cc.country_coverage("CA").dimensions:
        assert d.method, f"{d.dimension} did not say how it resolved"


def test_the_country_code_is_normalised():
    assert cc.country_coverage("ca").country_code == "CA"
    assert cc.country_coverage(" us ").country_code == "US"


# --------------------------------------------------------------------------- #
# The distinction is only closed if it reaches the page a human reads
# --------------------------------------------------------------------------- #


def _reporter():
    """The command-line reporter, loaded by path because scripts/ is not a package."""
    path = Path(cc.__file__).resolve().parents[2] / "scripts" / "country_coverage.py"
    spec = importlib.util.spec_from_file_location("country_coverage_reporter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_page_says_how_the_verdicts_were_read_in_both_directions():
    """Provenance is stated in words, never implied by the absence of a mark.

    The per-verdict marks are printed only for a read of the file on disk, so a
    fully imported run carries none at all and is indistinguishable, on the
    page, from a run by a tool that never tracked provenance. That fully
    imported run is what a machine with a cluster produces, which is the exact
    environment this instrument's own defect survived in.
    """
    reporter = _reporter()

    clean = reporter._provenance({"import": 253})
    assert len(clean) == 1, clean
    assert "all 253 verdicts came from importing the live module" in clean[0]

    # A table parsed on purpose is not a degraded import and must not be called one.
    parsed = reporter._provenance({"import": 252, "source": 1})
    assert any("252 from importing the live module" in line for line in parsed), parsed
    assert not any("weaker evidence" in line for line in parsed), (
        f"a deliberate structural parse was reported as weaker evidence: {parsed}"
    )

    fell_back = reporter._provenance({"import": 230, "source (RuntimeError on import)": 23})
    assert any("230 from importing the live module" in line for line in fell_back), fell_back
    assert any("23 of those name an exception" in line for line in fell_back), fell_back
    assert any("weaker evidence" in line for line in fell_back), fell_back

    # A verdict that read nothing must not be totalled as one that read the module.
    nothing = reporter._provenance({"import": 90, "declared (no registry exists)": 9, "(none)": 2})
    assert any("90 from importing the live module" in line for line in nothing), nothing
    assert any("9 declared (no registry exists)" in line for line in nothing), nothing
    assert any("2 from nothing at all" in line for line in nothing), nothing
    assert not any("weaker evidence" in line for line in nothing), nothing

    # Two reasons to declare something get two clauses. One clause covering both
    # would still read as true, which is why this is asserted rather than left to
    # a reading of the code: the failure is a sentence that stays grammatical
    # while becoming false, and nothing about the output would look wrong.
    two = reporter._provenance(
        {
            "import": 90,
            "declared (no registry exists)": 9,
            "declared (the registry is a service we do not call)": 4,
        }
    )
    assert any("9 declared (no registry exists)" in line for line in two), two
    assert any("4 declared (the registry is a service we do not call)" in line for line in two), two
    assert not any("13 declared" in line for line in two), (
        f"two reasons were merged into one clause and one of them is now described wrongly: {two}"
    )


def test_the_printed_census_names_its_provenance_on_the_import_path_too(monkeypatch, capsys):
    """End to end, on the path that used to print nothing about how it read.

    Asserted against the reporter's real output rather than against the field,
    because a method string that only a test ever reads closes nothing: the
    failure this instrument exists to prevent is a human being unable to tell a
    gap in the product from a gap in the instrument.
    """
    reporter = _reporter()
    # --ignore-unprobed because this test is about how the page labels its
    # provenance, and the registry census below it now fails the run on purpose.
    # Without the flag the assertions here would be riding on an exit code that
    # belongs to a different property.
    monkeypatch.setattr(sys, "argv", ["country_coverage.py", "DE", "--ignore-unprobed"])
    assert reporter.main() == 0

    out = capsys.readouterr().out
    assert "registry limits:" in out, out
    assert "[read by import]" in out, "the census line went unlabelled on the import path"
    assert "provenance:" in out, "the page never said how the verdicts were read"
    assert "from importing the live module" in out, out
    assert "declared (no registry exists)" in out, out


def test_the_page_names_the_interpreter_that_produced_it(monkeypatch, capsys):
    """The same tree prints a different page under a different interpreter.

    Nine countries came back with eighteen verdicts read from source under one
    interpreter and eighteen read from nothing at all under another, because a
    dependency was installed in one and missing in the other. Provenance that
    names the method but not the interpreter stops one level above the thing
    that actually decided the page, so this line is printed on every run.
    """
    reporter = _reporter()
    monkeypatch.setattr(sys, "argv", ["country_coverage.py", "DE", "--ignore-unprobed"])
    reporter.main()

    out = capsys.readouterr().out
    assert "interpreter:" in out, "the page never said which interpreter produced it"
    assert sys.executable in out, out
    # Healthy runs too. A line printed only when something is wrong makes its
    # absence carry meaning, which is the defect this whole lane started from.
    assert "instrument healthy" in out, "expected a healthy run here; the assertion above is now untested"


def test_the_unhealthy_exit_names_the_package_and_not_only_the_exception():
    """A reader should not have to decode ModuleNotFoundError into an action."""
    reporter = _reporter()

    details = [
        "probe raised ModuleNotFoundError: No module named 'hijridate'",
        "probe raised ModuleNotFoundError: No module named 'hijridate'",
        "probe raised RuntimeError: no cluster",
    ]
    assert reporter._missing_packages(details) == ["hijridate"], "one missing package, named once"

    # A submodule failure names the distribution somebody would install, not the
    # dotted path, which is not a thing that can be installed.
    assert reporter._missing_packages(["No module named 'lxml.etree'"]) == ["lxml"]
    assert reporter._missing_packages(["probe raised RuntimeError: no cluster"]) == []


def test_a_probe_that_read_nothing_does_not_report_that_it_imported():
    """The method default is "import", so silence there is a claim, not an absence.

    security_of_payment has no registry to import and is declared from a reading
    of the tree, and a probe that raised read nothing at all. Both used to
    inherit the default and be counted on the printed page among the verdicts
    taken from the live module, which is the same small untruth the schedule
    probe carried on its failure path.
    """
    absent = _one("DE", "security_of_payment.deadlines")
    assert absent.verdict == cc.ABSENT
    assert absent.method.startswith("declared"), f"a probe with nothing to import reported {absent.method!r}"
    # The reason has to be on the verdict, because the reporter groups on this
    # string and prints it verbatim rather than supplying a reason of its own.
    assert absent.method != "declared", "a declared verdict must say why it was declared"

    raised = cc._run("probe.that.raises", _raise_on_purpose, "DE")
    assert raised.verdict == cc.UNRESOLVED
    assert raised.method == "(none)", f"a probe that raised reported {raised.method!r}"


def _raise_on_purpose(country: str):
    raise RuntimeError("staged failure")


# --------------------------------------------------------------------------- #
# A shared row is a limit, and a limit nobody counts is one that gets
# rediscovered rather than remembered
# --------------------------------------------------------------------------- #


def test_the_shared_row_census_is_taken_over_the_axis_and_not_over_the_cohort():
    """The figure must not move when the list of countries somebody asks about does.

    Drawn from _COHORT this same fact would read as 2, because the cohort holds
    DE and SA and none of the other six countries on a shared row. The register
    would then print a number that grows whenever the cohort does, which is the
    failure mode the module's own prose warns about two paragraphs further up.
    The assertion that catches it is the one on AT, BH, CH, KW, OM and QA: they
    are on the axis, they are on a shared row, and they are in no cohort here.
    """
    census = cc.shared_calendar_rows()
    assert census.on_axis == 19, f"the axis moved: {census.on_axis}"
    assert len(census.on_shared_row) == 8, f"expected 8 on a shared row, got {census.on_shared_row}"
    assert set(census.shared) == {"DACH", "GULF"}, f"the shared rows moved: {sorted(census.shared)}"
    off_cohort = set(census.on_shared_row) - set(_COHORT)
    assert off_cohort == {"AT", "BH", "CH", "KW", "OM", "QA"}, (
        f"the census looks drawn from the cohort rather than from the registry: {off_cohort}"
    )
    assert "8 of 19" in census.summary(), census.summary()


def test_the_two_registry_figures_are_separate_measurements_of_the_same_axis():
    """Seventeen of nineteen and eight of nineteen are different facts, and both are quoted.

    Sixteen is how many countries on the axis are not keys of the table at all,
    which is why the probe is forbidden from reading the table. Eight is how
    many share their row, which is the limit the register prints. They
    decompose exactly: eight are only spelled differently, eight actually share.
    Swapping one number for the other in a sentence would leave every other
    check in this file green, so the arithmetic is asserted rather than trusted.
    """
    calendars, _resolve, axis, _method = cc._schedule_registry()
    not_a_key = {code for code in axis if code not in calendars}
    shared = set(cc.shared_calendar_rows().on_shared_row)
    assert len(not_a_key) == 17, f"countries missing from the table keys moved: {sorted(not_a_key)}"
    assert len(shared) == 8, f"countries on a shared row moved: {sorted(shared)}"
    assert shared < not_a_key, "a country on a shared row was also a table key; the decomposition changed"
    assert len(not_a_key - shared) == 9, f"the 8 + 9 = 17 decomposition broke: {sorted(not_a_key - shared)}"


def test_a_shared_row_is_named_on_the_country_report_and_counted_in_its_summary():
    """Named where one country is read, counted where the country is summarised."""
    de = _one("DE", "calendar.schedule_regions")
    assert de.verdict == cc.COVERED, f"DACH is a real regional week, not a stand-in: {de.detail}"
    assert de.shares_row_with == ("AT", "CH"), de.shares_row_with
    assert cc.SHARED_ROW in de.detail, de.detail

    sa = _one("SA", "calendar.schedule_regions")
    assert sa.shares_row_with == ("BH", "KW", "OM", "QA"), sa.shares_row_with

    us = _one("US", "calendar.schedule_regions")
    assert us.verdict == cc.COVERED, us.detail
    assert us.shares_row_with == (), f"US has the US row to itself: {us.shares_row_with}"
    assert cc.SHARED_ROW not in us.detail, us.detail

    assert "1 on a shared row" in cc.country_coverage("DE").summary()
    assert "0 on a shared row" in cc.country_coverage("US").summary()


def test_the_census_reads_the_same_registry_when_the_import_is_gone(monkeypatch):
    """The registry figure survives the same missing database the probe does."""
    live = cc.shared_calendar_rows()
    assert live.method == "import"

    monkeypatch.setitem(sys.modules, _SCHEDULE_SERVICE, None)
    off = cc.shared_calendar_rows()
    assert off.method.startswith("source"), f"an isolated read must not be labelled {off.method!r}"
    assert off.shared == live.shared, f"{off.shared} != {live.shared}"
    assert off.on_own_row == live.on_own_row, f"{off.on_own_row} != {live.on_own_row}"


# --------------------------------------------------------------------------- #
# A probe that goes quiet has stopped measuring, and says so in a way that reads
# like a small denominator rather than like a hole
# --------------------------------------------------------------------------- #


def test_no_dimension_is_unresolved_anywhere_in_the_cohort():
    """No dimension fails to read its registry, for any country in the cohort.

    This is a floor, not the guard. It passes on a tree where the schedule probe
    is broken, because pytest boots a database and the probe's import therefore
    succeeds here and nowhere else. Read a failure of this test as "some probe
    lost its registry"; read the test below as the one that checks the probe
    still answers when the import is the thing that went away.
    """
    silent: dict[str, list[str]] = {}
    for code in _COHORT:
        for d in cc.country_coverage(code).by_verdict(cc.UNRESOLVED):
            silent.setdefault(d.dimension, []).append(f"{code}: {d.detail}")
    assert not silent, f"dimensions that could not read their registry: {silent}"


def test_the_schedule_probe_still_answers_when_its_module_will_not_import(monkeypatch):
    """The probe answers off a cluster, where its module cannot be imported.

    Importing app.modules.schedule.service reaches app.database, which builds an
    engine at import time and raises without a PostgreSQL URL. That is the
    ordinary state of a developer machine with nothing running, and it is the
    state the probe was silent in for every country while the suite stayed green.

    Putting None in sys.modules makes the import raise ModuleNotFoundError, which
    is the same shape of failure and does not need the database taken away from
    the rest of the session.
    """
    monkeypatch.setitem(sys.modules, _SCHEDULE_SERVICE, None)
    got = _one("DE", "calendar.schedule_regions")
    assert got.verdict != cc.UNRESOLVED, f"the probe went silent without its import: {got.detail}"
    assert got.method.startswith("source"), f"a read of the file on disk must not be labelled {got.method!r}"
    assert got.population, "the probe answered without naming the regions it read"


def test_the_isolated_read_and_the_import_agree_about_every_country(monkeypatch):
    """The fallback path returns what the import path returns, country by country.

    This is the test that makes the fix honest rather than convenient. An edit
    that widens a probe until it answers can be told from one that reads the
    registry correctly by exactly this: the answers off the cluster have to be
    the answers the live module gives, including the ones that are not COVERED.
    """
    live = {code: _one(code, "calendar.schedule_regions") for code in _COHORT}
    assert {d.method for d in live.values()} == {"import"}, "this test needs the import path to be the live one"
    assert len({d.verdict for d in live.values()}) > 1, "one verdict everywhere; this proves nothing about agreement"

    monkeypatch.setitem(sys.modules, _SCHEDULE_SERVICE, None)
    disagreed = {
        code: (live[code].verdict, off.verdict)
        for code in _COHORT
        if (off := _one(code, "calendar.schedule_regions")).verdict != live[code].verdict
    }
    assert not disagreed, f"the isolated read answered differently from the import: {disagreed}"


def test_the_schedule_probe_is_unresolved_when_the_registry_itself_is_renamed(monkeypatch):
    """A renamed registry is a finding about the tree, not something to route around.

    The probe has two ways to reach the calendars and must not use the second to
    paper over a symbol the first proved is gone. Here the import succeeds and
    the name does not exist, so the answer has to be UNRESOLVED rather than a
    confident one assembled from the file on disk.
    """
    import app.modules.schedule.service as svc

    monkeypatch.delattr(svc, "WORK_CALENDARS", raising=True)
    got = _one("DE", "calendar.schedule_regions")
    assert got.verdict == cc.UNRESOLVED, f"a missing registry was answered anyway: {got.verdict} / {got.detail}"


# --------------------------------------------------------------------------- #
# The denominator
#
# The defect these close: a coverage figure whose divisor is the set of probes
# somebody already wrote is a measurement of the instrument. A registry nobody
# probed was absent from the divisor as well as the dividend, so the percentage
# stayed flattering and moved only when a probe was added. The divisor is now
# walked out of the tree, and these gate that it stays walked.
# --------------------------------------------------------------------------- #


def test_the_denominator_moves_when_the_tree_gains_a_registry(monkeypatch):
    """The property the whole change exists for.

    A registry appearing in the product has to move the figure with nobody
    editing a list. Staged by handing the census one extra discovered registry,
    which is what the walk would return the day somebody adds one.
    """
    before = cc.registry_census()
    invented = registries.DiscoveredRegistry(
        symbol="app.modules.invented.thing.SOME_REGISTRY",
        codes=("DE", "FR", "NL"),
        entries=3,
        kind="literal",
        path="app/modules/invented/thing.py",
        iso_hits=3,
    )
    monkeypatch.setattr(cc, "discover_registries", lambda: (*before.discovered, invented))

    after = cc.registry_census()
    assert after.denominator == before.denominator + 1, (
        f"a new registry did not move the denominator: {before.denominator} -> {after.denominator}"
    )
    assert invented in after.unprobed, "a registry nobody probes was not reported as unprobed"


def test_a_registry_no_probe_reads_is_named_rather_than_skipped():
    """Skipping is the failure. Being named is the fix.

    An unprobed registry reported as neither covered nor missing is the shape of
    defect this file exists to prevent, one level up: it is not a country that
    went unanswered but a whole axis that was never asked about.
    """
    census = cc.registry_census()
    assert census.unprobed, "nothing is unprobed, which would mean the walk found less than the probes read"
    assert all(r.symbol not in census.covered for r in census.unprobed)
    assert census.probed + len(census.unprobed) == census.denominator, census.summary()


def test_the_denominator_is_the_union_and_not_the_walk_alone():
    """Four probes read registries the walk structurally cannot see.

    NOTICE_PERIODS is keyed by contract standard, CREDENTIAL_TYPES is a closed
    vocabulary, _AACE_CLASSES is a ladder of integers and LaborRateTemplate is a
    model column. None holds a country-shaped token, so counting only what the
    walk found would drop those four out of the universe and make the ratio a
    fact about the walk instead of about the product.
    """
    census = cc.registry_census()
    walked = {r.symbol for r in census.discovered}
    invisible = census.covered - walked
    assert invisible, "every covered symbol is discoverable; this test no longer guards anything"
    assert census.denominator == len(walked | census.covered)
    assert census.denominator > len(walked), "the union is no larger than the walk, so the probes were dropped"


def test_every_symbol_a_probe_claims_to_cover_is_really_there():
    """A probe naming a registry that has moved is how a rename goes quiet.

    The census subtracts on these strings, so a stale one silently inflates the
    probed count: the registry is still discovered under its new name and lands
    in unprobed, while the old name keeps being counted as covered.
    """
    root = Path(cc.__file__).resolve().parents[2]
    missing = []
    for symbol in sorted(cc.covered_symbols()):
        if "/" in symbol:
            if not (root / symbol).is_file():
                missing.append(symbol)
            continue
        dotted, _, name = symbol.rpartition(".")
        try:
            cc._module_level_node(dotted, name)
            continue
        except Exception:  # noqa: BLE001 - the parse is only the first of two ways to look
            pass
        try:
            module = importlib.import_module(dotted)
        except Exception:  # noqa: BLE001 - a module that will not import cannot vouch for the name
            missing.append(symbol)
            continue
        if not hasattr(module, name):
            missing.append(symbol)
    assert not missing, f"probes name registries that are not in the tree: {missing}"


def test_discovery_reads_the_shape_of_the_value_and_not_the_name_of_the_field():
    """The wrong-key trap, gated.

    The field name axis in this tree is at least six wide - country_code,
    country_iso, iso_code, country, jurisdiction, code. A first pass at this
    inventory keyed on ``country_code`` and read countries.json, the largest
    country registry in the product, as ZERO countries, because that file spells
    it ``iso_code``; the same pass missed CWICR_V3_CATALOGUES entirely, because
    that one spells it ``country_iso``. Both are asserted here by their awkward
    spelling, so a pass that goes back to looking for a name fails.
    """
    found = {r.symbol: r for r in registries.discover_registries()}

    seeded = found.get("app/modules/i18n_foundation/seed_data/countries.json")
    assert seeded is not None, "the 198-row country list was not discovered; the pass is keying on a field name"
    assert seeded.country_count > 150, seeded.country_count

    catalogue = found.get("app.modules.costs.cwicr_v3_catalogue.CWICR_V3_CATALOGUES")
    assert catalogue is not None, "the catalogue registry spells its field country_iso and was not discovered"
    assert catalogue.country_count > 30, catalogue.country_count


def test_the_walk_finds_the_registry_an_iso_filter_would_have_lost():
    """Why there is no country filter on the discovery pass, recorded as a number.

    WORK_CALENDARS has exactly three country-shaped keys among its thirteen -
    RU, UK and US - and "UK" is not a country code, so intersecting the pass with
    the product's own country list leaves two and drops the table below the
    threshold. The filter would lose the very registry the schedule probe exists
    to read, which is the measured reason this pass favours recall and states its
    noise instead of suppressing it.
    """
    found = {r.symbol: r for r in registries.discover_registries()}
    calendars = found.get("app.modules.schedule.service.WORK_CALENDARS")
    assert calendars is not None, "the work calendars fell out of the walk"
    assert calendars.country_count == registries.MIN_CODES, (
        f"WORK_CALENDARS now has {calendars.country_count} country-shaped keys, not {registries.MIN_CODES}; "
        "the margin this threshold was chosen for has moved and the choice needs remaking"
    )


def test_the_five_claimed_axes_are_probed():
    """Units, regional packs, cost classification, the second tax table, e-invoicing.

    Each is an axis the product claims per-country support on, and each was
    reachable from the tree while no dimension asked it anything.
    """
    named = set(cc.dimensions())
    for dimension in (
        "units.measurement_system",
        "packs.regional_coverage",
        "cost_classification.catalogue_standard",
        "tax.vat_rate_table",
        "einvoice.clearance_regime",
    ):
        assert dimension in named, f"{dimension} is not in the manifest"


def test_the_two_tax_registries_are_probed_separately_and_disagree():
    """Collapsing them would hide the drift their own comment warns about.

    tax_configurations.json carries forty-one countries and core/tax._RAW
    twenty-three. They are two hand-kept tables of different scope, so a country
    covered by one and not the other is the finding, and one merged "tax"
    dimension could not report it.
    """
    seeded = {c: _one(c, "tax.rates").verdict for c in _COHORT}
    table = {c: _one(c, "tax.vat_rate_table").verdict for c in _COHORT}
    assert cc.UNRESOLVED not in set(seeded.values()) | set(table.values())
    disagree = {c for c in _COHORT if seeded[c] != table[c]}
    assert disagree, (
        "the two tax registries agreed about every country. Either one of them is not being read, or "
        "somebody has genuinely reconciled the two tables - and that is a fix, not a regression. If it "
        "is the second, delete this test; do not put drift back to make it pass."
    )


def test_the_units_probe_asks_the_resolver_rather_than_pack_membership():
    """Membership of a pack's country list is not the question a caller asks.

    resolve_measurement_system returns None both when no pack claims a country
    and when several claim it and disagree, and the difference decides whether
    anybody has work to do. A country the packs do claim must therefore never
    come back MISSING, which is what reading the lists alone would report.
    """
    claimed = cc._pack_countries()
    assert claimed, "no pack claims any country; this test proves nothing"
    for code in sorted(claimed):
        got = _one(code, "units.measurement_system")
        assert got.verdict in (cc.COVERED, cc.FALLBACK), (
            f"{code} is claimed by a pack and the units probe called it {got.verdict}: {got.detail}"
        )


def test_the_reporter_fails_on_a_registry_nobody_probes(monkeypatch, capsys):
    """Loud, not skipped - and the flag that says so is the only way past it."""
    reporter = _reporter()

    monkeypatch.setattr(sys, "argv", ["country_coverage.py", "DE"])
    assert reporter.main() == 3, "an unprobed registry did not get its own exit code"
    out = capsys.readouterr().out
    assert "INSTRUMENT INCOMPLETE" in out, out
    assert "NO PROBE" in out, "the unprobed registries were counted but never named"
    assert "registries:" in out, "the page never printed the derived denominator"

    monkeypatch.setattr(sys, "argv", ["country_coverage.py", "DE", "--ignore-unprobed"])
    assert reporter.main() == 0, "the escape hatch did not let the rest of the page through"


def test_every_report_site_states_how_it_was_read():
    """A field recording how something was learned must never guess.

    ``method`` defaults to "import", the strongest value it can take, and that
    default has already produced a false claim on this page once: report sites
    inherited it while importing nothing, and the provenance line then said
    seventy-two of ninety-nine verdicts came from the live module when the true
    figure was sixty-three. Adding probes multiplies report sites, so the
    default gets more chances to be wrong with every dimension added.

    The default is left alone deliberately. Changing it would move the
    reporter's bucket arithmetic, which prints on every run of the hygiene lane,
    to buy what this test buys for nothing: a site that forgets is caught here,
    at the point somebody can still fix it, rather than relabelled at runtime.
    """
    source = Path(cc.__file__).read_text(encoding="utf-8")
    silent = [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "DimensionReport"
        and "method" not in {kw.arg for kw in node.keywords}
    ]
    assert not silent, (
        f'DimensionReport built without method= at line(s) {silent}. It will inherit "import" and be '
        "counted on the page as evidence taken from the live module. Say how the verdict was really read."
    )


def test_the_near_miss_flag_describes_and_never_subtracts():
    """The suppression list, refused again in the one place it could sneak back.

    Two uppercase letters is also a US state, a data unit and a schedule
    relationship type, so the walk catches things that are not country
    registries. Naming them on the page is the answer; dropping them is not.
    The moment a near miss stops being counted, the divisor is once more a
    hand-kept list of what somebody decided was interesting, which is the whole
    defect this census exists to end.
    """
    census = cc.registry_census()
    near = [r for r in census.discovered if r.is_near_miss]
    assert near, "nothing is a near miss; either the tree changed or the annotation is not being computed"
    assert all(r.symbol in {d.symbol for d in census.discovered} for r in near)
    assert census.denominator == len({r.symbol for r in census.discovered} | census.covered), (
        "the denominator no longer counts every discovered registry, so something is being skipped"
    )
    counted = {r.symbol for r in census.discovered}
    assert all(r.symbol in counted for r in near), "a near miss fell out of the count it is supposed to stay in"


def test_the_walk_caught_a_list_of_us_states_and_the_page_says_so():
    """The measured example that made the annotation necessary.

    us_pack's config carries FL, NY, TX and WA beside its country list, so the
    shape rule reads six country-shaped tokens where the product means two. It
    is worth pinning because a probe already covers this registry: it never
    reaches the NO PROBE list, so before the near-miss section nothing on the
    page mentioned it at all, and a reader had no way to learn that four of
    those six were states. An unannotated pass would have carried the error
    silently, which is the failure mode the whole task is about.
    """
    found = {r.symbol: r for r in registries.discover_registries()}
    pack = found.get("app.modules.us_pack.config.PACK_CONFIG")
    assert pack is not None, "the us pack config fell out of the walk"
    assert {"FL", "NY", "TX", "WA"}.issubset(set(pack.non_iso)), pack.non_iso
    assert pack.is_near_miss, f"{pack.iso_purity:.0%} ISO and not flagged; the reader is never told about the states"
    assert pack.symbol in cc.covered_symbols(), (
        "this registry is probed, which is what makes the annotation the only way to see it"
    )


def test_a_registry_names_the_file_it_was_found_in():
    """A red lane nobody can act on gets silenced instead of fixed."""
    root = Path(cc.__file__).resolve().parents[2]
    for registry in registries.discover_registries():
        assert registry.path, f"{registry.symbol} was discovered without a path"
        assert (root / registry.path).is_file(), f"{registry.symbol} names {registry.path}, which is not a file"


def test_the_reference_country_list_refuses_to_arrive_nearly_empty():
    """A count from a reader with a fallback is a fact about the reader.

    If the shipped list moved or its field names changed, an empty reference
    set would quietly mark every registry in the tree a near miss and the page
    would read as though the product had no countries at all.
    """
    assert len(registries.iso_codes()) >= registries._MIN_ISO_CODES
    assert "DE" in registries.iso_codes() and "US" in registries.iso_codes()
    assert "UK" not in registries.iso_codes(), "UK is not an ISO alpha-2 code and must not be in the reference set"


def test_the_pack_list_is_the_products_own_and_not_a_copy_of_it():
    """Two hand-kept mirrors of one registry always drift, and this pair did.

    The covers list for the pack probes was written out by hand and named
    twelve modules. A thirteenth was added to the product's own
    PACK_CONFIG_MODULES while this file still said twelve, so the product would
    have loaded a pack, that pack would have claimed countries on the coverage
    page, and the census would still have counted its config as a registry
    nobody probes. A numerator kept as a copy has exactly the defect the
    denominator was rebuilt to remove, one column to the left.

    Asserted as set equality against the product rather than against a number,
    because a count would pass the day one module was swapped for another.
    """
    from app.core.regional_packs import PACK_CONFIG_MODULES

    assert set(cc._PACK_CONFIGS) == {f"{module}.PACK_CONFIG" for module in PACK_CONFIG_MODULES}, (
        "the pack probes name a different set of configs than the product loads; derive this list, do not copy it"
    )
    assert set(cc._PACK_CONFIGS) <= cc.covered_symbols()


def test_the_contract_dimension_is_named_for_what_it_actually_reads():
    """A dimension named wider than its source gives a confident wrong answer.

    NOTICE_PERIODS is keyed by contract standard, so "keyed by standard, not by
    country" is true of it. The damage was entirely in the old name,
    contract.standard_families, which a reader scanning for "does this country
    have contract rules" answered with a no that was never about the country.
    """
    named = set(cc.dimensions())
    assert "contract.standard_families" not in named, "the old wider name is back"
    assert "contract.notice_periods_by_standard" in named
    assert _one("DE", "contract.notice_periods_by_standard").verdict == cc.NOT_KEYED


def test_the_country_keyed_contract_registry_is_probed_too():
    """Renaming alone would have traded a wrong answer for an accurate silence.

    The reader's question is legitimate and the answer exists, keyed by country,
    in the compliance packs. Silence is how e-invoicing clearance shipped
    unnoticed, so the honest answer has to be printed rather than merely not
    misstated.
    """
    assert "contract.compliance_pack" in set(cc.dimensions())
    covered = {c for c in _COHORT if _one(c, "contract.compliance_pack").verdict == cc.COVERED}
    missing = {c for c in _COHORT if _one(c, "contract.compliance_pack").verdict == cc.MISSING}
    assert covered and missing, (
        f"a country-keyed dimension that answers the same way for every country is not reading a country key: "
        f"covered={sorted(covered)} missing={sorted(missing)}"
    )
    assert "app.modules.contracts.compliance_packs.PACK_BY_COUNTRY" in cc.covered_symbols()


def test_the_copies_of_the_classification_mapping_have_been_reconciled():
    """The copies this dimension existed to catch drifting are gone.

    This replaces ``test_the_third_copy_of_the_classification_mapping_is_read_and_disagrees``,
    whose own docstring said to delete it once somebody reconciled the tables
    rather than reintroduce drift to keep it passing. The shipped catalogues,
    the match pipeline and the validation rules each used to keep a country to
    classification standard table, and for AU, IN and ZA the match pipeline
    ranked against nrm while the catalogue named masterformat.

    They read one table now, so the assertion flips: no country may report the
    FALLBACK verdict that meant "two copies disagree here", and the two
    dimensions that read the mapping must agree wherever both have an answer.
    """
    assert "cost_classification.match_standard" in set(cc.dimensions())
    codes = ("AU", "IN", "ZA", "BR", "MA", "TN", "PL", "DE", "GB", "US")
    drifted = {code for code in codes if _one(code, "cost_classification.match_standard").verdict == cc.FALLBACK}
    assert not drifted, f"{sorted(drifted)} still report two classification tables disagreeing"

    resolved = {code for code in codes if _one(code, "cost_classification.match_standard").verdict == cc.COVERED}
    assert len(resolved) == len(codes), (
        f"only {sorted(resolved)} of {sorted(codes)} resolve to a standard; the one table has lost countries"
    )


def test_the_two_iban_tables_agree_wherever_they_overlap() -> None:
    """The invariant between the copies, and the one worth failing on.

    Two modules hold a table of IBAN lengths. Today they name a different set
    of countries, which the ``validation.iban_length`` dimension reports, but
    every country in both carries the same number. That agreement is the thing
    a second copy puts at risk: an edit to one table is invisible from the
    other, and a length that disagrees is an account number one path accepts
    and the other rejects. If the copies are ever reconciled into one table
    this test has nothing left to compare and should be deleted with them.
    """
    from app.core.country_coverage import _iban_length_tables

    paid, validated = _iban_length_tables()
    shared = sorted(set(paid) & set(validated))
    assert shared, "the two IBAN tables no longer overlap at all, so one of them has moved"

    disagreements = {
        country: (paid[country], validated[country]) for country in shared if paid[country] != validated[country]
    }
    assert not disagreements, (
        f"the two copies of the IBAN length table disagree on {sorted(disagreements)}: "
        f"{disagreements} as (payment, validation). One of those numbers rejects an account "
        "number the other accepts"
    )


def test_the_iban_copies_are_probed_separately_and_not_as_a_union() -> None:
    """A merged dimension could not report the population gap, so there are two.

    The point of probing the copies apart is that the smaller table's verdict
    for a country the larger one knows says the length exists in the product
    and this path cannot see it. A union would report that country as covered.
    """
    from app.core.country_coverage import _iban_length_tables

    paid, validated = _iban_length_tables()
    only_paid = sorted(set(paid) - set(validated))
    assert only_paid, "the tables no longer diverge; if they were reconciled, drop this test"

    country = only_paid[0]
    assert _one(country, "payment.iban_length").verdict == cc.COVERED, (
        f"{country} has a length of its own on the payment path and the dimension does not say so"
    )
    seen_by_validation = _one(country, "validation.iban_length")
    assert seen_by_validation.verdict == cc.FALLBACK, (
        f"{country} is in the payment table and not in the validation one, so the validation dimension owes "
        f"a FALLBACK and returned {seen_by_validation.verdict}; a union of the two tables reports COVERED here "
        "and the population gap disappears"
    )
    assert str(paid[country]) in seen_by_validation.detail, (
        f"the FALLBACK for {country} does not name the length the other copy holds, which is the only part of "
        "it a reader can act on"
    )


def test_a_country_with_no_iban_regime_is_not_reported_as_a_gap() -> None:
    """Zero means the length check is skipped on purpose, not that a row is missing.

    Both call sites in the validation rules read a zero as skip, so a probe
    that called it MISSING would be inventing work. The payment copy says the
    same thing by leaving the row out, which is why only this dimension can
    report it.
    """
    from app.core.country_coverage import _iban_length_tables

    _, validated = _iban_length_tables()
    zeroed = sorted(country for country, length in validated.items() if length == 0)
    assert zeroed, "nothing is marked as having no IBAN regime any more; the sentinel has changed"

    for country in zeroed:
        report = _one(country, "validation.iban_length")
        assert report.verdict == cc.COVERED, (
            f"{country} carries a zero, which both call sites read as skip the length check, and the dimension "
            f"reports {report.verdict}; a country that was exempted on purpose is not a coverage gap"
        )
        assert "on purpose" in report.detail, (
            f"the verdict for {country} does not say the exemption was deliberate, so a reader cannot tell it "
            "from a row that happens to be covered"
        )


# --------------------------------------------------------------------------- #
# The five registries the census named and nothing asked about
#
# These closed a gap the census had been printing for some time: a registry no
# probe reads is reported as neither covered nor missing, so a country can be
# absent from it and the page says nothing either way. Four of the five live in
# app.core.demo_projects, which imports its ORM models at module scope, so they
# exercise the source-read path off a cluster and the import path under pytest.
# --------------------------------------------------------------------------- #

_DEMO_PROJECTS = "app.core.demo_projects"

#: A country in none of these five tables, used as the control that stops the
#: probes passing on an answer of COVERED for anything.
#:
#: It was RU until the Russian pack shipped and put RU in all five, at which
#: point every one of these went red for the right reason: the control had
#: become covered. That is the expected way this constant dies, so when it
#: goes red again, repick it rather than reaching for the probe.
#:
#: It then became PL, and died the same death when the Warsaw pack shipped.
#: Twice is a pattern worth naming: the countries we reach for as controls are
#: the ones we reach for as markets, because both lists are picked for the same
#: reason. So this pick was made against the classification registry rather
#: than by taste. BD is one of only three of the twenty-five candidate
#: countries that COUNTRY_TO_STANDARD does not know at all, which makes it the
#: furthest from being packable and therefore the longest-lived control
#: available, without being an unreal market that would make this test a
#: formality.
_A_COUNTRY_NO_TABLE_HOLDS = "BD"

#: Dimension and a country the registry holds. The control above is the other
#: half of each case.
_NEW_DIMENSIONS = (
    ("estimate.markup_region", "DE"),
    ("demo.notice_authority", "DE"),
    ("demo.address_country_names", "DE"),
    ("demo.notice_clause", "GB"),
    ("demo.catalogue_projects", "DE"),
)

#: The demo dimensions that keep answering off a cluster, through the source
#: read. All four, including the catalogue, whose registry is assembled at
#: import time and whose fallback therefore rebuilds the merge rather than
#: parsing a literal - which is exactly why it needs the agreement test below
#: more than the other three do.
_NEW_DEMO_DIMENSIONS = (
    "demo.notice_authority",
    "demo.address_country_names",
    "demo.notice_clause",
    "demo.catalogue_projects",
)


@pytest.mark.parametrize(("dimension", "held"), _NEW_DIMENSIONS)
def test_the_new_registries_answer_in_both_directions(dimension, held):
    """Green on the real registry is half the evidence; this is the other half."""
    absent = _A_COUNTRY_NO_TABLE_HOLDS
    covered = _one(held, dimension)
    assert covered.verdict == cc.COVERED, f"{dimension} does not see {held}: {covered.detail}"

    missing = _one(absent, dimension)
    assert missing.verdict == cc.MISSING, (
        f"{dimension} reports {missing.verdict} for the control country {absent}. Either a pack now covers it, "
        "in which case repick _A_COUNTRY_NO_TABLE_HOLDS, or the probe cannot go red and will never catch the "
        "regression it exists for"
    )
    assert missing.population, "the probe reported a gap without naming the population it read"


def test_the_country_name_keyed_registry_is_read_by_its_values():
    """_COUNTRY_ISO2 is keyed by English country name, and the ISO code is the value.

    The one registry on this page whose country axis is its values. A probe
    written by copying its siblings reaches for ``set(_COUNTRY_ISO2)``, takes a
    population of fifteen English names, and reports every country on earth
    MISSING with a full population printed underneath to make it look measured.
    This is the guard on that, and it fails loudly rather than quietly because
    the wrong reading is a plausible-looking one.
    """
    report = _one("DE", "demo.address_country_names")
    assert report.verdict == cc.COVERED, f"the ISO values are not being read: {report.detail}"
    assert "Germany" not in report.population, (
        f"the population is the English names, so the keys are being read instead of the values: {report.population}"
    )
    assert "DE" in report.population


@pytest.mark.parametrize("dimension", _NEW_DEMO_DIMENSIONS)
def test_the_demo_probes_answer_when_their_module_will_not_import(monkeypatch, dimension):
    """Off a cluster, app.core.demo_projects raises before any literal is reachable.

    Its module-scope ORM imports reach app.database, which builds an engine at
    import time. That is the ordinary state of a developer machine with nothing
    running, and the state the whole tool has to keep working in.
    """
    monkeypatch.setitem(sys.modules, _DEMO_PROJECTS, None)
    got = _one("DE", dimension)
    assert got.verdict != cc.UNRESOLVED, f"{dimension} went silent without its import: {got.detail}"
    assert got.method.startswith("source"), f"a read of the file on disk must not be labelled {got.method!r}"


def test_the_demo_source_read_and_the_import_agree_about_every_country(monkeypatch):
    """The fallback returns what the import returns, as whole populations.

    Compared as full sets rather than as verdicts over the cohort, and that is
    the point of the test rather than a detail of it. Asked country by country
    over nine cohort members, this passed while the catalogue rebuild was also
    reporting NZ, which no cohort member would ever have made it mention. A
    probe that reads its registry correctly and a probe widened until the
    cohort stops complaining are indistinguishable from inside the cohort.

    This is also the pin underneath _catalogue_from_source, which
    re-implements the pack merge in AST. If the loader changes how it globs a
    pack directory, names the template, maps the address or dedupes an id, this
    is the test that has to approve it.
    """
    live = {dimension: _one("DE", dimension) for dimension in _NEW_DEMO_DIMENSIONS}
    assert {d.method for d in live.values()} == {"import"}, "this test needs the import path to be the live one"
    assert all(d.population for d in live.values()), "an empty population would make agreement meaningless"

    monkeypatch.setitem(sys.modules, _DEMO_PROJECTS, None)
    off = {dimension: _one("DE", dimension) for dimension in _NEW_DEMO_DIMENSIONS}
    assert {d.method.split()[0] for d in off.values()} == {"source"}, "the import path was still reachable"

    disagreed = {
        dimension: (
            sorted(set(live[dimension].population) - set(off[dimension].population)),
            sorted(set(off[dimension].population) - set(live[dimension].population)),
        )
        for dimension in _NEW_DEMO_DIMENSIONS
        if set(live[dimension].population) != set(off[dimension].population)
    }
    assert not disagreed, f"source read differs from the import (import-only, source-only): {disagreed}"


@pytest.mark.parametrize(
    ("dimension", "symbol"),
    [
        ("demo.notice_authority", "_AUTHORITY_BY_COUNTRY"),
        ("demo.address_country_names", "_COUNTRY_ISO2"),
        ("demo.notice_clause", "_NOTICE_CLAUSE_BY_COUNTRY"),
        ("demo.catalogue_projects", "DEMO_CATALOG"),
    ],
)
def test_a_demo_probe_is_unresolved_when_its_registry_is_renamed(monkeypatch, dimension, symbol):
    """A renamed registry is a finding about the tree, not something to route around.

    Each of these probes has two ways to reach its table and must not use the
    second to paper over a symbol the first proved is gone. The import succeeds
    here and the name does not exist, so the answer has to be UNRESOLVED rather
    than a confident one assembled from the file on disk.
    """
    import app.core.demo_projects as demo

    monkeypatch.delattr(demo, symbol, raising=True)
    got = _one("DE", dimension)
    assert got.verdict == cc.UNRESOLVED, f"a missing registry was answered anyway: {got.verdict} / {got.detail}"


def test_a_demo_registry_emptied_is_unresolved_rather_than_everyone_missing(monkeypatch):
    import app.core.demo_projects as demo

    monkeypatch.setattr(demo, "_AUTHORITY_BY_COUNTRY", {})
    got = _one("DE", "demo.notice_authority")
    assert got.verdict == cc.UNRESOLVED, f"an emptied registry read as a coverage gap: {got.verdict}"


def test_a_demo_registry_that_lost_its_shape_is_unresolved(monkeypatch):
    """A table that stopped being a table cannot be asked about a country."""
    import app.core.demo_projects as demo

    monkeypatch.setattr(demo, "_NOTICE_CLAUSE_BY_COUNTRY", ["GB", "US"])
    got = _one("GB", "demo.notice_clause")
    assert got.verdict == cc.UNRESOLVED, f"a wrongly-shaped registry was answered anyway: {got.detail}"


def test_the_six_registries_are_no_longer_in_the_unprobed_census():
    """The census is what reports the gap, so it is where the fix has to show."""
    unprobed = {r.symbol for r in cc.registry_census().unprobed}
    closed = {
        "app.modules.boq.markup_templates.REGION_BY_COUNTRY",
        "app.modules.boq.markup_templates.DEFAULT_MARKUP_TEMPLATES",
        "app.core.demo_projects._AUTHORITY_BY_COUNTRY",
        "app.core.demo_projects._COUNTRY_ISO2",
        "app.core.demo_projects._NOTICE_CLAUSE_BY_COUNTRY",
        "app.core.demo_projects.DEMO_CATALOG",
    }
    assert not (closed & unprobed), f"still reported as nobody's registry: {sorted(closed & unprobed)}"
    assert closed <= cc.covered_symbols(), "a probe stopped naming the registry it reads"


def test_the_markup_stacks_are_recorded_as_region_keyed_and_never_asked_about_a_country():
    """The registry the walk most convincingly mistakes for a country table.

    Its keys are region names, ten of which are two uppercase letters. The
    wrong probe here is the natural one to write and it is confidently wrong in
    both directions at once, so this pins the specific wrong answers rather
    than only the right verdict: GB is a country that is served and is not a
    key, UK is a key that is not a country, and AT, CH and SA are all served
    through region names the walk cannot even see.
    """
    got = _one("GB", "estimate.markup_stack")
    assert got.verdict == cc.NOT_KEYED, f"a region-keyed registry was asked a country question: {got.detail}"
    assert got.verdict not in (cc.COVERED, cc.MISSING), "regions are being read as a country axis"
    assert "REGION_BY_COUNTRY" in got.detail, "the verdict does not send the reader to the dimension that answers"

    # The countries the wrong probe would misreport, each one served today.
    for served in ("GB", "AT", "CH", "SA"):
        assert _one(served, "estimate.markup_region").verdict == cc.COVERED, (
            f"{served} is meant to reach a stack through REGION_BY_COUNTRY; this test's premise has moved"
        )


def test_the_markup_stack_probe_is_unresolved_when_its_registry_empties(monkeypatch):
    """The red half: emptied is a broken registry, not a registry with no country axis."""
    from app.modules.boq import markup_templates

    monkeypatch.setattr(markup_templates, "DEFAULT_MARKUP_TEMPLATES", {})
    got = _one("GB", "estimate.markup_stack")
    assert got.verdict == cc.UNRESOLVED, f"an empty registry still reported {got.verdict}"
    assert got.verdict != cc.NOT_KEYED, "an emptied registry is indistinguishable from a region-keyed one"


def _seed_catalogue_rows() -> list[dict]:
    """The hand-written DEMO_CATALOG rows, without importing the module."""
    return [
        row for row in ast.literal_eval(cc._module_level_node(_DEMO_PROJECTS, "DEMO_CATALOG")) if isinstance(row, dict)
    ]


def test_the_catalogue_answers_off_a_cluster_out_of_the_packs_and_not_the_seeds(monkeypatch):
    """DEMO_CATALOG is assembled at import time, so the fallback rebuilds the merge.

    The five rows written in the file are seeds; register_pack_templates
    appends one per pack template. Answering out of the literal alone was
    measured against the import and disagreed about nine countries - CA, CN,
    IN, BR, NL, AU, MX, SA and ZA are each in the assembled list and none of
    them is in the literal.

    So the assertion is deliberately on CA rather than on DE. DE would pass on
    the seed rows alone and would prove only that something answered; CA can be
    reached only by reading the pack files, which is the half of the rebuild
    that can actually be got wrong.
    """
    seeded = {row["country"] for row in _seed_catalogue_rows() if row.get("country")}
    assert "CA" not in seeded, f"CA is a seed row now, so this test no longer proves the merge was rebuilt: {seeded}"

    monkeypatch.setitem(sys.modules, _DEMO_PROJECTS, None)
    got = _one("CA", "demo.catalogue_projects")
    assert got.verdict == cc.COVERED, f"the rebuild did not reach a pack-supplied country: {got.detail}"
    assert got.method.startswith("source"), f"a read of the files on disk must not be labelled {got.method!r}"

    absent = _one(_A_COUNTRY_NO_TABLE_HOLDS, "demo.catalogue_projects")
    assert absent.verdict == cc.MISSING, (
        f"the rebuild reports {absent.verdict} for the control country {_A_COUNTRY_NO_TABLE_HOLDS}; "
        "repick it if a pack now covers it"
    )


def test_the_catalogue_literal_really_is_narrower_than_the_assembled_list():
    """The measurement the rebuild exists for, kept executable.

    If somebody later stops assembling the catalogue at import time, this fails
    and the probe may go back to reading the literal directly. Without it, the
    reason for the whole of _catalogue_from_source lives only in a docstring.
    """
    import app.core.demo_projects as demo

    live = {row["country"] for row in demo.DEMO_CATALOG if row.get("country")}
    seeded = {row["country"] for row in _seed_catalogue_rows() if row.get("country")}
    assert seeded < live, (
        f"the literal is no longer a strict subset of the assembled catalogue (literal={sorted(seeded)}, "
        f"live={sorted(live)}); the reason this probe rebuilds rather than parses may have gone"
    )


def test_no_pack_demo_id_collides_with_a_seed_row():
    """The dedupe assumption under the rebuild, kept executable rather than assumed.

    register_pack_templates appends a catalogue row only for a demo_id that is
    not already present, which keeps a hand-written row authoritative over a
    pack that would clash with it. _catalogue_from_source copies that rule, and
    today the rule changes nothing: every pack id is distinct from every seed
    id and from every other pack id, measured, so the branch never fires.

    That is a fact about the tree and not a guarantee about it. This is the
    tripwire: if a pack ever takes a seed's id, the rebuild starts depending on
    a branch nothing has ever exercised, and somebody should look at it on
    purpose rather than discover it through a wrong country on a report.
    """
    seed_ids = {str(row.get("demo_id")) for row in _seed_catalogue_rows()}
    packs = sorted(cc._source_of(_DEMO_PROJECTS).parent.joinpath("demo_packs").glob("*.py"))
    pack_ids = []
    for path in packs:
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        call = cc._pack_template_call(path)
        assert call is not None, f"{path.name} binds no module-level TEMPLATE call, so the loader would skip it"
        pack_ids.append(str(cc._call_kwarg(call, "demo_id")))

    assert len(pack_ids) > 20, f"the pack directory came back nearly empty ({len(pack_ids)}); nothing was measured"
    assert not (seed_ids & set(pack_ids)), f"a pack now shares a seed's demo_id: {sorted(seed_ids & set(pack_ids))}"
    assert len(pack_ids) == len(set(pack_ids)), "two packs share a demo_id, so only the first would reach the catalogue"
