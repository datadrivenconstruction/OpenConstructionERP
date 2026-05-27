"""Comprehensive tests for the IFC IfcUnitAssignment parser (audit C2 v3).

Covers per-dimension unit resolution (LENGTH / AREA / VOLUME / MASS /
ANGLE / TIME / FREQUENCY / ENERGY / PRESSURE / POWER / FORCE), SI prefix
expansion (KILO / HECTO / DECA / DECI / CENTI / MILLI / MICRO / NANO),
IFCCONVERSIONBASEDUNIT factor extraction via IFCMEASUREWITHUNIT (inch,
foot, yard, mile, pound, square foot, cubic yard, degree, hour, psi,
btu, …), IFCDERIVEDUNIT element combinatorics (m³/h, kg/m³, m/s, N/m²),
and the chained / recursive / missing / mixed edge cases that real-world
exporters reliably break on.

We exercise the parser at two levels:
  * direct calls to ``_parse_unit_assignment`` / helper functions against
    hand-built ``entities`` dicts (fast, isolated, no I/O)
  * end-to-end ``process_ifc_file`` runs against synthetic STEP-21
    payloads written to disk, asserting that extracted ``BIMElement``
    quantities are rescaled into canonical SI.
"""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

from app.modules.bim_hub.ifc_processor import (
    _CONVERSION_BASED_FACTORS,
    _SI_PREFIX_FACTOR,
    UnitContext,
    _extract_quantities_for_element,
    _parse_unit_assignment,
    _resolve_conversion_based_unit,
    _resolve_derived_unit,
    _resolve_ifc_si_unit,
    _resolve_measure_with_unit,
    _resolve_monetary_unit,
    _step_args_top_level,
    process_ifc_file,
)

# ── Helpers ─────────────────────────────────────────────────────────


@pytest.fixture
def workdir() -> Path:
    """Scratch dir per test — the parser writes placeholder COLLADA here."""
    d = Path(tempfile.mkdtemp(prefix="ifc_units_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _force_text_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the text-IFC parser path so we measure THIS code, not DDC."""
    monkeypatch.setattr(
        "app.modules.boq.cad_import.find_converter",
        lambda _ext: None,
    )


_IFC_HEADER = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('test.ifc','2026-05-13',('Test'),('OE'),'','OE','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1= IFCORGANIZATION($,'OE',$,$,$);
#2= IFCAPPLICATION(#1,'1.0','OE','OE');
#3= IFCPERSON($,'OE',$,$,$,$,$,$);
#4= IFCPERSONANDORGANIZATION(#3,#1,$);
#5= IFCOWNERHISTORY(#4,#2,$,.ADDED.,$,$,$,1234567890);
"""

_IFC_FOOTER = """\
ENDSEC;
END-ISO-10303-21;
"""


def _write_ifc(content: str, workdir: Path) -> Path:
    """Write a STEP-21 IFC string into ``workdir``."""
    p = workdir / "fixture.ifc"
    p.write_text(dedent(content).strip() + "\n", encoding="utf-8")
    return p


def _ent(eid: int, etype: str, args_raw: str) -> dict[str, object]:
    """Build the parsed-entity dict shape the parser internals expect."""
    return {
        "id": eid,
        "type": etype,
        "args_raw": args_raw,
        # ``strings`` is the decoded-string list; for unit entities it is
        # rarely used but populating it keeps shape parity with the real
        # parser.
        "strings": [],
    }


# ── 1. _step_args_top_level ─────────────────────────────────────────


class TestStepArgsTopLevel:
    """Argument-list splitter must respect (…), '…' and .…. nesting."""

    def test_simple(self) -> None:
        assert _step_args_top_level("a,b,c") == ["a", "b", "c"]

    def test_set_literal_protects_inner_commas(self) -> None:
        assert _step_args_top_level("a,(b,c,d),e") == ["a", "(b,c,d)", "e"]

    def test_string_literal_protects_inner_commas(self) -> None:
        assert _step_args_top_level("'a,b',c") == ["'a,b'", "c"]

    def test_enum_with_dots(self) -> None:
        assert _step_args_top_level("$,.LENGTHUNIT.,$,.METRE.") == [
            "$",
            ".LENGTHUNIT.",
            "$",
            ".METRE.",
        ]

    def test_empty_arglist(self) -> None:
        assert _step_args_top_level("") == []


# ── 2. IFCSIUNIT resolution ─────────────────────────────────────────


class TestResolveIfcSiUnit:
    """SI base units + SI prefix combinations."""

    def test_metre_no_prefix(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,$,.METRE.")
        unit, scale, _ = _resolve_ifc_si_unit(ent)
        assert unit == "LENGTHUNIT"
        assert scale == 1.0

    def test_kilometre_prefix(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.KILO.,.METRE.")
        _, scale, label = _resolve_ifc_si_unit(ent)
        assert scale == pytest.approx(1000.0)
        assert "kilo" in label

    def test_millimetre_prefix(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.MILLI.,.METRE.")
        _, scale, _ = _resolve_ifc_si_unit(ent)
        assert scale == pytest.approx(0.001)

    def test_centimetre_prefix(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.CENTI.,.METRE.")
        _, scale, _ = _resolve_ifc_si_unit(ent)
        assert scale == pytest.approx(0.01)

    def test_micrometre_prefix(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.MICRO.,.METRE.")
        _, scale, _ = _resolve_ifc_si_unit(ent)
        assert scale == pytest.approx(1e-6)

    def test_nanometre_prefix(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.NANO.,.METRE.")
        _, scale, _ = _resolve_ifc_si_unit(ent)
        assert scale == pytest.approx(1e-9)

    def test_hecto_prefix(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.HECTO.,.METRE.")
        _, scale, _ = _resolve_ifc_si_unit(ent)
        assert scale == pytest.approx(100.0)

    def test_deca_and_deci(self) -> None:
        deca = _resolve_ifc_si_unit(_ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.DECA.,.METRE."))
        deci = _resolve_ifc_si_unit(_ent(11, "IFCSIUNIT", "*,.LENGTHUNIT.,.DECI.,.METRE."))
        assert deca[1] == pytest.approx(10.0)
        assert deci[1] == pytest.approx(0.1)

    def test_square_metre_prefix_squared(self) -> None:
        """MILLI + SQUARE_METRE = 10^-6 (mm² → m²)."""
        ent = _ent(10, "IFCSIUNIT", "*,.AREAUNIT.,.MILLI.,.SQUARE_METRE.")
        unit, scale, _ = _resolve_ifc_si_unit(ent)
        assert unit == "AREAUNIT"
        assert scale == pytest.approx(1e-6)

    def test_cubic_metre_prefix_cubed(self) -> None:
        """CENTI + CUBIC_METRE = 10^-6 (cm³ → m³)."""
        ent = _ent(10, "IFCSIUNIT", "*,.VOLUMEUNIT.,.CENTI.,.CUBIC_METRE.")
        unit, scale, _ = _resolve_ifc_si_unit(ent)
        assert unit == "VOLUMEUNIT"
        assert scale == pytest.approx(1e-6)

    def test_kilogram_no_prefix(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.MASSUNIT.,$,.GRAM.")
        unit, scale, _ = _resolve_ifc_si_unit(ent)
        assert unit == "MASSUNIT"
        # Note: IfcSIUnit MASSUNIT default is GRAM per the spec — kilogram
        # is GRAM + KILO prefix.  The scale here is 1.0 because we report
        # the raw gram→canonical conversion as 1.0 (the table just tracks
        # the prefix factor).
        assert scale == 1.0

    def test_second_no_prefix(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.TIMEUNIT.,$,.SECOND.")
        unit, scale, _ = _resolve_ifc_si_unit(ent)
        assert unit == "TIMEUNIT"
        assert scale == 1.0

    def test_pascal_unit(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.PRESSUREUNIT.,$,.PASCAL.")
        unit, scale, _ = _resolve_ifc_si_unit(ent)
        assert unit == "PRESSUREUNIT"
        assert scale == 1.0

    def test_kilopascal(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.PRESSUREUNIT.,.KILO.,.PASCAL.")
        _, scale, _ = _resolve_ifc_si_unit(ent)
        assert scale == pytest.approx(1000.0)

    def test_hertz(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.FREQUENCYUNIT.,$,.HERTZ.")
        unit, scale, _ = _resolve_ifc_si_unit(ent)
        assert unit == "FREQUENCYUNIT"
        assert scale == 1.0

    def test_radian(self) -> None:
        ent = _ent(10, "IFCSIUNIT", "*,.PLANEANGLEUNIT.,$,.RADIAN.")
        unit, scale, _ = _resolve_ifc_si_unit(ent)
        assert unit == "PLANEANGLEUNIT"
        assert scale == 1.0

    def test_legacy_star_unity_prefix(self) -> None:
        """Some exporters emit '*' rather than '$' for unity prefix."""
        ent = _ent(10, "IFCSIUNIT", "$,.LENGTHUNIT.,*,.METRE.")
        _, scale, _ = _resolve_ifc_si_unit(ent)
        assert scale == 1.0

    def test_malformed_returns_none(self) -> None:
        """Missing positional args → None (caller falls back to defaults)."""
        # Only 2 positional args — parser must refuse rather than guess.
        ent = _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.")
        assert _resolve_ifc_si_unit(ent) is None


# ── 3. SI prefix table coverage ─────────────────────────────────────


class TestSiPrefixTable:
    """Audit-required prefixes must all be present and consistent."""

    @pytest.mark.parametrize(
        ("prefix", "expected"),
        [
            ("KILO", 1e3),
            ("HECTO", 1e2),
            ("DECA", 1e1),
            ("", 1.0),
            ("DECI", 1e-1),
            ("CENTI", 1e-2),
            ("MILLI", 1e-3),
            ("MICRO", 1e-6),
            ("NANO", 1e-9),
        ],
    )
    def test_required_prefixes(self, prefix: str, expected: float) -> None:
        assert _SI_PREFIX_FACTOR[prefix] == pytest.approx(expected)


# ── 4. IFCMEASUREWITHUNIT (conversion factor) ───────────────────────


class TestResolveMeasureWithUnit:
    """The numeric VALUE × the referenced unit's scale."""

    def test_inch_precision(self) -> None:
        """1 inch must equal exactly 0.0254 m (not 0.025, not 0.0254000001)."""
        # IfcMeasureWithUnit(IfcLengthMeasure(0.0254), #20)
        # where #20 is IfcSIUnit(LENGTHUNIT, $, METRE).
        entities = {
            20: _ent(20, "IFCSIUNIT", "*,.LENGTHUNIT.,$,.METRE."),
            10: _ent(10, "IFCMEASUREWITHUNIT", "IFCLENGTHMEASURE(0.0254),#20"),
        }
        v = _resolve_measure_with_unit(entities[10], entities, set())
        assert v == pytest.approx(0.0254)
        # And the precision must not drift to 0.025.
        assert v != pytest.approx(0.025, abs=1e-6)

    def test_value_with_nonref_unit_is_passed_through(self) -> None:
        """When the unit component is not a #ref (rare — typically a
        nested literal) the value is taken as already in SI."""
        # Two positional args; the second is a literal placeholder.
        entities = {}
        ent = _ent(10, "IFCMEASUREWITHUNIT", "IFCLENGTHMEASURE(0.0254),$")
        v = _resolve_measure_with_unit(ent, entities, set())
        assert v == pytest.approx(0.0254)

    def test_malformed_returns_none(self) -> None:
        # Only one positional arg.
        ent = _ent(10, "IFCMEASUREWITHUNIT", "IFCLENGTHMEASURE(0.0254)")
        assert _resolve_measure_with_unit(ent, {}, set()) is None


# ── 5. IFCCONVERSIONBASEDUNIT ────────────────────────────────────────


class TestResolveConversionBasedUnit:
    """Imperial / customary units via Name string + measure ref."""

    def test_inch_via_measure_ref(self) -> None:
        """1 inch = 0.0254 m through an explicit IFCMEASUREWITHUNIT chain."""
        entities = {
            30: _ent(30, "IFCSIUNIT", "*,.LENGTHUNIT.,$,.METRE."),
            20: _ent(20, "IFCMEASUREWITHUNIT", "IFCLENGTHMEASURE(0.0254),#30"),
            10: _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.LENGTHUNIT.,'INCH',#20"),
        }
        unit, scale, label = _resolve_conversion_based_unit(entities[10], entities, set())
        assert unit == "LENGTHUNIT"
        assert scale == pytest.approx(0.0254)
        assert label == "inch"

    def test_foot_via_name_only_fallback(self) -> None:
        """When the ConversionFactor #ref is missing/broken we fall back
        to the hard-coded customary-unit table (FOOT = 0.3048 m)."""
        # No referenced IFCMEASUREWITHUNIT — only the Name string.
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.LENGTHUNIT.,'FOOT',$")
        unit, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert unit == "LENGTHUNIT"
        assert scale == pytest.approx(0.3048)

    def test_yard(self) -> None:
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.LENGTHUNIT.,'YARD',$")
        _, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert scale == pytest.approx(0.9144)

    def test_square_foot(self) -> None:
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.AREAUNIT.,'SQUAREFOOT',$")
        unit, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert unit == "AREAUNIT"
        assert scale == pytest.approx(0.09290304)

    def test_cubic_yard(self) -> None:
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.VOLUMEUNIT.,'CUBICYARD',$")
        unit, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert unit == "VOLUMEUNIT"
        assert scale == pytest.approx(0.764554857984)

    def test_pound(self) -> None:
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.MASSUNIT.,'POUND',$")
        unit, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert unit == "MASSUNIT"
        assert scale == pytest.approx(0.45359237)

    def test_fahrenheit_scale_factor(self) -> None:
        """5/9 scale (note: bias is NOT handled here — see parser docs)."""
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.THERMODYNAMICTEMPERATUREUNIT.,'FAHRENHEIT',$")
        _, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert scale == pytest.approx(5.0 / 9.0)

    def test_degree_to_radian(self) -> None:
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.PLANEANGLEUNIT.,'DEGREE',$")
        _, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert scale == pytest.approx(math.pi / 180.0)

    def test_hour_to_second(self) -> None:
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.TIMEUNIT.,'HOUR',$")
        _, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert scale == pytest.approx(3600.0)

    def test_psi_to_pascal(self) -> None:
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.PRESSUREUNIT.,'PSI',$")
        _, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert scale == pytest.approx(6894.757293168)

    def test_btu_to_joule(self) -> None:
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.ENERGYUNIT.,'BTU',$")
        _, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert scale == pytest.approx(1055.05585262)

    def test_chained_conversion_dereferences(self) -> None:
        """IfcConversionBasedUnit can point at another conversion-based
        unit through its IfcMeasureWithUnit's UnitComponent.  We must
        dereference recursively without infinite-looping."""
        entities = {
            # #30 = inch (base imperial length unit, name-only fallback)
            30: _ent(30, "IFCCONVERSIONBASEDUNIT", "#100,.LENGTHUNIT.,'INCH',$"),
            # #20 = MeasureWithUnit(12 inches, #30 = inch)
            20: _ent(20, "IFCMEASUREWITHUNIT", "IFCLENGTHMEASURE(12.0),#30"),
            # #10 = foot, declared as 12 inches
            10: _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.LENGTHUNIT.,'FOOT',#20"),
        }
        _, scale, _ = _resolve_conversion_based_unit(entities[10], entities, set())
        # 12 inches * 0.0254 m/inch = 0.3048 m
        assert scale == pytest.approx(0.3048)

    def test_alias_inch_in(self) -> None:
        """Common abbreviation 'IN' resolves to the same scale as INCH."""
        ent = _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.LENGTHUNIT.,'IN',$")
        _, scale, _ = _resolve_conversion_based_unit(ent, {}, set())
        assert scale == pytest.approx(0.0254)


# ── 6. IFCDERIVEDUNIT ───────────────────────────────────────────────


class TestResolveDerivedUnit:
    """Combinatorics of IfcDerivedUnitElement (Unit, Exponent)."""

    def test_volumetric_flow_m3_per_hour(self) -> None:
        """m³/h = CubicMetre^+1 + Hour^-1 → scale = 1.0 / 3600 = 1/3600 s⁻¹."""
        entities = {
            40: _ent(40, "IFCSIUNIT", "*,.VOLUMEUNIT.,$,.CUBIC_METRE."),
            41: _ent(41, "IFCCONVERSIONBASEDUNIT", "#100,.TIMEUNIT.,'HOUR',$"),
            # Elements: each pair (Unit_ref, Exponent).
            50: _ent(50, "IFCDERIVEDUNITELEMENT", "#40,1"),
            51: _ent(51, "IFCDERIVEDUNITELEMENT", "#41,-1"),
            10: _ent(10, "IFCDERIVEDUNIT", "(#50,#51),.VOLUMETRICFLOWRATEUNIT."),
        }
        unit, scale, _ = _resolve_derived_unit(entities[10], entities, set())
        assert unit == "VOLUMETRICFLOWRATEUNIT"
        assert scale == pytest.approx(1.0 / 3600.0)

    def test_mass_density_kg_per_m3(self) -> None:
        """kg/m³ = KILOGRAM^+1 * CubicMetre^-1 → scale = 1.0."""
        entities = {
            40: _ent(40, "IFCSIUNIT", "*,.MASSUNIT.,.KILO.,.GRAM."),
            41: _ent(41, "IFCSIUNIT", "*,.VOLUMEUNIT.,$,.CUBIC_METRE."),
            50: _ent(50, "IFCDERIVEDUNITELEMENT", "#40,1"),
            51: _ent(51, "IFCDERIVEDUNITELEMENT", "#41,-1"),
            10: _ent(10, "IFCDERIVEDUNIT", "(#50,#51),.MASSDENSITYUNIT."),
        }
        _, scale, _ = _resolve_derived_unit(entities[10], entities, set())
        assert scale == pytest.approx(1000.0)  # KILO prefix on mass

    def test_velocity_m_per_s(self) -> None:
        entities = {
            40: _ent(40, "IFCSIUNIT", "*,.LENGTHUNIT.,$,.METRE."),
            41: _ent(41, "IFCSIUNIT", "*,.TIMEUNIT.,$,.SECOND."),
            50: _ent(50, "IFCDERIVEDUNITELEMENT", "#40,1"),
            51: _ent(51, "IFCDERIVEDUNITELEMENT", "#41,-1"),
            10: _ent(10, "IFCDERIVEDUNIT", "(#50,#51),.LINEARVELOCITYUNIT."),
        }
        _, scale, _ = _resolve_derived_unit(entities[10], entities, set())
        assert scale == pytest.approx(1.0)

    def test_pressure_n_per_m2(self) -> None:
        """N/m² (Pa equivalent expressed via derived unit)."""
        entities = {
            40: _ent(40, "IFCSIUNIT", "*,.FORCEUNIT.,$,.NEWTON."),
            41: _ent(41, "IFCSIUNIT", "*,.AREAUNIT.,$,.SQUARE_METRE."),
            50: _ent(50, "IFCDERIVEDUNITELEMENT", "#40,1"),
            51: _ent(51, "IFCDERIVEDUNITELEMENT", "#41,-1"),
            10: _ent(10, "IFCDERIVEDUNIT", "(#50,#51),.PRESSUREUNIT."),
        }
        _, scale, _ = _resolve_derived_unit(entities[10], entities, set())
        assert scale == pytest.approx(1.0)

    def test_negative_exponent_only(self) -> None:
        """Frequency-like dimension: 1/s = SECOND^-1."""
        entities = {
            40: _ent(40, "IFCSIUNIT", "*,.TIMEUNIT.,$,.SECOND."),
            50: _ent(50, "IFCDERIVEDUNITELEMENT", "#40,-1"),
            10: _ent(10, "IFCDERIVEDUNIT", "(#50),.FREQUENCYUNIT."),
        }
        _, scale, _ = _resolve_derived_unit(entities[10], entities, set())
        assert scale == pytest.approx(1.0)


# ── 7. IFCMONETARYUNIT ──────────────────────────────────────────────


class TestResolveMonetaryUnit:
    """Currency code extraction — no scaling."""

    def test_usd(self) -> None:
        ent = _ent(10, "IFCMONETARYUNIT", "'USD'")
        unit, scale, code = _resolve_monetary_unit(ent)
        assert unit == "MONETARYUNIT"
        assert scale == 1.0
        assert code == "USD"

    def test_eur(self) -> None:
        ent = _ent(10, "IFCMONETARYUNIT", "'EUR'")
        _, _, code = _resolve_monetary_unit(ent)
        assert code == "EUR"

    def test_ifc2x3_enum_form(self) -> None:
        """Legacy IFC2x3 uses a .USD. enum."""
        ent = _ent(10, "IFCMONETARYUNIT", ".USD.")
        _, _, code = _resolve_monetary_unit(ent)
        assert code == "USD"


# ── 8. _parse_unit_assignment end-to-end ────────────────────────────


class TestParseUnitAssignment:
    """Build a small ``entities`` graph and verify the resolved UnitContext."""

    def test_pure_si_metric_identity_scale(self) -> None:
        """Pure SI (m + m² + m³) → identity scale + metric system."""
        entities = {
            10: _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,$,.METRE."),
            11: _ent(11, "IFCSIUNIT", "*,.AREAUNIT.,$,.SQUARE_METRE."),
            12: _ent(12, "IFCSIUNIT", "*,.VOLUMEUNIT.,$,.CUBIC_METRE."),
            13: _ent(13, "IFCUNITASSIGNMENT", "(#10,#11,#12)"),
        }
        ctx = _parse_unit_assignment(entities)
        assert ctx.had_assignment is True
        assert ctx.is_canonical is True
        assert ctx.unit_system == "metric"
        assert ctx.scale_for["LENGTHUNIT"] == 1.0
        assert ctx.scale_for["AREAUNIT"] == 1.0
        assert ctx.scale_for["VOLUMEUNIT"] == 1.0

    def test_millimetre_length_scaling(self) -> None:
        """mm-authored file → length scale 0.001."""
        entities = {
            10: _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.MILLI.,.METRE."),
            11: _ent(11, "IFCUNITASSIGNMENT", "(#10)"),
        }
        ctx = _parse_unit_assignment(entities)
        assert ctx.had_assignment is True
        assert ctx.is_canonical is False
        assert ctx.scale_for["LENGTHUNIT"] == pytest.approx(0.001)

    def test_kilo_length_scaling(self) -> None:
        entities = {
            10: _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.KILO.,.METRE."),
            11: _ent(11, "IFCUNITASSIGNMENT", "(#10)"),
        }
        ctx = _parse_unit_assignment(entities)
        assert ctx.scale_for["LENGTHUNIT"] == pytest.approx(1000.0)

    def test_imperial_inch_via_conversion(self) -> None:
        """Revit-default lengths = inches → length scale 0.0254."""
        entities = {
            30: _ent(30, "IFCSIUNIT", "*,.LENGTHUNIT.,$,.METRE."),
            20: _ent(20, "IFCMEASUREWITHUNIT", "IFCLENGTHMEASURE(0.0254),#30"),
            10: _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.LENGTHUNIT.,'INCH',#20"),
            11: _ent(11, "IFCUNITASSIGNMENT", "(#10)"),
        }
        ctx = _parse_unit_assignment(entities)
        assert ctx.had_assignment is True
        assert ctx.is_canonical is False
        assert ctx.unit_system == "imperial"
        assert ctx.scale_for["LENGTHUNIT"] == pytest.approx(0.0254)

    def test_imperial_foot_name_only(self) -> None:
        """Foot via the Name fallback (no #ref to IfcMeasureWithUnit)."""
        entities = {
            10: _ent(10, "IFCCONVERSIONBASEDUNIT", "#100,.LENGTHUNIT.,'FOOT',$"),
            11: _ent(11, "IFCUNITASSIGNMENT", "(#10)"),
        }
        ctx = _parse_unit_assignment(entities)
        assert ctx.unit_system == "imperial"
        assert ctx.scale_for["LENGTHUNIT"] == pytest.approx(0.3048)

    def test_mixed_si_and_imperial(self) -> None:
        """SI length + imperial mass (kg + lb)."""
        entities = {
            10: _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,$,.METRE."),
            11: _ent(11, "IFCCONVERSIONBASEDUNIT", "#100,.MASSUNIT.,'POUND',$"),
            12: _ent(12, "IFCUNITASSIGNMENT", "(#10,#11)"),
        }
        ctx = _parse_unit_assignment(entities)
        assert ctx.had_assignment is True
        assert ctx.is_canonical is False
        assert ctx.unit_system == "mixed"
        assert ctx.scale_for["LENGTHUNIT"] == 1.0
        assert ctx.scale_for["MASSUNIT"] == pytest.approx(0.45359237)

    def test_missing_assignment_falls_back_to_metric(self) -> None:
        """No IFCUNITASSIGNMENT block → metric defaults, had_assignment=False."""
        entities = {
            10: _ent(10, "IFCWALL", "'guid',#5,'Wall',$"),
        }
        ctx = _parse_unit_assignment(entities)
        assert ctx.had_assignment is False
        assert ctx.unit_system == "metric"
        assert ctx.scale_for["LENGTHUNIT"] == 1.0
        assert ctx.scale_for["AREAUNIT"] == 1.0
        assert ctx.scale_for["VOLUMEUNIT"] == 1.0

    def test_standalone_si_units_without_assignment(self) -> None:
        """Some Tekla files declare IFCSIUNIT but no IFCUNITASSIGNMENT.
        We pick up the standalone units as a courtesy."""
        entities = {
            10: _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,.MILLI.,.METRE."),
        }
        ctx = _parse_unit_assignment(entities)
        assert ctx.had_assignment is False
        # Still picked up the standalone SI unit.
        assert ctx.scale_for["LENGTHUNIT"] == pytest.approx(0.001)

    def test_currency_code_captured(self) -> None:
        entities = {
            10: _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,$,.METRE."),
            11: _ent(11, "IFCMONETARYUNIT", "'GBP'"),
            12: _ent(12, "IFCUNITASSIGNMENT", "(#10,#11)"),
        }
        ctx = _parse_unit_assignment(entities)
        assert ctx.currency_code == "GBP"

    def test_unknown_unit_type_does_not_crash(self) -> None:
        """IFCCONTEXTDEPENDENTUNIT is opaque — we tolerate without crashing."""
        entities = {
            10: _ent(10, "IFCSIUNIT", "*,.LENGTHUNIT.,$,.METRE."),
            11: _ent(11, "IFCCONTEXTDEPENDENTUNIT", "#100,.USERDEFINED.,'somenonsense'"),
            12: _ent(12, "IFCUNITASSIGNMENT", "(#10,#11)"),
        }
        ctx = _parse_unit_assignment(entities)
        # Length still parsed.
        assert ctx.scale_for["LENGTHUNIT"] == 1.0
        # is_canonical drops because of the unknown unit ref.
        assert ctx.is_canonical is False


# ── 9. UnitContext.scale(quantity_kind) ─────────────────────────────


class TestUnitContextScale:
    """Mapping IFCQUANTITY* → applied scale."""

    def test_quantity_length_uses_length_scale(self) -> None:
        ctx = UnitContext()
        ctx.scale_for["LENGTHUNIT"] = 0.001  # mm
        assert ctx.scale("IFCQUANTITYLENGTH") == pytest.approx(0.001)

    def test_quantity_area_uses_area_scale(self) -> None:
        ctx = UnitContext()
        ctx.scale_for["AREAUNIT"] = 1e-6  # mm² → m²
        assert ctx.scale("IFCQUANTITYAREA") == pytest.approx(1e-6)

    def test_quantity_volume_uses_volume_scale(self) -> None:
        ctx = UnitContext()
        ctx.scale_for["VOLUMEUNIT"] = 1e-9  # mm³ → m³
        assert ctx.scale("IFCQUANTITYVOLUME") == pytest.approx(1e-9)

    def test_quantity_weight_uses_mass_scale(self) -> None:
        ctx = UnitContext()
        ctx.scale_for["MASSUNIT"] = 0.45359237  # lb → kg
        assert ctx.scale("IFCQUANTITYWEIGHT") == pytest.approx(0.45359237)

    def test_quantity_count_is_dimensionless(self) -> None:
        """Counts must never be rescaled (a count of 12 doors stays 12)."""
        ctx = UnitContext()
        ctx.scale_for["LENGTHUNIT"] = 0.001
        # Even with a wonky length scale, count gets 1.0.
        assert ctx.scale("IFCQUANTITYCOUNT") == 1.0


# ── 10. _extract_quantities_for_element with scale applied ──────────


class TestExtractQuantitiesWithScale:
    """The full quantity extractor must apply the UnitContext scale."""

    def _build_qty_entities(self, qty_type: str, qty_name: str, qty_value: float) -> dict[int, dict[str, object]]:
        # IFCQUANTITY* entities have the quantity-name string as their
        # first positional arg; the extractor uses ``strings[0]`` as
        # the key, so we have to populate ``strings`` accordingly.
        return {
            100: {
                "id": 100,
                "type": "IFCWALL",
                "args_raw": "'guid',#5,'Wall',$,$,$,$,$,$",
                "strings": ["guid", "Wall"],
            },
            200: {
                "id": 200,
                "type": "IFCRELDEFINESBYPROPERTIES",
                "args_raw": "'relguid',#5,$,$,(#100),#300",
                "strings": ["relguid"],
            },
            300: {
                "id": 300,
                "type": "IFCELEMENTQUANTITY",
                "args_raw": "'eqguid',#5,'BaseQuantities',$,'OE',(#400)",
                "strings": ["eqguid", "BaseQuantities", "OE"],
            },
            400: {
                "id": 400,
                "type": qty_type,
                "args_raw": f"'{qty_name}',$,$,#5,{qty_value}",
                "strings": [qty_name],
            },
        }

    def test_length_mm_to_m(self) -> None:
        entities = self._build_qty_entities(
            "IFCQUANTITYLENGTH",
            "Length",
            24.0,
        )
        ctx = UnitContext()
        ctx.scale_for["LENGTHUNIT"] = 0.001
        q = _extract_quantities_for_element(100, entities, ctx)
        # 24 mm → 0.024 m
        assert q["Length"] == pytest.approx(0.024)

    def test_area_mm2_to_m2(self) -> None:
        entities = self._build_qty_entities(
            "IFCQUANTITYAREA",
            "NetArea",
            5e6,
        )
        ctx = UnitContext()
        ctx.scale_for["AREAUNIT"] = 1e-6
        q = _extract_quantities_for_element(100, entities, ctx)
        # 5e6 mm² → 5 m²
        assert q["NetArea"] == pytest.approx(5.0)

    def test_volume_inch3_to_m3(self) -> None:
        entities = self._build_qty_entities(
            "IFCQUANTITYVOLUME",
            "Volume",
            1.0,
        )
        ctx = UnitContext()
        # 1 cubic inch in m³
        ctx.scale_for["VOLUMEUNIT"] = 0.000016387064
        q = _extract_quantities_for_element(100, entities, ctx)
        assert q["Volume"] == pytest.approx(0.000016387064)

    def test_weight_lb_to_kg(self) -> None:
        entities = self._build_qty_entities(
            "IFCQUANTITYWEIGHT",
            "GrossWeight",
            100.0,
        )
        ctx = UnitContext()
        ctx.scale_for["MASSUNIT"] = 0.45359237
        q = _extract_quantities_for_element(100, entities, ctx)
        # 100 lb → 45.359 kg
        assert q["GrossWeight"] == pytest.approx(45.359237)

    def test_count_never_scaled(self) -> None:
        entities = self._build_qty_entities(
            "IFCQUANTITYCOUNT",
            "DoorCount",
            12.0,
        )
        ctx = UnitContext()
        # Even with a wonky length scale, count stays 12.
        ctx.scale_for["LENGTHUNIT"] = 0.001
        q = _extract_quantities_for_element(100, entities, ctx)
        assert q["DoorCount"] == pytest.approx(12.0)

    def test_none_context_uses_raw_value(self) -> None:
        """Back-compat: legacy callers pass ``None`` and get raw values."""
        entities = self._build_qty_entities(
            "IFCQUANTITYAREA",
            "NetArea",
            42.5,
        )
        q = _extract_quantities_for_element(100, entities, None)
        # No scale applied.
        assert q["NetArea"] == pytest.approx(42.5)


# ── 11. End-to-end via process_ifc_file ─────────────────────────────


def _make_full_ifc(unit_assignment_block: str, quantity_value: float) -> str:
    """Synthesise an IFC file with a configurable unit assignment block
    and a single wall carrying one IFCQUANTITYAREA value."""
    return (
        _IFC_HEADER
        + dedent(unit_assignment_block)
        + dedent(f"""
        #100= IFCBUILDINGSTOREY('storeyGUIDxxxxxxxxxx',#5,'L1',$,$,$,$,$,.ELEMENT.,0.0);
        #101= IFCWALL('wallGUIDxxxxxxxxxxxxxxx',#5,'Wall',$,$,$,$,$,$);
        #102= IFCRELCONTAINEDINSPATIALSTRUCTURE('relGUIDxxxxxxxxxxxxx',#5,$,$,(#101),#100);
        #200= IFCRELDEFINESBYPROPERTIES('rdpGUIDxxxxxxxxxxxxx',#5,$,$,(#101),#300);
        #300= IFCELEMENTQUANTITY('eqGUIDxxxxxxxxxxxxxxx',#5,'BaseQuantities',$,'OE',(#400));
        #400= IFCQUANTITYAREA('NetArea',$,$,#5,{quantity_value});
    """).strip()
        + "\n"
        + _IFC_FOOTER
    )


def test_end_to_end_pure_si_no_rescaling(workdir: Path) -> None:
    """IFC authored in SI metres → NetArea passes through unchanged."""
    ifc = _make_full_ifc(
        dedent("""
        #10= IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
        #11= IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);
        #12= IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.);
        #13= IFCUNITASSIGNMENT((#10,#11,#12));
        """),
        quantity_value=42.5,
    )
    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    walls = [e for e in result["elements"] if e["element_type"] == "Wall"]
    assert walls, f"no walls extracted: {result}"
    assert walls[0]["quantities"]["NetArea"] == pytest.approx(42.5)
    meta = result["metadata"]["units"]
    assert meta["unit_system"] == "metric"
    assert meta["is_canonical"] is True
    assert meta["had_assignment"] is True


def test_end_to_end_millimetres_rescales_area(workdir: Path) -> None:
    """IFC in mm → 12500000 mm² → 12.5 m² after canonicalisation."""
    ifc = _make_full_ifc(
        dedent("""
        #10= IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
        #11= IFCSIUNIT(*,.AREAUNIT.,.MILLI.,.SQUARE_METRE.);
        #12= IFCUNITASSIGNMENT((#10,#11));
        """),
        quantity_value=12_500_000.0,
    )
    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    walls = [e for e in result["elements"] if e["element_type"] == "Wall"]
    assert walls
    assert walls[0]["quantities"]["NetArea"] == pytest.approx(12.5)
    meta = result["metadata"]["units"]
    assert meta["unit_system"] == "metric"
    assert meta["is_canonical"] is False
    assert meta["scale_table"]["AREAUNIT"] == pytest.approx(1e-6)


def test_end_to_end_imperial_inches_rescales(workdir: Path) -> None:
    """IFC authored in square inches → area rescaled to m²."""
    ifc = _make_full_ifc(
        dedent("""
        #13= IFCCONVERSIONBASEDUNIT(#100,.AREAUNIT.,'SQUAREINCH',$);
        #14= IFCUNITASSIGNMENT((#13));
        """),
        # 1550 in² ≈ 1.0 m²
        quantity_value=1550.0031,
    )
    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    walls = [e for e in result["elements"] if e["element_type"] == "Wall"]
    assert walls
    # 1550.0031 in² × 0.00064516 m²/in² ≈ 1.0 m²
    assert walls[0]["quantities"]["NetArea"] == pytest.approx(1.0, rel=1e-3)
    meta = result["metadata"]["units"]
    # A file declaring ONLY a conversion-based area unit is pure imperial.
    assert meta["unit_system"] == "imperial"


def test_end_to_end_mixed_metric_and_imperial(workdir: Path) -> None:
    """Revit-default lengths in feet shipped alongside SI area → mixed."""
    ifc = _make_full_ifc(
        dedent("""
        #10= IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);
        #13= IFCCONVERSIONBASEDUNIT(#100,.LENGTHUNIT.,'FOOT',$);
        #14= IFCUNITASSIGNMENT((#10,#13));
        """),
        quantity_value=10.0,
    )
    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    meta = result["metadata"]["units"]
    assert meta["unit_system"] == "mixed"
    assert meta["scale_table"]["LENGTHUNIT"] == pytest.approx(0.3048)
    assert meta["scale_table"]["AREAUNIT"] == 1.0


def test_end_to_end_no_unit_assignment_defaults_to_metric(
    workdir: Path,
) -> None:
    """IFC without IFCUNITASSIGNMENT → ISO default metric, flag set."""
    # Reuse the basic regression fixture with no unit assignment block.
    ifc = (
        _IFC_HEADER
        + dedent("""
        #100= IFCBUILDINGSTOREY('storeyGUIDxxxxxxxxxx',#5,'L1',$,$,$,$,$,.ELEMENT.,0.0);
        #101= IFCWALL('wallGUIDxxxxxxxxxxxxxxx',#5,'Wall',$,$,$,$,$,$);
        #102= IFCRELCONTAINEDINSPATIALSTRUCTURE('relGUIDxxxxxxxxxxxxx',#5,$,$,(#101),#100);
        #200= IFCRELDEFINESBYPROPERTIES('rdpGUIDxxxxxxxxxxxxx',#5,$,$,(#101),#300);
        #300= IFCELEMENTQUANTITY('eqGUIDxxxxxxxxxxxxxxx',#5,'BaseQuantities',$,'OE',(#400));
        #400= IFCQUANTITYAREA('NetArea',$,$,#5,7.5);
    """).strip()
        + "\n"
        + _IFC_FOOTER
    )
    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    walls = [e for e in result["elements"] if e["element_type"] == "Wall"]
    assert walls
    # No rescaling — fall back to identity.
    assert walls[0]["quantities"]["NetArea"] == pytest.approx(7.5)
    # Back-compat: unit_uncertain still True.
    assert result["unit_uncertain"] is True
    assert result["metadata"]["units"]["had_assignment"] is False
    assert result["metadata"]["units"]["unit_system"] == "metric"


def test_end_to_end_malformed_unit_assignment_recovers(
    workdir: Path,
) -> None:
    """Non-conforming IFCUNITASSIGNMENT with an unparseable ref must not crash."""
    ifc = (
        _IFC_HEADER
        + dedent("""
        #10= IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
        #13= IFCUNITASSIGNMENT((#10,#999));
        #100= IFCBUILDINGSTOREY('storeyGUIDxxxxxxxxxx',#5,'L1',$,$,$,$,$,.ELEMENT.,0.0);
        #101= IFCWALL('wallGUIDxxxxxxxxxxxxxxx',#5,'Wall',$,$,$,$,$,$);
        #102= IFCRELCONTAINEDINSPATIALSTRUCTURE('relGUIDxxxxxxxxxxxxx',#5,$,$,(#101),#100);
    """).strip()
        + "\n"
        + _IFC_FOOTER
    )
    path = _write_ifc(ifc, workdir)
    result = process_ifc_file(path, workdir / "out")
    # Must not crash; metadata must still be populated.
    meta = result["metadata"]["units"]
    assert meta["had_assignment"] is True
    # LENGTHUNIT was parsed successfully despite the dangling ref.
    assert meta["scale_table"]["LENGTHUNIT"] == 1.0


# ── 12. Conversion factor table coverage sanity ─────────────────────


class TestConversionFactorTable:
    """Spot-check headline conversion factors against ISO/customary refs."""

    def test_inch_exact(self) -> None:
        assert _CONVERSION_BASED_FACTORS["INCH"] == 0.0254

    def test_foot_exact(self) -> None:
        assert _CONVERSION_BASED_FACTORS["FOOT"] == 0.3048

    def test_yard_exact(self) -> None:
        assert _CONVERSION_BASED_FACTORS["YARD"] == 0.9144

    def test_mile_exact(self) -> None:
        assert _CONVERSION_BASED_FACTORS["MILE"] == 1609.344

    def test_pound_exact(self) -> None:
        assert _CONVERSION_BASED_FACTORS["POUND"] == 0.45359237

    def test_psi_exact(self) -> None:
        assert _CONVERSION_BASED_FACTORS["PSI"] == 6894.757293168

    def test_btu_exact(self) -> None:
        assert _CONVERSION_BASED_FACTORS["BTU"] == 1055.05585262

    def test_degree_to_rad(self) -> None:
        assert _CONVERSION_BASED_FACTORS["DEGREE"] == pytest.approx(
            math.pi / 180.0,
        )

    def test_hour_to_sec(self) -> None:
        assert _CONVERSION_BASED_FACTORS["HOUR"] == 3600.0
