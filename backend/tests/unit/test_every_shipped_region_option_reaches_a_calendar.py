"""Every region the product offers must reach a working week someone chose for it.

**The defect this file exists to prevent, and why the previous gate missed it.**

``schedule.service.get_work_calendar`` resolves a region string to a planning
week. The region strings it is actually handed come from ``project.region``,
which is written by the project region picker in
``frontend/src/features/projects/CreateProjectPage.tsx``.

The gate that already covers this resolver,
``test_work_calendar_rest_days_do_not_conflict.py``, walks
``_CALENDAR_BY_COUNTRY`` and ``core.calendar._WORKING_WEEK``. Both are keyed by
ISO 3166-1 alpha-2 country codes. The picker emits none: it ships compound
CamelCase tokens like ``GulfStates`` and ``MiddleEast``. So the instrument and
the product spoke different vocabularies, every assertion passed, and a user who
picked "Gulf States" for a Doha project was silently given a Monday-Friday week
in a country whose statutory rest day is Friday.

Twenty-one of the thirty shipped options resolved to ``DEFAULT``. The resolver
was never wrong about the vocabulary it was asked about; it was never asked
about the one the product speaks.

**Therefore the population here is read from the picker file itself.** Copying
the values into this module would rebuild exactly the blind spot above: the copy
and the picker would drift, and the drift would be invisible because both sides
would still be internally consistent. The parse is cross-checked two independent
ways below, because a parse that silently matches nothing is a green gate over
an empty population, which is the same failure wearing a different hat.

**What this file asserts, and what it deliberately does not.**

It asserts that every shipped option is *classified*: it either resolves to a
calendar chosen for it, or it is named in one of the two tables below with a
reason. It cannot assert that the classification is *right*. Adding a picker
option ``Egypt`` together with a Monday-Friday ``EGYPT`` calendar would pass here
and still be wrong, because Egypt works Sunday-Thursday. Judging whether a week
matches a country is what the rest-days gate does, against a sourced country
week. This file closes the gap where nobody asked the question at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.country_registries import iso_codes
from app.modules.schedule.service import (
    _CALENDAR_BY_COUNTRY,
    _CALENDAR_BY_LABEL,
    _CALENDAR_BY_LEGACY_HEAD,
    _CALENDAR_BY_PICKER_REGION,
    WORK_CALENDARS,
    get_work_calendar,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PICKER = REPO_ROOT / "frontend" / "src" / "features" / "projects" / "CreateProjectPage.tsx"

#: The picker's free-text escape hatch. It is a UI mode rather than a region, and
#: the value never reaches the backend: the page substitutes the typed text
#: before submitting. Excluded from the population for that reason, not waived.
FREE_TEXT_OPTION = "__custom__"

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _names(days: object) -> str:
    """Render a weekday set as day names, so a failure reads without decoding."""
    return ", ".join(_DAY_NAMES[d] for d in sorted(days))  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# The two ways a shipped option is allowed to answer DEFAULT.
#
# An option in neither table, resolving to DEFAULT, fails. That is the whole
# point: it means someone added a region to the product and nobody decided what
# week it works.
# --------------------------------------------------------------------------- #

#: Options whose week really is Monday-Friday, so DEFAULT is the right answer and
#: a calendar of their own would only duplicate it. The reason is required
#: because "it happens to be Monday-Friday" and "nobody looked" produce the same
#: resolver output, and only a written reason tells them apart.
PICKER_REGIONS_THAT_ARE_MONDAY_TO_FRIDAY: dict[str, str] = {
    "Australia": "Saturday-Sunday weekend.",
    "Croatia": "Saturday-Sunday weekend; the Labour Act sets a 40-hour week over five days.",
    "Czech": "Saturday-Sunday weekend.",
    "INTL": "Multi-region, so no single week applies; DEFAULT is the neutral answer rather than a guess.",
    "Italy": "Saturday-Sunday weekend.",
    "Japan": "Saturday-Sunday weekend.",
    "Korea": "Saturday-Sunday weekend.",
    "Mexico": "Saturday-Sunday weekend.",
    "Netherlands": "Saturday-Sunday weekend.",
    "NewZealand": "Saturday-Sunday weekend.",
    "Nordics": (
        "Saturday-Sunday weekend across all four. Deliberately not routed to the DACH calendar, "
        "which _CALENDAR_BY_LEGACY_HEAD's 'NORDIC' entry would suggest: DACH is also Monday-Friday "
        "and eight hours, so routing there changes no computed date and only makes a Stockholm "
        "project render a badge reading 'Germany/DACH'."
    ),
    "Poland": "Saturday-Sunday weekend.",
    "SouthAfrica": "Saturday-Sunday weekend.",
    "Turkey": "Saturday-Sunday weekend; Turkey has never used a Friday rest day.",
}

#: Options whose week is a genuinely open question, kept apart from the table
#: above so that "we checked and it is Monday-Friday" is never confused with "we
#: could not tell". These answer DEFAULT today, which is a guess, and each line
#: says what would settle it. Splitting the option or sourcing a calendar is a
#: product decision, not a test's to make.
PICKER_REGIONS_WHOSE_WEEK_IS_UNSETTLED: dict[str, str] = {
    "NorthAfrica": (
        "Genuinely split: Egypt, Libya, Algeria and Sudan rest Friday-Saturday and work "
        "Sunday-Thursday, while Morocco and Tunisia rest Saturday-Sunday. No single week is right "
        "for the option as shipped, and Egypt is the largest construction market in it, so DEFAULT "
        "is wrong there. Settled by splitting the picker option, not by widening a calendar."
    ),
    "EastAfrica": (
        "Kenya, Tanzania and Uganda are Monday-Friday, but Ethiopia and much of the region run a "
        "six-day site week, which is the same unsourced construction-convention question the CHINA "
        "and INDIA entries carry. Settled by sourcing a site week, not by assuming one."
    ),
    "WestAfrica": (
        "Nigeria, Ghana and Senegal are Monday-Friday by statute, with a six-day site week common "
        "in practice. Same unsourced question as EastAfrica."
    ),
    "LatinAmerica": (
        "Covers countries whose statutory weeks differ materially: Brazil already has its own "
        "Monday-Saturday 44h entry, while Mexico is listed separately. What the residual 'Other' "
        "option should mean is undecided."
    ),
    "SoutheastAsia": (
        "Monday-Friday for the office week across most of the region, but Indonesia, Malaysia and "
        "Vietnam commonly run six-day construction weeks. Unsourced, same class as the CHINA entry: "
        "a longer site week is a deliberate model this product already ships, so what is undecided "
        "here is whether the region has one, not whether its rest day is misplaced."
    ),
}


#: Quote-agnostic on purpose: the repo has no frontend autoformatter, so a file
#: may be edited into double quotes at any time, and a single-quote-only pattern
#: would then match nothing and pass over an empty population.
_OPTION_RE = re.compile(r"""\{\s*value:\s*(['"])(.*?)\1\s*,\s*label:\s*(['"])(.*?)\3\s*\}""")


def _picker_block() -> str:
    """The REGION_GROUPS literal, as text.

    Raises:
        AssertionError: The picker file or the literal is not where this gate
            expects it. Failing loudly matters more than usual here: a gate that
            cannot find its population must never be allowed to pass empty.
    """
    assert PICKER.is_file(), (
        f"the project region picker is not at {PICKER}. This gate reads the shipped picker as its "
        "population and cannot fall back to a copy, because a copy is what it exists to prevent. "
        "Re-point PICKER at the file that now defines REGION_GROUPS."
    )
    source = PICKER.read_text(encoding="utf-8")
    marker = "const REGION_GROUPS"
    assert marker in source, (
        f"{PICKER.name} no longer declares {marker}. If the region options moved to a shared module, "
        "re-point this gate at it; do not copy the values here."
    )
    start = source.index(marker)
    end = source.index("\n];", start)
    return source[start:end]


def _shipped_options() -> list[tuple[str, str]]:
    """Every ``{value, label}`` pair the region picker ships, in file order.

    Returns:
        Pairs of option value and human label.
    """
    block = _picker_block()
    return [(m.group(2), m.group(4)) for m in _OPTION_RE.finditer(block)]


def test_the_picker_parse_finds_every_option_the_file_declares() -> None:
    """Cross-check the population two independent ways before trusting it.

    A regex that matches nothing yields an empty population, and every
    ``for option in population`` assertion below then passes while measuring
    nothing. So the count of parsed pairs is checked against a count taken a
    different way - occurrences of the ``value:`` key - and the free-text option
    is asserted present, since it is the one value guaranteed to be in the list.
    """
    block = _picker_block()
    parsed = _shipped_options()
    declared = len(re.findall(r"\bvalue:", block))

    assert parsed, (
        "the option regex matched nothing in the REGION_GROUPS block. The picker's quoting or "
        "option shape has changed; fix the pattern, because an empty population passes every other "
        "assertion in this file."
    )
    assert len(parsed) == declared, (
        f"the option regex found {len(parsed)} options but the block declares {declared} 'value:' "
        "keys. The parse is dropping options, and a dropped option is one this gate never checks.\n"
        f"parsed: {[v for v, _ in parsed]}"
    )
    assert FREE_TEXT_OPTION in {v for v, _ in parsed}, (
        f"{FREE_TEXT_OPTION!r} is missing from the parsed options. It is the picker's free-text "
        "escape hatch and has always shipped; its absence means the parse is reading the wrong "
        "block, or the picker changed in a way this gate has not caught up with."
    )
    assert len(parsed) == len({v for v, _ in parsed}), (
        f"the picker ships a duplicate option value: {[v for v, _ in parsed]}"
    )


@pytest.mark.parametrize(("value", "label"), [o for o in _shipped_options() if o[0] != FREE_TEXT_OPTION])
def test_a_shipped_region_option_reaches_a_calendar_or_is_declared_monday_to_friday(value: str, label: str) -> None:
    """No option may answer DEFAULT by accident.

    Resolving to a calendar of its own passes. Answering DEFAULT passes only
    when this file names the option and says why. Anything else is a region the
    product offers with no week behind it, which is how the Gulf shipped a
    Monday-Friday planning week for four years of Friday rest days.
    """
    calendar = get_work_calendar(value)
    if calendar is not WORK_CALENDARS["DEFAULT"]:
        return

    declared = value in PICKER_REGIONS_THAT_ARE_MONDAY_TO_FRIDAY or value in PICKER_REGIONS_WHOSE_WEEK_IS_UNSETTLED

    assert declared, (
        f"the project region picker ships {value!r} ({label}) and get_work_calendar falls through to "
        f"WORK_CALENDARS['DEFAULT'] ({_names(calendar['work_days'])}) for it.\n"
        "Nothing decided that this region works Monday to Friday; it is simply absent from every "
        "keyspace the resolver reads, and an absent region is indistinguishable from one with no "
        "special calendar.\n"
        "Close it one of three ways:\n"
        "  - map it in schedule.service._CALENDAR_BY_PICKER_REGION, if a calendar suits it;\n"
        "  - add it to PICKER_REGIONS_THAT_ARE_MONDAY_TO_FRIDAY with the reason its week really is "
        "Monday-Friday;\n"
        "  - add it to PICKER_REGIONS_WHOSE_WEEK_IS_UNSETTLED, saying what would settle it.\n"
        "Do not delete this assertion: it is the only thing that connects the picker's vocabulary "
        "to the resolver's."
    )


def test_neither_declaration_table_holds_an_option_the_picker_no_longer_ships() -> None:
    """A stale waiver is a waiver nobody reads.

    An entry naming a value the picker has dropped, or one that now resolves to a
    calendar of its own, is dead text that makes the tables look more considered
    than they are.
    """
    shipped = {v for v, _ in _shipped_options()}
    problems: list[str] = []
    for table_name, table in (
        ("PICKER_REGIONS_THAT_ARE_MONDAY_TO_FRIDAY", PICKER_REGIONS_THAT_ARE_MONDAY_TO_FRIDAY),
        ("PICKER_REGIONS_WHOSE_WEEK_IS_UNSETTLED", PICKER_REGIONS_WHOSE_WEEK_IS_UNSETTLED),
    ):
        for value in sorted(table):
            if value not in shipped:
                problems.append(f"  {table_name}[{value!r}]: the picker no longer ships this option")
            elif get_work_calendar(value) is not WORK_CALENDARS["DEFAULT"]:
                problems.append(
                    f"  {table_name}[{value!r}]: now resolves to {get_work_calendar(value)['label']}, "
                    "so the entry is stale and should be deleted"
                )

    assert problems == [], "these declarations no longer describe anything:\n" + "\n".join(problems)


def test_the_two_declaration_tables_do_not_both_claim_the_same_option() -> None:
    """A settled Monday-Friday week and an unknown week cannot both be claimed for one option."""
    both = sorted(set(PICKER_REGIONS_THAT_ARE_MONDAY_TO_FRIDAY) & set(PICKER_REGIONS_WHOSE_WEEK_IS_UNSETTLED))
    assert both == [], (
        f"{both} are declared both settled Monday-Friday and unsettled. Pick one: the tables mean "
        "opposite things, and an option in both makes the settled table unreadable as a statement."
    )


def test_every_declaration_carries_a_reason() -> None:
    """An empty reason is a waiver with the justification left out."""
    thin = sorted(
        f"  {value}: {reason!r}"
        for table in (PICKER_REGIONS_THAT_ARE_MONDAY_TO_FRIDAY, PICKER_REGIONS_WHOSE_WEEK_IS_UNSETTLED)
        for value, reason in table.items()
        if len(reason.strip()) < 20
    )
    assert thin == [], (
        "these declarations carry no usable reason:\n"
        + "\n".join(thin)
        + "\nThe reason is the whole value of the table; without it the entry is just a silenced "
        "assertion."
    )


def test_the_gulf_and_middle_east_options_reach_the_sunday_to_thursday_week() -> None:
    """Pin the specific defect, so it cannot come back by an entry being dropped.

    The parametrized test above would go green again if someone added these two
    to the Monday-Friday table, since that is a legitimate way to close it for
    other regions. For these two it is not: Friday is the statutory rest day in
    Saudi Arabia, Qatar, Kuwait and Bahrain, so the week is asserted directly.

    ``GulfStates`` is labelled "Gulf States (UAE, Saudi Arabia, Qatar)" and the
    UAE left the Sunday-Thursday week in 2022, so this answer is right for five
    of the six GCC states and wrong for the one named first in the label. That is
    the same trade-off ``_CALENDAR_BY_LABEL``'s "MIDDLE EAST" entry already makes,
    and the UAE stays reachable by "AE", "AE_DUBAI" and "United Arab Emirates".
    Splitting the picker option is the real fix and is a product decision.
    """
    for value in ("GulfStates", "MiddleEast"):
        calendar = get_work_calendar(value)
        assert calendar["work_days"] == {6, 0, 1, 2, 3}, (
            f"the picker option {value!r} resolves to {_names(calendar['work_days'])} "
            f"({calendar['label']}). It must reach the Sunday-Thursday Gulf week: a planning week "
            "that works Friday contradicts Qatar Labour Law No. 14 of 2004 Art. 75 and Kuwait "
            "Labour Law No. 6 of 2010 Art. 64, and does so silently, because a duration still "
            "comes back as a plausible number."
        )
        assert calendar["hours_per_day"] == 8


@pytest.mark.parametrize("typed", ["Qatar", "Saudi Arabia", "Kuwait", "Bahrain", "Oman"])
def test_a_gulf_country_typed_as_free_text_gets_the_same_week_as_its_iso_code(typed: str) -> None:
    """The region field accepts free text, and the natural spelling was the wrong one.

    The picker's "Custom..." option stores whatever the user types. "QA" resolved
    to Sunday-Thursday while "Qatar" fell through to Monday-Friday, so the same
    project got two different weeks depending on which form was entered, and the
    longer, more obvious form was the one that was wrong.
    """
    calendar = get_work_calendar(typed)
    assert calendar["work_days"] == {6, 0, 1, 2, 3}, (
        f"the free-text region {typed!r} resolves to {_names(calendar['work_days'])} "
        f"({calendar['label']}), not the Sunday-Thursday week its ISO code reaches. A region typed "
        "by its country name must not get a different week from the same country's code."
    )


def test_the_head_keyspaces_stay_disjoint() -> None:
    """Three maps answer the same head lookup, so order must not be able to decide anything.

    ``get_work_calendar`` consults ``_CALENDAR_BY_COUNTRY``, then
    ``_CALENDAR_BY_LEGACY_HEAD``, then ``_CALENDAR_BY_PICKER_REGION``, and takes
    the first hit. While the key sets are disjoint that order is unobservable. If
    they ever overlap, the answer starts depending on the order the maps happen
    to be written in, which is the property that let AR mean both Argentina and
    Arabic.
    """
    overlaps: list[str] = []
    named = (
        ("_CALENDAR_BY_COUNTRY", _CALENDAR_BY_COUNTRY),
        ("_CALENDAR_BY_LEGACY_HEAD", _CALENDAR_BY_LEGACY_HEAD),
        ("_CALENDAR_BY_PICKER_REGION", _CALENDAR_BY_PICKER_REGION),
    )
    for i, (left_name, left) in enumerate(named):
        for right_name, right in named[i + 1 :]:
            shared = sorted(set(left) & set(right))
            if shared:
                overlaps.append(f"  {left_name} and {right_name} both key {shared}")

    assert overlaps == [], (
        "the head keyspaces overlap, so which calendar answers now depends on the order "
        "get_work_calendar consults them in:\n" + "\n".join(overlaps)
    )


def test_no_head_keyspace_outside_the_country_map_holds_an_iso_country_code() -> None:
    """The invariant that keeps the maps disjoint, asserted rather than described.

    ``_CALENDAR_BY_LEGACY_HEAD`` says in a comment that nothing in it may be a
    two-letter ISO code, because AR and PT once sat with the country codes
    meaning Arabic and Portuguese, and Buenos Aires was given the Gulf week of
    six ten-hour days. ``_CALENDAR_BY_PICKER_REGION`` inherits the same rule.

    The test is membership of the shipped ISO list, not string length. Length
    would be the wrong instrument and would fail the tree as it stands: HI, SP
    and ZH are ISO 639-1 *language* codes and UK is the superseded alias for GB,
    so all four are two letters and none of them is a country code. Asserting
    length would force four correct entries to be renamed to satisfy the gate.

    Checking against ``iso_codes()`` also makes this bite on the case that
    matters and that length would miss in the other direction: a future entry
    keyed by a real country code, which would then be shadowed by, or shadow,
    ``_CALENDAR_BY_COUNTRY`` depending on consultation order.
    """
    shipped = iso_codes()
    for name, table in (
        ("_CALENDAR_BY_LEGACY_HEAD", _CALENDAR_BY_LEGACY_HEAD),
        ("_CALENDAR_BY_PICKER_REGION", _CALENDAR_BY_PICKER_REGION),
    ):
        offenders = sorted(k for k in table if k in shipped)
        assert offenders == [], (
            f"{name} holds {offenders}, which are ISO 3166-1 alpha-2 codes the product ships. A "
            "country code belongs in _CALENDAR_BY_COUNTRY and means that country; holding one here "
            "makes the answer depend on which map get_work_calendar happens to consult first."
        )


def test_no_label_prefix_swallows_a_shipped_picker_option() -> None:
    """``_CALENDAR_BY_LABEL`` matches by prefix, so disjointness is not enough for it.

    The other maps are exact-key lookups. This one is consulted with
    ``startswith``, and it is consulted *before* the head lookup, so a label that
    is a prefix of a picker value would capture that value and the picker map
    would never be reached. The precedent is real: a bare "UNITED" entry used to
    catch every label beginning with that word, and gave "United Arab Emirates"
    the American calendar.

    A picker value that resolves through a label prefix on purpose is fine, so
    long as it lands on the calendar the picker map would have chosen. What must
    not happen is a prefix quietly answering for an unrelated region.
    """
    captured: list[str] = []
    for value, label in _shipped_options():
        if value == FREE_TEXT_OPTION:
            continue
        normalized = value.strip().upper()
        if normalized in WORK_CALENDARS:
            continue
        for prefix in _CALENDAR_BY_LABEL:
            if not normalized.startswith(prefix):
                continue
            via_label = WORK_CALENDARS[_CALENDAR_BY_LABEL[prefix]]
            intended = _CALENDAR_BY_PICKER_REGION.get(normalized)
            if intended is None or WORK_CALENDARS[intended] is not via_label:
                captured.append(
                    f"  {value!r} ({label}) starts with the label {prefix!r} and is answered "
                    f"{via_label['label']}, which is not what _CALENDAR_BY_PICKER_REGION intends "
                    f"for it ({intended or 'nothing'})"
                )

    assert captured == [], (
        "a label prefix captures a shipped picker option before the head lookup runs:\n"
        + "\n".join(captured)
        + "\nLengthen the label so it cannot prefix an unrelated region."
    )
