"""Converter-installer hardening regression — Audit A2 / A9 / A11.

The DDC converter installer pulls binaries from the GitHub Contents API
into ``~/.openestimator/converters/``. A poisoned response could
silently redirect downloads to an attacker-controlled CDN (A2), plant a
symlink at the install target (A9), or balloon the install to fill the
disk (A11). These tests pin the corresponding defences:

* A2: only GitHub-owned hosts are allowed to serve converter files.
* A9: ``_download_one_file`` removes any pre-existing symlink at the
  target before writing (and uses ``O_NOFOLLOW`` on POSIX so a TOCTOU
  symlink replacement is rejected at open time).
* A11: the helper streams in chunks and enforces a per-file byte cap.

All assertions are pure-function — no network calls. The streaming-cap
test uses an in-memory ``urlopen`` shim.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

from app.modules.takeoff.router import (
    _ALLOWED_DOWNLOAD_HOSTS,
    _MAX_DOWNLOAD_BYTES,
    _check_download_url_allowed,
    _download_one_file,
    _verify_pe_executable,
)


def _minimal_pe(pe_off: int = 0x80) -> bytes:
    """Build the smallest buffer that satisfies the PE structural
    checks: 'MZ' at 0, e_lfanew (LE uint32 @0x3C) → ``pe_off``,
    'PE\\0\\0' at ``pe_off``, plus a DOS stub containing real newline
    (0x0A) bytes so a CRLF-mangle replace actually shifts the header
    (mirrors a genuine binary; an all-zero stub would make the
    corruption test a no-op)."""
    buf = bytearray(b"MZ" + b"\x00" * (0x40 - 2))
    buf[0x3C:0x40] = pe_off.to_bytes(4, "little")
    # DOS stub with embedded 0x0A bytes, padded out to pe_off.
    stub = b"This program cannot be run in DOS mode.\x0d\x0a\x0a$"
    buf += stub + b"\x00" * (pe_off - len(buf) - len(stub))
    buf += b"PE\x00\x00" + b"\x00" * 64  # header + padding so size > pe_off+4
    return bytes(buf)


# ── A2: host allow-list --------------------------------------------------


def test_allows_raw_githubusercontent() -> None:
    """The canonical blob-download host must be allowed."""
    _check_download_url_allowed(
        "https://raw.githubusercontent.com/org/repo/main/file.exe"
    )


def test_allows_github_com() -> None:
    """``github.com`` is allowed (Contents API sometimes returns this)."""
    _check_download_url_allowed("https://github.com/org/repo/raw/main/file.exe")


def test_allows_blob_cdn() -> None:
    """objects.githubusercontent.com is GitHub's >5MB blob CDN."""
    _check_download_url_allowed(
        "https://objects.githubusercontent.com/abc/def"
    )


def test_rejects_attacker_cdn() -> None:
    """Any non-GitHub host must be rejected — closes the substitution attack."""
    with pytest.raises(RuntimeError, match="not on the converter allow-list"):
        _check_download_url_allowed(
            "https://attacker.example.com/poisoned.exe"
        )


def test_rejects_lookalike_subdomain() -> None:
    """No fuzzy host matching — ``raw.githubusercontent.com.evil.tld`` must die.

    Python's ``urlparse(...).hostname`` returns the full registered
    name so the substring trick used in some legacy validators doesn't
    apply here, but pin it explicitly.
    """
    with pytest.raises(RuntimeError):
        _check_download_url_allowed(
            "https://raw.githubusercontent.com.evil.tld/file.exe"
        )


def test_rejects_file_scheme() -> None:
    """``file://`` URLs would read from the local filesystem — refuse."""
    with pytest.raises(RuntimeError, match="non-HTTP"):
        _check_download_url_allowed("file:///etc/passwd")


def test_rejects_ftp_scheme() -> None:
    """No non-HTTP(S) schemes regardless of host."""
    with pytest.raises(RuntimeError, match="non-HTTP"):
        _check_download_url_allowed("ftp://raw.githubusercontent.com/x")


def test_allowed_hosts_constant_includes_three_github_hosts() -> None:
    """Catches accidental shrinking of the allow-list during refactors."""
    assert "raw.githubusercontent.com" in _ALLOWED_DOWNLOAD_HOSTS
    assert "github.com" in _ALLOWED_DOWNLOAD_HOSTS
    assert "objects.githubusercontent.com" in _ALLOWED_DOWNLOAD_HOSTS


# ── A11: streaming size cap ----------------------------------------------


class _FakeResponse:
    """Minimal urlopen response stand-in for streaming-cap tests."""

    def __init__(self, body: bytes, content_length: int | None) -> None:
        self._body = io.BytesIO(body)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        self._body.close()


def test_size_cap_constant_is_reasonable() -> None:
    """If someone bumps the cap to a stupid value, fail loudly.

    256 MB <= cap <= 2 GB is the sane band — the largest single
    legitimate file today is the ~140 MB IfcExporter.exe and 2 GB is
    the SQLite blob ceiling.
    """
    assert 256 * 1024 * 1024 <= _MAX_DOWNLOAD_BYTES <= 2 * 1024 * 1024 * 1024


def test_streaming_cap_rejects_oversized_content_length(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Declared Content-Length above the cap must be rejected pre-stream."""
    import urllib.request

    big = _MAX_DOWNLOAD_BYTES + 1024
    fake_resp = _FakeResponse(b"x" * 16, content_length=big)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_a, **_kw: fake_resp,
    )

    target = tmp_path / "out.bin"
    with pytest.raises(RuntimeError, match="declared size"):
        _download_one_file(
            "https://raw.githubusercontent.com/org/repo/main/f",
            target,
        )


def test_streaming_cap_rejects_oversized_body_when_content_length_lies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Even with a lying small Content-Length, the streaming guard kicks in.

    Defence-in-depth: the upstream could omit or fake the header, so
    we trust only the bytes-on-the-wire count.
    """
    import urllib.request

    # Lie: declare 100 bytes, actually send (cap + 1024).
    real_body = b"x" * (_MAX_DOWNLOAD_BYTES + 1024)
    fake_resp = _FakeResponse(real_body, content_length=100)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_a, **_kw: fake_resp,
    )

    target = tmp_path / "out.bin"
    with pytest.raises(RuntimeError, match="exceeded the per-file cap"):
        _download_one_file(
            "https://raw.githubusercontent.com/org/repo/main/f",
            target,
        )


def test_streaming_writes_small_body_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Happy path — a 1 KB blob is downloaded and persisted verbatim."""
    import urllib.request

    body = b"a small payload" * 64  # ~1 KB
    fake_resp = _FakeResponse(body, content_length=len(body))
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_a, **_kw: fake_resp,
    )

    target = tmp_path / "small.bin"
    written = _download_one_file(
        "https://raw.githubusercontent.com/org/repo/main/f",
        target,
    )
    assert written == len(body)
    assert target.read_bytes() == body


# ── PE integrity gate (WinError 216 root-cause defence) -----------------


def test_verify_accepts_well_formed_pe(tmp_path: Path) -> None:
    """A structurally valid PE returns ``None`` (no problem)."""
    p = tmp_path / "RvtExporter.exe"
    p.write_bytes(_minimal_pe())
    assert _verify_pe_executable(p) is None


def test_verify_rejects_missing_mz(tmp_path: Path) -> None:
    """A renamed ZIP / HTML error page (no 'MZ') is rejected."""
    p = tmp_path / "RvtExporter.exe"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 200)
    reason = _verify_pe_executable(p)
    assert reason is not None and "MZ" in reason


def test_verify_rejects_crlf_mangled_binary(tmp_path: Path) -> None:
    """The exact WinError 216 corruption: every 0x0A rewritten as
    0x0D 0x0A shifts the PE header so the signature is no longer where
    e_lfanew points. This MUST be caught at install time."""
    mangled = _minimal_pe().replace(b"\x0a", b"\x0d\x0a")
    p = tmp_path / "RvtExporter.exe"
    p.write_bytes(mangled)
    reason = _verify_pe_executable(p)
    assert reason is not None and "PE signature" in reason


def test_verify_rejects_truncated_file(tmp_path: Path) -> None:
    """A truncated download (smaller than the DOS header) is rejected."""
    p = tmp_path / "RvtExporter.exe"
    p.write_bytes(b"MZ" + b"\x00" * 8)
    assert _verify_pe_executable(p) is not None


def test_verify_rejects_e_lfanew_past_eof(tmp_path: Path) -> None:
    """e_lfanew pointing beyond the file (truncation/corruption) fails
    before we try to seek to a bogus offset."""
    # Valid 64-byte DOS header whose e_lfanew claims the PE header is
    # at 0x9000 — but the file is only 64 bytes.
    buf = bytearray(b"MZ" + b"\x00" * (0x40 - 2))
    buf[0x3C:0x40] = (0x9000).to_bytes(4, "little")
    p = tmp_path / "RvtExporter.exe"
    p.write_bytes(bytes(buf))
    reason = _verify_pe_executable(p)
    assert reason is not None and "e_lfanew" in reason


# ── A9: symlink/TOCTOU ---------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="symlink rights differ on Windows")
def test_pre_existing_symlink_at_target_is_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A symlink already at the install path must NOT be followed.

    We plant a symlink pointing at a sentinel file, then download a
    different blob. After the call the sentinel must be untouched
    and the real file at the install path must contain the new bytes.
    """
    import urllib.request

    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_bytes(b"DO NOT TOUCH")

    target = tmp_path / "install.exe"
    os.symlink(sentinel, target)
    assert target.is_symlink()

    body = b"new converter binary"
    fake_resp = _FakeResponse(body, content_length=len(body))
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_a, **_kw: fake_resp,
    )

    _download_one_file(
        "https://raw.githubusercontent.com/org/repo/main/f",
        target,
    )

    # Sentinel must be untouched — the old impl would have written
    # "new converter binary" into it via the symlink.
    assert sentinel.read_bytes() == b"DO NOT TOUCH"
    # And the real install target must hold the new content.
    assert not target.is_symlink()
    assert target.read_bytes() == body
