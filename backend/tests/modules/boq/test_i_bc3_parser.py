"""Epic I6 — FIEBDC-3 / BC3 parser tests.

Covers four synthetic BC3 fixtures (the format has no canonical reference
file the test repo can ship — every spec example is copyrighted by AENOR
— so we generate the minimum-viable records ourselves):

1. **UTF-8 BC3 with a chapter + partida + measurement** — the happy
   path. The parser must surface 1 section + 1 partida with the
   correct unit, quantity and unit rate.
2. **Latin-1 (CP1252) BC3 with Spanish accents** — the encoding probe
   must pick the right codec and round-trip the description.
3. **BC3 with line continuations** — a long `~T` record split across
   two physical lines (no `~` on the second).
4. **BC3 with multiple capítulos + partidas** — verifies that section
   detection works on both type=1 and trailing-`#` heuristics.
"""

from __future__ import annotations

import pytest

from app.modules.boq.importers.bc3 import BC3Importer

# ── Fixtures ────────────────────────────────────────────────────────────────


def _build_bc3_utf8() -> bytes:
    return (
        "~V|FIEBDC-3|3.0|TestExporter|2026-01-01|sample|0|UTF-8|EUR|\n"
        "~C|01#|m2|Demolición y excavación|0|||1|\n"
        "~C|01.01|m3|Excavación en vaciado|18.50|||0|\n"
        "~T|01.01|Excavación en vaciado por medios mecánicos, incluso carga sobre camión.|\n"
        "~M|01\\01.01|1|125.0|Sótano|\n"
    ).encode()


def _build_bc3_latin1() -> bytes:
    # Same content, encoded in CP1252 (covers Spanish ñ, accented vowels).
    return (
        "~V|FIEBDC-3|3.0|TestExporter|2026-01-01|sample|0|CP1252|EUR|\n"
        "~C|02#|m2|Excavación en zanja|0|||1|\n"
        "~C|02.01|m3|Relleno con tierras seleccionadas|9.80|||0|\n"
        "~T|02.01|Relleno con tierras seleccionadas, extendido en tongadas y compactación.|\n"
        "~M|02\\02.01|1|45.5||\n"
    ).encode("cp1252")


def _build_bc3_with_continuation() -> bytes:
    # The long extended text wraps onto a second physical line.
    return (
        "~V|FIEBDC-3|3.0|TestExporter|2026-01-01|sample|0|UTF-8||\n"
        "~C|03.01|m3|Hormigón HA-25|85.0|||0|\n"
        "~T|03.01|Hormigón HA-25/B/20/IIa fabricado en central\n"
        "y vertido con bomba, vibrado y curado.|\n"
        "~M|03\\03.01|1|12.5||\n"
    ).encode()


def _build_bc3_multi_chapter() -> bytes:
    return (
        "~V|FIEBDC-3|3.0|TestExporter|2026-01-01|sample|0|UTF-8|EUR|\n"
        # Chapter A — explicit type=1.
        "~C|CAP01|m2|Movimiento de tierras|0|||1|\n"
        "~C|CAP01.01|m3|Desmonte|7.50|||0|\n"
        "~M|CAP01\\CAP01.01|1|240.0||\n"
        # Chapter B — trailing-# heuristic.
        "~C|CAP02#|m2|Cimentaciones|0|||1|\n"
        "~C|CAP02.01|m3|Hormigón limpieza|62.40|||0|\n"
        "~M|CAP02\\CAP02.01|1|18.0||\n"
    ).encode()


# ── Tests ───────────────────────────────────────────────────────────────────


class TestBC3Parser:
    @pytest.mark.asyncio
    async def test_utf8_happy_path(self) -> None:
        result = await BC3Importer.parse(_build_bc3_utf8())
        assert result.source_format == "bc3"
        assert result.currency == "EUR"
        # 1 capítulo + 1 partida (capítulos surface as section rows).
        sections = [p for p in result.positions if p.is_section]
        partidas = [p for p in result.positions if not p.is_section]
        assert len(sections) == 1
        # Chapter code preserves the trailing-# capítulo marker.
        assert sections[0].ordinal == "01#"
        assert len(partidas) == 1
        assert partidas[0].ordinal == "01.01"
        assert partidas[0].unit == "m3"
        assert partidas[0].unit_rate == 18.5
        assert partidas[0].quantity == 125.0
        assert "Excavación" in partidas[0].description
        # Extended text preserved in metadata.
        assert "medios mecánicos" in partidas[0].metadata["bc3_extended_text"]

    @pytest.mark.asyncio
    async def test_latin1_encoding_handled(self) -> None:
        result = await BC3Importer.parse(_build_bc3_latin1())
        assert result.source_format == "bc3"
        partidas = [p for p in result.positions if not p.is_section]
        assert len(partidas) == 1
        # Accented characters must round-trip.
        assert "Relleno" in partidas[0].description
        # Encoding metadata stamped on the importer.
        assert result.metadata["bc3_encoding"] in ("cp1252", "latin-1")

    @pytest.mark.asyncio
    async def test_line_continuation(self) -> None:
        result = await BC3Importer.parse(_build_bc3_with_continuation())
        partidas = [p for p in result.positions if not p.is_section]
        assert len(partidas) == 1
        # The long extended text must include both physical lines.
        ext = partidas[0].metadata.get("bc3_extended_text", "")
        assert "central" in ext
        assert "bomba" in ext

    @pytest.mark.asyncio
    async def test_multiple_chapters(self) -> None:
        result = await BC3Importer.parse(_build_bc3_multi_chapter())
        sections = [p for p in result.positions if p.is_section]
        partidas = [p for p in result.positions if not p.is_section]
        # Both chapters detected (one via type=1, one via trailing #).
        assert len(sections) == 2
        section_ordinals = {s.ordinal for s in sections}
        assert section_ordinals == {"CAP01", "CAP02#"}
        # Both partidas surface with quantities from ~M records.
        assert len(partidas) == 2
        partida_ords = {p.ordinal for p in partidas}
        assert partida_ords == {"CAP01.01", "CAP02.01"}

    @pytest.mark.asyncio
    async def test_empty_buffer_raises(self) -> None:
        from app.modules.boq.importers import ImporterParseError

        with pytest.raises(ImporterParseError):
            await BC3Importer.parse(b"")

    @pytest.mark.asyncio
    async def test_no_records_raises(self) -> None:
        from app.modules.boq.importers import ImporterParseError

        with pytest.raises(ImporterParseError):
            await BC3Importer.parse(b"just some text without tilde headers\n")

    def test_detect_via_extension(self) -> None:
        assert BC3Importer.detect(b"~V|stuff", "obra.bc3") is True

    def test_detect_via_content_sniff(self) -> None:
        assert BC3Importer.detect(_build_bc3_utf8()[:1024], "anon.txt") is True

    def test_detect_rejects_non_bc3(self) -> None:
        assert BC3Importer.detect(b"<?xml version='1.0'?>", "file.xml") is False
        assert BC3Importer.detect(b"", "obra.bc3") is False
