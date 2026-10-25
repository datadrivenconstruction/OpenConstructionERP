"""The release wheel ships large frontend assets xz-packed; the server must serve them plain.

scripts/pack_frontend_dist.py replaces big JS/CSS/JSON/WASM files with ``<name>.xz``
before the wheel is built. A browser still asks for ``<name>`` and must get the
original bytes with the original media type. A plain, unpacked dist must keep working.
"""

from __future__ import annotations

import importlib.util
import lzma
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
    cli_static.mount_frontend(app)
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
