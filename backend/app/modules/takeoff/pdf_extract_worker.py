# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Out-of-process PDF text/table extractor for takeoff uploads.

Why this runs in a child process
---------------------------------
The takeoff upload endpoint used to parse the PDF *inside the API worker
process*. On a container running a single uvicorn worker as PID 1 with no
memory limit, one large vector-dense CAD sheet driving pdfplumber's
``extract_tables`` past available RAM got the whole process OOM-killed
(SIGKILL, no traceback), taking every connected user down at once. A
malformed PDF that segfaults the native MuPDF / pdfminer C layer is the
same class of no-log kill.

This module is the isolated child. The API process runs it via::

    python -m app.modules.takeoff.pdf_extract_worker <pdf_path> <max_pages>

with a wall-clock timeout, and on POSIX the child self-caps its address
space with ``RLIMIT_AS`` so a runaway parse dies cleanly (non-zero exit)
instead of driving the *host* into the kernel OOM killer. A crash, an OOM
or a native segfault in here kills only this child; the API keeps serving
and the caller degrades gracefully.

Output contract (a single JSON object on stdout)::

    {
      "page_count": int,          # true total pages, even if truncated
      "pages": [
        {"page": int, "text": str,
         "tables": [[[str, ...], ...], ...], "has_text": bool},
        ...
      ],
      "truncated": bool           # True when page_count > len(pages)
    }

``page_count`` is the true total page count even when only ``max_pages``
pages were extracted (``truncated`` is then True). A hard failure prints a
short reason to stderr and exits non-zero; a PDF that simply cannot be read
by either parser exits 0 with ``page_count == 0`` and an empty ``pages``
list (the caller maps that to a "could not parse" response).

The module imports only the standard library plus the two PDF parsers
(lazily), so it ships in the wheel and starts fast without pulling the DB
or web stack into the child.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

# Above this many vector primitives on a single page, skip ``extract_tables``
# (pdfplumber's most memory-hungry operation) and fall back to plain text.
# A dense CAD sheet can carry hundreds of thousands of line / rect / char
# objects; running the table finder across all of them is the exact
# allocation spike that OOM-killed the API process. Text extraction on the
# same page is cheap and safe, so a dense page still yields its text.
VECTOR_DENSITY_LIMIT = 50_000

_DEFAULT_PARSE_MEM_MB = 1536
_MIN_PARSE_MEM_MB = 256
_MAX_PARSE_MEM_MB = 8192


def _parse_mem_cap_mb() -> int:
    """Return the child address-space cap in MB from the environment.

    Reads ``OE_TAKEOFF_PARSE_MEM_MB``. Defaults to 1536 MB and is clamped to
    ``[256, 8192]``. An unset, empty or unparseable value falls back to the
    default, so a misconfiguration can never remove the cap entirely.
    """
    raw = os.environ.get("OE_TAKEOFF_PARSE_MEM_MB", "").strip()
    if not raw:
        return _DEFAULT_PARSE_MEM_MB
    try:
        mb = int(raw)
    except (ValueError, TypeError):
        return _DEFAULT_PARSE_MEM_MB
    return max(_MIN_PARSE_MEM_MB, min(_MAX_PARSE_MEM_MB, mb))


def _apply_memory_rlimit() -> None:
    """Cap this process's virtual address space on POSIX (``RLIMIT_AS``).

    Once set, a runaway allocation raises ``MemoryError`` or the child is
    killed with a non-zero exit instead of pushing the *host* into the OOM
    killer. This is a no-op on Windows (no ``resource`` module / no
    ``setrlimit``), where the API is not deployed as the single-PID
    container that the cap protects. If the limit cannot be set we log and
    continue uncapped, relying on the parent's wall-clock timeout as the
    remaining backstop.
    """
    if sys.platform == "win32":
        return
    try:
        import resource
    except ImportError:
        return
    if not hasattr(resource, "setrlimit") or not hasattr(resource, "RLIMIT_AS"):
        return
    cap = _parse_mem_cap_mb() * 1024 * 1024
    try:
        _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        # Never raise an existing (lower) hard limit; clamp our cap under it.
        new_hard = cap if hard == resource.RLIM_INFINITY else min(cap, hard)
        resource.setrlimit(resource.RLIMIT_AS, (min(cap, new_hard), new_hard))
    except (ValueError, OSError):
        logger.warning("pdf_extract_worker: could not set RLIMIT_AS", exc_info=True)


# ── Vector-density guard (unit-tested directly) ─────────────────────────────


def page_object_count(page: object) -> int:
    """Count the vector primitives on a pdfplumber page.

    Sums chars, lines, rects and curves from ``page.objects`` (a pdfplumber
    dict keyed by object type), falling back to the typed list accessors
    (``page.chars`` etc.) when ``objects`` is not a dict. Every access is
    guarded with a default so a stub or non-pdfplumber page-like object
    counts as 0 (treated as not dense) instead of raising - which keeps the
    guard safe for tests and unusual inputs.

    Args:
        page: A pdfplumber ``Page`` (or any object exposing ``objects`` /
            the typed accessors).

    Returns:
        The total number of vector primitives found, or 0 when none of the
        expected accessors are present.
    """
    objects = getattr(page, "objects", None)
    if isinstance(objects, dict):
        return sum(len(objects.get(key) or ()) for key in ("char", "line", "rect", "curve"))
    total = 0
    for attr in ("chars", "lines", "rects", "curves", "edges"):
        try:
            total += len(getattr(page, attr, None) or ())
        except TypeError:
            continue
    return total


def is_vector_dense(object_count: int, *, threshold: int = VECTOR_DENSITY_LIMIT) -> bool:
    """Return True when a page is too dense for a safe ``extract_tables``.

    Args:
        object_count: The page's vector-primitive count from
            :func:`page_object_count`.
        threshold: The density above which the table finder is skipped.
            Defaults to :data:`VECTOR_DENSITY_LIMIT`.

    Returns:
        ``True`` when ``object_count`` exceeds ``threshold``.
    """
    return object_count > threshold


# ── Parsing ─────────────────────────────────────────────────────────────────


def _fingerprint(pdf_path: str, filename: str | None) -> str:
    """Build a short, path-free diagnostic string for a PDF on disk.

    Includes the caller-supplied filename hint and the on-disk byte size,
    mirroring the service-side fingerprint so a production log line can be
    triaged without access to the bytes. Never emits the absolute temp path.
    """
    try:
        size = Path(pdf_path).stat().st_size
    except OSError:
        size = 0
    name_hint = filename or "<anonymous>"
    return f"filename={name_hint!r} size={size}B"


def _resolve_page_limit(total: int, max_pages: int | None) -> int:
    """Clamp the number of pages to extract to ``[0, total]``.

    ``max_pages`` of ``None`` or ``<= 0`` means "all pages".
    """
    if max_pages is None or max_pages <= 0:
        return total
    return min(total, max_pages)


def count_pdf_pages(pdf_path: str, *, filename: str | None = None) -> int:
    """Count the pages in a PDF - pdfplumber first, pypdfium2 as a fallback.

    Both failure paths log the input fingerprint so an operator can
    correlate the log line with the upload without leaking the bytes. Returns
    0 when both parsers fail (failure-safe, matching the historical
    contract).
    """
    fp = _fingerprint(pdf_path, filename)
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except Exception:
        logger.warning(
            "takeoff.pdf_count pdfplumber failed (%s) - falling back to pypdfium2",
            fp,
            exc_info=True,
        )
        try:
            from app.core import pdf_reader

            return pdf_reader.page_count(Path(pdf_path).read_bytes())
        except Exception:
            logger.exception(
                "takeoff.pdf_count both pdfplumber and pypdfium2 failed (%s) - reporting zero pages",
                fp,
            )
            return 0


def _extract_with_pdfium(pdf_path: str, max_pages: int | None, fp: str) -> dict:
    """Fallback extractor: pypdfium2 text-only (no tables).

    Used when pdfplumber raises. PDFium is a different parser from pdfminer,
    so a file pdfplumber cannot read often still opens here. Returns the same
    dict contract as :func:`extract_pdf_data`; on its own failure the
    double-failure line is logged and an empty result returned.
    """
    try:
        from app.core import pdf_reader

        with pdf_reader.open_pdf(Path(pdf_path).read_bytes()) as doc:
            total = doc.page_count
            limit = _resolve_page_limit(total, max_pages)
            pages: list[dict] = []
            empty = 0
            for i in range(limit):
                page = doc[i]
                text = page.text() or ""
                page.close()
                has_text = bool(text.strip())
                if not has_text:
                    empty += 1
                pages.append({"page": i + 1, "text": text.strip(), "tables": [], "has_text": has_text})
        if empty:
            logger.info(
                "takeoff.pdf_extract pypdfium2: %d of %d page(s) had no text layer "
                "(likely scanned - OCR needed to recover content) (%s)",
                empty,
                len(pages),
                fp,
            )
        return {"page_count": total, "pages": pages, "truncated": limit < total}
    except Exception as exc:
        logger.exception(
            "takeoff.pdf_extract both pdfplumber and pypdfium2 failed (%s) - document will have no extracted pages",
            fp,
        )
        # The traceback above goes to this child's stderr, which the parent
        # only reads on a non-zero exit - and this path exits 0. So the reason
        # travels in the result instead, or an operator whose reader is simply
        # broken sees nothing but "check the file".
        return {
            "page_count": 0,
            "pages": [],
            "truncated": False,
            "reader_error": f"{type(exc).__name__}: {exc}"[:300],
        }


def extract_pdf_data(pdf_path: str, max_pages: int | None = None, *, filename: str | None = None) -> dict:
    """Extract text and tables from a PDF on disk, page by page.

    pdfplumber is used first. For each of the first ``max_pages`` pages
    (``None`` / ``<= 0`` means all pages) the page's vector-primitive density
    is measured via :func:`page_object_count`; when it exceeds
    :data:`VECTOR_DENSITY_LIMIT` the memory-hungry ``extract_tables`` call is
    skipped and only the plain text is taken (this is the exact operation
    that OOM-killed the server on dense CAD sheets). If pdfplumber raises,
    the whole document falls back to pypdfium2 text extraction.

    Args:
        pdf_path: Path to the PDF file on disk.
        max_pages: Maximum pages to extract; ``None`` / ``<= 0`` means all.
        filename: Optional original filename, used only for the log
            fingerprint.

    Returns:
        A dict with ``page_count`` (true total), ``pages`` (up to
        ``max_pages`` entries) and ``truncated``. Never raises for a parse
        failure - an unreadable document returns ``page_count == 0`` with an
        empty ``pages`` list and a ``reader_error`` string naming the
        exception that ended both attempts.
    """
    fp = _fingerprint(pdf_path, filename)
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            all_pages = pdf.pages
            total = len(all_pages)
            limit = _resolve_page_limit(total, max_pages)
            pages: list[dict] = []
            empty = 0
            for i in range(limit):
                page = all_pages[i]
                page_text = ""
                page_tables: list[list[list[str]]] = []

                if is_vector_dense(page_object_count(page)):
                    # Dense CAD sheet: skip the table finder, keep the text.
                    text = page.extract_text()
                    if text:
                        page_text = text
                else:
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            cleaned = [[str(cell or "") for cell in row] for row in table]
                            page_tables.append(cleaned)
                            for row in cleaned:
                                page_text += "\t".join(row) + "\n"
                    else:
                        text = page.extract_text()
                        if text:
                            page_text = text

                has_text = bool(page_text.strip())
                if not has_text:
                    empty += 1
                pages.append(
                    {
                        "page": i + 1,
                        "text": page_text.strip(),
                        "tables": page_tables,
                        "has_text": has_text,
                    }
                )
            if empty:
                logger.info(
                    "takeoff.pdf_extract pdfplumber: %d of %d page(s) had no text "
                    "(likely scanned - OCR needed to recover content) (%s)",
                    empty,
                    len(pages),
                    fp,
                )
        return {"page_count": total, "pages": pages, "truncated": limit < total}
    except Exception:
        logger.warning(
            "takeoff.pdf_extract pdfplumber failed (%s) - falling back to pypdfium2",
            fp,
            exc_info=True,
        )
        return _extract_with_pdfium(pdf_path, max_pages, fp)


# ── Entry point ─────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    """Run the extractor as a subprocess and emit JSON on stdout.

    Usage: ``pdf_extract_worker <pdf_path> [max_pages]``.

    Applies the POSIX memory cap first, then extracts. Returns 0 on success
    (including the "unreadable document" case, which is a valid JSON result
    with 0 pages), and a non-zero code on a usage error, a missing input, an
    out-of-memory kill or an unexpected failure.
    """
    if not argv:
        print("usage: pdf_extract_worker <pdf_path> [max_pages]", file=sys.stderr)
        return 2

    pdf_path = argv[0]
    max_pages: int | None = None
    if len(argv) >= 2:
        try:
            max_pages = int(argv[1])
        except (ValueError, TypeError):
            max_pages = None

    _apply_memory_rlimit()

    if not Path(pdf_path).is_file():
        print(f"pdf_extract_worker: input not found: {pdf_path}", file=sys.stderr)
        return 3

    try:
        result = extract_pdf_data(pdf_path, max_pages)
    except MemoryError:
        # RLIMIT_AS tripped inside our own guard - report a clean failure.
        print("pdf_extract_worker: out of memory (RLIMIT_AS reached)", file=sys.stderr)
        return 4
    except Exception as exc:  # pragma: no cover - defensive last resort
        print(f"pdf_extract_worker: unexpected failure: {exc}", file=sys.stderr)
        return 1

    try:
        sys.stdout.write(json.dumps(result))
        sys.stdout.flush()
    except (OSError, ValueError, TypeError) as exc:
        print(f"pdf_extract_worker: could not serialise result: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # Minimal logging so child WARNING / ERROR lines land on stderr and show
    # up in container logs (the parent captures and forwards stderr).
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    raise SystemExit(main(sys.argv[1:]))
