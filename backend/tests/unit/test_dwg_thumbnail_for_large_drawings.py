"""A large drawing's preview comes from the parsed geometry, not the slow ezdxf renderer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.modules.dwg_takeoff import dxf_processor
from app.modules.dwg_takeoff import service as service_mod


def _line(x: float) -> dict[str, Any]:
    return {
        "entity_type": "LINE",
        "layer": "0",
        "color": "#ffffff",
        "geometry_data": {"start": {"x": x, "y": 0.0}, "end": {"x": x, "y": 10.0}},
        "layout": "Model",
    }


def test_the_preview_draws_model_space_linework_and_skips_block_definitions() -> None:
    arc = {
        "entity_type": "ARC",
        "color": "#ff0000",
        "geometry_data": {"center": {"x": 0, "y": 0}, "radius": 5, "start_angle": 0, "end_angle": 1.5},
    }
    in_block = {**_line(999.0), "block": "DOOR"}
    svg = dxf_processor.svg_thumbnail_from_entities([_line(0.0), _line(20.0), arc, in_block])
    assert svg.startswith("<svg")
    assert svg.count("<polyline") == 3
    assert 'stroke="#ff0000"' in svg


def test_an_empty_drawing_still_gets_a_valid_preview() -> None:
    assert dxf_processor.svg_thumbnail_from_entities([]).startswith("<svg")


def test_a_large_drawing_never_reaches_the_ezdxf_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    many = [_line(float(i)) for i in range(dxf_processor.THUMBNAIL_RENDER_MAX_ENTITIES + 1)]
    monkeypatch.setattr(dxf_processor, "parse_dxf", lambda _p: {"entities": many})

    def slow_render(_p: str) -> str:
        raise AssertionError("the ezdxf renderer must not run for a large drawing")

    monkeypatch.setattr(dxf_processor, "generate_svg_thumbnail", slow_render)
    monkeypatch.setattr(service_mod, "_get_entities_dir", lambda: str(tmp_path))
    monkeypatch.setattr(service_mod, "_dwg_data_base", lambda: str(tmp_path))

    service_mod._process_dxf_sync("big.dxf", "d/entities.json", "d/thumbnail.svg")

    thumb = os.path.join(tmp_path, "dwg_thumbnails", "d", "thumbnail.svg")
    assert Path(thumb).read_text(encoding="utf-8").startswith("<svg")
