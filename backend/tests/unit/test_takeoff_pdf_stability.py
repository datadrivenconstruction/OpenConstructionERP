"""Unit tests for PDF takeoff stability (Indian / global edge cases).

Covers the fixes shipped in v3.0.x to address fresh-install report from a
user in India where PDF takeoff did not perform as expected:

  * Empty (0-byte) uploads — rejected at upload time, not deep in parser.
  * Password-protected PDFs — detected before any parser runs, with a
    structured ``HTTPException(400)`` telling the user exactly how to
    fix it.
  * Oversize uploads — gated by ``OE_TAKEOFF_MAX_UPLOAD_MB`` env var
    with a 413 + remediation message.
  * Scanned/photocopy PDFs (no embedded text layer) — the empty-text
    case is detected and either OCR'd (when ``[cv]`` extra is
    installed) or persisted with ``status="needs_ocr"`` so the user
    sees their file in the list with a clear next step.
  * Indian numbering: lakh / crore comma-grouping, decimal-comma,
    feet-inches, mixed mm/m units in ``extract_tables``.

Tests are pure-Python — they never invoke real PaddleOCR or hit the
filesystem outside ``tmp_path``.
"""

from __future__ import annotations

import logging
import sys
import types
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.takeoff import service as takeoff_service
from app.modules.takeoff.service import (
    _is_encrypted_pdf,
    _max_upload_bytes,
    _normalize_unit,
    _ocr_dpi,
    _ocr_langs,
    _parse_indian_number,
)

# ---------------------------------------------------------------------------
# _is_encrypted_pdf
# ---------------------------------------------------------------------------


class TestIsEncryptedPdf:
    def test_returns_false_for_empty(self):
        assert _is_encrypted_pdf(b"") is False

    def test_returns_false_for_plain_pdf(self):
        # Minimal-ish PDF header + body + xref + no /Encrypt anywhere
        body = b"%PDF-1.4\n" + b"%hello world\n" * 100 + b"trailer<<>>\n%%EOF"
        assert _is_encrypted_pdf(body) is False

    def test_returns_true_for_encrypted_trailer(self):
        body = (
            b"%PDF-1.6\n"
            + b"... some object stream content ...\n" * 5
            + b"trailer\n<< /Size 12 /Root 1 0 R /Encrypt 11 0 R /ID [<abc><def>] >>\n%%EOF"
        )
        assert _is_encrypted_pdf(body) is True

    def test_returns_true_for_xref_stream_with_encrypt(self):
        body = b"%PDF-1.7\n" + (b"pad" * 1000) + b"\n<< /Encrypt 8 0 R /Root 1 0 R >>\n%%EOF"
        assert _is_encrypted_pdf(body) is True

    def test_only_scans_trailer_block_not_whole_file(self):
        # /Encrypt appearing in a content stream way earlier in the file
        # must NOT be flagged — keep false-positive bar high.
        body = b"%PDF-1.4\n(/Encrypt is just a string here)\n" + b"safe" * 5000 + b"\ntrailer<<>>\n%%EOF"
        # The /Encrypt token lives outside the last 8 KB and is in a
        # content-string parenthesis — must not trigger.
        # Pad to push the false-positive token outside the 8 KB tail window.
        prefix = b"%PDF-1.4\n(/Encrypt is just a string here)\n"
        body = prefix + (b"safe" * 5000) + (b"x" * 10000) + b"\ntrailer<<>>\n%%EOF"
        assert _is_encrypted_pdf(body) is False

    def test_returns_true_for_inline_encrypt_dict(self):
        """Some generators (e.g. LibreOffice) emit /Encrypt << ... >> inline
        instead of an indirect reference /Encrypt N 0 R.  D-TKC-ENC01 fix.
        """
        body = (
            b"%PDF-1.7\n"
            + b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            + b"xref\n0 2\n"
            + b"trailer\n<< /Size 2 /Encrypt << /Filter /Standard /R 6 >> >>\n%%EOF"
        )
        assert _is_encrypted_pdf(body) is True

    def test_returns_false_for_partial_encrypt_word_in_content(self):
        """String '/Encrypting' in a content stream should NOT match."""
        body = b"%PDF-1.4\n" + b"pad" * 1000 + b"\n(Encrypting data...)\ntrailer<<>>\n%%EOF"
        assert _is_encrypted_pdf(body) is False


# ---------------------------------------------------------------------------
# Upload size cap & env overrides
# ---------------------------------------------------------------------------


class TestUploadCaps:
    def test_default_is_unlimited(self, monkeypatch):
        """No env var set → 0 (unlimited) per product default 2026-05-13."""
        monkeypatch.delenv("OE_TAKEOFF_MAX_UPLOAD_MB", raising=False)
        assert _max_upload_bytes() == 0

    def test_zero_env_is_unlimited(self, monkeypatch):
        """Explicit OE_TAKEOFF_MAX_UPLOAD_MB=0 → 0 (unlimited)."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "0")
        assert _max_upload_bytes() == 0

    def test_negative_env_is_unlimited(self, monkeypatch):
        """Negative env value treated as unlimited (defensive)."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "-5")
        assert _max_upload_bytes() == 0

    def test_env_override(self, monkeypatch):
        """Operator-configured cap returns bytes for that many MB."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "50")
        assert _max_upload_bytes() == 50 * 1024 * 1024

    def test_garbage_env_falls_back_to_default(self, monkeypatch):
        """Unparseable env value falls back to unlimited."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "not-a-number")
        assert _max_upload_bytes() == 0


class TestOcrTuning:
    def test_default_dpi_is_200(self, monkeypatch):
        monkeypatch.delenv("OE_TAKEOFF_OCR_DPI", raising=False)
        assert _ocr_dpi() == 200

    def test_dpi_clamped_to_safe_range(self, monkeypatch):
        monkeypatch.setenv("OE_TAKEOFF_OCR_DPI", "50")
        assert _ocr_dpi() == 72  # floor
        monkeypatch.setenv("OE_TAKEOFF_OCR_DPI", "9000")
        assert _ocr_dpi() == 600  # ceiling

    def test_langs_default_covers_indian_scripts(self, monkeypatch):
        monkeypatch.delenv("OE_TAKEOFF_OCR_LANGS", raising=False)
        langs = _ocr_langs()
        # Must include en + at least one Indian script + Arabic
        assert "en" in langs
        assert "hi" in langs  # Hindi (devanagari)
        assert "ta" in langs  # Tamil
        assert "te" in langs  # Telugu
        assert "ar" in langs  # Arabic

    def test_langs_custom_env(self, monkeypatch):
        monkeypatch.setenv("OE_TAKEOFF_OCR_LANGS", "en, hi, ta")
        assert _ocr_langs() == ["en", "hi", "ta"]


# ---------------------------------------------------------------------------
# _parse_indian_number — Indian / EU / imperial number parsing
# ---------------------------------------------------------------------------


class TestParseIndianNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Indian lakh / crore
            ("1,00,000", 100000.0),  # 1 lakh
            ("10,00,000", 1000000.0),  # 10 lakh
            ("1,23,45,678", 12345678.0),  # 1.23 crore
            # US / UK thousand-grouped
            ("1,500", 1500.0),
            ("1,500.50", 1500.5),
            ("12,345.67", 12345.67),
            # Plain integer / decimal
            ("1500", 1500.0),
            ("1500.5", 1500.5),
            ("0", 0.0),
            ("-25", -25.0),
            # German / Indo-EU: thousands with dot, decimal with comma
            ("1.500,50", 1500.5),
            ("12.345,67", 12345.67),
            # Decimal-comma (no thousands)
            ("12,5", 12.5),
            ("0,75", 0.75),
            # Trailing unit suffix
            ("1500mm", 1500.0),
            ("12.5m", 12.5),
            ("1,500 m2", 1500.0),
            ("100 SqM", 100.0),
            # Feet-inches
            ("5'-6\"", 5.5),
            # Empty / whitespace / None
            ("", 0.0),
            ("   ", 0.0),
            (None, 0.0),
            # Numeric pass-through
            (42, 42.0),
            (3.14, 3.14),
        ],
    )
    def test_parses(self, raw, expected):
        assert _parse_indian_number(raw) == pytest.approx(expected)

    def test_unparseable_returns_zero_not_raises(self):
        # Garbage strings must not raise — they must return 0.0 so the
        # caller (extract_tables) keeps processing the rest of the table.
        assert _parse_indian_number("abc") == 0.0
        assert _parse_indian_number("???") == 0.0

    def test_partial_digits_extracted_as_last_resort(self):
        # When the format doesn't match any known pattern but contains
        # digits, last-resort fallback strips non-digit chars and tries.
        assert _parse_indian_number("Rs. 1500 only") == 1500.0


# ---------------------------------------------------------------------------
# _normalize_unit — unit aliases (Indian / DACH / imperial)
# ---------------------------------------------------------------------------


class TestNormalizeUnit:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Indian running metre
            ("RMt", "m"),
            ("RM", "m"),
            ("Running metre", "m"),
            ("running meter", "m"),
            # Indian square metre / cubic metre
            ("SqM", "m2"),
            ("Sq.M", "m2"),
            ("Sq M", "m2"),
            ("CuM", "m3"),
            ("Cu.M", "m3"),
            # Indian square / cubic feet
            ("SFT", "sft"),
            ("Sq Ft", "sft"),
            ("CFT", "cft"),
            ("Cu Ft", "cft"),
            # Indian count
            ("Nos", "pcs"),
            ("NOS.", "pcs"),
            ("No.", "pcs"),
            ("Number", "pcs"),
            # Lump sum
            ("LS", "lsum"),
            ("Lump sum", "lsum"),
            # Plain metric pass-through
            ("m", "m"),
            ("m2", "m2"),
            ("m3", "m3"),
            ("kg", "kg"),
            # Tonne aliases
            ("MT", "t"),
            ("Tonne", "t"),
            # Empty / None
            ("", "pcs"),
            (None, "pcs"),
            # Unknown unit → lowercase pass-through (don't break user data)
            ("widgets", "widgets"),
        ],
    )
    def test_maps(self, raw, expected):
        assert _normalize_unit(raw) == expected


# ---------------------------------------------------------------------------
# upload_document gates: 0-byte, oversize, encrypted
# ---------------------------------------------------------------------------


class _StubRepo:
    async def create(self, doc):  # pragma: no cover - not reached when gates fire
        return doc


def _make_service():
    svc = object.__new__(takeoff_service.TakeoffService)
    svc.session = MagicMock()
    svc.repo = _StubRepo()
    svc.measurement_repo = MagicMock()
    return svc


class TestUploadDocumentGates:
    @pytest.mark.asyncio
    async def test_zero_byte_upload_rejected(self):
        svc = _make_service()
        with pytest.raises(HTTPException) as exc:
            await svc.upload_document(
                filename="blank.pdf",
                content=b"",
                size_bytes=0,
                owner_id=str(uuid.uuid4()),
            )
        assert exc.value.status_code == 400
        assert "empty" in str(exc.value.detail).lower()

    @pytest.mark.asyncio
    async def test_oversize_upload_rejected_with_413_when_cap_configured(self, monkeypatch):
        """Free-tier deployments may set OE_TAKEOFF_MAX_UPLOAD_MB → 413."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "1")  # 1 MB cap
        svc = _make_service()
        big = b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024)  # 2 MB
        with pytest.raises(HTTPException) as exc:
            await svc.upload_document(
                filename="huge.pdf",
                content=big,
                size_bytes=len(big),
                owner_id=str(uuid.uuid4()),
            )
        assert exc.value.status_code == 413
        detail = str(exc.value.detail)
        assert "too large" in detail.lower()
        # The error message must tell the user how to raise the limit.
        assert "OE_TAKEOFF_MAX_UPLOAD_MB" in detail

    @pytest.mark.asyncio
    async def test_oversize_upload_accepted_when_unlimited(self, monkeypatch):
        """Product default: no env → no 413 even for huge payloads.

        The upload gate must not be the place that rejects large files;
        memory safety comes from streaming chunked I/O upstream, not from
        a fixed cap. We only verify the *gate* passes — downstream
        parser failure is irrelevant for this regression test.
        """
        monkeypatch.delenv("OE_TAKEOFF_MAX_UPLOAD_MB", raising=False)
        svc = _make_service()
        # 2 MB payload; in production this could be 5 GB — the gate
        # logic itself is O(1), so size is immaterial to the assertion.
        big = b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024)
        # Stub the parser so the test doesn't touch real PDF code paths
        # — we only care that the size gate does not raise 413.
        svc.session.add = MagicMock()

        async def _fake_flush():
            return None

        svc.session.flush = _fake_flush
        # Patch out the actual heavy work; we only test the gate.
        import app.modules.takeoff.service as svc_mod

        monkeypatch.setattr(svc_mod, "_count_pdf_pages", lambda *a, **k: 1)
        monkeypatch.setattr(
            svc_mod,
            "_extract_pdf_pages",
            lambda *a, **k: [{"page": 1, "text": "hello"}],
        )

        class _AwaitableCreate:
            async def create(self, doc):
                return doc

        svc.repo = _AwaitableCreate()
        # Should not raise 413 — we explicitly tolerate any other outcome
        # (the simulated parser path lets it succeed cleanly).
        try:
            await svc.upload_document(
                filename="huge.pdf",
                content=big,
                size_bytes=len(big),
                owner_id=str(uuid.uuid4()),
            )
        except HTTPException as exc:
            assert exc.status_code != 413, (
                f"Unlimited config must not produce a 413 — got: {exc.status_code} {exc.detail}"
            )

    @pytest.mark.asyncio
    async def test_encrypted_pdf_rejected_with_actionable_message(self):
        svc = _make_service()
        encrypted = b"%PDF-1.6\n" + b"some content\n" * 10 + b"trailer\n<< /Size 5 /Root 1 0 R /Encrypt 4 0 R >>\n%%EOF"
        with pytest.raises(HTTPException) as exc:
            await svc.upload_document(
                filename="locked.pdf",
                content=encrypted,
                size_bytes=len(encrypted),
                owner_id=str(uuid.uuid4()),
            )
        assert exc.value.status_code == 400
        detail = str(exc.value.detail)
        # Must mention password and give a hint on how to remove it.
        assert "password" in detail.lower()
        assert any(tool in detail.lower() for tool in ("acrobat", "qpdf"))


# ---------------------------------------------------------------------------
# Scanned-PDF: empty text on every page → status="needs_ocr"
# ---------------------------------------------------------------------------


class _FakePageNoText:
    def extract_tables(self):
        return []

    def extract_text(self):
        return ""  # scanned PDF: no embedded text layer


class _FakePdfNoText:
    pages = [_FakePageNoText() for _ in range(3)]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class TestScannedPdfNeedsOcr:
    @pytest.fixture(autouse=True)
    def _stub_pdfplumber(self):
        """Stub pdfplumber + pymupdf to simulate a 3-page scanned PDF.

        pdfplumber returns pages with empty text + no tables;
        pymupdf reports 3 pages for the count probe.  paddleocr is NOT
        installed so the OCR fallback returns []; upload should then
        persist with status="needs_ocr".
        """
        # pdfplumber
        fake_pdfplumber = types.ModuleType("pdfplumber")
        fake_pdfplumber.open = lambda _buf: _FakePdfNoText()  # type: ignore[attr-defined]
        sys.modules["pdfplumber"] = fake_pdfplumber

        # pymupdf
        fake_pymupdf = types.ModuleType("pymupdf")

        class _StubDoc:
            def __init__(self):
                self._pages = [MagicMock(get_text=MagicMock(return_value="")) for _ in range(3)]

            def __iter__(self):
                return iter(self._pages)

            def __len__(self):
                return len(self._pages)

            def close(self):
                return None

        fake_pymupdf.open = lambda **_kw: _StubDoc()  # type: ignore[attr-defined]
        sys.modules["pymupdf"] = fake_pymupdf

        # Ensure paddleocr is NOT importable so the OCR fallback returns [].
        sys.modules.pop("paddleocr", None)

        yield

        for name in ("pdfplumber", "pymupdf", "paddleocr"):
            sys.modules.pop(name, None)

    @pytest.mark.asyncio
    async def test_scanned_pdf_persists_with_needs_ocr_status(self, tmp_path, monkeypatch, caplog):
        # Redirect upload dir to tmp_path so we don't write into the user's home.
        monkeypatch.setattr(
            takeoff_service,
            "_TAKEOFF_DOCUMENTS_DIR",
            tmp_path / "takeoff",
        )
        svc = _make_service()
        scanned = b"%PDF-1.4\n" + b"scanned-bytes" * 100  # no /Encrypt, non-empty

        with caplog.at_level(logging.INFO, logger="app.modules.takeoff.service"):
            doc = await svc.upload_document(
                filename="scan.pdf",
                content=scanned,
                size_bytes=len(scanned),
                owner_id=str(uuid.uuid4()),
            )

        assert doc.status == "needs_ocr", "Scanned-PDF must be persisted with needs_ocr status"
        assert doc.pages == 3
        # A clear log line tells operators to install [cv].
        install_hints = [
            r
            for r in caplog.records
            if "install [cv] extra" in r.getMessage().lower()
            or "install" in r.getMessage().lower()
            and "cv" in r.getMessage().lower()
        ]
        assert install_hints, "Operator-facing OCR install hint not logged"


# ---------------------------------------------------------------------------
# extract_tables with Indian-locale data
# ---------------------------------------------------------------------------


class _DocumentStub:
    """Mimics TakeoffDocument enough for extract_tables to walk page_data."""

    def __init__(self, page_data):
        self.page_data = page_data


class _RepoStub:
    def __init__(self, doc):
        self._doc = doc

    async def get_by_id(self, _id):
        return self._doc


class TestExtractTablesIndianLocale:
    @pytest.mark.asyncio
    async def test_indian_lakh_and_decimal_comma_and_units(self):
        page_data = [
            {
                "page": 1,
                "tables": [
                    [
                        ["Item", "Quantity", "Unit"],
                        ["Cement bags", "1,00,000", "Nos"],  # 1 lakh
                        ["Steel rebar", "12,5", "MT"],  # decimal-comma + tonne alias
                        ["Concrete slab", "1,500.50", "SqM"],  # thousands + sq.m
                        ["Wall plastering", "5'-6\"", "RMt"],  # feet-inches + running metre
                        ["Bricks", "1,23,45,678", "NOS."],  # crore + count alias
                    ]
                ],
            }
        ]
        svc = _make_service()
        svc.repo = _RepoStub(_DocumentStub(page_data))

        result = await svc.extract_tables(str(uuid.uuid4()))
        elements = result["elements"]
        assert len(elements) == 5

        by_desc = {el["description"]: el for el in elements}
        assert by_desc["Cement bags"]["quantity"] == 100000.0
        assert by_desc["Cement bags"]["unit"] == "pcs"
        assert by_desc["Steel rebar"]["quantity"] == 12.5
        assert by_desc["Steel rebar"]["unit"] == "t"
        assert by_desc["Concrete slab"]["quantity"] == 1500.5
        assert by_desc["Concrete slab"]["unit"] == "m2"
        assert by_desc["Wall plastering"]["quantity"] == pytest.approx(5.5)
        assert by_desc["Wall plastering"]["unit"] == "m"
        assert by_desc["Bricks"]["quantity"] == 12345678.0
        assert by_desc["Bricks"]["unit"] == "pcs"
