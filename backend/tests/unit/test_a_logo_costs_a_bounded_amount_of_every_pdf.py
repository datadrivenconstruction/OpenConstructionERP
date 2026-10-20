# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An uploaded logo costs a bounded amount of every PDF, and costs it off the
event loop.

The logo a workspace uploads is drawn on the letterhead of page one and in the
header band of every page after it, at about 60 x 20 mm. What reached the page
was whatever was uploaded, at its full resolution, and two shapes of that were
expensive enough to be a denial of service by a signed-in user:

  * An SVG says how large its page is in its own opening tag. A 146-byte file
    declaring a hundred thousand units passed the sanitiser, and the server
    rasterised it to whatever it declared. The server no longer rasterises SVG
    at all: the browser sends a PNG next to it, and that PNG is the logo the
    documents see, shrunk like any other raster.
  * A 1000 x 1000 photograph is 3.82 MiB as a data URL, inside the upload
    limit, and went into the file at 1000 x 1000 to be drawn at 57 pt square.
    The RFI came out at 3.7 MB.

Both are measured here against an ordinary logo of the same kind rather than
against an absolute number, because what matters is that the hostile file is no
worse than the honest one, and an absolute threshold measured on one machine is
a flake on another.

The second half is where the work runs. These renders are seconds of CPU with
no await in them, so on the event loop they stall every other request the
worker is serving. The test for that watches the loop rather than reading the
source: a coroutine ticking beside the render counts how often it got to run.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import io
import time
from pathlib import Path
from typing import Any

import pypdf
import pytest
from PIL import Image

from app.core import app_branding, branding_router, company_profile, pdf_appearance
from app.core.pdf_branding import (
    _LETTERHEAD_LOGO_MAX_H,
    _LETTERHEAD_LOGO_MAX_W,
    _LOGO_PIXELS_PER_POINT,
    render_sample_pdf,
)
from tests._pdf_probe import image_boxes

#: An SVG page this large is ordinary; the same file declaring the second is
#: the attack. Both are the same handful of bytes and draw the same square.
ORDINARY_SIDE = 300
HOSTILE_SIDE = 100_000


def _svg(side: int) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" height="{side}" viewBox="0 0 100 100">'
        '<rect width="100" height="100" fill="#0b5394"/></svg>'
    ).encode()


@functools.lru_cache(maxsize=8)
def _png(size: tuple[int, int], *, noise: bool = False) -> bytes:
    """A logo-shaped PNG. ``noise`` makes one that will not compress, the worst case.

    Hashed rather than random so two runs build the same bytes, and joined from
    a list rather than concatenated in a loop, which for three megabytes of it
    is the difference between a tenth of a second and three and a half minutes.
    """
    if noise:
        width, height = size
        needed = width * height * 3
        chunks = []
        seed = b"logo-noise"
        total = 0
        while total < needed:
            seed = hashlib.sha256(seed).digest()
            chunks.append(seed)
            total += len(seed)
        image = Image.frombytes("RGB", size, b"".join(chunks)[:needed])
    else:
        image = Image.new("RGB", size, "#0b5394")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _data_url(raw: bytes, kind: str) -> str:
    return f"data:image/{kind};base64," + base64.b64encode(raw).decode("ascii")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty data dir, so a logo on the machine running the tests never reaches a document."""
    for module in (app_branding, company_profile, pdf_appearance):
        monkeypatch.setattr(module, "resolve_data_dir", lambda: tmp_path)
    return tmp_path


def _store(data_dir: Path, data_url: str, png: str | None = None) -> None:
    """Store the logo the way the settings page does, through the real sanitiser.

    ``png`` is the raster the browser sends next to an SVG logo.
    """
    stored = company_profile.write_company_profile(
        {
            "legal_name": "Acme Bau GmbH",
            "address": "Hauptstrasse 12\n10115 Berlin",
            "document_logo_data_url": data_url,
            "document_logo_png_data_url": png or "",
        },
        data_dir,
    )
    assert stored.get("document_logo_data_url"), (
        "the sanitiser rejected this logo, so the rest of the case would be measuring nothing"
    )
    if png:
        assert stored.get("document_logo_png_data_url"), "the sanitiser rejected the PNG companion"


def _pictures(pdf: bytes) -> list[tuple[int, int, float, float]]:
    """Every image on page one: ``(stored_px_w, stored_px_h, drawn_pt_w, drawn_pt_h)``, in drawing order."""
    page = pypdf.PdfReader(io.BytesIO(pdf)).pages[0]
    stored = [
        (int(ref.get_object()["/Width"]), int(ref.get_object()["/Height"]))
        for ref in (page["/Resources"].get("/XObject") or {}).values()
        if ref.get_object().get("/Subtype") == "/Image"
    ]
    boxes = image_boxes(pdf)
    assert len(stored) == len(boxes), f"{len(stored)} image resources but {len(boxes)} drawn"
    return [(w, h, box.x1 - box.x0, box.y1 - box.y0) for (w, h), box in zip(stored, boxes, strict=True)]


def _render(times: int = 1) -> tuple[bytes, float]:
    """The settings sample, and the best wall time of ``times`` runs.

    The best rather than the mean: a slow run can be this machine doing
    something else, a fast one cannot be the code being slower than it is.
    """
    render_sample_pdf()  # warm the caches, so the first import is not in the timing
    best = float("inf")
    pdf = b""
    for _ in range(times):
        start = time.perf_counter()
        pdf = render_sample_pdf()
        best = min(best, time.perf_counter() - start)
    return pdf, best


# ── The raster a logo reaches the page as ─────────────────────────────────


def test_a_hostile_svg_without_a_png_costs_nothing(data_dir: Path) -> None:
    """The server never reads the page an SVG declares, so declaring a huge one buys nothing."""
    _store(data_dir, _data_url(_svg(HOSTILE_SIDE), "svg+xml"))
    pdf, _ = _render()
    assert pdf.startswith(b"%PDF")
    assert _pictures(pdf) == [], "an SVG with no PNG next to it was drawn as something"


@pytest.mark.parametrize(
    ("label", "logo"),
    [
        ("svg companion", lambda: (_data_url(_svg(ORDINARY_SIDE), "svg+xml"), _data_url(_png((4000, 1300)), "png"))),
        ("wide raster", lambda: (_data_url(_png((4000, 1300)), "png"), None)),
        ("square photograph", lambda: (_data_url(_png((1000, 1000), noise=True), "png"), None)),
    ],
)
def test_a_logo_goes_into_the_pdf_at_the_size_it_is_drawn_not_the_size_it_was_uploaded(
    label: str, logo: Any, data_dir: Path
) -> None:
    """No more than a few pixels per point, whatever was uploaded."""
    _store(data_dir, *logo())
    pictures = _pictures(render_sample_pdf())
    assert pictures, f"{label}: no image on the sample's page, so there is nothing to measure"
    for width, height, drawn_w, drawn_h in pictures:
        assert drawn_w > 0 and drawn_h > 0, f"{label}: the logo is drawn in an empty box"
        # One point of slack per side: a thumbnail lands on whole pixels.
        assert width <= _LETTERHEAD_LOGO_MAX_W * _LOGO_PIXELS_PER_POINT + 1, (
            f"{label}: {width}x{height} px stored to be drawn {drawn_w:.0f}x{drawn_h:.0f} pt, "
            f"which is {width / drawn_w:.0f} pixels per point"
        )
        assert height <= _LETTERHEAD_LOGO_MAX_H * _LOGO_PIXELS_PER_POINT + 1, (
            f"{label}: {width}x{height} px stored for a {drawn_w:.0f}x{drawn_h:.0f} pt box"
        )


def test_an_ordinary_logo_is_left_exactly_as_it_was_uploaded(data_dir: Path) -> None:
    """The negative control, in pixels: the shrink only touches what is oversized.

    A wordmark of the size firms actually upload is already about two pixels per
    point, and re-encoding it would be a change to every existing document for
    no gain. Paired with the cases above, which prove the shrink does happen.
    """
    uploaded = (360, 120)
    assert uploaded[0] <= _LETTERHEAD_LOGO_MAX_W * _LOGO_PIXELS_PER_POINT, (
        "this fixture is supposed to be inside the bound; pick a smaller one"
    )
    _store(data_dir, _data_url(_png(uploaded), "png"))
    pictures = _pictures(render_sample_pdf())
    assert [(width, height) for width, height, _, _ in pictures] == [uploaded], (
        f"an ordinary {uploaded[0]}x{uploaded[1]} logo was re-encoded as {pictures}"
    )


def test_shrinking_a_logo_does_not_move_the_box_it_is_drawn_in(data_dir: Path) -> None:
    """The same mark at two resolutions lands in the same rectangle.

    The drawn size is worked out from the size the logo arrived at, before any
    shrinking, precisely so that this holds: a letterhead that shifted when a
    logo was re-encoded would be this fix showing up on the page.
    """
    boxes = {}
    for label, size in (("small", (360, 120)), ("huge", (4000, 1333))):
        _store(data_dir, _data_url(_png(size), "png"))
        pictures = _pictures(render_sample_pdf())
        assert len(pictures) == 1, f"{label}: expected one logo on the page, found {len(pictures)}"
        boxes[label] = pictures[0][2:]
    assert boxes["huge"] == pytest.approx(boxes["small"], abs=0.5), (
        f"the same mark is drawn {boxes['small']} when small and {boxes['huge']} when large"
    )


# ── What it costs ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "honest", "hostile"),
    [
        (
            "svg",
            lambda: (_data_url(_svg(ORDINARY_SIDE), "svg+xml"), _data_url(_png((360, 120)), "png")),
            lambda: (_data_url(_svg(HOSTILE_SIDE), "svg+xml"), _data_url(_png((1000, 1000), noise=True), "png")),
        ),
        (
            "raster",
            lambda: (_data_url(_png((360, 120)), "png"), None),
            lambda: (_data_url(_png((1000, 1000), noise=True), "png"), None),
        ),
    ],
)
def test_an_expensive_logo_costs_what_an_ordinary_one_costs(
    label: str, honest: Any, hostile: Any, data_dir: Path
) -> None:
    """Size and time, both measured against the honest logo rather than a constant."""
    _store(data_dir, *honest())
    honest_pdf, honest_time = _render(times=3)
    _store(data_dir, *hostile())
    hostile_pdf, hostile_time = _render(times=3)

    assert len(hostile_pdf) < len(honest_pdf) * 4, (
        f"{label}: the expensive logo makes a {len(hostile_pdf) / 1024:.0f} KiB document "
        f"where the ordinary one makes {len(honest_pdf) / 1024:.0f} KiB"
    )
    # Generous on purpose. Before the fix this ratio was 20x and more; a bound
    # that a loaded machine can trip teaches the team to ignore the test.
    assert hostile_time < max(honest_time * 8, 2.0), (
        f"{label}: the expensive logo takes {hostile_time:.2f}s against {honest_time:.2f}s for the ordinary one"
    )


# ── Where it runs ─────────────────────────────────────────────────────────


async def _ticks_while(work: Any) -> int:
    """How many times a coroutine beside ``work`` got to run while it ran.

    Zero means the event loop was held for the whole of it and this worker
    answered nobody.
    """
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    ticker = asyncio.create_task(tick())
    try:
        await asyncio.sleep(0)  # let the ticker reach its first await
        await work
    finally:
        ticker.cancel()
    return ticks


HELD = 0.25


async def test_rendering_the_settings_sample_leaves_the_event_loop_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both samples are drawn off the loop, and the instrument can tell the difference."""

    def slow(*_args: Any, **_kwargs: Any) -> bytes:
        time.sleep(HELD)
        return b"%PDF-1.4\n"

    import app.core.pdf_branding as pdf_branding

    monkeypatch.setattr(pdf_branding, "render_sample_pdf", slow)

    free = await _ticks_while(branding_router.get_document_appearance_sample())
    assert free > 5, f"the workspace sample held the loop for all of its {HELD}s ({free} ticks)"

    # The control: the same renderer called the way the handler used to call it.
    # Without this a test that never sees the loop move would pass just as well.
    async def on_the_loop() -> None:
        slow()

    held = await _ticks_while(on_the_loop())
    assert held < free, (
        f"the instrument cannot tell the two apart: {held} ticks while the loop was held, {free} while it was free"
    )
