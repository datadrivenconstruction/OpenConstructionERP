"""A meeting transcript upload is parsed in a worker thread, page by page.

``_extract_text_from_file`` ran pdfplumber on the event loop for up to 50
pages, so every other request waited for the parse, and every parsed page's
layout stayed in memory until the document closed. These tests pin both: the
parse happens on another thread, and each page is released once it is read,
including a page whose extraction fails.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types

import pytest

from app.modules.meetings import router as meetings_router


class _FakePage:
    def __init__(self, text: str | None, *, fail: bool = False) -> None:
        self._text = text
        self._fail = fail
        self.closed = False

    def extract_text(self) -> str | None:
        if self._fail:
            raise ValueError("broken content stream")
        return self._text

    def close(self) -> None:
        self.closed = True


class _FakePdf:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> _FakePdf:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _install_fake_pdfplumber(monkeypatch: pytest.MonkeyPatch, pages: list[_FakePage]) -> list[int]:
    """Replace pdfplumber with one that serves ``pages``; return the threads that opened it."""
    opened_on: list[int] = []

    def _open(_stream: object) -> _FakePdf:
        opened_on.append(threading.get_ident())
        return _FakePdf(pages)

    monkeypatch.setitem(sys.modules, "pdfplumber", types.SimpleNamespace(open=_open))
    return opened_on


def test_a_pdf_transcript_is_parsed_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [_FakePage("Item 1: slab pour moved"), _FakePage(None), _FakePage("Item 2: crane booked")]
    opened_on = _install_fake_pdfplumber(monkeypatch, pages)

    async def _run() -> tuple[str, int]:
        loop_thread = threading.get_ident()
        text = await meetings_router._extract_text_from_file(b"%PDF-1.7", "minutes.pdf")
        return text, loop_thread

    text, loop_thread = asyncio.run(_run())

    assert text == "Item 1: slab pour moved\nItem 2: crane booked"
    assert opened_on and opened_on[0] != loop_thread


def test_every_page_is_released_after_it_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [_FakePage("one"), _FakePage("two"), _FakePage("three")]
    _install_fake_pdfplumber(monkeypatch, pages)

    assert meetings_router._extract_text_sync(b"%PDF-1.7", "minutes.pdf") == "one\ntwo\nthree"
    assert [p.closed for p in pages] == [True, True, True]


def test_a_page_that_fails_to_parse_is_still_released(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [_FakePage("one"), _FakePage(None, fail=True), _FakePage("three")]
    _install_fake_pdfplumber(monkeypatch, pages)

    # A failed page ends the parse with no text, as it did before; the page it
    # failed on is released all the same.
    assert meetings_router._extract_text_sync(b"%PDF-1.7", "minutes.pdf") == ""
    assert pages[0].closed and pages[1].closed
    assert not pages[2].closed


def test_only_the_first_fifty_pages_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [_FakePage(f"p{i}") for i in range(60)]
    _install_fake_pdfplumber(monkeypatch, pages)

    text = meetings_router._extract_text_sync(b"%PDF-1.7", "minutes.pdf")

    assert text.splitlines() == [f"p{i}" for i in range(50)]
    assert all(p.closed for p in pages[:50]) and not any(p.closed for p in pages[50:])


@pytest.mark.parametrize(
    ("content", "expected"),
    [("Protokoll Baubesprechung".encode(), "Protokoll Baubesprechung"), (b"caf\xe9", "caf\xe9")],
)
def test_a_text_transcript_reads_utf8_then_latin1(content: bytes, expected: str) -> None:
    assert asyncio.run(meetings_router._extract_text_from_file(content, "minutes.txt")) == expected
