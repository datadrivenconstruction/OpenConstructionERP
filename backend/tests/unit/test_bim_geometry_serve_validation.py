"""‌⁠‍Serve-time geometry validation guards bad bytes from reaching the viewer.

Regression for an external user report (Downtown Medical Center / RVT) where
``_validate_geometry_file`` caught corrupt geometry only on ingest, while
already-stored bad blobs kept streaming to the browser and surfaced as
opaque Three.js errors. The serve-time guard in ``router.py`` peeks at the
first ~4 KB of every geometry response and rejects payloads that do not
match the format their extension promises.
"""

from __future__ import annotations

import json

from app.modules.bim_hub.router import _quick_validate_geometry_bytes


class TestGeometryServeValidationGLB:
    def test_valid_glb_passes(self) -> None:
        # Minimal valid GLB header: "glTF" magic + version 2 + length 12 +
        # pad up to 200 bytes (size floor) of arbitrary content.
        head = b"glTF" + (2).to_bytes(4, "little") + (12).to_bytes(4, "little")
        ok, reason = _quick_validate_geometry_bytes(head + b"\x00" * 250, ".glb")
        assert ok is True
        assert reason == "ok"

    def test_glb_magic_mismatch_rejected(self) -> None:
        # The user-reported case: bytes start with "<?xml ve" but are
        # served from a ``.glb`` slot — would crash GLTFLoader otherwise.
        ok, reason = _quick_validate_geometry_bytes(b"<?xml ve" + b"\x00" * 300, ".glb")
        assert ok is False
        assert "magic mismatch" in reason

    def test_glb_wrong_version_rejected(self) -> None:
        head = b"glTF" + (1).to_bytes(4, "little") + (12).to_bytes(4, "little")
        ok, reason = _quick_validate_geometry_bytes(head + b"\x00" * 250, ".glb")
        assert ok is False
        assert "version" in reason


class TestGeometryServeValidationDAE:
    def test_valid_collada_passes(self) -> None:
        body = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">\n'
            b"  <library_visual_scenes/>\n"
            b"</COLLADA>\n"
        ).ljust(300, b" ")
        ok, reason = _quick_validate_geometry_bytes(body, ".dae")
        assert ok is True
        assert reason == "ok"

    def test_xml_but_not_collada_rejected_with_first_tag_hint(self) -> None:
        # Exact user-report shape: "<?xml ve" head + non-COLLADA root.
        body = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<ifcXML xmlns="http://www.buildingsmart-tech.org/ifcXML/IFC4/final">\n'
            b"  <header/>\n"
            b"</ifcXML>\n"
        ).ljust(300, b" ")
        ok, reason = _quick_validate_geometry_bytes(body, ".dae")
        assert ok is False
        assert "no <COLLADA> root" in reason
        # The diagnostic surfaces what we DID find so an admin can act.
        assert "<ifcXML>" in reason or "<ifcxml>" in reason.lower()

    def test_html_error_page_rejected(self) -> None:
        body = (b"<!DOCTYPE html><html><head><title>502 Bad Gateway</title></head></html>").ljust(300, b" ")
        ok, reason = _quick_validate_geometry_bytes(body, ".dae")
        assert ok is False
        assert "no <COLLADA> root" in reason


class TestGeometryServeValidationCommon:
    def test_empty_buffer_rejected(self) -> None:
        ok, reason = _quick_validate_geometry_bytes(b"", ".dae")
        assert ok is False
        assert "empty" in reason

    def test_truncated_buffer_rejected(self) -> None:
        ok, reason = _quick_validate_geometry_bytes(b"short", ".dae")
        assert ok is False
        assert "small" in reason

    def test_unknown_extension_passes_through(self) -> None:
        # Forward-compat: a future ".obj" / ".ply" extension we forgot to
        # special-case should not 422 the response.
        ok, reason = _quick_validate_geometry_bytes(b"x" * 400, ".obj")
        assert ok is True
        assert "unknown extension" in reason

    def test_valid_gltf_json_passes(self) -> None:
        # Real-world gltf JSON files are pure JSON with no trailing data,
        # so we pad with a long inert string field rather than NUL bytes.
        body = json.dumps(
            {
                "asset": {"version": "2.0", "generator": "x" * 250},
                "scenes": [],
            }
        ).encode()
        assert len(body) >= 200
        ok, reason = _quick_validate_geometry_bytes(body, ".gltf")
        assert ok is True, f"unexpected rejection: {reason}"

    def test_gltf_missing_asset_rejected(self) -> None:
        body = json.dumps({"scenes": [], "comment": "x" * 250}).encode()
        assert len(body) >= 200
        ok, reason = _quick_validate_geometry_bytes(body, ".gltf")
        assert ok is False
        assert "asset" in reason
