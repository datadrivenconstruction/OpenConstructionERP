# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A saved setting must be seen even when the clock did not move.

:mod:`app.core.pdf_appearance` and :mod:`app.core.app_branding` both keep a
process-local cache of their parsed settings file so a PDF export does not
re-read it once per page. Both used to decide whether that cache was still good
by comparing modification times alone, which assumes the filesystem gives two
different contents two different timestamps. Windows does not: two writes in
the same clock tick get a byte-for-byte identical ``st_mtime_ns``, measured at
139 collisions in 200 consecutive pairs on a developer machine. The file
changes, the recorded time does not, and the cache keeps serving the previous
answer until some later save happens to land in a different tick.

For appearance that is worse than a stale render. The PUT endpoint reads the
stored values, merges the admin's fields over them and writes the result back,
so a stale read is persisted: the save that was shadowed is reverted on disk.

These tests force the collision with :func:`os.utime` instead of racing for it,
so the defect reproduces on every platform. Raced, it showed up only on the
Windows lane, which is advisory - the bug would have been guarded by a job that
cannot fail the build.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.core.app_branding import branding_path, read_branding, write_branding
from app.core.pdf_appearance import appearance_path, read_appearance, write_appearance


def _freeze_timestamp(path: Path, taken_from: os.stat_result) -> None:
    """Give *path* the timestamps a previous version of it had."""
    os.utime(path, ns=(taken_from.st_atime_ns, taken_from.st_mtime_ns))


def _assert_only_the_length_gives_it_away(path: Path, before: os.stat_result) -> None:
    """State the premise of the two cross-process tests so it cannot rot.

    Those tests prove the size half of the cache stamp does its job, which only
    means anything while the two contents really are different lengths on disk.
    Picking a longer string is not enough to guarantee that: ``write_text``
    turns every newline into two bytes on Windows, and the first pair chosen
    here landed on 70 bytes each despite differing by a character.
    """
    now = path.stat()
    assert now.st_mtime_ns == before.st_mtime_ns, "the timestamp collision is what is being tested"
    assert now.st_size != before.st_size, "the two contents must differ in length on disk"


# ── appearance ────────────────────────────────────────────────────────


def test_a_second_appearance_save_on_the_same_timestamp_is_still_seen(tmp_path: Path) -> None:
    """The two footers are the same length, so only the write bust can catch this."""
    write_appearance({"footer_text": "alpha"}, tmp_path)
    assert read_appearance(tmp_path)["footer_text"] == "alpha"
    before = appearance_path(tmp_path).stat()

    write_appearance({"footer_text": "omega"}, tmp_path)
    _freeze_timestamp(appearance_path(tmp_path), before)

    assert read_appearance(tmp_path)["footer_text"] == "omega"


def test_an_appearance_file_rewritten_by_another_process_is_still_seen(tmp_path: Path) -> None:
    """A worker cannot be told to forget; a changed length has to give it away.

    The API process busts its own cache when it writes, but a Celery worker
    rendering the export holds a cache of its own and never sees that call.
    """
    write_appearance({"footer_text": "alpha"}, tmp_path)
    assert read_appearance(tmp_path)["footer_text"] == "alpha"
    before = appearance_path(tmp_path).stat()

    # Straight to disk, the way a second process would leave it.
    longer = "a considerably longer footer line than the one before it"
    appearance_path(tmp_path).write_text(json.dumps({"footer_text": longer}), encoding="utf-8")
    _freeze_timestamp(appearance_path(tmp_path), before)

    _assert_only_the_length_gives_it_away(appearance_path(tmp_path), before)
    assert read_appearance(tmp_path)["footer_text"] == longer


def test_a_reset_on_the_same_timestamp_is_still_seen(tmp_path: Path) -> None:
    """Restore defaults unlinks the file, which the cache must not outlive."""
    from app.core.pdf_appearance import DEFAULT_APPEARANCE, reset_appearance

    write_appearance({"footer_text": "alpha"}, tmp_path)
    assert read_appearance(tmp_path)["footer_text"] == "alpha"

    reset_appearance(tmp_path)

    assert read_appearance(tmp_path) == DEFAULT_APPEARANCE


# ── branding ──────────────────────────────────────────────────────────


def test_a_second_branding_save_on_the_same_timestamp_is_still_seen(tmp_path: Path) -> None:
    """Both names are nine characters, so size cannot rescue this one either."""
    write_branding({"mode": "text", "company_name": "Alpha Ltd"}, tmp_path)
    assert read_branding(tmp_path)["company_name"] == "Alpha Ltd"
    before = branding_path(tmp_path).stat()

    write_branding({"mode": "text", "company_name": "Omega Ltd"}, tmp_path)
    _freeze_timestamp(branding_path(tmp_path), before)

    assert read_branding(tmp_path)["company_name"] == "Omega Ltd"


def test_a_branding_file_rewritten_by_another_process_is_still_seen(tmp_path: Path) -> None:
    write_branding({"mode": "text", "company_name": "Alpha Ltd"}, tmp_path)
    assert read_branding(tmp_path)["company_name"] == "Alpha Ltd"
    before = branding_path(tmp_path).stat()

    longer = "A considerably longer company name than the first"
    branding_path(tmp_path).write_text(json.dumps({"mode": "text", "company_name": longer}), encoding="utf-8")
    _freeze_timestamp(branding_path(tmp_path), before)

    _assert_only_the_length_gives_it_away(branding_path(tmp_path), before)
    assert read_branding(tmp_path)["company_name"] == longer
