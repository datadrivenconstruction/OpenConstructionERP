"""The DWG original of the demo drawing set ships with the package and matches SET_VERSION."""

from pathlib import Path

import pytest

import app.scripts as scripts_pkg
from app.scripts.demo_drawing_set import SET_VERSION
from app.scripts.seed_dwg_drawing import shipped_demo_dwg

ASSETS = Path(scripts_pkg.__file__).parent / "demo_drawing_assets"


def test_shipped_dwg_matches_set_version() -> None:
    path = shipped_demo_dwg()
    assert path is not None, f"residential_block_set_v{SET_VERSION}.dwg is missing; rebuild with --dwg"
    assert Path(path).name == f"residential_block_set_v{SET_VERSION}.dwg"
    # A stale file of another version would be shipped dead weight.
    assert sorted(p.name for p in ASSETS.glob("*.dwg")) == [Path(path).name]


def test_shipped_dwg_has_dwg_magic() -> None:
    path = shipped_demo_dwg()
    assert path is not None
    head = Path(path).read_bytes()[:6]
    assert head[:4] == b"AC10", head
    assert head[4:6].isdigit(), head


@pytest.mark.parametrize("name", ["README.md", "LICENSE"])
def test_dwg_assets_carry_licence_notes(name: str) -> None:
    text = (ASSETS / name).read_text(encoding="utf-8")
    assert "CC0" in text
    assert "LibreDWG" in text


def test_dwg_source_is_flat_and_leaves_libredwg_handles_free(tmp_path: Path) -> None:
    ezdxf = pytest.importorskip("ezdxf")
    from app.scripts.demo_drawing_set import _LIBREDWG_RESERVED_HANDLES, build_drawing_set_for_dwg

    out = tmp_path / "src.dxf"
    build_drawing_set_for_dwg(str(out))
    doc = ezdxf.readfile(out)
    assert doc.dxfversion == "AC1015"
    assert not list(doc.modelspace().query("INSERT"))
    assert [b.name for b in doc.blocks if not b.name.startswith("*")] == []
    for handle in _LIBREDWG_RESERVED_HANDLES:
        assert doc.entitydb.get(handle) is None


def test_seed_attaches_the_dwg_original_beside_the_dxf(tmp_path: Path) -> None:
    import uuid

    from app.scripts.seed_dwg_drawing import _attach_original_dwg

    drawing_id = uuid.uuid4()
    name = _attach_original_dwg(str(tmp_path), drawing_id)
    assert name == f"{drawing_id}.dwg"
    assert (tmp_path / name).read_bytes() == Path(shipped_demo_dwg() or "").read_bytes()
