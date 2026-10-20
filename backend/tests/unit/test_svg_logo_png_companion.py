# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An SVG logo is printed from the PNG the browser rasterised it to.

The server does not rasterise SVG. The browser sends a PNG next to the SVG, and
both stores keep it only while the SVG it belongs to is the logo: a raster logo,
or a new logo that arrives without a PNG, must not leave a stale picture behind
for the documents to print.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.core import app_branding, company_profile, pdf_appearance
from app.core.company_profile_router import router as company_profile_router
from app.core.pdf_branding import _logo_candidates, render_sample_pdf
from app.dependencies import get_current_user_payload

_SVG = "data:image/svg+xml;base64," + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode()
_OTHER_SVG = (
    "data:image/svg+xml;base64," + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" id="b"/>').decode()
)


def _png(width: int = 60, height: int = 20, colour: str = "#1f6f43") -> str:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    for module in (app_branding, company_profile, pdf_appearance):
        monkeypatch.setattr(module, "resolve_data_dir", lambda: tmp_path)
    return tmp_path


# -- company profile sanitiser -----------------------------------------------


def test_the_profile_keeps_the_png_next_to_an_svg_logo() -> None:
    clean = company_profile.sanitise({"document_logo_data_url": _SVG, "document_logo_png_data_url": _png()})
    assert clean["document_logo_data_url"] == _SVG
    assert clean["document_logo_png_data_url"] == _png()


@pytest.mark.parametrize("logo", [_png(10, 10), "", "data:image/jpeg;base64,/9j/4AAQ"])
def test_the_profile_drops_the_png_when_the_logo_is_not_an_svg(logo: str) -> None:
    clean = company_profile.sanitise({"document_logo_data_url": logo, "document_logo_png_data_url": _png()})
    assert clean["document_logo_png_data_url"] == ""


@pytest.mark.parametrize(
    "png",
    [
        None,
        7,
        "",
        "data:image/png;base64,",
        "data:image/jpeg;base64,/9j/4AAQ",
        _SVG,
        "data:image/png;base64," + "A" * company_profile.MAX_LOGO_DATA_URL_CHARS,
    ],
    ids=["none", "int", "empty", "no-body", "jpeg", "svg", "over-cap"],
)
def test_the_profile_drops_a_companion_that_is_not_a_usable_png(png: object) -> None:
    clean = company_profile.sanitise({"document_logo_data_url": _SVG, "document_logo_png_data_url": png})
    assert clean["document_logo_data_url"] == _SVG
    assert clean["document_logo_png_data_url"] == ""


# -- app branding sanitiser --------------------------------------------------


def test_the_branding_keeps_the_png_next_to_an_svg_logo() -> None:
    clean = app_branding.sanitise({"mode": "logo", "logo_data_url": _SVG, "logo_png_data_url": _png()})
    assert clean["logo_data_url"] == _SVG
    assert clean["logo_png_data_url"] == _png()


@pytest.mark.parametrize("logo", [_png(10, 10), None])
def test_the_branding_drops_the_png_when_the_logo_is_not_an_svg(logo: str | None) -> None:
    clean = app_branding.sanitise({"mode": "logo", "logo_data_url": logo, "logo_png_data_url": _png()})
    assert clean["logo_png_data_url"] is None


@pytest.mark.parametrize("png", [None, 7, "", "data:image/jpeg;base64,/9j/4AAQ", _SVG])
def test_the_branding_drops_a_companion_that_is_not_a_png(png: object) -> None:
    clean = app_branding.sanitise({"mode": "logo", "logo_data_url": _SVG, "logo_png_data_url": png})
    assert clean["logo_png_data_url"] is None


def test_the_branding_png_survives_a_write_and_a_read(data_dir: Path) -> None:
    app_branding.write_branding({"mode": "logo", "logo_data_url": _SVG, "logo_png_data_url": _png()}, data_dir)
    assert app_branding.read_branding(data_dir)["logo_png_data_url"] == _png()


# -- the PUT merge -----------------------------------------------------------


@pytest.fixture
def admin() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(company_profile_router, prefix="/api/v1")

    async def _payload() -> dict[str, str]:
        return {"sub": "user-under-test", "role": "admin"}

    app.dependency_overrides[get_current_user_payload] = _payload
    with TestClient(app) as client:
        yield client


def test_a_put_with_a_logo_and_its_png_stores_both(admin: TestClient, data_dir: Path) -> None:
    response = admin.put(
        "/api/v1/company-profile/", json={"document_logo_data_url": _SVG, "document_logo_png_data_url": _png()}
    )
    assert response.status_code == 200
    stored = company_profile.read_company_profile(data_dir)
    assert (stored["document_logo_data_url"], stored["document_logo_png_data_url"]) == (_SVG, _png())


def test_a_put_with_a_new_logo_and_no_png_clears_the_stale_png(admin: TestClient, data_dir: Path) -> None:
    company_profile.write_company_profile(
        {"legal_name": "Acme", "document_logo_data_url": _SVG, "document_logo_png_data_url": _png()}, data_dir
    )
    response = admin.put("/api/v1/company-profile/", json={"document_logo_data_url": _OTHER_SVG})
    assert response.status_code == 200
    stored = company_profile.read_company_profile(data_dir)
    assert stored["document_logo_data_url"] == _OTHER_SVG
    assert stored["document_logo_png_data_url"] == ""
    assert stored["legal_name"] == "Acme"


def test_a_put_that_leaves_the_logo_alone_keeps_its_png(admin: TestClient, data_dir: Path) -> None:
    company_profile.write_company_profile(
        {"legal_name": "Acme", "document_logo_data_url": _SVG, "document_logo_png_data_url": _png()}, data_dir
    )
    response = admin.put("/api/v1/company-profile/", json={"phone": "+49 30 1234567"})
    assert response.status_code == 200
    assert company_profile.read_company_profile(data_dir)["document_logo_png_data_url"] == _png()


# -- what the documents offer to draw ----------------------------------------


def test_an_svg_logo_is_offered_as_its_png() -> None:
    profile = {"document_logo_data_url": _SVG, "document_logo_png_data_url": _png()}
    assert _logo_candidates({}, profile) == [_png()]


def test_an_svg_logo_without_a_png_is_not_offered_and_the_next_logo_is() -> None:
    profile = {"document_logo_data_url": _SVG, "document_logo_png_data_url": ""}
    branding = {"logo_data_url": _png(30, 10), "logo_png_data_url": None}
    assert _logo_candidates(branding, profile) == [_png(30, 10)]
    assert _logo_candidates({}, profile) == []


def test_an_svg_app_logo_is_offered_as_its_png() -> None:
    branding = {"logo_data_url": _SVG, "logo_png_data_url": _png()}
    assert _logo_candidates(branding, {}) == [_png()]


# -- the rendered page -------------------------------------------------------


def test_an_svg_only_logo_still_gives_a_valid_pdf_with_the_name(data_dir: Path) -> None:
    from app.core import pdf_reader

    company_profile.write_company_profile(
        {"legal_name": "Acme Bau GmbH", "address": "Hauptstrasse 12\n10115 Berlin", "document_logo_data_url": _SVG},
        data_dir,
    )
    pdf = render_sample_pdf()
    assert pdf.startswith(b"%PDF")
    with pdf_reader.open_pdf(pdf) as doc:
        assert doc.page_count >= 1
        assert "Acme Bau GmbH" in doc[0].text()


def test_an_svg_logo_with_a_png_prints_the_png(data_dir: Path) -> None:
    from tests._pdf_probe import image_boxes

    company_profile.write_company_profile(
        {
            "legal_name": "Acme Bau GmbH",
            "document_logo_data_url": _SVG,
            "document_logo_png_data_url": _png(),
        },
        data_dir,
    )
    assert len(image_boxes(render_sample_pdf())) == 1
