"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The diacritics gate must not ask for an accented email address.

A stripped spelling is correct inside an email address and wrong in a display
string, and the demo packs carry both on the same line for the same firm:

    ("Kurpfalz Kältetechnik GmbH", "vergabe@kurpfalz-kaelte.de", ...)

Before the exemption the gate reported all twenty-nine addresses in the packs and
instructed the reader to write the accented form. Following that instruction
breaks every one of the addresses, and the gate then goes green. That is the
failure this file exists to prevent, so the controls matter more than the
positive case: a test that only checks an address is ignored would also pass
against a gate that had been switched off.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[3] / "scripts" / "check_seed_diacritics.py"


def _gate():
    spec = importlib.util.spec_from_file_location("check_seed_diacritics", GATE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _gate()


def test_the_gate_script_is_where_this_test_thinks_it_is() -> None:
    # Resolving the script by relative path is the one way this file can pass
    # while testing nothing, so it is asserted rather than assumed.
    assert GATE.is_file(), f"gate script not found at {GATE}"


# ── The positive case: a real regression is still caught ────────────────────
@pytest.mark.parametrize(
    ("literal", "bad"),
    [
        # Spelled out rather than derived from the literal. The gate matches on
        # letter boundaries, so "kaelte" does not match inside "kaeltetechnik" -
        # the denylist carries those as two entries - and a test that guesses
        # which entry applies tests its own guess.
        ('"Kurpfalz Kaeltetechnik GmbH"', "kaeltetechnik"),
        ('"Sueddeutsche Lebensmittelmaerkte GmbH"', "sueddeutsche"),
        ('"Sueddeutsche Lebensmittelmaerkte GmbH"', "lebensmittelmaerkte"),
        ('"Tiefbau Bergstrasse GmbH"', "bergstrasse"),
        ('"Gruenbau Kraichgau GmbH"', "gruenbau"),
    ],
)
def test_a_stripped_spelling_in_a_display_string_is_reported(literal: str, bad: str) -> None:
    assert gate.outside_addresses(literal.lower(), bad) is True


# ── The exemption itself ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("literal", "bad"),
    [
        ('"vergabe@kurpfalz-kaelte.de"', "kaelte"),
        ('"angebote@rn-kuehlanlagen.de"', "kuehlanlagen"),
        ('"vergabe@tiefbau-bergstrasse.de"', "bergstrasse"),
        ('"t.gerlach@sueddeutsche-lebensmittelmaerkte.example"', "lebensmittelmaerkte"),
        ('"kontakt@pruefingenieur-mahler.example"', "pruefingenieur"),
    ],
)
def test_a_stripped_spelling_inside_an_address_is_not_reported(literal: str, bad: str) -> None:
    assert gate.outside_addresses(literal.lower(), bad) is False


# ── The control that matters: one exempt hit must not excuse a real one ─────
def test_an_address_on_the_line_does_not_excuse_a_display_string_beside_it() -> None:
    """The shape the packs actually use, with the display name broken too.

    If the exemption were written per literal rather than per occurrence, the
    address would swallow the whole line and this regression would ship. That is
    the single most likely way to get this wrong, so it is pinned here rather
    than left to the parametrised cases above, none of which can see it.
    """
    line = '("Kurpfalz Kaelte GmbH", "vergabe@kurpfalz-kaelte.de", 0.5)'
    assert gate.outside_addresses(line.lower(), "kaelte") is True


def test_the_correct_shipped_shape_is_silent() -> None:
    """The same line as the packs actually write it: accented name, ASCII address."""
    line = '("Kurpfalz Kältetechnik GmbH", "vergabe@kurpfalz-kaelte.de", 0.5)'
    assert gate.outside_addresses(line.lower(), "kaelte") is False


# ── Not-an-address must stay unexempt ───────────────────────────────────────
@pytest.mark.parametrize(
    "literal",
    [
        '"Maengelliste kaelte Rohbau"',  # bare words
        '"kaelte@"',  # an at sign is not an address
        '"kaelte.de"',  # a bare hostname is deliberately not exempt yet
    ],
)
def test_things_that_are_not_addresses_are_not_exempt(literal: str) -> None:
    assert gate.outside_addresses(literal.lower(), "kaelte") is True


# ── The shipped tree ────────────────────────────────────────────────────────
def test_the_shipped_packs_pass_the_gate(capsys: pytest.CaptureFixture[str]) -> None:
    """Exit 0 over the real denylist, which is what the lane will see.

    This is the assertion that would have failed all day before the exemption,
    with twenty-nine addresses reported as broken German.
    """
    assert gate.main([]) == 0
    out = capsys.readouterr()
    assert "file(s) scanned against" in out.out
    # A pass over nothing scanned reads exactly like a pass over eleven files.
    scanned = int(out.out.split("seed diacritics: ")[1].split(" file")[0])
    assert scanned > 0, "the gate passed without scanning anything"
