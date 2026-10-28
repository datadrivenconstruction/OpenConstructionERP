# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The notice register's screen holds a hand-written copy of the standard registry.

``ChangeIntelligencePage`` carries two literals that mirror
``change_intelligence.time_bar``: the contract-standard picker, whose values are
sent back to the register endpoint as the ``standard`` override, and a token to
label map for the resolved badge. Nothing generates them from the backend and
nothing compared them until this file, which is the same shape of defect
``test_contract_standard_registration`` guards on the server side: a family added
to one table and forgotten in another.

Both failure directions are quiet, which is why they need a test rather than a
reviewer.

A standard the backend recognises and the picker omits cannot be chosen, so a
project whose contract is that standard shows a badge naming a standard that is
not in the list underneath it. That happened: CCDC was recognised by the engine
and returned for two shipped packs while the picker offered five other families
and not that one.

A picker value the backend cannot resolve is worse, because it fails silently in
the other direction. The endpoint takes the override as free text, and an
unresolvable one falls through to the project's own standard, so the screen
reports periods for a standard the user did not pick and never says so. A typo
in the literal is enough.

The picker is deliberately allowed to hold a standard with no notice periods.
Recognised and timed are different questions, and a user choosing a held family
should get "no deadline asserted" rather than the family being missing from the
list as though the product had never heard of it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.change_intelligence.time_bar import (
    NOTICE_PERIODS,
    NOTICE_PERIODS_HELD,
    STANDARD_UNKNOWN,
    normalize_standard,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PAGE_PATH = REPO_ROOT / "frontend" / "src" / "features" / "change-intelligence" / "ChangeIntelligencePage.tsx"

_PICKER_RE = re.compile(r"const NOTICE_STANDARDS\s*=\s*\[(?P<body>[^\]]*)\]")
_DISPLAY_RE = re.compile(r"const NOTICE_STANDARD_DISPLAY\s*:[^=]*=\s*\{(?P<body>[^}]*)\}")
_QUOTED_RE = re.compile(r"'([^']*)'")


def recognised_standards() -> set[str]:
    """Every family the bridge can return for a record, held periods included."""
    return set(NOTICE_PERIODS) | set(NOTICE_PERIODS_HELD)


def picker_values(source: str) -> list[str]:
    """The literal option values of the contract-standard picker, in order.

    Takes the source as an argument rather than reading the file, so the tests
    below can hand it a doctored page and watch the extractor react instead of
    proving that a regular expression can return an empty list.
    """
    match = _PICKER_RE.search(source)
    if match is None:
        raise AssertionError(
            "NOTICE_STANDARDS was not found in the page source; the picker was renamed or "
            "reshaped and this gate is no longer reading the thing it claims to read"
        )
    return _QUOTED_RE.findall(match.group("body"))


def display_tokens(source: str) -> list[str]:
    """The canonical tokens the resolved badge knows a label for."""
    match = _DISPLAY_RE.search(source)
    if match is None:
        raise AssertionError(
            "NOTICE_STANDARD_DISPLAY was not found in the page source; the badge map was "
            "renamed or reshaped and this gate is no longer reading the thing it claims to read"
        )
    return [line.split(":", 1)[0].strip() for line in match.group("body").splitlines() if ":" in line]


@pytest.fixture(scope="module")
def page_source() -> str:
    assert PAGE_PATH.is_file(), f"{PAGE_PATH} is missing; this gate cannot be satisfied by not running"
    return PAGE_PATH.read_text(encoding="utf-8")


def test_every_picker_value_resolves_to_the_family_it_names(page_source: str) -> None:
    """A value the backend cannot resolve is silently ignored, not rejected."""
    values = [v for v in picker_values(page_source) if v]
    assert values, "the picker offers no standard at all; the extractor matched nothing useful"

    for value in values:
        resolved = normalize_standard(value)
        assert resolved != STANDARD_UNKNOWN, (
            f"the picker offers {value!r}, which the engine does not resolve; choosing it would "
            f"fall back to the project's own standard and the screen would not say so"
        )
        assert resolved == value.upper(), (
            f"the picker offers {value!r} but the engine resolves it to {resolved}; the option "
            f"names one family and selects another"
        )


def test_the_picker_offers_every_standard_the_engine_recognises(page_source: str) -> None:
    """Recognised by the engine and absent from the list is a badge with no option."""
    offered = {normalize_standard(v) for v in picker_values(page_source) if v}
    missing = sorted(recognised_standards() - offered)
    assert missing == [], (
        f"the engine recognises {missing} and the picker does not offer them, so a project on "
        f"one of those standards sees a resolved badge it cannot select underneath"
    )


def test_the_picker_keeps_the_project_default_option(page_source: str) -> None:
    """The empty value is what sends no override at all, and it must stay first."""
    values = picker_values(page_source)
    assert values and values[0] == "", "the project-default option must be present and first"


def test_the_badge_labels_exactly_the_families_the_engine_can_return(page_source: str) -> None:
    """A token with no label falls through to a generic humaniser and reads wrong."""
    labelled = set(display_tokens(page_source))
    assert labelled == recognised_standards(), (
        f"the resolved badge labels {sorted(labelled)} and the engine can return {sorted(recognised_standards())}"
    )


def test_a_standard_dropped_from_the_page_is_reported(page_source: str) -> None:
    """The gate is not vacuous: take a family out of the page and it must notice.

    Without this, the tests above prove only that two set comparisons can come
    back equal. The doctored source removes one real option, and the extractor
    has to report a shorter list rather than the list it read a moment ago.

    The removal is done inside the matched declaration rather than on the whole
    page. A blind replace of the first ``'FIDIC', `` hits an earlier line, the
    picker comes back intact, and the control passes while proving nothing.
    """
    intact = picker_values(page_source)
    match = _PICKER_RE.search(page_source)
    assert match is not None

    body = match.group("body")
    assert body.count("'FIDIC'") == 1, "the option this control removes is not unique inside the declaration"
    doctored_body = body.replace("'FIDIC', ", "", 1)
    assert doctored_body != body, "the control doctored nothing, so it is about to prove nothing"
    doctored = page_source[: match.start()] + f"const NOTICE_STANDARDS = [{doctored_body}]" + page_source[match.end() :]

    assert picker_values(doctored) == [v for v in intact if v != "FIDIC"]
    assert recognised_standards() - {normalize_standard(v) for v in picker_values(doctored) if v} == {"FIDIC"}


def test_the_extractor_refuses_a_page_it_cannot_read() -> None:
    """A renamed literal must fail loudly rather than sweep an empty list."""
    with pytest.raises(AssertionError, match="NOTICE_STANDARDS was not found"):
        picker_values("const SOMETHING_ELSE = ['', 'FIDIC'];")
    with pytest.raises(AssertionError, match="NOTICE_STANDARD_DISPLAY was not found"):
        display_tokens("const SOMETHING_ELSE: Record<string, string> = { FIDIC: 'FIDIC' };")
