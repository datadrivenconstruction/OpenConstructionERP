"""Unit tests for takeoff PDF-parsing error logging (v2.4.0).

Audit finding: :mod:`app.modules.takeoff.service` was swallowing
``pdfplumber`` and ``pypdfium2`` exceptions with a single generic
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
    service helper's outer try/except then falls through to pypdfium2.
    """
    fake = types.ModuleType("pdfplumber")

    def _open(_buf):  # pragma: no cover - stub only
        if raise_with is not None:
            raise raise_with
        raise AssertionError("no parser behaviour configured")

    fake.open = _open  # type: ignore[attr-defined]
    sys.modules["pdfplumber"] = fake


def _install_fake_pdfium(monkeypatch, raise_with: Exception | None, pages: int = 0) -> None:
    """Replace the ``pdf_reader`` entry points the fallback uses with a stub.

    If ``raise_with`` is not None ``open_pdf`` and ``page_count`` raise that
    exception; otherwise they report a document with ``pages`` blank pages.
    """
    from app.core import pdf_reader

    class _StubPage:
        def text(self):
            return ""

        def close(self):
            return None

    class _StubDoc:
        def __init__(self, page_count: int) -> None:
            self.page_count = page_count

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def __getitem__(self, index: int) -> _StubPage:
            return _StubPage()

    def _open_pdf(*_args, **_kwargs):  # pragma: no cover - stub only
        if raise_with is not None:
            raise raise_with
        return _StubDoc(pages)

    def _page_count(*_args, **_kwargs):  # pragma: no cover - stub only
        if raise_with is not None:
            raise raise_with
        return pages

    monkeypatch.setattr(pdf_reader, "open_pdf", _open_pdf)
    monkeypatch.setattr(pdf_reader, "page_count", _page_count)


@pytest.fixture(autouse=True)
def _restore_pdf_modules():
    """Snapshot + restore the pdfplumber entry around each test.

    Keeps cross-test bleed to zero regardless of what a test stubs.
    """
    snapshot = {name: sys.modules.get(name) for name in ("pdfplumber",)}
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
    def test_pdfplumber_failure_falls_back_and_logs_warning(self, caplog, monkeypatch):
        _install_fake_pdfplumber(RuntimeError("pdfplumber-boom"))
        _install_fake_pdfium(monkeypatch, None, pages=2)

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

    def test_both_parsers_failing_logs_exception(self, caplog, monkeypatch):
        _install_fake_pdfplumber(RuntimeError("pdfplumber-boom"))
        _install_fake_pdfium(monkeypatch, RuntimeError("pdfium-boom"))

        with caplog.at_level(logging.WARNING, logger="app.modules.takeoff.service"):
            pages = _extract_pdf_pages(b"not really a pdf", filename="garbage.bin")

        # Original semantics: on full failure we return an empty list.
        assert pages == []

        # The EXCEPTION-level line is the headline ("both failed").
        both_failed = [rec for rec in caplog.records if "both pdfplumber and pypdfium2 failed" in rec.getMessage()]
        assert both_failed, "double-failure log not emitted"
        msg = both_failed[0].getMessage()
        assert "garbage.bin" in msg
        assert "size=" in msg
        assert both_failed[0].levelno == logging.ERROR
        assert both_failed[0].exc_info is not None

    def test_pdfplumber_happy_path_does_not_log_at_warning(self, caplog):
        """No pdfplumber failure, no pypdfium2 fallback — should be silent."""

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
    def test_double_failure_returns_zero_and_logs(self, caplog, monkeypatch):
        _install_fake_pdfplumber(RuntimeError("count-boom"))
        _install_fake_pdfium(monkeypatch, RuntimeError("count-boom"))

        with caplog.at_level(logging.WARNING, logger="app.modules.takeoff.service"):
            n = _count_pdf_pages(b"%PDF-garbage", filename="junk.pdf")

        assert n == 0

        both_failed = [
            rec
            for rec in caplog.records
            if "takeoff.pdf_count" in rec.getMessage() and "both pdfplumber and pypdfium2 failed" in rec.getMessage()
        ]
        assert both_failed
        assert "junk.pdf" in both_failed[0].getMessage()
        assert both_failed[0].levelno == logging.ERROR

    def test_fallback_to_pdfium_emits_warning(self, caplog, monkeypatch):
        _install_fake_pdfplumber(RuntimeError("count-boom"))
        _install_fake_pdfium(monkeypatch, None, pages=7)

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
    async def test_unparseable_pdf_raises_generic_http_and_logs_server_side(self, monkeypatch, caplog, tmp_path):
        """A definitively unreadable PDF → generic 400, no server-side leak.

        The isolated worker ran cleanly (exit 0) but neither parser could read
        a single page (``page_count == 0``, no pages), so the upload is
        rejected with a generic message and the bytes we wrote are cleaned up.
        The parser's own diagnostics now live in the child's stderr; the
        parent logs the rejection summary.
        """
        import subprocess

        monkeypatch.setattr(takeoff_service, "_takeoff_documents_dir", lambda: tmp_path / "td")

        def _fake_worker(pdf_path, *, max_pages, timeout_s):
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b'{"page_count": 0, "pages": [], "truncated": false}',
                stderr=b"",
            )

        monkeypatch.setattr(takeoff_service, "_run_pdf_worker", _fake_worker)

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
        assert "pypdfium2" not in detail
        assert "Traceback" not in detail
        assert "Failed to parse" in detail

        # Parent-side rejection summary is logged. The filename appears
        # server-side (logs are server-only) but not in the user-facing detail.
        rejection = [rec for rec in caplog.records if "rejecting upload" in rec.getMessage()]
        assert rejection, "rejection summary not logged"
        assert rejection[0].levelno == logging.WARNING
        assert "weird.pdf" in rejection[0].getMessage()


# ---------------------------------------------------------------------------
# Sanity: logger name matches module path
# ---------------------------------------------------------------------------


def test_logger_namespace():
    assert takeoff_service.logger.name == "app.modules.takeoff.service"
