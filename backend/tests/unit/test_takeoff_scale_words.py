"""A ratio on a drawing is a scale only when the sheet says so."""

from __future__ import annotations

import pytest

from app.modules.takeoff.scale_detect import detect_best_scale


def _best(text: str, **page: float) -> int | None:
    best, _ranked = detect_best_scale([{"page": 1, "text": text, **page}])
    return best.ratio if best else None


@pytest.mark.parametrize(
    "text",
    [
        "Раствор цементный 1:3",
        "Рампа 1:12",
        "Бетон 1:2:4",
        "Mortar mix 1:3",
        "Grout 1:2",
        "Mörtel 1:4",
        "Pente 1:50",
        "Ramp gradient 1:12",
        "gutter 10 m 1:80",
        "fall to outlet 1:80",
    ],
)
def test_a_mix_or_a_fall_is_no_scale(text: str) -> None:
    assert _best(text) is None


def test_a_mix_does_not_beat_the_scale() -> None:
    assert _best("Раствор цементный 1:3\nМасштаб 1:100") == 100
    assert _best("Масштаб 1:100\nРампа 1:12") == 100


@pytest.mark.parametrize(
    ("text", "ratio"),
    [
        ("M 1:100", 100),
        ("М 1:50", 50),
        ("E 1:50", 50),
        ("SCALE 1:200", 200),
        ("Maßstab 1:50", 50),
        ("Масштаб: 1:25", 25),
        ("縮尺1:100", 100),
        ("Scale\n1:50", 50),
    ],
)
def test_a_scale_word_or_initial_names_the_scale(text: str, ratio: int) -> None:
    assert _best(text) == ratio


def test_a_word_only_contains_the_keyword() -> None:
    # "escalator" holds "escala" and "scala"; a bare odd ratio stays below the bar.
    best, ranked = detect_best_scale([{"page": 1, "text": "Escalator 1:37"}])
    assert best is None or not best.detail.get("near_keyword")
    assert all(not c.detail.get("near_keyword") for c in ranked)


def test_a_tag_glued_to_a_digit_is_not_part_of_the_measure() -> None:
    assert _best('TYPE A1 1/4" = 1\'-0"') == 48


def test_a_mixed_fraction_is_still_read() -> None:
    assert _best('1 1/2" = 1\'-0"') == 8


def test_the_main_drawing_is_the_smallest_scale_on_the_sheet() -> None:
    assert _best('UNIT PLAN 1/4" = 1\'-0"\nJAMB 3" = 1\'-0"\n1 1/2" = 1\'-0"') == 48


def test_a_detail_callout_does_not_set_the_sheet_scale() -> None:
    assert _best('DETAIL 3" = 1\'-0"\nFLOOR 1/8" = 1\'-0"') == 96


def test_a_detail_alone_still_answers() -> None:
    assert _best("Detail scale 1:1") == 1


def test_a_scale_stated_for_another_paper_is_read_on_this_one() -> None:
    a3 = {"width_pt": 1190.6, "height_pt": 841.9}
    a1 = {"width_pt": 2384.0, "height_pt": 1684.0}
    assert _best("Scale 1:100 @ A1", **a3) == 200
    assert _best("Scale 1:100 @ A1", **a1) == 100
    assert _best("Scale 1:100 @ A1") == 100
    assert _best("Scale 1:100 @ A1", width_pt=1000.0, height_pt=500.0) == 100


def test_table_text_is_not_read_twice_and_the_paper_size_comes_along(tmp_path) -> None:
    pytest.importorskip("pdfplumber")
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A3
    from reportlab.pdfgen import canvas

    from app.modules.takeoff.pdf_extract_worker import extract_pdf_data

    path = tmp_path / "table.pdf"
    c = canvas.Canvas(str(path), pagesize=A3)
    c.grid([100, 200, 300], [500, 540, 580])
    c.drawString(110, 550, "Masonry")
    c.drawString(210, 550, "Mortar")
    c.drawString(110, 510, "Render")
    c.drawString(210, 510, "Gypsum")
    c.save()
    page = extract_pdf_data(str(path))["pages"][0]
    assert page["text"].count("Masonry") == 1
    assert page["width_pt"] == pytest.approx(A3[0])
    assert page["height_pt"] == pytest.approx(A3[1])
