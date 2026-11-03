"""OCR fallback for scanned drawing sheets: routing, confidence, hold-until-confirm.

No tesseract in CI: the engine is a stub module, the PDF is an image-only page
rasterised with PIL in the test.
"""

from __future__ import annotations

import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.documents import sheet_checks, sheet_ocr
from app.modules.documents.service import SheetService, _read_sheet_pages


def _scan_pdf(path: Path) -> None:
    pil = pytest.importorskip("PIL.Image")
    pil.new("RGB", (1200, 800), "white").save(str(path), "PDF", resolution=100)


def _fake_tesseract(monkeypatch: pytest.MonkeyPatch, words: list[tuple[str, int]]) -> None:
    mod = types.ModuleType("pytesseract")
    mod.Output = SimpleNamespace(DICT="dict")  # type: ignore[attr-defined]
    mod.image_to_data = lambda *_a, **_k: {  # type: ignore[attr-defined]
        "text": [w for w, _ in words],
        "conf": [c for _, c in words],
    }
    monkeypatch.setitem(sys.modules, "pytesseract", mod)


def test_scanned_page_is_read_by_ocr_with_a_confidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "scan.pdf"
    _scan_pdf(pdf)
    _fake_tesseract(monkeypatch, [("A-101", 90), ("FLOOR", 80), ("PLAN", 70), ("", -1)])
    pages = _read_sheet_pages(pdf, tmp_path, "u", "scan.pdf", "scan.pdf")
    [page] = pages
    assert page["extraction"]["source"] == "ocr"
    assert page["extraction"]["needs_review"] is True
    assert page["extraction"]["confidence"] == pytest.approx(0.8)
    assert "A-101" in (page["sheet_number"] or "")


def test_missing_engine_creates_the_sheet_and_flags_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "scan.pdf"
    _scan_pdf(pdf)
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    [page] = _read_sheet_pages(pdf, tmp_path, "u", "scan.pdf", "scan.pdf")
    assert page["extraction"] == {
        "source": "ocr",
        "confidence": 0.0,
        "needs_review": True,
        "reason": "ocr_unavailable",
    }
    assert sheet_ocr.is_held({"extraction": page["extraction"]})


def test_page_cap_stops_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "scan.pdf"
    _scan_pdf(pdf)
    _fake_tesseract(monkeypatch, [("A-1", 99)])
    with sheet_ocr.TitleBlockOcr(pdf, max_pages=0) as ocr:
        assert ocr.read(0).reason == "ocr_page_cap"


def test_held_only_below_the_stacking_confidence() -> None:
    assert sheet_ocr.is_held({"extraction": {"needs_review": True, "confidence": 0.59}})
    assert not sheet_ocr.is_held({"extraction": {"needs_review": True, "confidence": 0.6}})
    assert not sheet_ocr.is_held({"extraction": {"needs_review": False, "confidence": 0.1}})
    assert not sheet_ocr.is_held({})


def _sheet(number: str, rev: str, *, conf: float | None = None, current: bool = True) -> SimpleNamespace:
    meta = {} if conf is None else {"extraction": {"source": "ocr", "confidence": conf, "needs_review": True}}
    return SimpleNamespace(
        id=uuid.uuid4(),
        sheet_number=number,
        sheet_title="Plan",
        revision=rev,
        page_number=1,
        is_current=current,
        previous_version_id=None,
        metadata_=meta,
        project_id=uuid.uuid4(),
    )


class _Repo:
    def __init__(self, *heads: SimpleNamespace) -> None:
        self.heads = heads

    async def current_by_chain_key(self, _project: uuid.UUID) -> dict[str, list[SimpleNamespace]]:
        out: dict[str, list[SimpleNamespace]] = {}
        for h in self.heads:
            out.setdefault("A101", []).append(h)
        return out


@pytest.mark.asyncio
async def test_low_confidence_scan_is_held_then_stacked_on_confirm() -> None:
    old = _sheet("A-101", "A")
    scan = _sheet("A-101", "B", conf=0.4)
    svc = SheetService.__new__(SheetService)
    svc.repo = _Repo(old, scan)  # type: ignore[assignment]

    assert await svc._supersede_previous_sheets(scan.project_id, [scan]) == 0  # type: ignore[arg-type]
    assert old.is_current and scan.previous_version_id is None

    scan.metadata_["extraction"]["needs_review"] = False  # what confirm does before stacking
    assert await svc._supersede_previous_sheets(scan.project_id, [scan]) == 1  # type: ignore[arg-type]
    assert scan.previous_version_id == old.id and not old.is_current


@pytest.mark.asyncio
async def test_confirm_clears_the_flag_and_stacks_a_held_scan() -> None:
    old = _sheet("A-101", "A")
    scan = _sheet("A-101", "B", conf=0.4)
    svc = SheetService.__new__(SheetService)
    svc.repo = _Repo(old, scan)  # type: ignore[assignment]

    async def get_sheet(_id: uuid.UUID) -> SimpleNamespace:
        return scan

    async def flush() -> None:
        return None

    svc.get_sheet = get_sheet  # type: ignore[method-assign]
    svc.session = SimpleNamespace(flush=flush)  # type: ignore[assignment]
    await svc.confirm_extraction(scan.id)
    assert scan.metadata_["extraction"]["needs_review"] is False
    assert scan.previous_version_id == old.id


def test_reread_never_overwrites_an_ocr_sheet() -> None:
    scan = _sheet("A-101", "B", conf=0.9)
    scan.discipline = None
    assert SheetService._apply_reread(scan, {}) == 0  # type: ignore[arg-type]
    assert scan.sheet_number == "A-101"


def test_sheet_checks() -> None:
    assert sheet_checks.check_number_present({"page_number": 3})
    assert not sheet_checks.check_number_present({"sheet_number": "A-1"})
    assert sheet_checks.check_number_unique_in_set({"sheet_number": "A-1", "duplicates": 1})
    assert sheet_checks.check_revision_not_lower({"sheet_number": "A-1", "revision": "A", "current_revision": "C"})
    assert not sheet_checks.check_revision_not_lower({"sheet_number": "A-1", "revision": "D", "current_revision": "C"})
    low = {"sheet_number": "A-1", "extraction": {"source": "ocr", "needs_review": True, "confidence": 0.5}}
    assert sheet_checks.check_low_confidence_unconfirmed(low)[0].params["confidence"] == "50%"
    assert not sheet_checks.check_low_confidence_unconfirmed(
        {**low, "extraction": {**low["extraction"], "needs_review": False}}
    )
