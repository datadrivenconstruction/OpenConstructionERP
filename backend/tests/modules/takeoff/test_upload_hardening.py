# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Upload hardening: a PDF upload can never OOM-kill the API process.

These are DB-free unit tests. They exercise:

* the out-of-process PDF parser (``pdf_extract_worker``): its JSON contract on
  a real tiny PDF, page truncation, and the vector-density guard that stops
  ``extract_tables`` from OOM-ing on a dense CAD sheet;
* the service upload path: the finite size cap (413), the isolated real
  subprocess round-trip, and graceful degradation when the isolated parser
  times out / crashes (the document must still persist);
* the router bounded read: an over-cap upload is rejected 413 after reading at
  most ``cap + 1`` bytes, never the whole (potentially multi-GB) body.
"""

from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.takeoff import pdf_extract_worker, service
from app.modules.takeoff.pdf_extract_worker import (
    VECTOR_DENSITY_LIMIT,
    extract_pdf_data,
    is_vector_dense,
    page_object_count,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tiny_pdf(path, *, texts: list[str] | None = None) -> None:
    """Write a minimal, real PDF (one page per text) to ``path`` via reportlab."""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=(595, 842))
    for text in texts or ["Hello Takeoff 12345"]:
        c.setFont("Helvetica", 11)
        c.drawString(72, 842 - 72, text)
        c.showPage()
    c.save()


def _make_service():
    """A ``TakeoffService`` with a mocked session and an echo repository."""
    svc = object.__new__(service.TakeoffService)
    svc.session = MagicMock()
    svc.measurement_repo = MagicMock()

    class _Repo:
        async def create(self, doc):
            return doc

    svc.repo = _Repo()
    return svc


_OWNER = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Vector-density guard (unit-tested directly) — requirement (d)
# ---------------------------------------------------------------------------


class TestVectorDensityGuard:
    def test_object_count_from_objects_dict(self):
        page = MagicMock()
        page.objects = {"char": [0] * 3, "line": [0] * 2, "rect": [0], "curve": [0] * 4}
        assert page_object_count(page) == 10

    def test_object_count_fallback_accessors(self):
        class _P:
            chars = [0] * 5
            lines = [0] * 2

        # rects / curves / edges absent → counted as 0.
        assert page_object_count(_P()) == 7

    def test_object_count_unknown_object_is_zero(self):
        assert page_object_count(object()) == 0

    def test_is_vector_dense_threshold(self):
        assert is_vector_dense(VECTOR_DENSITY_LIMIT) is False
        assert is_vector_dense(VECTOR_DENSITY_LIMIT + 1) is True
        assert is_vector_dense(10, threshold=5) is True

    def test_extract_skips_tables_on_dense_page(self, monkeypatch, tmp_path):
        """A vector-dense page must NOT call extract_tables (the OOM op)."""
        import sys
        import types

        calls = {"tables": 0}

        class _DensePage:
            objects = {"char": [0] * (VECTOR_DENSITY_LIMIT + 1)}

            def extract_tables(self):
                calls["tables"] += 1
                return [[["should", "not", "run"]]]

            def extract_text(self):
                return "DENSE PAGE TEXT"

        class _Pdf:
            pages = [_DensePage()]

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        fake = types.ModuleType("pdfplumber")
        fake.open = lambda _p: _Pdf()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pdfplumber", fake)

        result = extract_pdf_data(str(tmp_path / "dense.pdf"), None)

        assert calls["tables"] == 0, "extract_tables must be skipped on a dense page"
        assert result["pages"][0]["text"] == "DENSE PAGE TEXT"
        assert result["pages"][0]["tables"] == []

    def test_extract_uses_tables_on_sparse_page(self, monkeypatch, tmp_path):
        """A sparse page still runs extract_tables and preserves the result."""
        import sys
        import types

        calls = {"tables": 0}

        class _SparsePage:
            objects = {"char": [0] * 10}

            def extract_tables(self):
                calls["tables"] += 1
                return [[["a", "b"]]]

            def extract_text(self):
                return "unused"

        class _Pdf:
            pages = [_SparsePage()]

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        fake = types.ModuleType("pdfplumber")
        fake.open = lambda _p: _Pdf()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pdfplumber", fake)

        result = extract_pdf_data(str(tmp_path / "sparse.pdf"), None)

        assert calls["tables"] == 1
        # extract_tables returns a list of tables; each table is kept as-is,
        # so one table [["a", "b"]] lands as [[["a", "b"]]] in the page.
        assert result["pages"][0]["tables"] == [[["a", "b"]]]


# ---------------------------------------------------------------------------
# Worker JSON contract & entry point
# ---------------------------------------------------------------------------


class TestWorkerContract:
    def test_extract_contract_on_tiny_pdf(self, tmp_path):
        pdf = tmp_path / "tiny.pdf"
        _make_tiny_pdf(pdf)
        result = extract_pdf_data(str(pdf), None, filename="tiny.pdf")

        assert result["page_count"] == 1
        assert result["truncated"] is False
        pages = result["pages"]
        assert len(pages) == 1
        page = pages[0]
        assert set(page) >= {"page", "text", "tables", "has_text"}
        assert page["page"] == 1
        assert "Hello" in page["text"]
        assert page["has_text"] is True
        assert isinstance(page["tables"], list)

    def test_extract_truncates_to_max_pages(self, tmp_path):
        pdf = tmp_path / "multi.pdf"
        _make_tiny_pdf(pdf, texts=["Page one", "Page two", "Page three"])
        result = extract_pdf_data(str(pdf), 2, filename="multi.pdf")

        assert result["page_count"] == 3
        assert len(result["pages"]) == 2
        assert result["truncated"] is True

    @staticmethod
    def _run_worker(argv: list[str]) -> subprocess.CompletedProcess:
        """Run the entry point in a child interpreter, the way the service does.

        ``main()`` starts by capping its own address space with ``RLIMIT_AS``,
        which is correct for the worker and ruinous for whoever calls it
        in-process: the cap lands on the test runner and is never lifted.
        ``setrlimit`` does not look at what is already mapped, so the call
        itself succeeds and it is the *next* allocation that dies. On the
        nightly full suite this starved the interpreter into a ``MemoryError``
        raised through ``sys.unraisablehook``, which belongs to no test and so
        could not be attributed to one, and the shard then sat wedged until the
        120 minute job ceiling. It is a no-op on Windows, so only the POSIX
        runners paid. Launching a child keeps the cap where it belongs and
        exercises the same ``python -m`` path the service uses in production.
        """
        return subprocess.run(
            [sys.executable, "-m", "app.modules.takeoff.pdf_extract_worker", *argv],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(service._backend_root()),
            env=service._pdf_worker_env(),
            check=False,
        )

    def test_main_emits_json_and_exits_zero(self, tmp_path):
        pdf = tmp_path / "tiny.pdf"
        _make_tiny_pdf(pdf)
        proc = self._run_worker([str(pdf), "10"])
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data["page_count"] == 1
        assert "Hello" in data["pages"][0]["text"]

    def test_main_missing_input_exits_nonzero(self, tmp_path):
        assert self._run_worker([str(tmp_path / "nope.pdf")]).returncode == 3

    def test_main_no_args_exits_nonzero(self):
        # Returns before the memory cap is applied, but goes through the child
        # too: a reordering inside main() must not quietly re-arm the trap.
        assert self._run_worker([]).returncode == 2

    def test_mem_cap_default_and_clamp(self, monkeypatch):
        monkeypatch.delenv("OE_TAKEOFF_PARSE_MEM_MB", raising=False)
        assert pdf_extract_worker._parse_mem_cap_mb() == 1536
        monkeypatch.setenv("OE_TAKEOFF_PARSE_MEM_MB", "50")
        assert pdf_extract_worker._parse_mem_cap_mb() == 256  # floor
        monkeypatch.setenv("OE_TAKEOFF_PARSE_MEM_MB", "999999")
        assert pdf_extract_worker._parse_mem_cap_mb() == 8192  # ceiling
        monkeypatch.setenv("OE_TAKEOFF_PARSE_MEM_MB", "garbage")
        assert pdf_extract_worker._parse_mem_cap_mb() == 1536


# ---------------------------------------------------------------------------
# Service: isolated parse round-trip & normal upload — requirement (a)
# ---------------------------------------------------------------------------


class TestIsolatedParse:
    @pytest.mark.asyncio
    async def test_parse_pdf_isolated_real_subprocess(self, tmp_path):
        """The real ``python -m ...pdf_extract_worker`` child parses a PDF."""
        pdf = tmp_path / "tiny.pdf"
        _make_tiny_pdf(pdf)
        result = await service._parse_pdf_isolated(pdf, filename="tiny.pdf")
        assert result is not None
        page_count, pages, truncated, reader_error = result
        assert page_count == 1
        assert "Hello" in pages[0]["text"]
        assert truncated is False
        assert reader_error is None

    @pytest.mark.asyncio
    async def test_upload_persists_pages_text_and_tables(self, monkeypatch, tmp_path):
        monkeypatch.setattr(service, "_takeoff_documents_dir", lambda: tmp_path / "td")

        async def _fake_parse(*_a, **_k):
            return (
                2,
                [
                    {"page": 1, "text": "Bill of quantities", "tables": [["Item", "Qty"]], "has_text": True},
                    {"page": 2, "text": "notes", "tables": [], "has_text": True},
                ],
                False,
                None,
            )

        monkeypatch.setattr(service, "_parse_pdf_isolated", _fake_parse)

        svc = _make_service()
        content = b"%PDF-1.4\n" + b"body"
        doc = await svc.upload_document(
            filename="boq.pdf",
            content=content,
            size_bytes=len(content),
            owner_id=_OWNER,
        )

        assert doc.pages == 2
        assert "Bill of quantities" in doc.extracted_text
        assert doc.page_data[0]["tables"] == [["Item", "Qty"]]
        assert doc.status == "uploaded"


# ---------------------------------------------------------------------------
# Service: size cap (413) — requirement (b)
# ---------------------------------------------------------------------------


class TestSizeCap:
    @pytest.mark.asyncio
    async def test_over_cap_upload_rejected_413_without_parsing(self, monkeypatch, tmp_path):
        """An over-cap payload returns 413 and the parser is never launched."""
        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "1")  # 1 MB cap
        monkeypatch.setattr(service, "_takeoff_documents_dir", lambda: tmp_path / "td")

        def _must_not_run(*_a, **_k):
            raise AssertionError("worker must not run for an over-cap upload")

        monkeypatch.setattr(service, "_run_pdf_worker", _must_not_run)

        svc = _make_service()
        payload = b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024)  # 2 MB > 1 MB cap
        with pytest.raises(HTTPException) as exc:
            await svc.upload_document(
                filename="big.pdf",
                content=payload,
                size_bytes=len(payload),
                owner_id=_OWNER,
            )
        assert exc.value.status_code == 413

    @pytest.mark.asyncio
    async def test_router_bounds_read_and_rejects_oversize(self, monkeypatch):
        """The route reads at most cap+1 bytes and rejects an over-cap upload."""
        from app.modules.takeoff import router as takeoff_router

        monkeypatch.setenv("OE_TAKEOFF_MAX_UPLOAD_MB", "1")  # cap = 1 MB
        monkeypatch.setattr(takeoff_router.upload_limiter, "is_allowed", lambda _uid: (True, None))
        cap = service._max_upload_bytes()

        class _FakeUpload:
            def __init__(self, avail: int) -> None:
                self.filename = "huge.pdf"
                self.read_calls: list[int] = []
                self._avail = avail

            async def read(self, n: int = -1) -> bytes:
                self.read_calls.append(n)
                size = self._avail if n is None or n < 0 else min(n, self._avail)
                return b"%PDF-" + b"x" * (max(size, 5) - 5)

        up = _FakeUpload(cap + 100)
        with pytest.raises(HTTPException) as exc:
            await takeoff_router.upload_document(
                user_id=_OWNER,
                file=up,  # type: ignore[arg-type]
                project_id=None,
                service=None,  # type: ignore[arg-type] - not reached before 413
                session=None,
            )

        assert exc.value.status_code == 413
        # Bounded: asked for exactly cap+1, never an unbounded read(-1).
        assert up.read_calls == [cap + 1]
        assert -1 not in up.read_calls


# ---------------------------------------------------------------------------
# Service: graceful degradation — requirement (c)
# ---------------------------------------------------------------------------


class TestDegradeOnWorkerFailure:
    @pytest.mark.asyncio
    async def test_upload_persists_when_worker_times_out(self, monkeypatch, tmp_path):
        monkeypatch.setattr(service, "_takeoff_documents_dir", lambda: tmp_path / "td")

        def _timeout(_path, *, max_pages, timeout_s):
            raise subprocess.TimeoutExpired(cmd="worker", timeout=timeout_s)

        monkeypatch.setattr(service, "_run_pdf_worker", _timeout)

        svc = _make_service()
        content = b"%PDF-1.4\n" + b"body"
        doc = await svc.upload_document(
            filename="slow.pdf",
            content=content,
            size_bytes=len(content),
            owner_id=_OWNER,
        )

        # Persisted, not raised - the user keeps their upload.
        assert doc is not None
        assert doc.pages == 0
        assert doc.page_data == []
        assert doc.metadata_.get("parse_degraded") is True
        # The bytes are on disk even though extraction was skipped.
        assert (tmp_path / "td" / f"{doc.id}.pdf").exists()

    @pytest.mark.asyncio
    async def test_upload_persists_when_worker_exits_nonzero(self, monkeypatch, tmp_path):
        monkeypatch.setattr(service, "_takeoff_documents_dir", lambda: tmp_path / "td")

        def _nonzero(_path, *, max_pages, timeout_s):
            return subprocess.CompletedProcess(args=[], returncode=137, stdout=b"", stderr=b"Killed")

        monkeypatch.setattr(service, "_run_pdf_worker", _nonzero)

        svc = _make_service()
        content = b"%PDF-1.4\n" + b"body"
        doc = await svc.upload_document(
            filename="crash.pdf",
            content=content,
            size_bytes=len(content),
            owner_id=_OWNER,
        )

        assert doc is not None
        assert doc.pages == 0
        assert doc.metadata_.get("parse_degraded") is True

    @pytest.mark.asyncio
    async def test_definitive_parse_failure_still_400(self, monkeypatch, tmp_path):
        """Worker ran fine (exit 0) but no page readable → 400, bytes cleaned up."""
        monkeypatch.setattr(service, "_takeoff_documents_dir", lambda: tmp_path / "td")

        def _empty(_path, *, max_pages, timeout_s):
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b'{"page_count": 0, "pages": [], "truncated": false}',
                stderr=b"",
            )

        monkeypatch.setattr(service, "_run_pdf_worker", _empty)

        svc = _make_service()
        content = b"%PDF-1.4\n" + b"unreadable"
        with pytest.raises(HTTPException) as exc:
            await svc.upload_document(
                filename="empty.pdf",
                content=content,
                size_bytes=len(content),
                owner_id=_OWNER,
            )
        assert exc.value.status_code == 400
        # No orphaned bytes left behind on the definitive-failure path.
        td = tmp_path / "td"
        leftover = list(td.glob("*.pdf")) if td.exists() else []
        assert leftover == []
