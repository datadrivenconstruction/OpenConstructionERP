"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The release wheel ships large frontend assets xz-packed; the server must serve them plain.

scripts/pack_frontend_dist.py replaces big JS/CSS/JSON/WASM files with ``<name>.xz``
before the wheel is built. A browser still asks for ``<name>`` and must get the
original bytes with the original media type. A plain, unpacked dist must keep working.
"""

from __future__ import annotations

import importlib.util
import lzma
import shutil
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cli_static

BIG_JS = ("export const t = " + repr("x" * 300_000) + ";\n").encode()
REPO = Path(__file__).resolve().parents[3]


def _load_packer():
    spec = importlib.util.spec_from_file_location("pack_frontend_dist", REPO / "scripts" / "pack_frontend_dist.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "cesium" / "Workers").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (d / "sw.js").write_bytes(BIG_JS)
    (d / "assets" / "i18n-de-AB12CD34.js").write_bytes(BIG_JS)
    (d / "assets" / "small-AB12CD34.js").write_text("export const ok = 1;\n", encoding="utf-8")
    (d / "cesium" / "Workers" / "big.js").write_bytes(BIG_JS)
    monkeypatch.setattr(cli_static, "get_frontend_dir", lambda: d)
    monkeypatch.setattr(cli_static.tempfile, "gettempdir", lambda: str(tmp_path / "cache"))
    return d


def _client() -> TestClient:
    app = FastAPI()
    cli_static.mount_frontend(app, expand_in_background=False)
    return TestClient(app)


@pytest.mark.parametrize("packed", [False, True])
@pytest.mark.parametrize("url", ["/assets/i18n-de-AB12CD34.js", "/cesium/Workers/big.js", "/sw.js"])
def test_big_asset_is_served_with_original_bytes(dist: Path, url: str, packed: bool) -> None:
    if packed:
        count, _, _ = _load_packer().pack(dist)
        assert count == 2  # root-level sw.js stays plain
        assert not (dist / "assets" / "i18n-de-AB12CD34.js").exists()
        assert lzma.decompress((dist / "assets" / "i18n-de-AB12CD34.js.xz").read_bytes()) == BIG_JS
    client = _client()
    for _ in range(2):  # second hit comes from the expansion cache
        r = client.get(url)
        assert r.status_code == 200
        assert r.content == BIG_JS
        assert r.headers["content-type"].startswith("text/javascript")


def test_small_asset_and_missing_asset(dist: Path) -> None:
    _load_packer().pack(dist)
    client = _client()
    assert client.get("/assets/small-AB12CD34.js").status_code == 200
    assert client.get("/assets/gone-AB12CD34.js").status_code == 404


def test_traversal_through_packed_lookup_is_refused(dist: Path, tmp_path: Path) -> None:
    (tmp_path / "secret.js.xz").write_bytes(lzma.compress(b"secret"))
    assert cli_static.expand_packed_asset(dist / "assets", "../../secret.js") is None


@pytest.mark.parametrize("packed", [False, True])
@pytest.mark.parametrize("name", ["fonts", "inter", "ibm-plex-sans", "source-sans-3"])
def test_self_hosted_font_stylesheets_are_css_not_the_spa_page(dist: Path, name: str, packed: bool) -> None:
    fonts = dist / "assets" / "vendor" / "fonts"
    fonts.mkdir(parents=True)
    shutil.copy(REPO / "frontend" / "public" / "assets" / "vendor" / "fonts" / f"{name}.css", fonts / f"{name}.css")
    if packed:
        _load_packer().pack(dist / "assets")
    r = _client().get(f"/assets/vendor/fonts/{name}.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "@font-face" in r.text


def test_expansion_at_startup_is_idempotent(dist: Path) -> None:
    _load_packer().pack(dist)
    assert cli_static.expand_all_packed(dist) == 2
    plain = dist / "assets" / "i18n-de-AB12CD34.js"
    assert plain.read_bytes() == BIG_JS  # expanded in place, next to the .xz
    mtime = plain.stat().st_mtime_ns
    assert cli_static.expand_all_packed(dist) == 0
    assert plain.stat().st_mtime_ns == mtime


def test_background_expansion_finishes_and_prunes_copies_no_longer_shipped(dist: Path) -> None:
    _load_packer().pack(dist)
    (dist / "assets" / "old-ZZ12CD34.js").write_bytes(b"old")
    (dist / ".xz-expanded").write_text("assets/old-ZZ12CD34.js\n", encoding="utf-8")
    cli_static.start_background_expansion(dist).join(30)
    assert (dist / "cesium" / "Workers" / "big.js").read_bytes() == BIG_JS
    assert not (dist / "assets" / "old-ZZ12CD34.js").exists()


def test_concurrent_requests_decompress_once(dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _load_packer().pack(dist)
    calls: list[Path] = []
    real = cli_static._decompress

    def slow(packed: Path, target: Path) -> None:
        calls.append(packed)
        time.sleep(0.2)
        real(packed, target)

    monkeypatch.setattr(cli_static, "_decompress", slow)
    results: list[Path | None] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(cli_static.expand_packed_asset(dist / "assets", "i18n-de-AB12CD34.js"))
        )
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert len(set(results)) == 1
    assert results[0].read_bytes() == BIG_JS


def test_missing_js_with_packed_copy_is_served_with_type_and_immutable_cache(dist: Path) -> None:
    _load_packer().pack(dist)
    assert not (dist / "assets" / "i18n-de-AB12CD34.js").exists()
    r = _client().get("/assets/i18n-de-AB12CD34.js")
    assert r.status_code == 200
    assert r.content == BIG_JS
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_unhashed_asset_is_not_cached_as_immutable(dist: Path) -> None:
    (dist / "assets" / "plain.css").write_text("a{}", encoding="utf-8")
    assert _client().get("/assets/plain.css").headers["cache-control"] == "no-cache"


def test_read_only_dist_expands_into_cache_dir(dist: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _load_packer().pack(dist)
    monkeypatch.setattr(cli_static, "_dir_writable", lambda _d: False)
    r = _client().get("/assets/i18n-de-AB12CD34.js")
    assert r.status_code == 200
    assert r.content == BIG_JS
    assert not (dist / "assets" / "i18n-de-AB12CD34.js").exists()
    assert list((tmp_path / "cache").rglob("i18n-de-AB12CD34.js"))


@pytest.mark.parametrize("url", ["/assets/broken-AB12CD34.js", "/cesium/broken.js"])
def test_corrupt_packed_asset_is_a_clean_500_logged_once(
    dist: Path, url: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    (dist / url.lstrip("/")).with_name("broken-AB12CD34.js.xz" if "assets" in url else "broken.js.xz").write_bytes(
        b"not xz at all"
    )
    client = _client()
    with caplog.at_level("ERROR", logger=cli_static.logger.name):
        first = client.get(url)
        second = client.get(url)
    assert first.status_code == second.status_code == 500
    assert sum("Could not expand packed frontend asset" in m for m in caplog.messages) == 1
    assert client.get("/assets/small-AB12CD34.js").status_code == 200
    assert cli_static.expand_all_packed(dist) == 0
