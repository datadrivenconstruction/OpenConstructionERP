"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FIEBDC-3 / BC3 exporter tests - build_bc3 + parser round-trip.

The exporter's contract is that a priced ``BOQWithSections`` serialised to
BC3 re-imports through :class:`BC3Importer` with its chapters, partidas,
codes, units, quantities, unit rates and descriptions intact - and that the
bytes decode in a real Spanish estimating tool (CP1252 by default, UTF-8
when a character needs it, declared honestly in ``~V``).

We assert the round-trip because it exercises both halves at once: any
drift in field order (the ``TYPE`` at index 6 gotcha), the measurement
placement or the encoding shows up as a lost value on re-import.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.boq.exporters.bc3 import build_bc3
from app.modules.boq.importers.bc3 import BC3Importer

# ── Fixtures ────────────────────────────────────────────────────────────────


def _pos(
    *,
    ordinal: str,
    description: str,
    unit: str,
    quantity: str,
    unit_rate: str,
    bc3_code: str | None = None,
    bc3_unit_original: str | None = None,
    reference_code: str | None = None,
) -> SimpleNamespace:
    """A duck-typed ``PositionResponse`` carrying only what build_bc3 reads."""
    meta: dict[str, str] = {}
    if bc3_unit_original is not None:
        meta["bc3_unit_original"] = bc3_unit_original
    classification: dict[str, str] = {}
    if bc3_code is not None:
        classification["bc3_code"] = bc3_code
    return SimpleNamespace(
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=Decimal(quantity),
        unit_rate=Decimal(unit_rate),
        classification=classification,
        metadata=meta,
        reference_code=reference_code,
    )


def _section(ordinal: str, description: str, positions: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(ordinal=ordinal, description=description, positions=positions)


def _boq(
    name: str,
    sections: list[SimpleNamespace],
    positions: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(name=name, sections=sections, positions=positions or [])


def _sample_boq() -> SimpleNamespace:
    return _boq(
        name="Vivienda unifamiliar",
        sections=[
            _section(
                "01",
                "Movimiento de tierras",
                [
                    _pos(
                        ordinal="01.01",
                        bc3_code="01.01",
                        description="Excavacion en vaciado por medios mecanicos",
                        unit="m3",
                        quantity="125.000",
                        unit_rate="18.50",
                    ),
                    _pos(
                        ordinal="01.02",
                        bc3_code="01.02",
                        description="Relleno con tierras seleccionadas",
                        unit="m3",
                        quantity="45.500",
                        unit_rate="9.80",
                    ),
                ],
            ),
            _section(
                "02",
                "Cimentaciones",
                [
                    _pos(
                        ordinal="02.01",
                        bc3_code="02.01",
                        description="Hormigon de limpieza HL-150",
                        unit="m3",
                        quantity="18.000",
                        unit_rate="62.40",
                    ),
                ],
            ),
        ],
        positions=[
            # An ungrouped partida (no section) with a unit that maps ud->pcs->ud.
            _pos(
                ordinal="99.01",
                bc3_code="99.01",
                description="Ayudas de albanileria",
                unit="pcs",
                quantity="4.000",
                unit_rate="150.00",
                bc3_unit_original="ud",
            ),
        ],
    )


# ── Tests ───────────────────────────────────────────────────────────────────


class TestBC3Exporter:
    @pytest.mark.asyncio
    async def test_round_trip_structure_and_values(self) -> None:
        data, charset = build_bc3(_sample_boq(), project_name="Vivienda unifamiliar", project_currency="EUR")
        # Pure-ASCII/Latin content -> CP1252 (the Spanish desktop default).
        assert charset == "windows-1252"

        result = await BC3Importer.parse(data)
        assert result.source_format == "bc3"
        assert result.currency == "EUR"

        sections = [p for p in result.positions if p.is_section]
        partidas = [p for p in result.positions if not p.is_section]

        # Two chapters, three partidas; the TYPE=3 obra root is dropped on import.
        assert {s.ordinal for s in sections} == {"01", "02"}
        assert {p.ordinal for p in partidas} == {"01.01", "01.02", "02.01", "99.01"}

        by_code = {p.ordinal: p for p in partidas}
        assert by_code["01.01"].unit == "m3"
        assert by_code["01.01"].quantity == 125.0
        assert by_code["01.01"].unit_rate == 18.5
        assert "Excavacion" in by_code["01.01"].description

        assert by_code["02.01"].quantity == 18.0
        assert by_code["02.01"].unit_rate == 62.4

        # The ungrouped partida survived and its original "ud" unit round-trips
        # (exported verbatim as "ud", re-normalised back to "pcs" on import).
        assert by_code["99.01"].quantity == 4.0
        assert by_code["99.01"].unit == "pcs"

    @pytest.mark.asyncio
    async def test_spanish_accents_round_trip_cp1252(self) -> None:
        boq = _boq(
            "Reforma",
            [
                _section(
                    "01",
                    "Albañilería",
                    [
                        _pos(
                            ordinal="01.01",
                            bc3_code="01.01",
                            description="Tabique de ladrillo cerámico, revestido de mortero",
                            unit="m2",
                            quantity="30.000",
                            unit_rate="24.65",
                        )
                    ],
                )
            ],
        )
        data, charset = build_bc3(boq, project_name="Reforma", project_currency="EUR")
        assert charset == "windows-1252"

        result = await BC3Importer.parse(data)
        partidas = [p for p in result.positions if not p.is_section]
        assert len(partidas) == 1
        assert "cerámico" in partidas[0].description
        assert result.metadata["bc3_encoding"] in ("cp1252", "latin-1")

    @pytest.mark.asyncio
    async def test_non_latin_falls_back_to_utf8(self) -> None:
        # A CJK description cannot be represented in CP1252, so the exporter
        # must fall back to UTF-8 and declare it - no data loss.
        boq = _boq(
            "Project",
            [
                _section(
                    "01",
                    "钢筋混凝土",
                    [
                        _pos(
                            ordinal="01.01",
                            bc3_code="01.01",
                            description="现浇钢筋混凝土墙",
                            unit="m3",
                            quantity="10.000",
                            unit_rate="120.00",
                        )
                    ],
                )
            ],
        )
        data, charset = build_bc3(boq, project_name="Project", project_currency="USD")
        assert charset == "utf-8"

        result = await BC3Importer.parse(data)
        partidas = [p for p in result.positions if not p.is_section]
        assert len(partidas) == 1
        assert "现浇钢筋混凝土墙" in partidas[0].description
        assert partidas[0].quantity == 10.0

    @pytest.mark.asyncio
    async def test_reserved_characters_do_not_break_records(self) -> None:
        # Pipe / backslash / tilde / hash in free text must be neutralised so
        # they cannot corrupt the record structure.
        boq = _boq(
            "Edge",
            [
                _section(
                    "01",
                    "Section | with ~reserved\\ chars #1",
                    [
                        _pos(
                            ordinal="01.01",
                            bc3_code="01.01",
                            description="Panel 2000|1000 ~mm #A\\B",
                            unit="pcs",
                            quantity="2.000",
                            unit_rate="55.00",
                        )
                    ],
                )
            ],
        )
        data, _charset = build_bc3(boq, project_name="Edge", project_currency="EUR")
        result = await BC3Importer.parse(data)
        partidas = [p for p in result.positions if not p.is_section]
        sections = [p for p in result.positions if p.is_section]
        # Structure intact: exactly one chapter and one partida survived.
        assert len(sections) == 1
        assert len(partidas) == 1
        assert partidas[0].quantity == 2.0
        assert "Panel 2000" in partidas[0].description

    @pytest.mark.asyncio
    async def test_extended_text_round_trips(self) -> None:
        boq = _boq(
            "Obra",
            [
                _section(
                    "01",
                    "Estructura",
                    [
                        SimpleNamespace(
                            ordinal="01.01",
                            description="Hormigón HA-25",
                            unit="m3",
                            quantity=Decimal("12.5"),
                            unit_rate=Decimal("85.00"),
                            classification={"bc3_code": "01.01"},
                            metadata={
                                "bc3_extended_text": (
                                    "Hormigón HA-25/B/20/IIa fabricado en central y "
                                    "vertido con bomba, vibrado y curado."
                                )
                            },
                            reference_code=None,
                        )
                    ],
                )
            ],
        )
        data, _charset = build_bc3(boq, project_name="Obra", project_currency="EUR")
        result = await BC3Importer.parse(data)
        partidas = [p for p in result.positions if not p.is_section]
        assert len(partidas) == 1
        assert "bomba" in partidas[0].metadata.get("bc3_extended_text", "")

    @pytest.mark.asyncio
    async def test_empty_boq_is_valid_and_has_no_partidas(self) -> None:
        data, _charset = build_bc3(_boq("Empty", []), project_name="Empty", project_currency="")
        # A ~V + a TYPE=3 root concept is a well-formed BC3 file; the parser
        # accepts it and yields no positions (root is skipped).
        result = await BC3Importer.parse(data)
        assert [p for p in result.positions if not p.is_section] == []

    @pytest.mark.asyncio
    async def test_duplicate_reference_codes_stay_distinct(self) -> None:
        # Two positions sharing a reference_code must export as distinct
        # concepts (disambiguated) so neither quantity is lost on re-import.
        boq = _boq(
            "Dup",
            [
                _section(
                    "01",
                    "Repeated",
                    [
                        _pos(
                            ordinal="a",
                            reference_code="SHARED",
                            description="First instance",
                            unit="m",
                            quantity="10.000",
                            unit_rate="5.00",
                        ),
                        _pos(
                            ordinal="b",
                            reference_code="SHARED",
                            description="Second instance",
                            unit="m",
                            quantity="20.000",
                            unit_rate="5.00",
                        ),
                    ],
                )
            ],
        )
        data, _charset = build_bc3(boq, project_name="Dup", project_currency="EUR")
        result = await BC3Importer.parse(data)
        partidas = [p for p in result.positions if not p.is_section]
        assert len(partidas) == 2
        assert {float(p.quantity) for p in partidas} == {10.0, 20.0}
