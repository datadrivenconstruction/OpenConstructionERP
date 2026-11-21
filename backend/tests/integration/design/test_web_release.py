"""On-demand browser editor: feed, minisign check, streamed download, safe unpack, serving, engine-mode fallback."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from app.modules.design import web_release as wr
from app.modules.design.settings import DesignSettings

from .conftest import make_user
from .webrelease import ENTRY_JS, FEED_URL, SIG_URL, WASM, ZIP_URL, Keys, bundle_zip, feed_doc

BASE = "/api/v1/design"


class Server:
    """The release host: feed, zip and signature, each swappable; counts zip downloads."""

    def __init__(self) -> None:
        self.feed: bytes | None = None
        self.zip: bytes | None = None
        self.sig: str | None = None
        self.zip_hits = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == FEED_URL:
            return httpx.Response(200, content=self.feed) if self.feed is not None else httpx.Response(404)
        if url == ZIP_URL and self.zip is not None:
            self.zip_hits += 1
            return httpx.Response(200, content=self.zip)
        if url == SIG_URL and self.sig is not None:
            return httpx.Response(200, text=self.sig)
        return httpx.Response(404)

    def publish(self, data: bytes, keys: Keys, **feed_kw) -> None:
        self.zip = data
        self.sig = keys.sign(data)
        self.feed = json.dumps(feed_doc(data, **feed_kw)).encode()


@pytest.fixture
def server(monkeypatch):
    srv = Server()
    monkeypatch.setattr(wr, "transport", httpx.MockTransport(srv.handler))
    wr.forget_feed()
    wr.reset_install_state()
    yield srv
    wr.forget_feed()
    wr.reset_install_state()


@pytest.fixture
def keys() -> Keys:
    return Keys.new()


def settings(tmp_path: Path, keys: Keys | None = None, **kw) -> DesignSettings:
    return DesignSettings(
        web_feed_url=FEED_URL,
        web_editor_dir=str(tmp_path / "web-editor"),
        web_release_pubkey=keys.public_text if keys else "",
        **kw,
    )


# ── Feed ────────────────────────────────────────────────────────────────────


def test_feed_from_the_release_card_parses():
    data = bundle_zip()
    feed = wr.parse_feed(feed_doc(data), 200 * 1024**2)
    assert feed.version == "0.10.0" and feed.tag == "v0.10.0" and feed.bridge == (1,)
    assert feed.zip_bytes == len(data) and feed.zip_sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"schema": "ddc-web-release/2"}, "feed_invalid"),
        ({"bridge": []}, "feed_invalid"),
        ({"bridge": ["1"]}, "feed_invalid"),
        ({"version": "../1"}, "feed_invalid"),
        ({"zip": {"url": "http://downloads.test/x.zip", "bytes": 10, "sha256": "0" * 64}}, "feed_invalid"),
        ({"zip": {"url": ZIP_URL, "bytes": 10, "sha256": "ABC"}}, "feed_invalid"),
        ({"zip": {"url": ZIP_URL, "bytes": 999 * 1024**2, "sha256": "0" * 64}}, "too_large"),
        ({"signature_url": "ftp://x"}, "feed_invalid"),
    ],
)
def test_feed_refuses_what_it_cannot_trust(patch, code):
    doc = {**feed_doc(bundle_zip()), **patch}
    with pytest.raises(wr.ReleaseError) as e:
        wr.parse_feed(doc, 200 * 1024**2)
    assert e.value.code == code


def test_bridge_problem_names_the_side_to_update():
    assert wr.bridge_problem([1]) is None
    assert wr.bridge_problem([1, 2]) is None
    assert wr.bridge_problem([2]) == "erp_too_old"


# ── Minisign ────────────────────────────────────────────────────────────────


def test_minisign_signature_verifies_with_the_committed_key_format(keys):
    data = bundle_zip()
    key = wr.parse_public_key(keys.public_text)
    sig = wr.parse_signature(keys.sign(data))
    comment = wr.verify_signature(key, sig, hashlib.blake2b(data, digest_size=64).digest())
    assert comment.startswith("timestamp:")


def test_minisign_refuses_another_key_a_changed_file_and_the_legacy_form(keys):
    data = bundle_zip()
    digest = hashlib.blake2b(data, digest_size=64).digest()
    other = Keys.new()
    with pytest.raises(wr.ReleaseError, match="another key"):
        wr.verify_signature(wr.parse_public_key(other.public_text), wr.parse_signature(keys.sign(data)), digest)
    with pytest.raises(wr.ReleaseError) as e:
        wr.verify_signature(
            wr.parse_public_key(keys.public_text),
            wr.parse_signature(keys.sign(data + b"!")),
            digest,
        )
    assert e.value.code == "signature_mismatch"
    with pytest.raises(wr.ReleaseError, match="prehashed"):
        wr.verify_signature(
            wr.parse_public_key(keys.public_text), wr.parse_signature(keys.sign(data, algorithm=b"Ed")), digest
        )


def test_tampered_trusted_comment_is_refused(keys):
    data = bundle_zip()
    text = keys.sign(data).replace("trusted comment: timestamp", "trusted comment: timestamq")
    with pytest.raises(wr.ReleaseError) as e:
        wr.verify_signature(
            wr.parse_public_key(keys.public_text),
            wr.parse_signature(text),
            hashlib.blake2b(data, digest_size=64).digest(),
        )
    assert e.value.code == "signature_mismatch"


def test_no_key_configured_means_none(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "PUBKEY_FILE", tmp_path / "absent.pub")
    assert wr.public_key(settings(tmp_path)) is None


def test_committed_key_file_is_used_when_nothing_is_configured(tmp_path, monkeypatch, keys):
    pub = tmp_path / "web-release.pub"
    pub.write_text(keys.public_text, encoding="utf-8")
    monkeypatch.setattr(wr, "PUBKEY_FILE", pub)
    assert wr.public_key(settings(tmp_path)).key_id == keys.key_id


# ── Unpack ──────────────────────────────────────────────────────────────────


def _zip_file(tmp_path: Path, data: bytes) -> Path:
    p = tmp_path / "in.zip"
    p.write_bytes(data)
    return p


def test_unpack_installs_listed_files_and_their_precompressed_copies(tmp_path):
    root = tmp_path / "root"
    data = bundle_zip(extra={"notes/readme.txt": b"stray"})
    inst = wr.unpack(_zip_file(tmp_path, data), root, 10**8)
    assert inst.version == "0.10.0" and inst.entry == "ddc-editor.js" and inst.bridge == (1,)
    d = root / "0.10.0"
    assert (d / "ddc-editor.js").read_bytes() == ENTRY_JS
    assert (d / "ddc_web_editor_bg.wasm.br").exists() and (d / "ddc_web_editor_bg.wasm.gz").exists()
    assert not (d / "notes").exists()
    assert wr.read_installed(root) == inst


def test_unpack_strips_one_top_folder_and_replaces_the_previous_version(tmp_path):
    root = tmp_path / "root"
    wr.unpack(_zip_file(tmp_path, bundle_zip(version="0.9.0")), root, 10**8)
    inst = wr.unpack(_zip_file(tmp_path, bundle_zip(version="0.10.0", folder="web/")), root, 10**8)
    assert inst.version == "0.10.0"
    assert sorted(p.name for p in root.iterdir() if p.is_dir()) == ["0.10.0"]


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"tamper": "ddc_web_editor_bg.wasm"}, "integrity"),
        ({"bridge": [2]}, "erp_too_old"),
        ({"extra": {"../evil.js": b"x"}}, "bundle_invalid"),
    ],
)
def test_unpack_refuses_and_leaves_nothing_behind(tmp_path, kw, code):
    root = tmp_path / "root"
    with pytest.raises(wr.ReleaseError) as e:
        wr.unpack(_zip_file(tmp_path, bundle_zip(**kw)), root, 10**8)
    assert e.value.code == code
    assert wr.read_installed(root) is None
    assert not [p for p in root.iterdir() if p.name.startswith(".staging")]


def test_unpack_refuses_a_bomb(tmp_path):
    with pytest.raises(wr.ReleaseError) as e:
        wr.unpack(_zip_file(tmp_path, bundle_zip()), tmp_path / "root", 100)
    assert e.value.code == "too_large"


def test_unpack_refuses_a_manifest_naming_a_missing_file(tmp_path):
    p = tmp_path / "x.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema": "ddc-web-editor/1",
                    "version": "1",
                    "bridge": [1],
                    "entry": "a.js",
                    "files": [{"path": "a.js", "bytes": 1, "sha256": "0" * 64}],
                }
            ),
        )
    with pytest.raises(wr.ReleaseError, match="listed but not in the zip"):
        wr.unpack(p, tmp_path / "root", 10**8)


# ── Serving ─────────────────────────────────────────────────────────────────


def test_encodings_prefer_brotli_and_respect_q_zero():
    assert wr.accepted_encodings("gzip, deflate, br") == ["br", "gzip"]
    assert wr.accepted_encodings("br;q=0, gzip;q=0.5") == ["gzip"]
    assert wr.accepted_encodings(None) == []


def test_resolve_file_picks_the_precompressed_copy_and_only_listed_paths(tmp_path):
    root = tmp_path / "root"
    inst = wr.unpack(_zip_file(tmp_path, bundle_zip()), root, 10**8)
    f, ctype, enc = wr.resolve_file(inst, "0.10.0", "ddc_web_editor_bg.wasm", "gzip, br", root)
    assert (f.name, ctype, enc) == ("ddc_web_editor_bg.wasm.br", "application/wasm", "br")
    f, ctype, enc = wr.resolve_file(inst, "0.10.0", "ddc-editor.js", "gzip", root)
    assert f.name.endswith(".gz") and enc == "gzip" and ctype.startswith("text/javascript")
    f, _, enc = wr.resolve_file(inst, "0.10.0", "ddc-editor.js", None, root)
    assert f.read_bytes() == ENTRY_JS and enc is None
    for version, path in (("0.9.0", "ddc-editor.js"), ("0.10.0", "ddc-editor.js.br"), ("0.10.0", "../current.json")):
        with pytest.raises(wr.ReleaseError):
            wr.resolve_file(inst, version, path, None, root)


# ── Install job ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_streams_verifies_and_unpacks(tmp_path, server, keys):
    server.publish(bundle_zip(), keys)
    s = settings(tmp_path, keys)
    inst = await wr.install(await wr.read_feed(s), wr.public_key(s), s)
    assert inst.version == "0.10.0"
    root = wr.editor_root(s)
    assert (root / "0.10.0" / "ddc_web_editor_bg.wasm").read_bytes() == WASM
    assert not list(root.glob(".download-*"))


@pytest.mark.asyncio
async def test_install_refuses_a_zip_that_differs_from_the_feed(tmp_path, server, keys):
    server.publish(bundle_zip(), keys)
    server.zip = bundle_zip(version="0.10.1")  # swapped on the host after the feed was written
    server.sig = keys.sign(server.zip)
    s = settings(tmp_path, keys)
    with pytest.raises(wr.ReleaseError) as e:
        await wr.install(await wr.read_feed(s), wr.public_key(s), s)
    assert e.value.code == "integrity"
    assert wr.read_installed(wr.editor_root(s)) is None
    assert not list(wr.editor_root(s).glob(".download-*"))


@pytest.mark.asyncio
async def test_install_refuses_a_signature_by_another_key(tmp_path, server, keys):
    server.publish(bundle_zip(), Keys.new())
    s = settings(tmp_path, keys)
    with pytest.raises(wr.ReleaseError) as e:
        await wr.install(await wr.read_feed(s), wr.public_key(s), s)
    assert e.value.code == "signature_wrong_key"
    assert server.zip_hits == 0  # refused before the big download


@pytest.mark.asyncio
async def test_start_install_refuses_unsigned_without_fetching(tmp_path, server, monkeypatch):
    monkeypatch.setattr(wr, "PUBKEY_FILE", tmp_path / "absent.pub")
    server.publish(bundle_zip(), Keys.new())
    with pytest.raises(wr.ReleaseError) as e:
        await wr.start_install("u", settings(tmp_path))
    assert e.value.code == "no_key"
    assert server.zip_hits == 0


@pytest.mark.asyncio
async def test_start_install_says_which_side_is_too_old(tmp_path, server, keys):
    server.publish(bundle_zip(bridge=[2]), keys, bridge=[2])
    with pytest.raises(wr.ReleaseError) as e:
        await wr.start_install("u", settings(tmp_path, keys))
    assert e.value.code == "erp_too_old" and e.value.params == {"editor": [2], "host": [1]}


@pytest.mark.asyncio
async def test_feed_absent_is_cached_and_reported(tmp_path, server):
    s = settings(tmp_path)
    for _ in range(2):
        with pytest.raises(wr.ReleaseError) as e:
            await wr.read_feed(s)
        assert e.value.code == "feed_absent"


# ── API ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def api_settings(tmp_path, monkeypatch):
    """The module settings the routes read, pointed at the fake host and a temp dir."""
    from app.modules.design import web_release_api

    holder: dict[str, DesignSettings] = {}

    def use(keys: Keys | None) -> DesignSettings:
        holder["s"] = settings(tmp_path, keys)
        return holder["s"]

    monkeypatch.setattr(wr, "get_design_settings", lambda: holder["s"])
    monkeypatch.setattr(web_release_api, "get_design_settings", lambda: holder["s"])
    monkeypatch.setattr(wr, "PUBKEY_FILE", tmp_path / "absent.pub")
    return use


@pytest.mark.asyncio
async def test_api_engine_mode_while_the_feed_is_absent(client, server, api_settings):
    api_settings(None)
    _, h = await make_user(client)
    r = await client.get(f"{BASE}/web-editor", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["installed"] is None and body["feed"] == {"state": "absent"}
    assert body["signing"]["key"] is False and body["can_install"] is False
    assert body["host_bridge"] == [1]
    r = await client.post(f"{BASE}/web-editor/install", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_key"


@pytest.mark.asyncio
async def test_api_install_then_serve_precompressed(client, server, api_settings, keys):
    import asyncio

    api_settings(keys)
    server.publish(bundle_zip(), keys)
    viewer_id, viewer = await make_user(client, role="viewer")
    _, h = await make_user(client)
    assert (await client.post(f"{BASE}/web-editor/install", headers=viewer)).status_code == 403
    r = await client.post(f"{BASE}/web-editor/install", headers=h)
    assert r.status_code == 202, r.text
    await asyncio.wait_for(wr.install_state.task, 10)
    body = (await client.get(f"{BASE}/web-editor", headers=h)).json()
    assert body["install"]["state"] == "idle", body
    assert body["installed"]["version"] == "0.10.0" and body["update_available"] is False
    assert body["is_admin"] is False and body["can_remove"] is False
    url = body["installed"]["manifest_url"]
    assert url == f"{BASE}/web-editor/files/0.10.0/manifest.json"

    m = await client.get(url)  # no token: loaded by import()
    assert m.status_code == 200 and m.json()["entry"] == "ddc-editor.js"
    w = await client.get(f"{BASE}/web-editor/files/0.10.0/ddc_web_editor_bg.wasm", headers={"Accept-Encoding": "br"})
    assert w.status_code == 200
    assert w.headers["content-encoding"] == "br" and w.headers["content-type"] == "application/wasm"
    assert w.headers["vary"] == "Accept-Encoding" and "immutable" in w.headers["cache-control"]
    js = await client.get(f"{BASE}/web-editor/files/0.10.0/ddc-editor.js", headers={"Accept-Encoding": "identity"})
    assert js.content == ENTRY_JS and "content-encoding" not in js.headers
    assert (await client.get(f"{BASE}/web-editor/files/0.10.0/../current.json")).status_code == 404

    again = await client.post(f"{BASE}/web-editor/install", headers=h)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_installed"
    assert (await client.delete(f"{BASE}/web-editor", headers=h)).status_code == 403
    admin_id, admin = await make_user(client, role="admin")
    assert (await client.delete(f"{BASE}/web-editor", headers=admin)).status_code == 204
    assert (await client.get(f"{BASE}/web-editor", headers=h)).json()["installed"] is None
