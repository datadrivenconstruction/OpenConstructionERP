"""Unit tests for the multi-method ``.deb`` extractor.

These build synthetic Debian packages (an ``ar`` archive wrapping a
``data.tar.*`` payload) entirely from the standard library, so the test
runs without the application stack and without any real converter download.
The module under test is loaded by file path to sidestep the ``app`` package
import chain (which needs Python >= 3.12 / the full backend deps).
"""

from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[2] / "app" / "modules" / "takeoff" / "deb_extract.py"
_spec = importlib.util.spec_from_file_location("deb_extract_under_test", _MOD_PATH)
assert _spec and _spec.loader
deb_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deb_extract)


# ── synthetic .deb builders ───────────────────────────────────────────────────


def _ar_header(name: str, size: int) -> bytes:
    h = name.encode("ascii").ljust(16)
    h += b"0".ljust(12)  # mtime
    h += b"0".ljust(6)  # uid
    h += b"0".ljust(6)  # gid
    h += b"100644".ljust(8)  # mode
    h += str(size).encode("ascii").ljust(10)  # size
    h += b"\x60\x0a"  # 2-byte terminator
    assert len(h) == 60, len(h)
    return h


def _make_data_tar(members: dict[str, bytes], compression: str = "gz") -> bytes:
    mode = {"gz": "w:gz", "xz": "w:xz", "bz2": "w:bz2", "": "w:"}[compression]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as tf:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755 if name.endswith("Exporter") else 0o644
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_deb(path: Path, data_tar: bytes, data_name: str = "data.tar.gz") -> None:
    control = _make_data_tar({"./control": b"Package: ddc-ifcconverter\n"}, "gz")
    members = [
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", control),
        (data_name, data_tar),
    ]
    with open(path, "wb") as f:
        f.write(deb_extract._AR_MAGIC)
        for name, body in members:
            f.write(_ar_header(name, len(body)))
            f.write(body)
            if len(body) % 2 == 1:  # 2-byte alignment pad
                f.write(b"\n")


_BIN = b"\x7fELF" + b"x" * 4096  # > 1 KB so the size gate accepts it


# ── tests ─────────────────────────────────────────────────────────────────────


def test_extract_deb_gz_roundtrip(tmp_path: Path) -> None:
    data = _make_data_tar(
        {"usr/bin/IfcExporter": _BIN, "usr/lib/datadrivenconstruction/libfoo.so": b"lib" * 500},
        "gz",
    )
    deb = tmp_path / "pkg.deb"
    _make_deb(deb, data, "data.tar.gz")
    dest = tmp_path / "root"

    method = deb_extract.extract_deb(deb, dest)

    assert method in {"dpkg-deb", "python"}
    out = dest / "usr" / "bin" / "IfcExporter"
    assert out.is_file()
    assert out.read_bytes() == _BIN
    assert (dest / "usr" / "lib" / "datadrivenconstruction" / "libfoo.so").is_file()


def test_via_python_gz(tmp_path: Path) -> None:
    data = _make_data_tar({"usr/bin/IfcExporter": _BIN}, "gz")
    deb = tmp_path / "pkg.deb"
    _make_deb(deb, data, "data.tar.gz")
    dest = tmp_path / "root"

    # Force the pure-Python path regardless of whether dpkg-deb is installed.
    deb_extract._via_python(deb, dest, timeout=60)

    assert (dest / "usr" / "bin" / "IfcExporter").read_bytes() == _BIN


def test_via_python_xz(tmp_path: Path) -> None:
    data = _make_data_tar({"usr/bin/IfcExporter": _BIN}, "xz")
    deb = tmp_path / "pkg.deb"
    _make_deb(deb, data, "data.tar.xz")
    dest = tmp_path / "root"

    deb_extract._via_python(deb, dest, timeout=60)

    assert (dest / "usr" / "bin" / "IfcExporter").read_bytes() == _BIN


def test_via_python_uncompressed(tmp_path: Path) -> None:
    data = _make_data_tar({"usr/bin/DwgExporter": _BIN}, "")
    deb = tmp_path / "pkg.deb"
    _make_deb(deb, data, "data.tar")
    dest = tmp_path / "root"

    deb_extract._via_python(deb, dest, timeout=60)

    assert (dest / "usr" / "bin" / "DwgExporter").read_bytes() == _BIN


def test_path_traversal_is_blocked(tmp_path: Path) -> None:
    # A malicious payload that tries to escape the install root must not write
    # outside it - neither via the hardened ``data`` filter (new Pythons) nor
    # the manual member check (older Pythons).
    data = _make_data_tar({"../escape.txt": b"pwned", "usr/bin/IfcExporter": _BIN}, "gz")
    deb = tmp_path / "evil.deb"
    _make_deb(deb, data, "data.tar.gz")
    dest = tmp_path / "root"
    dest.mkdir()

    with pytest.raises(Exception):  # noqa: B017,PT011 - either filter or manual check rejects
        deb_extract._via_python(deb, dest, timeout=60)

    assert not (tmp_path / "escape.txt").exists()


def test_not_an_ar_archive(tmp_path: Path) -> None:
    bad = tmp_path / "bad.deb"
    bad.write_bytes(b"this is not an ar archive at all" * 10)
    dest = tmp_path / "root"

    with pytest.raises(deb_extract.DebExtractError):
        deb_extract.extract_deb(bad, dest)


def test_missing_data_member(tmp_path: Path) -> None:
    # An ar archive with only debian-binary + control - no data.tar.*.
    deb = tmp_path / "nodata.deb"
    control = _make_data_tar({"./control": b"Package: x\n"}, "gz")
    with open(deb, "wb") as f:
        f.write(deb_extract._AR_MAGIC)
        for name, body in (("debian-binary", b"2.0\n"), ("control.tar.gz", control)):
            f.write(_ar_header(name, len(body)))
            f.write(body)
            if len(body) % 2 == 1:
                f.write(b"\n")
    with pytest.raises(deb_extract.DebExtractError):
        deb_extract.extract_deb(deb, tmp_path / "root")


def test_zstd_payload_when_available(tmp_path: Path) -> None:
    zstandard = pytest.importorskip("zstandard")
    raw = _make_data_tar({"usr/bin/IfcExporter": _BIN}, "")
    compressed = zstandard.ZstdCompressor().compress(raw)
    deb = tmp_path / "pkg.deb"
    _make_deb(deb, compressed, "data.tar.zst")
    dest = tmp_path / "root"

    deb_extract._via_python(deb, dest, timeout=60)

    assert (dest / "usr" / "bin" / "IfcExporter").read_bytes() == _BIN
