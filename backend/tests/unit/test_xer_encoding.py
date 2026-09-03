# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A P6 export never says which code page it is in, so we have to be right anyway.

The defect these tests pin is not a crash. Decoding a cp1256 export as Latin-1
raises nothing, logs nothing and stores every Arabic activity name as mojibake,
so the only evidence is on the Gantt chart weeks later. A test that merely
asserts "the import succeeded" is exactly the test that was already passing.

Every language case therefore asserts the round trip: bytes encoded in a real
code page come back as the string that went in. And two cases go the other way,
because a decoder that answered "Arabic" to everything would satisfy the four
language tests on its own: a Western file has to stay Western, and text that is
valid UTF-8 has to stay UTF-8.
"""

from __future__ import annotations

import pytest

from app.modules.schedule.xer_encoding import decode_xer, sniff_code_page

# Construction vocabulary rather than lorem, because the sniff weighs letter
# frequency and a pangram or a proper noun is not what a schedule contains.
ARABIC = "الصالة المغطاة نادي الصيد حفر حتى منسوب التأسيس اعمال الخرسانة المسلحة"
RUSSIAN = "Разработка грунта в отвал устройство монолитных железобетонных фундаментов"
GREEK = "Εκσκαφη θεμελιων και κατασκευη οπλισμενου σκυροδεματος για τα θεμελια"
HEBREW = "חפירה ליסודות ויציקת בטון מזוין עבור היסודות של המבנה החדש וקירות המרתף"

LANGUAGES = [
    pytest.param(ARABIC, "cp1256", id="arabic-cp1256"),
    pytest.param(RUSSIAN, "cp1251", id="russian-cp1251"),
    pytest.param(GREEK, "cp1253", id="greek-cp1253"),
    pytest.param(HEBREW, "cp1255", id="hebrew-cp1255"),
]


def _xer(names: list[str]) -> str:
    """The smallest XER that carries activity names, shaped as P6 writes one."""
    header = "ERMHDR\t5.0\t2012-01-26\tProject\tadmin\tAdmin\tdbxDatabaseNoName\tProject Management\tEGP\n"
    rows = "".join(f"%R\t{100 + i}\t1\t10\tA{1000 + i}\t{name}\tTT_Task\tTK_NotStart\n" for i, name in enumerate(names))
    return (
        header
        + "%T\tPROJECT\n%F\tproj_id\tproj_short_name\n%R\t1\tHALL\n"
        + "%T\tTASK\n%F\ttask_id\tproj_id\twbs_id\ttask_code\ttask_name\ttask_type\tstatus_code\n"
        + rows
        + "%E\n"
    )


@pytest.mark.parametrize(("text", "page"), LANGUAGES)
def test_a_non_western_export_comes_back_as_what_was_exported(text: str, page: str) -> None:
    """The whole defect in one line: these names used to arrive as mojibake."""
    decoded, used = decode_xer(_xer([text]).encode(page))
    assert used == page
    assert text in decoded


@pytest.mark.parametrize(("text", "page"), LANGUAGES)
def test_the_old_ladder_really_did_corrupt_these_files(text: str, page: str) -> None:
    """Without this, the tests above could be passing over a defect that never
    existed. Latin-1 accepts every byte, so the old path produced a string
    rather than an error, and that string is not the one that was exported."""
    raw = _xer([text]).encode(page)
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert text not in raw.decode("latin-1")


def test_a_western_export_is_read_as_cp1252_not_latin1() -> None:
    """P6's Western default is cp1252, and the difference is not cosmetic: the
    0x80-0x9F range holds the curly quotes and the en dash, which Latin-1 maps
    onto C1 control characters. The name would import with invisible bytes in
    it and compare unequal to the same name typed by hand."""
    text = "Crane Operator ’Day Shift’ – 12h €450"
    decoded, used = decode_xer(_xer([text]).encode("cp1252"))
    assert used == "cp1252"
    assert text in decoded
    assert not any(0x80 <= ord(ch) <= 0x9F for ch in decoded), "C1 control characters reached the name"


def test_western_accents_are_not_mistaken_for_another_script() -> None:
    """The direction that a four-way vote gets wrong if nothing guards it. These
    are Latin letters that happen to be high bytes, and they arrive alone
    between ASCII rather than in runs."""
    text = "Façade béton armé préfabriqué, Straße, Größe, Prüfung, Maßnahme, Außenwand"
    raw = _xer([text]).encode("cp1252")
    assert sniff_code_page(raw) is None
    decoded, used = decode_xer(raw)
    assert used == "cp1252"
    assert text in decoded


def test_utf8_wins_before_anything_is_sniffed() -> None:
    """A modern export can be UTF-8, and its bytes are also decodable as several
    of the candidate pages. Strict UTF-8 sits above the sniff for that reason."""
    decoded, used = decode_xer(_xer([ARABIC]).encode("utf-8"))
    assert used == "utf-8"
    assert ARABIC in decoded


def test_a_byte_order_mark_is_not_left_in_the_first_field() -> None:
    """utf-8 alone decodes a BOM into a zero-width character that survives into
    the first cell of the header row, where it is invisible and breaks an
    equality check on ERMHDR."""
    decoded, used = decode_xer(_xer([ARABIC]).encode("utf-8-sig"))
    assert used == "utf-8-sig"
    assert decoded.startswith("ERMHDR")


def test_an_ascii_only_file_provokes_no_opinion() -> None:
    """Nothing to go on is a valid answer, and it has to be distinguishable from
    a confident one or the caller cannot choose a default."""
    assert sniff_code_page(_xer(["Excavate to foundation level"]).encode("ascii")) is None


def test_an_undefined_cp1252_byte_still_yields_text() -> None:
    """cp1252 leaves five bytes undefined, so it is not a floor. Latin-1 defines
    all 256 and is, which is the only reason it is still in the ladder."""
    raw = _xer(["Section"]).encode("ascii") + b"\x81\x8d\x8f\x90\x9d\n"
    decoded, used = decode_xer(raw)
    assert used == "latin-1"
    assert "ERMHDR" in decoded


@pytest.mark.parametrize(("text", "page"), LANGUAGES)
def test_the_sniff_names_the_page_and_not_merely_some_page(text: str, page: str) -> None:
    """Four languages against four candidates, so a decoder that always answered
    the same page would fail three of these rather than pass by luck."""
    assert sniff_code_page(_xer([text]).encode(page)) == page


# ── Too little evidence to have an opinion about ──────────────────────────────
#
# The tests above hand the sniff a whole vocabulary. The tests below hand it one
# short activity name, which is the shape that carries almost no evidence, and
# ask it to decline rather than guess. With five high bytes on the table every
# score is a multiple of 0.2, so a meaningless lead clears the margin.
#
# Three of the four named a wrong page before the floor existed. Arabic did not:
# its short names were already being declined, so that case pins the property
# rather than catching the regression, and the sweep below is what covers Arabic.
#
# Declining is not a worse answer than the old one. cp1252 is where these files
# already went, so the floor takes away a wrong claim rather than a right one.

SHORT_NAMES = [
    pytest.param("حفر حتى منسوب", "cp1256", id="arabic-short"),
    pytest.param("Разработка грунта", "cp1251", id="russian-short"),
    pytest.param("Εκσκαφη θεμελιων", "cp1253", id="greek-short"),
    pytest.param("בטון מזוין", "cp1255", id="hebrew-short"),
]


@pytest.mark.parametrize(("text", "page"), SHORT_NAMES)
def test_one_short_name_is_declined_rather_than_guessed(text: str, page: str) -> None:
    """Silence is the only honest answer to two words, and the route puts the
    page it used in front of the person importing, so a guess here is not an
    internal detail: it is a false statement about the file they are holding."""
    raw = _xer([text]).encode(page)
    assert sniff_code_page(raw) is None
    _decoded, used = decode_xer(raw)
    assert used == "cp1252", "declining must fall to the Western default, not to a guess"


def test_no_short_name_in_any_language_is_assigned_the_wrong_page() -> None:
    """The property the floor exists for, rather than four examples of it.

    Every window of two to thirty characters cut from the four vocabularies is a
    name a schedule could plausibly carry, which is several thousand of them. The
    sniff may decline any window it likes. It must never name a page the bytes
    were not written in.

    The control in the same loop is what keeps this from passing trivially: a
    sniff broken into answering ``None`` to everything would satisfy the sweep
    and fail the first assertion.
    """
    wrong: list[tuple[str, str, str]] = []
    windows = 0
    for text, page in [(ARABIC, "cp1256"), (RUSSIAN, "cp1251"), (GREEK, "cp1253"), (HEBREW, "cp1255")]:
        assert sniff_code_page(_xer([text]).encode(page)) == page, "a whole export must still be named"
        for start in range(len(text)):
            for length in range(2, 31):
                name = text[start : start + length].strip()
                if len(name) < 2:
                    continue
                windows += 1
                got = sniff_code_page(_xer([name]).encode(page))
                if got is not None and got != page:
                    wrong.append((page, got, name))
    assert windows > 5000, f"the sweep collapsed to {windows} windows and stopped being a population"
    assert not wrong, f"{len(wrong)} of {windows} names were given a page they were not written in: {wrong[:3]}"


# ── MSPDI, the same defect reached by the opposite route ──────────────────────
#
# The XER half of this file exists because a P6 export declares nothing. MSPDI
# declares its encoding in the XML declaration, so it needs no sniffing at all;
# it needed only to stop being decoded before the parser saw it. These two tests
# pin the property that makes the one-line fix correct, because the property is
# in ElementTree rather than in our code and could change under us.


def _mspdi(name: str) -> str:
    return (
        '<?xml version="1.0" encoding="windows-1256"?>'
        '<Project xmlns="http://schemas.microsoft.com/project">'
        f"<Name>{name}</Name></Project>"
    )


def test_a_declared_encoding_is_honoured_when_the_parser_is_given_bytes() -> None:
    import defusedxml.ElementTree as safe_ET

    raw = _mspdi(ARABIC).encode("cp1256")
    root = safe_ET.fromstring(raw)
    assert root.findtext("{http://schemas.microsoft.com/project}Name") == ARABIC


def test_decoding_first_throws_the_declaration_away() -> None:
    """Why the fix is to delete a step rather than to add one. Once the bytes
    are a str the declaration cannot be acted on, so it is ignored in silence
    and the document parses perfectly into the wrong names."""
    import defusedxml.ElementTree as safe_ET

    raw = _mspdi(ARABIC).encode("cp1256")
    root = safe_ET.fromstring(raw.decode("latin-1"))
    assert root.findtext("{http://schemas.microsoft.com/project}Name") != ARABIC
