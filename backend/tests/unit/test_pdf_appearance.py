# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Document appearance: the stored look of every generated PDF.

The test that matters most here is :func:`test_the_defaults_are_what_the_consumers_had_hard_coded`.
Making the look configurable meant lifting values out of the modules that drew
with them, and the whole promise of that change is that a workspace which never
opens the settings page gets the same document it got before. That promise is
kept by four numbers agreeing, and nothing else in the codebase checks that they
still do - so a well-meaning tidy-up of a default here would silently restyle
every contract, receipt and certificate in every deployment.
"""

from __future__ import annotations

import json

import pytest

from app.core.pdf_appearance import (
    DEFAULT_APPEARANCE,
    LOGO_ALIGNMENTS,
    MAX_FONT_SIZE,
    MAX_FOOTER_TEXT,
    MAX_MARGIN_MM,
    MIN_FONT_SIZE,
    MIN_MARGIN_MM,
    PAGE_SIZES,
    appearance_path,
    read_appearance,
    reset_appearance,
    resolve_page_size,
    sanitise,
    write_appearance,
)


def test_the_defaults_are_what_the_consumers_had_hard_coded() -> None:
    """An untouched workspace must render exactly what it rendered before.

    Each assertion pins one default against the module that used to own it as a
    literal. If someone changes a default here, this fails and names the
    consumer whose output would have moved.
    """
    from app.core import pdf_branding
    from app.modules.property_dev import document_templates

    assert DEFAULT_APPEARANCE["accent_color"] == pdf_branding._HEADER_COLOR.lower()
    assert DEFAULT_APPEARANCE["footer_color"] == pdf_branding._FOOTER_COLOR.lower()
    assert DEFAULT_APPEARANCE["margin_mm"] == document_templates.PAGE_MARGIN_MM
    # The generator's body style was 10 pt, and _styles scales the whole family
    # by base_font_size / 10, so this default is the identity scale.
    assert DEFAULT_APPEARANCE["base_font_size"] == 10
    assert document_templates._base_font_size() == 10.0
    # branded_header_footer has always drawn the logo at the left margin.
    assert DEFAULT_APPEARANCE["logo_align"] == "left"


def test_an_unset_workspace_reads_the_defaults(tmp_path) -> None:
    assert read_appearance(tmp_path) == DEFAULT_APPEARANCE


def test_a_saved_appearance_survives_a_read(tmp_path) -> None:
    written = write_appearance(
        {
            "accent_color": "#B22222",
            "footer_color": "#333",
            "base_font_size": 12,
            "page_size": "letter",
            "margin_mm": 15,
            "logo_align": "center",
            "footer_text": "  Acme Developments Ltd  ",
            "show_page_numbers": False,
        },
        tmp_path,
    )
    assert written["accent_color"] == "#b22222"
    assert written["page_size"] == "LETTER"
    assert written["footer_text"] == "Acme Developments Ltd"
    assert read_appearance(tmp_path) == written


def test_the_cache_notices_a_second_save(tmp_path) -> None:
    """The read is cached by mtime, so an admin's second save must still land.

    A cache keyed only by path would serve the first save forever, and the
    symptom would be a settings page that saves successfully and changes
    nothing.
    """
    write_appearance({"accent_color": "#111111"}, tmp_path)
    assert read_appearance(tmp_path)["accent_color"] == "#111111"
    path = appearance_path(tmp_path)
    path.write_text(json.dumps({"accent_color": "#222222"}), encoding="utf-8")
    # Force a distinct mtime: a same-nanosecond rewrite is not what an admin
    # save looks like, and pinning it here would test the clock, not the cache.
    stat = path.stat()
    import os

    os.utime(path, ns=(stat.st_atime_ns + 10**9, stat.st_mtime_ns + 10**9))
    assert read_appearance(tmp_path)["accent_color"] == "#222222"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("accent_color", "red"),
        ("accent_color", "#12345"),
        ("accent_color", None),
        ("footer_color", "rgb(1,2,3)"),
        ("page_size", "A3"),
        ("logo_align", "middle"),
        ("base_font_size", "large"),
        ("base_font_size", True),
        ("margin_mm", None),
        ("show_page_numbers", "yes"),
        ("show_letterhead", "no"),
        ("show_letterhead", 0),
    ],
)
def test_one_bad_value_costs_only_that_value(field: str, value: object) -> None:
    """A rejected field falls back alone; the rest of the payload survives.

    The alternative - discarding the whole payload - would mean a workspace
    losing its accent colour because it also sent a page size the build no
    longer offers.
    """
    payload = dict(DEFAULT_APPEARANCE)
    payload["accent_color"] = "#abcdef"
    payload["footer_text"] = "kept"
    payload[field] = value

    clean = sanitise(payload)

    assert clean[field] == DEFAULT_APPEARANCE[field]
    assert clean["footer_text"] == "kept"
    if field != "accent_color":
        assert clean["accent_color"] == "#abcdef"


@pytest.mark.parametrize(
    ("field", "sent", "expected"),
    [
        ("base_font_size", MIN_FONT_SIZE - 5, MIN_FONT_SIZE),
        ("base_font_size", MAX_FONT_SIZE + 50, MAX_FONT_SIZE),
        ("margin_mm", MIN_MARGIN_MM - 100, MIN_MARGIN_MM),
        ("margin_mm", MAX_MARGIN_MM + 1, MAX_MARGIN_MM),
    ],
)
def test_sizes_are_clamped_not_rejected(field: str, sent: int, expected: int) -> None:
    """Out of range means "as close as we allow", not "back to default".

    A slider dragged past the end should stop at the end. Snapping back to the
    default instead reads as the control being broken.
    """
    assert sanitise({field: sent})[field] == expected


def test_a_long_footer_is_trimmed_not_refused() -> None:
    clean = sanitise({"footer_text": "x" * (MAX_FOOTER_TEXT + 40)})
    assert len(clean["footer_text"]) == MAX_FOOTER_TEXT


@pytest.mark.parametrize("junk", [None, "", 7, [], "not a dict"])
def test_corrupt_input_reads_as_the_default(junk: object) -> None:
    assert sanitise(junk) == DEFAULT_APPEARANCE


def test_a_corrupt_file_never_raises(tmp_path) -> None:
    """A hand-edited file must cost the customisation, not the export."""
    appearance_path(tmp_path).write_text("{ this is not json", encoding="utf-8")
    assert read_appearance(tmp_path) == DEFAULT_APPEARANCE


def test_saving_the_platform_look_removes_the_file(tmp_path) -> None:
    """Storing "same as default" would freeze today's defaults into the file.

    A workspace that reset itself would then keep the old look after a platform
    restyle, which is the opposite of what resetting means.
    """
    write_appearance({"accent_color": "#123456"}, tmp_path)
    assert appearance_path(tmp_path).exists()
    write_appearance(dict(DEFAULT_APPEARANCE), tmp_path)
    assert not appearance_path(tmp_path).exists()
    assert read_appearance(tmp_path) == DEFAULT_APPEARANCE


def test_turning_the_letterhead_off_is_stored_and_on_is_the_default(tmp_path) -> None:
    """Off is a customisation and must be written; on is the default and must not.

    On by default is what keeps an upgrade invisible: with no company profile
    there is no letterhead to draw, so the flag changes nothing until a firm
    fills the profile in. A file that also predates the flag reads as on.
    """
    write_appearance({"show_letterhead": False}, tmp_path)
    assert appearance_path(tmp_path).exists()
    assert read_appearance(tmp_path)["show_letterhead"] is False

    write_appearance({"show_letterhead": True}, tmp_path)
    assert not appearance_path(tmp_path).exists()

    appearance_path(tmp_path).write_text(json.dumps({"accent_color": "#123456"}), encoding="utf-8")
    assert read_appearance(tmp_path)["show_letterhead"] is True


def test_reset_is_safe_when_nothing_was_saved(tmp_path) -> None:
    assert reset_appearance(tmp_path) == DEFAULT_APPEARANCE


@pytest.mark.parametrize("name", list(PAGE_SIZES))
def test_every_offered_page_size_resolves_to_a_real_size(name: str) -> None:
    width, height = resolve_page_size({"page_size": name})
    assert width > 0 and height > width


def test_an_unknown_page_size_resolves_to_the_default() -> None:
    assert resolve_page_size({"page_size": "A0"}) == PAGE_SIZES[DEFAULT_APPEARANCE["page_size"]]


def test_the_offered_choices_are_all_accepted_by_the_sanitiser() -> None:
    """Whatever the options endpoint advertises, the sanitiser must keep.

    These two lists are what the settings form is built from. If the form can
    offer a value the sanitiser discards, the control silently does nothing -
    the failure this pairing exists to prevent.
    """
    for name in PAGE_SIZES:
        assert sanitise({"page_size": name})["page_size"] == name
    for align in LOGO_ALIGNMENTS:
        assert sanitise({"logo_align": align})["logo_align"] == align
