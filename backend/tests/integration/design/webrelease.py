"""Fixtures for the on-demand browser editor: a bundle zip, a minisign key pair and signature, a feed document."""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

FEED_URL = "https://feed.test/erp-link/release/latest-web.json"
ZIP_URL = "https://downloads.test/v0.10.0/OpenConstructionDesign-v0.10.0-web.zip"
SIG_URL = ZIP_URL + ".minisig"


def _brotli(b: bytes) -> bytes:
    """Real brotli where the package is installed (httpx then decodes the response), a stand-in elsewhere."""
    try:
        import brotli
    except ImportError:
        return b"br:" + b
    return brotli.compress(b)


ENTRY_JS = b"export async function mount(element, host) { return { post() {}, unmount() {} }; }\n"
WASM = b"\x00asm\x01\x00\x00\x00" + bytes(range(256)) * 64


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


@dataclass
class Keys:
    secret: Ed25519PrivateKey
    key_id: bytes

    @classmethod
    def new(cls) -> Keys:
        return cls(Ed25519PrivateKey.generate(), os.urandom(8))

    @property
    def public_text(self) -> str:
        raw = self.secret.public_key().public_bytes_raw()
        return f"untrusted comment: minisign public key\n{b64(b'Ed' + self.key_id + raw)}\n"

    def sign(
        self, data: bytes, *, comment: str = "timestamp:1763600000\tfile:web.zip", algorithm: bytes = b"ED"
    ) -> str:
        message = hashlib.blake2b(data, digest_size=64).digest() if algorithm == b"ED" else data
        sig = self.secret.sign(message)
        glob = self.secret.sign(sig + comment.encode())
        return (
            "untrusted comment: signature from minisign secret key\n"
            f"{b64(algorithm + self.key_id + sig)}\ntrusted comment: {comment}\n{b64(glob)}\n"
        )


def bundle_zip(
    *,
    version: str = "0.10.0",
    bridge: list[int] | None = None,
    files: dict[str, bytes] | None = None,
    extra: dict[str, bytes] | None = None,
    folder: str = "",
    tamper: str | None = None,
) -> bytes:
    """A ``ddc-web-editor/1`` bundle zip with ``.br``/``.gz`` sidecars of the js and wasm files."""
    files = files or {"ddc-editor.js": ENTRY_JS, "ddc_web_editor_bg.wasm": WASM}
    manifest = {
        "schema": "ddc-web-editor/1",
        "version": version,
        "bridge": bridge or [1],
        "entry": "ddc-editor.js",
        "files": [{"path": p, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in files.items()],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(folder + "manifest.json", json.dumps(manifest))
        for p, b in files.items():
            zf.writestr(folder + p, b + (b"x" if p == tamper else b""))
            zf.writestr(folder + p + ".gz", gzip.compress(b))
            zf.writestr(folder + p + ".br", _brotli(b))
        for p, b in (extra or {}).items():
            zf.writestr(p, b)
    return buf.getvalue()


def feed_doc(data: bytes, *, version: str = "0.10.0", bridge: list[int] | None = None) -> dict:
    return {
        "schema": "ddc-web-release/1",
        "version": version,
        "tag": f"v{version}",
        "bridge": bridge or [1],
        "zip": {"url": ZIP_URL, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "signature_url": SIG_URL,
        "published_at": "2026-11-20T12:00:00Z",
    }
