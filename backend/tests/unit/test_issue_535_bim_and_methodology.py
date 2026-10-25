"""Revit DAE matching, type rows, type parameters, embedded PG cleanup, flat machinery base."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.core import embedded_pg
from app.modules.bim_hub import dataframe_store, ifc_processor
from app.modules.bim_hub.schemas import BIMElementResponse
from app.modules.bim_hub.smart_views import _lookup_key
from app.modules.methodology.bases import resolve_bases
from app.modules.methodology.templates import _FLAT_BASE_MAPPING

_NS = "http://www.collada.org/2005/11/COLLADASchema"


def _geometry(gid: str) -> str:
    return f'<geometry id="{gid}"><mesh><source><float_array>0 0 0 1 1 1</float_array></source></mesh></geometry>'


def _node(nid: str, tx: float, shapes: list[str]) -> str:
    matrix = f"1 0 0 {tx} 0 1 0 0 0 0 1 0 0 0 0 1"
    geoms = "".join(f'<instance_geometry url="#{s}"/>' for s in shapes)
    return f'<node id="{nid}"><matrix>{matrix}</matrix>{geoms}</node>'


def test_dae_bboxes_apply_node_matrix_and_read_every_shape(tmp_path: Path) -> None:
    dae = tmp_path / "m.dae"
    dae.write_text(
        f'<COLLADA xmlns="{_NS}"><library_geometries>{_geometry("a")}{_geometry("b")}</library_geometries>'
        f"<library_visual_scenes><visual_scene>{_node('10', 0, ['a', 'b'])}{_node('11', 5, ['a'])}"
        "</visual_scene></library_visual_scenes></COLLADA>",
        encoding="utf-8",
    )
    entries, _ = ifc_processor._dae_element_bboxes(dae)
    assert [e for e, _ in entries] == ["10", "10", "11"]
    assert entries[2][1] == pytest.approx((5, 0, 0, 6, 1, 1))


def test_gltf_world_matrices_chain_parents() -> None:
    gltf = {
        "scenes": [{"nodes": [0]}],
        "nodes": [{"children": [1], "translation": [1, 0, 0]}, {"mesh": 0, "translation": [0, 2, 0]}],
    }
    world = ifc_processor._gltf_world_matrices(gltf)
    bb = ifc_processor._transform_bbox((0, 0, 0, 1, 1, 1), world[1])
    assert bb == pytest.approx((1, 2, 0, 2, 3, 1))


def _element(**kw: object) -> BIMElementResponse:
    now = datetime.now(UTC)
    base = {"id": uuid4(), "model_id": uuid4(), "stable_id": "1", "created_at": now, "updated_at": now}
    return BIMElementResponse(**{**base, **kw})


def test_type_definition_flag() -> None:
    assert _element(properties={"Export Type to IFC": "Default"}).is_type_definition
    assert not _element(properties={"Export Type to IFC": "Default"}, storey="L1").is_type_definition
    assert not _element(properties={"[Type] Export Type to IFC": "x"}).is_type_definition


def test_lookup_key_falls_back_to_type_parameter() -> None:
    assert _lookup_key({"[Type] si_volume": 2.5}, "si_volume") == 2.5
    assert _lookup_key({"[Type] si_volume": 2.5, "SI_Volume": 1}, "si_volume") == 1


def test_read_element_cells_uses_type_column_when_plain_cell_empty(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "e.parquet"
    pq.write_table(
        pa.table({"id": ["1", "2"], "si_volume": [None, "3"], "[Type] si_volume": ["2.5", "9"]}),
        path,
    )
    monkeypatch.setattr(dataframe_store, "_existing_parquet_path", lambda *_a, **_k: path)
    columns, cells = dataframe_store.read_element_cells("p", "m", ["si_volume"], ["1", "2"])
    assert columns == {"si_volume": "si_volume"}
    assert cells["1"]["si_volume"] == "2.5"
    assert cells["2"]["si_volume"] == "3"


@pytest.mark.skipif(os.name != "nt", reason="Windows executable locking")
def test_remove_unless_running_deletes_idle_copy(tmp_path: Path) -> None:
    copy = tmp_path / "old"
    (copy / "bin").mkdir(parents=True)
    (copy / "bin" / "postgres.exe").write_bytes(b"x")
    embedded_pg._remove_unless_running(copy)
    assert not copy.exists()


def test_remove_unless_running_keeps_copy_whose_exe_is_in_use(tmp_path: Path, monkeypatch) -> None:
    copy = tmp_path / "old"
    exe = copy / "bin" / "postgres.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    monkeypatch.setattr(embedded_pg.os, "name", "nt")

    def _locked(self: Path, *a: object, **k: object) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", _locked)
    embedded_pg._remove_unless_running(copy)
    assert exe.exists()


def test_flat_methodologies_count_machinery_as_equipment() -> None:
    bases = resolve_bases(_FLAT_BASE_MAPPING, {"equipment": Decimal("10"), "machinery": Decimal("5")})
    assert bases["equipment"] == Decimal("15")
