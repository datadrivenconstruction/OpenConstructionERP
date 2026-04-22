"""Unit tests for takeoff PDF-parsing error logging (v2.4.0).

Audit finding: :mod:`app.modules.takeoff.service` was swallowing
``pdfplumber`` and ``pymupdf`` exceptions with a single generic
``logger.warning("PDF extraction failed …")`` — no filename, no size,
no stack, no extension, no magic-byte check.  Incidents in staging
produced log lines that were impossible to correlate with the
offending upload.

These tests exercise the new behaviour:

* First-pass (pdfplumber) failure → WARNING with input fingerprint +
  stack.
* Double-failure (both parsers raise) → one EXCEPTION-level line with
  the same fingerprint.
* User-facing :class:`HTTPException` stays generic (no paths, no
  stacks) to avoid leaking anything server-side to the API caller.

Pattern mirrors :mod:`tests.unit.test_cache_logging`.
"""

from __future__ import annotations

import logging
import sys
import types
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.takeoff import service as takeoff_service
from app.modules.takeoff.service import (
    _count_pdf_pages,
    _describe_pdf_input,
    _extract_pdf_pages,
)

# ---------------------------------------------------------------------------
# Helpers — inject fake pdf parsers via sys.modules so the real deps don't run
# ---------------------------------------------------------------------------


def _install_fake_pdfplumber(raise_with: Exception | None) -> None:
    """Replace ``pdfplumber`` in ``sys.modules`` with a stub.

    If ``raise_with`` is not None the stub's ``open`` raises it; the
    service helper's outer try/except then falls through to pymupdf.
    """
    fake = types.ModuleType("pdfplumber")

    def _open(_buf):  # pragma: no cover - stub only
        if raise_with is not None:
            raise raise_with
        raise AssertionError("no parser behaviour configured")

    fake.open = _open  # type: ignore[attr-defined]
    sys.modules["pdfplumber"] = fake


def _install_fake_pymupdf(raise_with: Exception | None, pages: int = 0) -> None:
    """Replace ``pymupdf`` in ``sys.modules`` with a stub.

    If ``raise_with`` is not None its ``open`` raises that exception;
    otherwise ``open`` returns a handle with ``pages`` blank pages.
    """
    fake = types.ModuleType("pymupdf")

    class _StubDoc:
        def __init__(self, page_count: int) -> None:
            self._pages = [MagicMock(get_text=MagicMock(return_value="")) for _ in range(page_count)]

        def __iter__(self):
            return iter(self._pages)

        def __len__(self):
            return len(self._pages)

        def close(self):
            return None

    def _open(*, stream=None, filetype=None):  # pragma: no cover - stub only
        if raise_with is not None:
            raise raise_with
        return _StubDoc(pages)

    fake.open = _open  # type: ignore[attr-defined]
    sys.modules["pymupdf"] = fake


@pytest.fixture(autouse=True)
def _restore_pdf_modules():
    """Snapshot + restore pdfplumber / pymupdf entries around each test.

    Keeps cross-test bleed to zero regardless of what a test stubs.
    """
    snapshot = {name: sys.modules.get(name) for name in ("pdfplumber", "pymupdf")}
    yield
    for name, mod in snapshot.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


# ---------------------------------------------------------------------------
# _describe_pdf_input
# ---------------------------------------------------------------------------


class TestDescribePdfInput:
    def test_reports_size_and_magic_and_extension(self):
        fp = _describe_pdf_input(b"%PDF-1.4 rest", filename="drawings.pdf")
        assert "size=" in fp
        assert "13B" in fp
        assert "has_pdf_magic=True" in fp
        assert ".pdf" in fp

    def test_handles_missing_filename_and_empty_content(self):
        fp = _describe_pdf_input(b"", filename=None)
        assert "size=0B" in fp
        assert "has_pdf_magic=False" in fp
        assert "<anonymous>" in fp

    def test_never_emits_absolute_paths(self):
        """Crucially: the fingerprint must not leak an absolute path —
        it's logged server-side but the security bar is the same as if
        it ended up in a user-visible error.
        """
        fp = _describe_pdf_input(b"%PDF-", filename="C:\\secret\\drawings.pdf")
        assert "C:\\secret" not in fp  # we only keep the basename via repr


# ---------------------------------------------------------------------------
# _extract_pdf_pages error paths
# ---------------------------------------------------------------------------


class TestExtractPdfPagesLogging:
    def test_pdfplumber_failure_falls_back_and_logs_warning(self, caplog):
        _install_fake_pdfplumber(RuntimeError("pdfplumber-boom"))
        _install_fake_pymupdf(None, pages=2)

        with caplog.at_level(logging.WARNING, logger="app.modules.takeoff.service"):
            pages = _extract_pdf_pages(b"%PDF-1.4 junk", filename="weird.pdf")

        # Fallback populated the list — semantics preserved.
        assert len(pages) == 2

        # The pdfplumber failure must now be visible in the log with
        # stack + fingerprint.
        matches = [
            rec
            for rec in caplog.records
            if "takeoff.pdf_extract" in rec.getMessage() and "pdfplumber failed" in rec.getMessage()
        ]
        assert matches, "pdfplumber failure log not emitted"
        msg = matches[0].getMessage()
        assert "weird.pdf" in msg
        assert "size=" in msg
        assert matches[0].levelno == logging.WARNING
        # exc_info propagates so operators get the full stack.
        assert matches[0].exc_info is not None

    def test_both_parsers_failing_logs_exception(self, caplog):
        _install_fake_pdfplumber(RuntimeError("pdfplumber-boom"))
        _install_fake_pymupdf(RuntimeError("pymupdf-boom"))

        with caplog.at_level(logging.WARNING, logger="app.modules.takeoff.service"):
            pages = _extract_pdf_pages(b"not really a pdf", filename="garbage.bin")

        # Original semantics: on full failure we return an empty list.
        assert pages == []

        # The EXCEPTION-level line is the headline ("both failed").
        both_failed = [rec for rec in caplog.records if "both pdfplumber and pymupdf failed" in rec.getMessage()]
        assert both_failed, "double-failure log not emitted"
        msg = both_failed[0].getMessage()
        assert "garbage.bin" in msg
        assert "size=" in msg
        assert both_failed[0].levelno == logging.ERROR
        assert both_failed[0].exc_info is not None

    def test_pdfplumber_happy_path_does_not_log_at_warning(self, caplog):
        """No pdfplumber failure, no pymupdf fallback — should be silent."""

        # Install a pdfplumber stub whose ``open`` returns a valid-ish
        # context manager so we exercise the success path.
        class _FakePage:
            def extract_tables(self):
                return []

            def extract_text(self):
                return "Line 1\nLine 2"

        class _FakePdf:
            pages = [_FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        fake_pdfplumber = types.ModuleType("pdfplumber")
        fake_pdfplumber.open = lambda _buf: _FakePdf()  # type: ignore[attr-defined]
        sys.modules["pdfplumber"] = fake_pdfplumber

        with caplog.at_level(logging.WARNING, logger="app.modules.takeoff.service"):
            pages = _extract_pdf_pages(b"%PDF-1.4 ok", filename="fine.pdf")

        assert len(pages) == 1
        assert "Line 1" in pages[0]["text"]
        assert not [rec for rec in caplog.records if "takeoff.pdf_extract" in rec.getMessage()]


# ---------------------------------------------------------------------------
# _count_pdf_pages error paths
# ---------------------------------------------------------------------------


class TestCountPdfPagesLogging:
    def test_double_failure_returns_zero_and_logs(self, caplog):
        _install_fake_pdfplumber(RuntimeError("count-boom"))
        _install_fake_pymupdf(RuntimeError("count-boom"))

        with caplog.at_level(logging.WARNING, logger="app.modules.takeoff.service"):
            n = _count_pdf_pages(b"%PDF-garbage", filename="junk.pdf")

        assert n == 0

        both_failed = [
            rec
            for rec in caplog.records
            if "takeoff.pdf_count" in rec.getMessage() and "both pdfplumber and pymupdf failed" in rec.getMessage()
        ]
        assert both_failed
        assert "junk.pdf" in both_failed[0].getMessage()
        assert both_failed[0].levelno == logging.ERROR

    def test_fallback_to_pymupdf_emits_warning(self, caplog):
        _install_fake_pdfplumber(RuntimeError("count-boom"))
        _install_fake_pymupdf(None, pages=7)

        with caplog.at_level(logging.WARNING, logger="app.modules.takeoff.service"):
            n = _count_pdf_pages(b"%PDF-something", filename="fallback.pdf")

        assert n == 7
        matches = [rec for rec in caplog.records if "takeoff.pdf_count pdfplumber failed" in rec.getMessage()]
        assert matches
        assert matches[0].levelno == logging.WARNING


# ---------------------------------------------------------------------------
# upload_document end-to-end: generic HTTPException + server-side fingerprint
# ---------------------------------------------------------------------------


class _StubRepo:
    async def create(self, doc):  # pragma: no cover - not reached on failure
        return doc


class TestUploadDocumentErrorPath:
    @pytest.mark.asyncio
    async def test_unparseable_pdf_raises_generic_http_and_logs_server_side(self, monkeypatch, caplog):
        """User-facing detail stays generic; server log keeps the details."""
        _install_fake_pdfplumber(RuntimeError("pdfplumber-boom"))
        _install_fake_pymupdf(RuntimeError("pymupdf-boom"))

        svc = object.__new__(takeoff_service.TakeoffService)
        svc.session = MagicMock()
        svc.repo = _StubRepo()
        svc.measurement_repo = MagicMock()

        with caplog.at_level(logging.WARNING, logger="app.modules.takeoff.service"):
            with pytest.raises(HTTPException) as excinfo:
                await svc.upload_document(
                    filename="C:\\secret\\weird.pdf",
                    content=b"not-a-real-pdf",
                    size_bytes=len(b"not-a-real-pdf"),
                    owner_id="00000000-0000-0000-0000-000000000000",
                )

        # 400 with a generic, path-free detail.
        assert excinfo.value.status_code == 400
        detail = excinfo.value.detail
        assert isinstance(detail, str)
        assert "C:\\secret" not in detail
        assert "pdfplumber" not in detail
        assert "pymupdf" not in detail
        assert "Traceback" not in detail
        assert "Failed to parse" in detail

        # Server-side: full diagnostic landed in the log.
        double_failure = [rec for rec in caplog.records if "both pdfplumber and pymupdf failed" in rec.getMessage()]
        assert double_failure, "double-failure not logged"
        # The filename still appears in the server log — that's fine
        # because logs are server-side only.
        assert "weird.pdf" in double_failure[0].getMessage()
        # Rejection summary line is there too.
        rejection = [rec for rec in caplog.records if "rejecting upload" in rec.getMessage()]
        assert rejection
        assert rejection[0].levelno == logging.WARNING


# ---------------------------------------------------------------------------
# Sanity: logger name matches module path
# ---------------------------------------------------------------------------


def test_logger_namespace():
    assert takeoff_service.logger.name == "app.modules.takeoff.service"
