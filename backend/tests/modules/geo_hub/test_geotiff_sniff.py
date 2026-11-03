"""GeoTIFF header sniffing: georeferenced, projected, bare, corrupt and bomb inputs."""

from __future__ import annotations

import io

import pytest
from PIL import Image, TiffImagePlugin

from app.modules.geo_hub.geotiff_sniff import GeoTiffError, sniff_geotiff
from app.modules.geo_hub.raster_pipeline import ImagePixelBudgetExceeded


def make_geotiff(
    *,
    size: tuple[int, int] = (40, 20),
    epsg: int | None = 4326,
    projected: bool = False,
    scale: tuple[float, float] = (0.001, 0.001),
    origin: tuple[float, float] = (13.40, 52.52),
) -> bytes:
    img = Image.new("RGB", size, "#336699")
    ifd = TiffImagePlugin.ImageFileDirectory_v2()
    if epsg is not None:
        ifd.tagtype[33550] = 12
        ifd[33550] = (scale[0], scale[1], 0.0)
        ifd.tagtype[33922] = 12
        ifd[33922] = (0.0, 0.0, 0.0, origin[0], origin[1], 0.0)
        key = 3072 if projected else 2048
        ifd.tagtype[34735] = 3
        ifd[34735] = (1, 1, 0, 1, key, 0, 1, epsg)
    buf = io.BytesIO()
    img.save(buf, format="TIFF", tiffinfo=ifd)
    return buf.getvalue()


def test_geographic_4326_bbox_and_gsd() -> None:
    meta = sniff_geotiff(make_geotiff())
    assert (meta.width, meta.height, meta.band_count) == (40, 20, 3)
    assert meta.crs_epsg == 4326
    assert meta.warnings == []
    min_lon, min_lat, max_lon, max_lat = meta.bbox_wgs84
    assert min_lon == pytest.approx(13.40)
    assert max_lon == pytest.approx(13.44)
    assert max_lat == pytest.approx(52.52)
    assert min_lat == pytest.approx(52.50)
    # 0.001 deg of longitude at 52.5 N is about 67.8 m
    assert meta.gsd_m == pytest.approx(67.8, abs=1.0)


def test_utm_32632_places_the_box_near_the_origin_in_wgs84() -> None:
    # 500000 E is the central meridian of zone 32 (9 E); 5_400_000 N is about 48.75 N.
    meta = sniff_geotiff(
        make_geotiff(epsg=32632, projected=True, scale=(0.05, 0.05), origin=(500_000.0, 5_400_000.0), size=(100, 100))
    )
    assert meta.crs_epsg == 32632
    min_lon, min_lat, max_lon, max_lat = meta.bbox_wgs84
    assert min_lon == pytest.approx(9.0, abs=1e-3)
    assert max_lon == pytest.approx(9.0, abs=1e-3)
    assert max_lat == pytest.approx(48.753, abs=0.001)
    assert meta.gsd_m == pytest.approx(0.05)


def test_utm_inverse_matches_a_known_point() -> None:
    # Berlin Alexanderplatz is about 392_000 E / 5_820_000 N in UTM 33N.
    from app.modules.geo_hub.geotiff_sniff import _utm_inverse

    lon, lat = _utm_inverse(392_000.0, 5_820_000.0, 33, False)
    assert lat == pytest.approx(52.52, abs=0.01)
    assert lon == pytest.approx(13.41, abs=0.01)


def test_plain_tiff_is_accepted_with_a_warning() -> None:
    meta = sniff_geotiff(make_geotiff(epsg=None))
    assert meta.crs_epsg is None
    assert meta.bbox_wgs84 is None
    assert meta.gsd_m is None
    assert "not_georeferenced" in meta.warnings


def test_user_defined_crs_gives_no_bbox() -> None:
    meta = sniff_geotiff(make_geotiff(epsg=32767, projected=True))
    assert meta.bbox_wgs84 is None
    assert "crs_unknown" in meta.warnings


def test_corrupt_bytes_raise() -> None:
    with pytest.raises(GeoTiffError):
        sniff_geotiff(b"II*\x00" + b"\xff" * 12)
    with pytest.raises(GeoTiffError):
        sniff_geotiff(b"not a tiff at all")


def test_png_is_not_a_tiff() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="PNG")
    with pytest.raises(GeoTiffError):
        sniff_geotiff(buf.getvalue())


def test_pixel_bomb_is_refused_without_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    data = make_geotiff(size=(64, 64))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ImagePixelBudgetExceeded):
        sniff_geotiff(data)


def test_path_input(tmp_path) -> None:
    p = tmp_path / "o.tif"
    p.write_bytes(make_geotiff())
    assert sniff_geotiff(p).crs_epsg == 4326
