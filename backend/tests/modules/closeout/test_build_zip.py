"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Closeout ZIP assembly test (real PostgreSQL session).

Exercises ``_build_zip_blob`` end to end and asserts the archive carries a
cover PDF, machine-readable manifest.json, an index.json and a README, and
that the manifest reflects completeness + gaps. COBie / punch / inspection
artifacts degrade gracefully (recorded as manifest notes) when the synthetic
project has no BIM model or evidence rows.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.modules.closeout.service import CloseoutService

pytestmark = pytest.mark.asyncio


async def test_build_zip_blob_produces_valid_archive(session, project_id):
    service = CloseoutService(session)
    package = await service.create_package(project_id, "commercial")

    # Verify one required document slot so the manifest shows partial progress.
    slots = await service.repo.list_slots(package.id)
    as_built = next(s for s in slots if s.slot_key == "as_built_drawings")
    await service.bind_slot(
        as_built,
        document_id=None,
        external_url="https://cde.example.com/as-built.pdf",
        mark_verified=True,
        verified_by="manager-1",
    )
    package = await service.get_package_or_404(package.id)

    zip_bytes, summary = await service._build_zip_blob(package)

    assert isinstance(zip_bytes, bytes) and zip_bytes
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        assert "cover.pdf" in names
        assert "manifest.json" in names
        assert "index.json" in names
        assert "README.md" in names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["kind"] == "construction_closeout_package"
        assert manifest["project_id"] == str(project_id)
        assert "completeness" in manifest
        assert isinstance(manifest["slots"], list) and manifest["slots"]
        # The verified as-built slot is recorded as verified.
        ab = next(s for s in manifest["slots"] if s["slot_key"] == "as_built_drawings")
        assert ab["status"] == "verified"

        index = json.loads(zf.read("index.json"))
        # cover.pdf is hashed in the index.
        cover = next((e for e in index if e["path"] == "cover.pdf"), None)
        assert cover is not None
        assert cover["size_bytes"] > 0
        assert len(cover["sha256"]) == 64

        cover_pdf = zf.read("cover.pdf")
        assert cover_pdf.startswith(b"%PDF")

    # COBie degrades to a note when the project has no BIM model.
    assert any("COBie" in note for note in summary["notes"])
    assert summary["size_bytes"] > 0
