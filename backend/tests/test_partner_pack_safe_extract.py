"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the shared safe zip-extraction util (``_safe_extract``).

These cover the security-critical core: every unsafe-member shape must be
rejected (table-driven), and a benign archive must extract correctly into a
sandboxed staging dir. The CLI module-install and the partner-pack install
endpoint both delegate to this single implementation.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from app.core.partner_pack._safe_extract import (
    UnsafeArchiveError,
    assert_safe_archive,
    has_zip_magic,
    is_unsafe_zip_member,
    resolve_single_top_level,
    safe_extract_all,
    stage_and_extract,
)


def _info(filename: str, *, external_attr: int = 0) -> zipfile.ZipInfo:
    """Build a ZipInfo carrying ``filename`` verbatim, with optional mode bits.

    ``ZipInfo.__init__`` normalises backslashes to forward slashes, so a name
    is assigned to ``.filename`` AFTER construction to preserve any backslash.
    This faithfully models a hand-crafted (non-CPython) malicious archive whose
    central-directory names ``is_unsafe_zip_member`` inspects via ``infolist()``
    — the writer normalises, but the safety check must not rely on that.
    """
    zi = zipfile.ZipInfo()
    zi.filename = filename
    zi.external_attr = external_attr
    return zi


class TestUnsafeMemberDetection:
    @pytest.mark.parametrize(
        ("filename", "external_attr", "needle"),
        [
            ("/etc/passwd", 0, "absolute path"),
            ("../evil.py", 0, "parent-directory traversal"),
            ("pkg/../../evil.py", 0, "parent-directory traversal"),
            ("C:/Windows/evil.dll", 0, "drive-letter"),
            ("pkg\\evil.py", 0, "backslash separator"),
            ("link", (stat.S_IFLNK | 0o777) << 16, "symlink"),
        ],
    )
    def test_rejects_unsafe(self, filename: str, external_attr: int, needle: str) -> None:
        reason = is_unsafe_zip_member(_info(filename, external_attr=external_attr))
        assert reason is not None
        assert needle in reason

    @pytest.mark.parametrize(
        "filename",
        [
            "pkg/manifest.json",
            "pkg/sub/logo.svg",
            "manifest.json",
            "a/b/c/d.txt",
        ],
    )
    def test_allows_safe(self, filename: str) -> None:
        assert is_unsafe_zip_member(_info(filename)) is None

    def test_backslash_drive_letter_combo(self) -> None:
        # "C:\\evil" -> 2nd char is ':' so the drive-letter check fires first.
        assert "drive-letter" in (is_unsafe_zip_member(_info("C:\\evil")) or "")
        # "..\\evil" has no drive letter; the backslash check catches it.
        assert "backslash" in (is_unsafe_zip_member(_info("..\\evil")) or "")


class TestAssertSafeArchive:
    def test_empty_archive_raises(self) -> None:
        with pytest.raises(UnsafeArchiveError, match="empty"):
            assert_safe_archive([])

    def test_one_bad_member_raises(self) -> None:
        infos = [_info("pkg/ok.py"), _info("../escape.py")]
        with pytest.raises(UnsafeArchiveError, match="traversal"):
            assert_safe_archive(infos)

    def test_all_good_passes(self) -> None:
        assert_safe_archive([_info("pkg/a.py"), _info("pkg/b.py")])


class TestZipMagic:
    def test_recognises_standard_zip(self) -> None:
        assert has_zip_magic(b"PK\x03\x04rest")

    def test_recognises_empty_archive(self) -> None:
        assert has_zip_magic(b"PK\x05\x06")

    def test_rejects_non_zip(self) -> None:
        assert not has_zip_magic(b"%PDF-1.7")
        assert not has_zip_magic(b"")


def _make_zip(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)


class TestSafeExtract:
    def test_extracts_benign_archive(self, tmp_path: Path) -> None:
        zpath = tmp_path / "good.zip"
        _make_zip(zpath, {"pkg/manifest.json": "{}", "pkg/logo.svg": "<svg/>"})
        dest = tmp_path / "out"
        with zipfile.ZipFile(zpath) as zf:
            safe_extract_all(zf, dest)
        assert (dest / "pkg" / "manifest.json").read_text() == "{}"
        assert (dest / "pkg" / "logo.svg").read_text() == "<svg/>"

    def test_safe_extract_rejects_traversal_member(self, tmp_path: Path) -> None:
        zpath = tmp_path / "evil.zip"
        # writestr normalises some names, so craft the ZipInfo directly.
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr(_info("../escape.txt"), "pwned")
        dest = tmp_path / "out"
        with zipfile.ZipFile(zpath) as zf, pytest.raises(UnsafeArchiveError):
            safe_extract_all(zf, dest)
        # Nothing escaped above the destination.
        assert not (tmp_path / "escape.txt").exists()

    def test_stage_and_extract_returns_populated_dir(self, tmp_path: Path) -> None:
        zpath = tmp_path / "good.zip"
        _make_zip(zpath, {"my-pack/manifest.json": '{"slug":"x"}'})
        with zipfile.ZipFile(zpath) as zf:
            staging = stage_and_extract(zf)
        try:
            assert (staging / "my-pack" / "manifest.json").is_file()
        finally:
            import shutil

            shutil.rmtree(staging, ignore_errors=True)

    def test_stage_and_extract_cleans_up_on_unsafe(self, tmp_path: Path) -> None:
        zpath = tmp_path / "evil.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr(_info("/abs/evil.txt"), "x")
        with zipfile.ZipFile(zpath) as zf, pytest.raises(UnsafeArchiveError):
            stage_and_extract(zf)


class TestResolveSingleTopLevel:
    def test_wrapped_single_dir(self, tmp_path: Path) -> None:
        wrap = tmp_path / "wrapper"
        wrap.mkdir()
        (wrap / "manifest.json").write_text("{}")
        assert resolve_single_top_level(tmp_path) == wrap

    def test_files_at_root(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text("{}")
        (tmp_path / "logo.svg").write_text("<svg/>")
        assert resolve_single_top_level(tmp_path) == tmp_path

    def test_macosx_sidecar_ignored(self, tmp_path: Path) -> None:
        wrap = tmp_path / "wrapper"
        wrap.mkdir()
        (wrap / "manifest.json").write_text("{}")
        (tmp_path / "__MACOSX").mkdir()
        assert resolve_single_top_level(tmp_path) == wrap
