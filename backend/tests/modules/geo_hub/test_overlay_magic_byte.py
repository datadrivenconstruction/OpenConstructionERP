"""Magic-byte sniffer rejects mislabelled uploads with HTTP 415."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_non_pdf_bytes_with_pdf_extension_rejected(
    http_client,
    tenant_a,
):
    fake = b"not a pdf at all, just some bytes pretending to be one"
    files = {"file": ("fake.pdf", fake, "application/pdf")}
    res = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-pdf",
        data={"project_id": tenant_a["project_id"], "page": "1"},
        files=files,
        headers=tenant_a["headers"],
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_non_image_bytes_with_png_extension_rejected(
    http_client,
    tenant_a,
):
    fake = b"clearly not a png" + b"\x00" * 32
    files = {"file": ("fake.png", fake, "image/png")}
    res = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-image",
        data={"project_id": tenant_a["project_id"]},
        files=files,
        headers=tenant_a["headers"],
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_image_endpoint_rejects_a_valid_pdf(http_client, tenant_a, tiny_pdf):
    """Cross-format upload — a real PDF posted to the image endpoint
    must still 415 because the image allow-list excludes ``pdf``."""
    pdf = tiny_pdf
    files = {"file": ("plan.png", pdf, "image/png")}
    res = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-image",
        data={"project_id": tenant_a["project_id"]},
        files=files,
        headers=tenant_a["headers"],
    )
    assert res.status_code == 415, res.text
