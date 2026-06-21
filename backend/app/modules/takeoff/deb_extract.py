"""Multi-method Debian ``.deb`` extraction for the no-root converter install.

A ``.deb`` is an ``ar`` archive holding three members: ``debian-binary``,
``control.tar.*`` and ``data.tar.*``. To unpack a CAD/BIM converter WITHOUT
root - or even without ``dpkg`` installed - we only need the ``data.tar.*``
payload extracted into a user-writable prefix. :func:`extract_deb` tries
several methods in order so the install succeeds on the widest possible range
of hosts (a full Debian/Ubuntu box, a minimal container, a non-Debian distro,
or an unprivileged account):

1. ``dpkg-deb -x`` - present on every Debian/Ubuntu base image; handles every
   payload compression including zstd. Fast and battle-tested.
2. A pure-Python ``ar`` reader + :mod:`tarfile` - needs no external tool at
   all. Handles gzip / xz / bzip2 / uncompressed payloads natively, and zstd
   when a decompressor is available (the ``zstandard`` package, otherwise a
   ``zstd`` / ``unzstd`` / ``zstdcat`` binary on PATH).

The first method that succeeds wins. This module imports only the standard
library, so it can be unit-tested without the application stack (the rest of
the converter installer lives in :mod:`app.modules.takeoff.router`, which
pulls in FastAPI).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

__all__ = ["extract_deb", "DebExtractError"]

_AR_MAGIC = b"!<arch>\n"
_AR_HEADER_LEN = 60
# Read/copy in modest chunks so a ~100 MB payload never lands fully in memory.
_CHUNK = 1 << 16


class DebExtractError(RuntimeError):
    """Raised when every available ``.deb`` extraction method has failed."""


class _MethodUnavailable(RuntimeError):
    """The tool a method needs is absent - move on to the next method."""


def extract_deb(deb_path: str | os.PathLike[str], dest_root: str | os.PathLike[str], *, timeout: int = 180) -> str:
    """Extract a ``.deb`` package's ``data.tar.*`` payload into ``dest_root``.

    Tries each method in turn and returns the name of the one that worked
    (``"dpkg-deb"`` or ``"python"``). Raises :class:`DebExtractError` only
    when every method has failed, with each method's error joined into the
    message so the caller can surface something actionable.

    The extraction is path-traversal safe: members that would escape
    ``dest_root`` (absolute paths, ``..`` segments, or symlinks pointing
    outside) are rejected/skipped.
    """
    deb = Path(deb_path)
    dest = Path(dest_root)
    dest.mkdir(parents=True, exist_ok=True)
    if not deb.is_file():
        raise DebExtractError(f"{deb} is not a file")

    errors: list[str] = []
    for name, method in (("dpkg-deb", _via_dpkg_deb), ("python", _via_python)):
        try:
            method(deb, dest, timeout=timeout)
            return name
        except _MethodUnavailable as exc:
            errors.append(f"{name}: unavailable ({exc})")
        except Exception as exc:  # noqa: BLE001 - record and try the next method
            errors.append(f"{name}: {exc}")
    raise DebExtractError(f"could not unpack {deb.name}; all methods failed: " + " | ".join(errors))


# ── Method 1: dpkg-deb ───────────────────────────────────────────────────────


def _via_dpkg_deb(deb: Path, dest: Path, *, timeout: int) -> None:
    exe = shutil.which("dpkg-deb")
    if exe is None:
        raise _MethodUnavailable("dpkg-deb not on PATH")
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [exe, "-x", str(deb), str(dest)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()[:300]
        raise RuntimeError(msg or f"dpkg-deb exited {proc.returncode}")


# ── Method 2: pure-Python ar reader + tarfile ────────────────────────────────


def _via_python(deb: Path, dest: Path, *, timeout: int) -> None:
    with tempfile.TemporaryDirectory(prefix="ddc_deb_py_") as tmp:
        raw = Path(tmp) / "data.tar.payload"
        member = _copy_data_member(deb, raw)
        suffix = member[len("data.tar") :].lstrip(".").lower()

        if suffix in ("", "tar"):
            tar_path = raw
        elif suffix == "zst" or suffix == "zstd":
            tar_path = Path(tmp) / "data.tar"
            _zstd_decompress(raw, tar_path, timeout=timeout)
        else:
            tar_path = raw  # gz/xz/bz2 are opened directly by tarfile below

        mode = {
            "gz": "r:gz",
            "xz": "r:xz",
            "bz2": "r:bz2",
            "lzma": "r:xz",
        }.get(suffix, "r:")
        with tarfile.open(tar_path, mode=mode) as tf:
            _safe_extractall(tf, dest)


def _copy_data_member(deb: Path, out: Path) -> str:
    """Stream the ``data.tar.*`` member out of the ``ar`` archive to ``out``.

    Returns the member name (e.g. ``data.tar.xz``). Reads the archive
    sequentially without loading the whole package into memory.
    """
    with open(deb, "rb") as f:
        if f.read(len(_AR_MAGIC)) != _AR_MAGIC:
            raise RuntimeError("not an ar archive (bad magic)")
        while True:
            header = f.read(_AR_HEADER_LEN)
            if len(header) < _AR_HEADER_LEN:
                break
            if header[58:60] != b"\x60\x0a":
                raise RuntimeError("corrupt ar header (bad terminator)")
            name = header[0:16].decode("ascii", "replace").strip().rstrip("/")
            size_field = header[48:58].decode("ascii", "replace").strip()
            try:
                size = int(size_field)
            except ValueError as exc:
                raise RuntimeError(f"corrupt ar header (bad size {size_field!r})") from exc
            if name.startswith("data.tar"):
                with open(out, "wb") as o:
                    remaining = size
                    while remaining > 0:
                        chunk = f.read(min(_CHUNK, remaining))
                        if not chunk:
                            raise RuntimeError("truncated ar member")
                        o.write(chunk)
                        remaining -= len(chunk)
                return name
            # Skip this member's body (members are 2-byte aligned).
            f.seek(size + (size & 1), os.SEEK_CUR)
    raise RuntimeError("no data.tar member found in .deb")


def _zstd_decompress(src: Path, dst: Path, *, timeout: int) -> None:
    """Decompress a ``.zst`` file ``src`` to ``dst``.

    Prefers the ``zstandard`` Python package (streamed, no full-file buffer);
    falls back to a ``zstd`` / ``unzstd`` / ``zstdcat`` binary on PATH.
    """
    try:
        import zstandard  # type: ignore[import-not-found]
    except ImportError:
        zstandard = None  # type: ignore[assignment]
    if zstandard is not None:
        try:
            dctx = zstandard.ZstdDecompressor()
            with open(src, "rb") as fin, open(dst, "wb") as fout:
                dctx.copy_stream(fin, fout)
            return
        except Exception:  # noqa: BLE001 - fall through to the CLI variants
            pass

    errs: list[str] = []
    for cli, args in (("zstd", ["-d", "-c"]), ("unzstd", ["-c"]), ("zstdcat", [])):
        exe = shutil.which(cli)
        if exe is None:
            continue
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [exe, *args],
                stdin=fin,
                stdout=fout,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        if proc.returncode == 0:
            return
        errs.append(proc.stderr.decode("utf-8", "replace").strip()[:120] or f"{cli} exited {proc.returncode}")

    detail = ("; " + " | ".join(errs)) if errs else ""
    raise RuntimeError(
        "zstd payload but no working decompressor (install the `zstandard` Python "
        "package or the `zstd` command)" + detail
    )


def _safe_extractall(tf: tarfile.TarFile, dest: Path) -> None:
    """Extract every member under ``dest``, rejecting path-traversal escapes."""
    # Python 3.12 (and 3.9+ patched) ship the hardened ``data`` filter - use it
    # when present; otherwise validate members by hand below.
    try:
        tf.extractall(dest, filter="data")  # type: ignore[call-arg]
        return
    except TypeError:
        pass

    dest_resolved = dest.resolve()
    base = str(dest_resolved) + os.sep
    for member in tf.getmembers():
        target = (dest_resolved / member.name).resolve()
        if target != dest_resolved and not str(target).startswith(base):
            raise RuntimeError(f"unsafe path in archive: {member.name!r}")
        if member.issym() or member.islnk():
            link_target = (target.parent / member.linkname).resolve()
            if not str(link_target).startswith(base):
                # Link would point outside the install root - skip it.
                continue
        tf.extract(member, dest_resolved)
