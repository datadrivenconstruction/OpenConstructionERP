"""The full browser editor (bundle ``ddc-web-editor/1``), fetched on demand from the release feed ``ddc-web-release/1``.

The bundle is never part of the package: the first time someone asks for it, the server reads the feed, streams the
zip to disk (never into memory), checks its size and SHA-256 against the feed and its minisign signature against the
configured public key, unpacks it under the app data dir and serves the files from there (precompressed ``.br``/``.gz``
when the browser accepts them). Without a public key nothing is downloaded. Without a feed, or with a bundle whose
bridge major this ERP does not speak, the Design section keeps working on the small engine shipped in the module.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from .settings import DesignSettings, get_design_settings

log = logging.getLogger(__name__)

#: Bridge majors this ERP host speaks (contract README §11).
HOST_BRIDGE: tuple[int, ...] = (1,)
FEED_SCHEMA = "ddc-web-release/1"
BUNDLE_SCHEMA = "ddc-web-editor/1"
#: Committed public key, used when no key is configured. Absent until the release key exists.
PUBKEY_FILE = Path(__file__).parent / "data" / "web-release.pub"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$")
_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/-]{0,255}$")
_FEED_MAX_BYTES = 64 * 1024
_SIG_MAX_BYTES = 4 * 1024
_CHUNK = 256 * 1024
SIDECARS = (".br", ".gz")


class ReleaseError(Exception):
    """A refusal with a stable code the UI translates; ``detail`` is for logs and admins."""

    def __init__(self, code: str, detail: str = "", **params: Any) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code
        self.params = params


# ── Feed ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Feed:
    version: str
    tag: str
    bridge: tuple[int, ...]
    zip_url: str
    zip_bytes: int
    zip_sha256: str
    signature_url: str
    published_at: str


def _https(url: Any, what: str) -> str:
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > 2048:
        raise ReleaseError("feed_invalid", f"{what} must be an https URL")
    return url


def parse_feed(doc: Any, max_bytes: int) -> Feed:
    """Validate a ``ddc-web-release/1`` document; anything unexpected is ``feed_invalid``."""
    if not isinstance(doc, dict) or doc.get("schema") != FEED_SCHEMA:
        raise ReleaseError("feed_invalid", f"schema is not {FEED_SCHEMA}")
    version, tag = doc.get("version"), doc.get("tag")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ReleaseError("feed_invalid", "version")
    if not isinstance(tag, str) or not _VERSION.fullmatch(tag):
        raise ReleaseError("feed_invalid", "tag")
    bridge = doc.get("bridge")
    if not isinstance(bridge, list) or not bridge or not all(type(b) is int and b > 0 for b in bridge):
        raise ReleaseError("feed_invalid", "bridge")
    z = doc.get("zip")
    if not isinstance(z, dict):
        raise ReleaseError("feed_invalid", "zip")
    size, sha = z.get("bytes"), z.get("sha256")
    if type(size) is not int or size <= 0:
        raise ReleaseError("feed_invalid", "zip.bytes")
    if size > max_bytes:
        raise ReleaseError("too_large", f"zip of {size} bytes is over the limit {max_bytes}", bytes=size)
    if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
        raise ReleaseError("feed_invalid", "zip.sha256")
    published = doc.get("published_at")
    return Feed(
        version=version,
        tag=tag,
        bridge=tuple(bridge),
        zip_url=_https(z.get("url"), "zip.url"),
        zip_bytes=size,
        zip_sha256=sha,
        signature_url=_https(doc.get("signature_url"), "signature_url"),
        published_at=published if isinstance(published, str) else "",
    )


def bridge_ok(majors: tuple[int, ...] | list[int]) -> bool:
    return any(m in HOST_BRIDGE for m in majors)


def bridge_problem(majors: tuple[int, ...] | list[int]) -> str | None:
    """``erp_too_old`` when the editor speaks only newer majors, ``editor_too_old`` when only older ones."""
    if bridge_ok(majors):
        return None
    return "erp_too_old" if min(majors) > max(HOST_BRIDGE) else "editor_too_old"


# ── Minisign ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PublicKey:
    key_id: bytes
    raw: bytes


def parse_public_key(text: str) -> PublicKey:
    """A minisign public key: the file (comment line + base64) or the base64 line alone."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.lower().startswith("untrusted comment:")]
    if len(lines) != 1:
        raise ReleaseError("key_invalid", "expected one base64 line")
    try:
        blob = base64.b64decode(lines[0], validate=True)
    except ValueError as exc:
        raise ReleaseError("key_invalid", "not base64") from exc
    if len(blob) != 42 or blob[:2] != b"Ed":
        raise ReleaseError("key_invalid", "not an Ed25519 minisign key")
    return PublicKey(key_id=blob[2:10], raw=blob[10:])


def public_key(settings: DesignSettings | None = None) -> PublicKey | None:
    """The configured key (``OE_DESIGN_WEB_RELEASE_PUBKEY``), else the committed file, else None."""
    s = settings or get_design_settings()
    text = s.web_release_pubkey.strip()
    if not text and PUBKEY_FILE.is_file():
        text = PUBKEY_FILE.read_text(encoding="utf-8")
    if not text.strip():
        return None
    return parse_public_key(text)


@dataclass(frozen=True)
class Signature:
    algorithm: bytes
    key_id: bytes
    signature: bytes
    trusted_comment: str
    global_signature: bytes


def parse_signature(text: str) -> Signature:
    lines = [ln.rstrip("\r") for ln in text.splitlines() if ln.strip()]
    if len(lines) != 4 or not lines[0].startswith("untrusted comment:") or not lines[2].startswith("trusted comment: "):
        raise ReleaseError("signature_invalid", "not a minisign signature")
    try:
        blob = base64.b64decode(lines[1], validate=True)
        glob = base64.b64decode(lines[3], validate=True)
    except ValueError as exc:
        raise ReleaseError("signature_invalid", "not base64") from exc
    if len(blob) != 74 or len(glob) != 64:
        raise ReleaseError("signature_invalid", "wrong length")
    return Signature(blob[:2], blob[2:10], blob[10:], lines[2][len("trusted comment: ") :], glob)


def verify_signature(key: PublicKey, sig: Signature, blake2b_digest: bytes) -> str:
    """Check a prehashed (``ED``) minisign signature and its trusted comment; returns the trusted comment.

    The legacy ``Ed`` form signs the whole file at once, which would need it in memory; it is refused.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if sig.algorithm != b"ED":
        raise ReleaseError("signature_invalid", "only prehashed (ED) minisign signatures are accepted")
    if sig.key_id != key.key_id:
        raise ReleaseError("signature_wrong_key", "signed with another key")
    pk = Ed25519PublicKey.from_public_bytes(key.raw)
    try:
        pk.verify(sig.signature, blake2b_digest)
        pk.verify(sig.global_signature, sig.signature + sig.trusted_comment.encode("utf-8"))
    except InvalidSignature as exc:
        raise ReleaseError("signature_mismatch", "the signature does not match the file") from exc
    return sig.trusted_comment


# ── Bundle on disk ──────────────────────────────────────────────────────────


def editor_root(settings: DesignSettings | None = None) -> Path:
    s = settings or get_design_settings()
    if s.web_editor_dir.strip():
        return Path(s.web_editor_dir.strip()).expanduser()
    from app.core.storage import resolve_data_dir

    return resolve_data_dir() / "design" / "web-editor"


@dataclass(frozen=True)
class Installed:
    version: str
    bridge: tuple[int, ...]
    entry: str
    files: dict[str, dict[str, Any]]
    bytes: int
    installed_at: str
    source: str

    @property
    def directory_name(self) -> str:
        return self.version


def _check_manifest(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get("schema") != BUNDLE_SCHEMA:
        raise ReleaseError("bundle_invalid", f"manifest schema is not {BUNDLE_SCHEMA}")
    if not isinstance(doc.get("version"), str) or not _VERSION.fullmatch(doc["version"]):
        raise ReleaseError("bundle_invalid", "manifest version")
    bridge = doc.get("bridge")
    if not isinstance(bridge, list) or not bridge or not all(type(b) is int and b > 0 for b in bridge):
        raise ReleaseError("bundle_invalid", "manifest bridge")
    files = doc.get("files")
    if not isinstance(files, list) or not files:
        raise ReleaseError("bundle_invalid", "manifest files")
    seen: set[str] = set()
    for f in files:
        if not isinstance(f, dict):
            raise ReleaseError("bundle_invalid", "manifest file entry")
        path, size, sha = f.get("path"), f.get("bytes"), f.get("sha256")
        if not isinstance(path, str) or not _PATH.fullmatch(path) or ".." in path.split("/") or path in seen:
            raise ReleaseError("bundle_invalid", f"file path {path!r}")
        if path == "manifest.json" or path.endswith(SIDECARS):
            raise ReleaseError("bundle_invalid", f"file path {path!r} is reserved")
        if type(size) is not int or size < 0 or not isinstance(sha, str) or not _SHA256.fullmatch(sha):
            raise ReleaseError("bundle_invalid", f"file {path} size or sha256")
        seen.add(path)
    if doc.get("entry") not in seen:
        raise ReleaseError("bundle_invalid", "entry is not one of the files")
    return doc


def read_installed(root: Path | None = None) -> Installed | None:
    root = root or editor_root()
    try:
        cur = json.loads((root / "current.json").read_text(encoding="utf-8"))
        version = cur["version"]
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            return None
        manifest = _check_manifest(json.loads((root / version / "manifest.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, ReleaseError):
        return None
    files = {f["path"]: f for f in manifest["files"]}
    return Installed(
        version=version,
        bridge=tuple(manifest["bridge"]),
        entry=manifest["entry"],
        files=files,
        bytes=sum(f["bytes"] for f in files.values()),
        installed_at=str(cur.get("installed_at", "")),
        source=str(cur.get("source", "")),
    )


def _members(zf: zipfile.ZipFile, max_unpacked: int) -> tuple[str, dict[str, zipfile.ZipInfo]]:
    """Safe member names of the zip, the folder the manifest sits in stripped; refuses traversal and bombs."""
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > 2000:
        raise ReleaseError("bundle_invalid", "too many files in the zip")
    if sum(i.file_size for i in infos) > max_unpacked:
        raise ReleaseError("too_large", "the unpacked bundle is over the limit")
    names = [i.filename for i in infos]
    prefix = ""
    if "manifest.json" not in names:
        tops = [n for n in names if n.endswith("/manifest.json") and n.count("/") == 1]
        if len(tops) != 1:
            raise ReleaseError("bundle_invalid", "no manifest.json in the zip")
        prefix = tops[0][: -len("manifest.json")]
    out: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        name = info.filename
        if not name.startswith(prefix):
            continue
        rel = name[len(prefix) :]
        p = PurePosixPath(rel)
        if p.is_absolute() or ".." in p.parts or "\\" in rel or not _PATH.fullmatch(rel):
            raise ReleaseError("bundle_invalid", f"unsafe path in the zip: {name!r}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ReleaseError("bundle_invalid", f"symbolic link in the zip: {name!r}")
        out[rel] = info
    return prefix, out


def unpack(zip_path: Path, root: Path, max_unpacked: int) -> Installed:
    """Check the bundle inside a verified zip and make it the current one; the previous version is removed."""
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{uuid.uuid4().hex}"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _, members = _members(zf, max_unpacked)
            with zf.open(members["manifest.json"]) as fh:
                raw = fh.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ReleaseError("bundle_invalid", "manifest.json is too large")
            try:
                manifest = _check_manifest(json.loads(raw))
            except ValueError as exc:
                raise ReleaseError("bundle_invalid", "manifest.json is not JSON") from exc
            problem = bridge_problem(manifest["bridge"])
            if problem:
                raise ReleaseError(problem, "bridge", editor=list(manifest["bridge"]), host=list(HOST_BRIDGE))
            listed = {f["path"]: f for f in manifest["files"]}
            wanted = {"manifest.json", *listed, *(p + s for p in listed for s in SIDECARS)}
            for path, spec in listed.items():
                if path not in members:
                    raise ReleaseError("bundle_invalid", f"{path} is listed but not in the zip")
            for rel, info in members.items():
                if rel not in wanted:
                    continue  # stray files are not unpacked
                dest = staging / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                size = 0
                with zf.open(info) as src, dest.open("wb") as out:
                    while chunk := src.read(_CHUNK):
                        h.update(chunk)
                        size += len(chunk)
                        out.write(chunk)
                spec = listed.get(rel)
                if spec is not None and (size != spec["bytes"] or h.hexdigest() != spec["sha256"]):
                    raise ReleaseError("integrity", f"{rel} does not match its size or SHA-256 in the manifest")
        version = manifest["version"]
        target = root / version
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
        _write_current(root, version, str(zip_path.name))
        for other in root.iterdir():
            if other.is_dir() and other.name != version:
                shutil.rmtree(other, ignore_errors=True)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    installed = read_installed(root)
    if installed is None:  # pragma: no cover - just written
        raise ReleaseError("bundle_invalid", "the unpacked bundle could not be read back")
    return installed


def _write_current(root: Path, version: str, source: str) -> None:
    tmp = root / f".current-{uuid.uuid4().hex}.json"
    tmp.write_text(
        json.dumps({"version": version, "installed_at": datetime.now(UTC).isoformat(), "source": source}),
        encoding="utf-8",
    )
    os.replace(tmp, root / "current.json")


def remove_installed(root: Path | None = None) -> bool:
    root = root or editor_root()
    if not root.exists():
        return False
    had = (root / "current.json").exists()
    shutil.rmtree(root, ignore_errors=True)
    return had


# ── Network ─────────────────────────────────────────────────────────────────

#: Tests swap in an ``httpx.MockTransport``.
transport: httpx.AsyncBaseTransport | None = None


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout, connect=15.0),
        follow_redirects=True,
        headers={"User-Agent": "OpenConstructionERP design module"},
    )


async def _get_small(client: httpx.AsyncClient, url: str, limit: int, code: str) -> bytes:
    async with client.stream("GET", url) as r:
        if r.status_code == 404:
            raise ReleaseError(f"{code}_absent", f"{url}: HTTP 404")
        if r.status_code != 200:
            raise ReleaseError(f"{code}_unreachable", f"{url}: HTTP {r.status_code}")
        if r.url.scheme != "https" and transport is None:
            raise ReleaseError(f"{code}_unreachable", "redirected away from https")
        body = b""
        async for chunk in r.aiter_bytes():
            body += chunk
            if len(body) > limit:
                raise ReleaseError(f"{code}_invalid", f"{url}: larger than {limit} bytes")
    return body


@dataclass
class _FeedCache:
    at: float = 0.0
    url: str = ""
    feed: Feed | None = None
    error: ReleaseError | None = None


_feed_cache = _FeedCache()


async def read_feed(settings: DesignSettings | None = None, *, fresh: bool = False) -> Feed:
    """The release feed, cached for ``web_feed_ttl_seconds`` (failures for a minute)."""
    s = settings or get_design_settings()
    url = s.web_feed_url.strip()
    if not url:
        raise ReleaseError("feed_off", "no release feed configured")
    now = time.monotonic()
    c = _feed_cache
    if not fresh and c.url == url and c.at:
        ttl = s.web_feed_ttl_seconds if c.feed else min(60, s.web_feed_ttl_seconds)
        if now - c.at < ttl:
            if c.feed:
                return c.feed
            assert c.error is not None
            raise c.error
    try:
        async with _client(30.0) as client:
            raw = await _get_small(client, url, _FEED_MAX_BYTES, "feed")
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            raise ReleaseError("feed_invalid", "not JSON") from exc
        feed = parse_feed(doc, s.web_release_max_bytes)
    except ReleaseError as exc:
        _feed_cache.__dict__.update(at=now, url=url, feed=None, error=exc)
        raise
    except httpx.HTTPError as exc:
        err = ReleaseError("feed_unreachable", f"{type(exc).__name__}: {exc}")
        _feed_cache.__dict__.update(at=now, url=url, feed=None, error=err)
        raise err from exc
    _feed_cache.__dict__.update(at=now, url=url, feed=feed, error=None)
    return feed


def forget_feed() -> None:
    _feed_cache.__dict__.update(at=0.0, url="", feed=None, error=None)


# ── Install job ─────────────────────────────────────────────────────────────


@dataclass
class InstallState:
    state: str = "idle"  # idle | downloading | verifying | unpacking | failed
    version: str | None = None
    done: int = 0
    total: int = 0
    error: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    started_by: str | None = None
    task: asyncio.Task | None = None

    def view(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "version": self.version,
            "done": self.done,
            "total": self.total,
            "error": self.error,
            "params": self.params,
        }


install_state = InstallState()
_install_lock = asyncio.Lock()


async def _download(client: httpx.AsyncClient, feed: Feed, dest: Path, st: InstallState) -> bytes:
    """Stream the zip to ``dest``; returns its BLAKE2b-512 digest (the minisign prehash). Checks size and SHA-256."""
    sha = hashlib.sha256()
    b2 = hashlib.blake2b(digest_size=64)
    size = 0
    async with client.stream("GET", feed.zip_url) as r:
        if r.status_code != 200:
            raise ReleaseError("download_failed", f"zip: HTTP {r.status_code}")
        if r.url.scheme != "https" and transport is None:
            raise ReleaseError("download_failed", "redirected away from https")
        with dest.open("wb") as out:
            async for chunk in r.aiter_bytes(_CHUNK):
                size += len(chunk)
                if size > feed.zip_bytes:
                    raise ReleaseError("integrity", "the zip is larger than the feed says")
                sha.update(chunk)
                b2.update(chunk)
                out.write(chunk)
                st.done = size
    if size != feed.zip_bytes or sha.hexdigest() != feed.zip_sha256:
        raise ReleaseError("integrity", "the zip does not match the size or SHA-256 in the feed")
    return b2.digest()


async def install(feed: Feed, key: PublicKey, settings: DesignSettings | None = None) -> Installed:
    """Download, verify and unpack one release. Runs as the background install job."""
    s = settings or get_design_settings()
    root = editor_root(s)
    root.mkdir(parents=True, exist_ok=True)
    st = install_state
    tmp = root / f".download-{uuid.uuid4().hex}.zip"
    try:
        st.state, st.version, st.done, st.total = "downloading", feed.version, 0, feed.zip_bytes
        async with _client(float(s.web_download_timeout_seconds)) as client:
            sig_text = (await _get_small(client, feed.signature_url, _SIG_MAX_BYTES, "signature")).decode(
                "utf-8", "replace"
            )
            signature = parse_signature(sig_text)
            if signature.key_id != key.key_id:
                raise ReleaseError("signature_wrong_key", "signed with another key")
            digest = await _download(client, feed, tmp, st)
        st.state = "verifying"
        trusted = verify_signature(key, signature, digest)
        st.state = "unpacking"
        installed = await asyncio.to_thread(unpack, tmp, root, s.web_release_max_unpacked_bytes)
        if installed.version != feed.version:
            log.warning("web editor: feed says %s, bundle manifest says %s", feed.version, installed.version)
        log.info("web editor %s installed (%s)", installed.version, trusted)
        return installed
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


async def start_install(user: str, settings: DesignSettings | None = None) -> InstallState:
    """Start the background install of the feed's release; refusals are raised before anything is fetched."""
    s = settings or get_design_settings()
    async with _install_lock:
        st = install_state
        if st.task is not None and not st.task.done():
            return st
        key = public_key(s)
        if key is None:
            raise ReleaseError("no_key", "no public key for the release signature is configured")
        feed = await read_feed(s, fresh=True)
        problem = bridge_problem(feed.bridge)
        if problem:
            raise ReleaseError(problem, "bridge", editor=list(feed.bridge), host=list(HOST_BRIDGE))
        have = read_installed(editor_root(s))
        if have is not None and have.version == feed.version:
            raise ReleaseError("already_installed", feed.version, version=feed.version)

        async def run() -> None:
            try:
                await install(feed, key, s)
                st.state, st.error, st.params = "idle", None, {}
            except ReleaseError as exc:
                log.warning("web editor install refused: %s (%s)", exc.code, exc.detail)
                st.state, st.error, st.params = "failed", exc.code, exc.params
            except (httpx.HTTPError, OSError, zipfile.BadZipFile) as exc:
                log.warning("web editor install failed: %s", exc)
                st.state, st.error, st.params = "failed", "download_failed", {}

        st.state, st.version, st.done, st.total = "downloading", feed.version, 0, feed.zip_bytes
        st.error, st.params, st.started_by = None, {}, user
        st.task = asyncio.create_task(run())
        return st


def reset_install_state() -> None:
    """Test hook."""
    global install_state
    install_state = InstallState()


# ── Serving ─────────────────────────────────────────────────────────────────

CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


def accepted_encodings(header: str | None) -> list[str]:
    """``br`` and ``gzip`` the browser accepts (q > 0), best first."""
    out: dict[str, float] = {}
    for part in (header or "").split(","):
        name, _, params = part.strip().partition(";")
        name = name.strip().lower()
        q = 1.0
        m = re.search(r"q=([0-9.]+)", params)
        if m:
            with contextlib.suppress(ValueError):
                q = float(m.group(1))
        if name in ("br", "gzip") and q > 0:
            out[name] = q
    return sorted(out, key=lambda n: (-out[n], n != "br"))


def resolve_file(
    installed: Installed, version: str, path: str, accept_encoding: str | None, root: Path | None = None
) -> tuple[Path, str, str | None]:
    """The file to send for ``path`` of the installed version: (file, content type, content encoding)."""
    if version != installed.version or (path != "manifest.json" and path not in installed.files):
        raise ReleaseError("not_found", path)
    base = (root or editor_root()) / installed.version
    plain = base / path
    ctype = CONTENT_TYPES.get(PurePosixPath(path).suffix.lower(), "application/octet-stream")
    for enc in accepted_encodings(accept_encoding):
        side = plain.with_name(plain.name + (".br" if enc == "br" else ".gz"))
        if side.is_file():
            return side, ctype, enc
    if not plain.is_file():
        raise ReleaseError("not_found", path)
    return plain, ctype, None
