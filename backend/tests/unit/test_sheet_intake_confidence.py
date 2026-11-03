# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DB-free tests: confidence of a title block read, the OCR crop, and the ``sheet_intake`` rules.

pytesseract is never installed in CI, so it is replaced by a fake module wherever
the OCR path runs.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import is_key_present
from app.core.validation.rules import (
    SheetLowConfidenceUnconfirmed,
    SheetNumberPresent,
    SheetNumberUniqueInSet,
    SheetRevisionNotLowerThanCurrent,
    register_builtin_rules,
)
from app.modules.documents import service as documents_service
from app.modules.documents import sheet_ocr
from app.modules.documents.sheet_fields import REVIEW_THRESHOLD, score_fields
from app.modules.documents.sheet_ocr import OcrUnavailable

# ── score_fields ────────────────────────────────────────────────────────────

FULL = {"sheet_number": "A-101", "sheet_title": "Plan", "revision": "B", "discipline": "Architectural"}


def test_a_complete_text_layer_read_is_trusted_but_never_certain() -> None:
    assert score_fields(FULL, "text") == pytest.approx(0.9)
    assert score_fields(FULL, "text") >= REVIEW_THRESHOLD


def test_a_bare_number_from_a_text_layer_is_below_the_threshold() -> None:
    fields = {"sheet_number": "A-101", "discipline": "Architectural"}
    assert score_fields(fields, "text") < REVIEW_THRESHOLD


def test_a_number_with_a_revision_or_a_title_is_trusted() -> None:
    assert score_fields({"sheet_number": "A-101", "revision": "B"}, "text") >= REVIEW_THRESHOLD
    assert score_fields({"sheet_number": "A-101", "sheet_title": "Plan"}, "text") >= REVIEW_THRESHOLD


def test_a_missing_number_caps_the_score_at_point_four() -> None:
    fields = {**FULL, "sheet_number": None}
    assert score_fields(fields, "text") <= 0.4


def test_an_ocr_read_is_capped_by_the_recogniser_confidence() -> None:
    assert score_fields(FULL, "ocr", 0.72) == pytest.approx(0.72)
    assert score_fields(FULL, "ocr", 0.99) == pytest.approx(0.9)
    assert score_fields(FULL, "ocr", None) == 0.0


# ── extraction block ────────────────────────────────────────────────────────


def test_every_ocr_read_needs_review_however_confident() -> None:
    block = documents_service._extraction("ocr", 0.9, None)
    assert block["needs_review"] is True
    assert block["reason"] == "ocr_read"


def test_a_confident_text_read_needs_no_review() -> None:
    block = documents_service._extraction("text", 0.9, None)
    assert block == {"source": "text", "confidence": 0.9, "needs_review": False, "reason": None}


def test_a_weak_text_read_is_low_confidence() -> None:
    block = documents_service._extraction("text", 0.54, None)
    assert block["needs_review"] is True
    assert block["reason"] == "low_confidence"


# ── OCR of the title block crop ─────────────────────────────────────────────


def test_mean_confidence_ignores_negative_and_empty_words() -> None:
    data = {
        "text": ["", "SHEET", "NO:", "A-101", "noise"],
        "conf": ["-1", "80", "60", "70", "-1"],
        "block_num": [1, 1, 1, 1, 1],
        "par_num": [1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 1, 2],
    }
    text, conf = sheet_ocr.mean_confidence(data)
    assert text == "SHEET NO: A-101"
    assert conf == pytest.approx(0.7)


def test_no_recognised_word_reads_as_zero_confidence() -> None:
    assert sheet_ocr.mean_confidence({"text": [""], "conf": ["-1"]}) == ("", 0.0)


def _scan_pdf(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (800, 1000), "white").save(str(path), format="PDF", resolution=100)


def _fake_tesseract(monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]) -> None:
    module = types.ModuleType("pytesseract")
    module.Output = types.SimpleNamespace(DICT="dict")

    def image_to_data(image: Any, lang: str = "eng", output_type: Any = None) -> dict[str, list[Any]]:
        seen["size"] = image.size
        seen["lang"] = lang
        return {
            "text": ["SHEET", "NO:", "A-101"],
            "conf": ["72", "72", "72"],
            "block_num": [1, 1, 1],
            "par_num": [1, 1, 1],
            "line_num": [1, 1, 1],
        }

    module.image_to_data = image_to_data
    module.get_languages = lambda config="": ["eng", "deu"]
    monkeypatch.setitem(sys.modules, "pytesseract", module)


def test_ocr_reads_only_the_bottom_right_crop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    pdf = tmp_path / "scan.pdf"
    _scan_pdf(pdf)
    seen: dict[str, Any] = {}
    _fake_tesseract(monkeypatch, seen)

    text, conf = sheet_ocr.ocr_title_block(pdf, 0, ["eng"])

    assert (text, conf) == ("SHEET NO: A-101", pytest.approx(0.72))
    # 800x1000 px at 100 dpi is 576x720 pt; the crop is its right half and bottom 45% at 200 dpi.
    width, height = seen["size"]
    assert 0.45 * 576 * 200 / 72 - 3 <= width <= 0.5 * 576 * 200 / 72 + 3
    assert 0.45 * 720 * 200 / 72 - 3 <= height <= 0.45 * 720 * 200 / 72 + 3
    assert seen["lang"] == "eng"


def test_ocr_without_pytesseract_is_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(OcrUnavailable):
        sheet_ocr.ocr_title_block(pdf, 0)


def test_ocr_stops_at_the_page_cap(tmp_path: Path) -> None:
    with pytest.raises(OcrUnavailable):
        sheet_ocr.ocr_title_block(tmp_path / "x.pdf", sheet_ocr.MAX_OCR_PAGES)


# ── a scanned page through the page reader ──────────────────────────────────


class _EmptyPage:
    """A pdfplumber page with no text layer."""

    chars: list[dict[str, Any]] = []
    bbox = (0, 0, 100, 100)

    def extract_text(self) -> str:
        return ""


def test_a_scan_is_read_by_ocr_and_held(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[int] = []

    def fake_ocr(path: Path, index: int, langs: Any = None, render_lock: Any = None) -> tuple[str, float]:
        calls.append(index)
        return "SHEET NO: A-101\nSHEET TITLE: Floor Plan\nREV B", 0.72

    monkeypatch.setattr(documents_service, "ocr_title_block", fake_ocr)
    fields = documents_service._page_fields(_EmptyPage(), None, tmp_path / "x.pdf", 3)

    assert calls == [3]
    assert fields["sheet_number"] == "A-101"
    assert fields["extraction"]["source"] == "ocr"
    assert fields["extraction"]["confidence"] == pytest.approx(0.72)
    assert fields["extraction"]["needs_review"] is True


def test_a_scan_without_ocr_is_kept_and_flagged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def no_ocr(*args: Any, **kwargs: Any) -> tuple[str, float]:
        raise OcrUnavailable("no tesseract")

    monkeypatch.setattr(documents_service, "ocr_title_block", no_ocr)
    fields = documents_service._page_fields(_EmptyPage(), None, tmp_path / "x.pdf", 0)

    assert fields["extraction"] == {
        "source": "ocr",
        "confidence": 0.0,
        "needs_review": True,
        "reason": "ocr_unavailable",
    }
    assert fields["sheet_number"] is None


class _TextPage(_EmptyPage):
    def extract_text(self) -> str:
        return "SHEET NO: A-101\nSHEET TITLE: Floor Plan\nREV B\nDATE: 2025-03-12\nSCALE: 1:100"


def test_a_text_layer_never_calls_ocr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*args: Any, **kwargs: Any) -> tuple[str, float]:
        raise AssertionError("OCR must not run for a page with text")

    monkeypatch.setattr(documents_service, "ocr_title_block", boom)
    fields = documents_service._page_fields(_TextPage(), None, tmp_path / "x.pdf", 0)

    assert fields["sheet_number"] == "A-101"
    assert fields["extraction"]["source"] == "text"
    assert fields["extraction"]["needs_review"] is False


# ── sheet_intake rules ──────────────────────────────────────────────────────


def _run(rule: Any, sheets: list[dict[str, Any]]) -> list[Any]:
    import asyncio

    ctx = ValidationContext(data={"sheets": sheets}, metadata={"locale": "en"})
    return asyncio.run(rule.validate(ctx))


def _sheet(id_: str = "s1", number: str | None = "A-101", revision: str | None = "B", **extra: Any) -> dict[str, Any]:
    return {"id": id_, "document_id": "d1", "page_number": 1, "sheet_number": number, "revision": revision, **extra}


def test_the_rules_are_registered_as_one_rule_set() -> None:
    register_builtin_rules()
    ids = {r["rule_id"] for r in rule_registry.list_rules("sheet_intake")}
    assert ids == {
        "sheet.number_present",
        "sheet.number_unique_in_set",
        "sheet.revision_not_lower_than_current",
        "sheet.low_confidence_unconfirmed",
    }
    for key in ("number_present", "number_unique_in_set", "revision_not_lower", "low_confidence_unconfirmed"):
        for part in ("fail", "suggestion"):
            assert is_key_present(f"sheet_intake.{key}.{part}", "en")


def test_number_present_flags_a_blank_number_as_an_error() -> None:
    bad = _run(SheetNumberPresent(), [_sheet("s1", None), _sheet("s2", "  ")])
    assert [r.passed for r in bad] == [False, False]
    assert bad[0].severity == Severity.ERROR
    good = _run(SheetNumberPresent(), [_sheet()])
    assert [r.passed for r in good] == [True]


def test_number_unique_flags_the_same_number_and_revision_twice_in_one_upload() -> None:
    sheets = [_sheet("s1", "A-101", "B", page_number=1), _sheet("s2", "A101", "b", page_number=4)]
    bad = _run(SheetNumberUniqueInSet(), sheets)
    assert len(bad) == 1 and bad[0].passed is False and bad[0].element_ref == "s2"
    assert bad[0].severity == Severity.ERROR
    assert "pages 1 and 4" in bad[0].message


def test_number_unique_allows_other_revisions_and_other_uploads() -> None:
    sheets = [
        _sheet("s1", "A-101", "B"),
        _sheet("s2", "A-101", "C"),
        {**_sheet("s3", "A-101", "B"), "document_id": "d2"},
    ]
    assert [r.passed for r in _run(SheetNumberUniqueInSet(), sheets)] == [True]


def test_a_held_sheet_older_than_the_current_one_is_a_warning() -> None:
    bad = _run(SheetRevisionNotLowerThanCurrent(), [_sheet("s1", revision="B", current_revisions=["D"])])
    assert bad[0].passed is False and bad[0].severity == Severity.WARNING


def test_a_held_sheet_newer_than_the_current_one_passes() -> None:
    ok = _run(SheetRevisionNotLowerThanCurrent(), [_sheet("s1", revision="E", current_revisions=["D"])])
    assert [r.passed for r in ok] == [True]
    # Not comparable labels are not claimed to be lower.
    assert [
        r.passed for r in _run(SheetRevisionNotLowerThanCurrent(), [_sheet(revision="02", current_revisions=["B"])])
    ] == [True]


def test_an_unconfirmed_machine_read_is_a_warning_and_a_confirmed_one_is_not() -> None:
    held = _sheet("s1", needs_review=True, confidence=0.72)
    done = _sheet("s2", needs_review=False, confidence=0.95)
    results = _run(SheetLowConfidenceUnconfirmed(), [held, done])
    assert len(results) == 1 and results[0].passed is False and results[0].severity == Severity.WARNING
    assert "72%" in results[0].message
    assert [r.passed for r in _run(SheetLowConfidenceUnconfirmed(), [done])] == [True]


def test_confirm_request_maps_the_form_names_to_sheet_columns() -> None:
    from app.modules.documents.schemas import SheetConfirmRequest

    changes = SheetConfirmRequest(number=" A-102 ", title="", revision="C").changes()
    assert changes.model_dump(exclude_unset=True) == {"sheet_number": "A-102", "revision": "C"}
    assert not SheetConfirmRequest().changes().model_fields_set


def test_the_confirm_and_thumbnail_routes_sit_under_the_sheets_prefix() -> None:
    from app.modules.documents.router import router

    routes = {(m, r.path) for r in router.routes for m in getattr(r, "methods", ())}
    assert ("POST", "/sheets/{sheet_id}/confirm-extraction/") in routes
    assert ("POST", "/sheets/confirm-bulk/") in routes
    assert ("POST", "/sheets/check-intake/") in routes
    assert ("GET", "/sheets/{sheet_id}/thumbnail/") in routes
