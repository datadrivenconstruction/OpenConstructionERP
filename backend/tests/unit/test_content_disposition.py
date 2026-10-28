"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A German LV name must survive the trip to the browser's save dialog.

The regression these pin: export endpoints built the header from
``name.encode("ascii", errors="replace")``, so "Bürogebäude Frankfurt
Europaviertel" reached the browser as ``B?rogeb?ude ...`` and was saved as
``B_rogeb_ude ...`` because ``?`` is illegal in a Windows filename.
"""

from urllib.parse import unquote

import pytest

from app.core.content_disposition import ascii_fallback_name, attachment_disposition


def test_umlauts_survive_in_the_utf8_parameter():
    header = attachment_disposition("Bürogebäude Frankfurt Europaviertel.X84")

    assert "filename*=UTF-8''" in header
    encoded = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == "Bürogebäude Frankfurt Europaviertel.X84"


def test_question_mark_never_reaches_the_client():
    """The old behaviour, named so it cannot come back quietly."""
    header = attachment_disposition("Bürogebäude Frankfurt Europaviertel.X84")

    assert "?" not in header.split("filename*=", 1)[0]


def test_ascii_fallback_stays_readable_rather_than_becoming_question_marks():
    assert ascii_fallback_name("Bürogebäude.X84") == "Burogebaude.X84"
    assert ascii_fallback_name("Éclairage extérieur.csv") == "Eclairage exterieur.csv"


@pytest.mark.parametrize(
    ("name", "forbidden"),
    [
        ('LV "Sonder" 2026.X84', '"'),
        ("Los 1/2 Rohbau.X84", "/"),
        ("Nord\\Süd.X84", "\\"),
        ("Was ist das?.X84", "?"),
    ],
)
def test_fallback_drops_characters_that_break_a_filename_or_the_header(name, forbidden):
    assert forbidden not in ascii_fallback_name(name)


def test_scripts_without_an_ascii_form_still_produce_a_usable_fallback():
    """Chinese has no Latin decomposition, so the fallback degrades but stays legal."""
    header = attachment_disposition("商务办公楼.X84")

    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert "?" not in fallback
    assert unquote(header.split("filename*=UTF-8''", 1)[1]) == "商务办公楼.X84"


def test_a_name_with_no_latin_form_at_all_gets_a_word_rather_than_underscores():
    header = attachment_disposition("商务办公楼")

    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert fallback == "download"
    # The extension is enough to keep the real fallback, so this only fires on
    # names that would otherwise be nothing but separators.
    assert ascii_fallback_name("商务办公楼.X84") == "_____.X84"
