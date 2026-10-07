# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A stored site photo carries no GPS block unless the deployer keeps it.

A photo's EXIF GPS says where a person stood, and the file travels on every
download and share. The upload still reads the coordinates onto the photo
record (the map pin), then drops the GPS block from the stored file. Other
EXIF tags stay, and ``OE_PHOTO_KEEP_EXIF_GPS=true`` stores files untouched.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from app.modules.documents.service import _EXIF_GPS_IFD_TAG, _keep_photo_gps, _strip_exif_gps

_ORIENTATION = 0x0112


def _jpeg(with_gps: bool) -> bytes:
    img = Image.new("RGB", (32, 24), (120, 140, 160))
    exif = Image.Exif()
    exif[_ORIENTATION] = 1
    if with_gps:
        exif[_EXIF_GPS_IFD_TAG] = {1: "N", 2: (52.0, 31.0, 12.0), 3: "E", 4: (13.0, 24.0, 18.0)}
    out = BytesIO()
    img.save(out, format="JPEG", exif=exif.tobytes(), quality=90)
    return out.getvalue()


def _exif_of(data: bytes) -> Image.Exif:
    with Image.open(BytesIO(data)) as img:
        return img.getexif()


def test_the_gps_block_is_removed_and_other_tags_stay() -> None:
    original = _jpeg(with_gps=True)
    assert _EXIF_GPS_IFD_TAG in _exif_of(original)

    stripped = _strip_exif_gps(original)

    exif = _exif_of(stripped)
    assert _EXIF_GPS_IFD_TAG not in exif
    assert exif[_ORIENTATION] == 1


def test_a_photo_without_gps_is_stored_byte_for_byte() -> None:
    original = _jpeg(with_gps=False)

    assert _strip_exif_gps(original) is original


def test_bytes_that_are_not_an_image_come_back_unchanged() -> None:
    junk = b"not an image at all"

    assert _strip_exif_gps(junk) is junk


@pytest.mark.parametrize(("value", "keep"), [(None, False), ("", False), ("false", False), ("true", True), ("1", True)])
def test_keeping_gps_is_an_explicit_opt_in(monkeypatch: pytest.MonkeyPatch, value: str | None, keep: bool) -> None:
    if value is None:
        monkeypatch.delenv("OE_PHOTO_KEEP_EXIF_GPS", raising=False)
    else:
        monkeypatch.setenv("OE_PHOTO_KEEP_EXIF_GPS", value)

    assert _keep_photo_gps() is keep
