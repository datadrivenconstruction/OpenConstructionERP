"""GAEB DA XML 3.3 exporter conformance + money round-trip tests.

The exporter must produce documents that validate against the official GAEB
DA XML 3.3 schema and that round-trip (export -> import) without losing a cent
or a position. These tests drive the pure ``build_gaeb_xml`` builder directly
(no app / DB), so they run anywhere lxml is installed.

XSD provenance / oracle
-----------------------
The official GAEB DA XML **3.3** XSD is not redistributed as a free direct
download (GAEB ships it to members). The closest freely-licensed official
schema is the GAEB DA XML **3.2** XSD (2012-01), committed under
``tests/fixtures/gaeb/xsd/``. The 3.3 BoQ element model is a superset of 3.2
for the X83/X84 exchange phases, so we use the 3.2 XSD as a faithful oracle
after two mechanical adaptations, both documented and asserted below:

* the schema target namespace ``.../DA8x/3.2`` is rewritten to ``.../DA8x/3.3``
  so it matches the namespace the exporter (and every real 3.3 file) declares;
* the ``Version`` / ``VersDate`` enumeration facets, which in 3.2 are pinned to
  ``3.2`` / ``2012-01``, are widened to also accept the 3.3 values ``3.3`` /
  ``2021-05``.

We pin the oracle's fidelity first by validating the official BVBS 3.3
Pruefdatei (a real-world conformant file) against it: if the rewritten schema
accepts the official file, it is a sound check for our own output. See
``qa/.../fixtures/gaeb/SOURCES.md`` for the XSD download provenance.

Run::

    cd backend
    python -m pytest tests/unit/test_gaeb_export_xsd.py -v --tb=short
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

etree = pytest.importorskip("lxml.etree")

from app.modules.boq.router import build_gaeb_xml

# ── XSD oracle ───────────────────────────────────────────────────────────────

_XSD_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb" / "xsd"
_ROOT_XSD = {
    "83": "GAEB_DA_XML_83_3.2_2012-01.xsd",
    "84": "GAEB_DA_XML_84_3.2_2012-01.xsd",
}


def _patched_schema_bytes(name: str) -> bytes:
    """Read an XSD source and adapt the 3.2 schema into a 3.3 oracle.

    Rewrites the DA8x/3.2 target namespace to DA8x/3.3 and widens the
    Version / VersDate enumeration facets to accept the 3.3 values.
    """
    data = (_XSD_DIR / name).read_bytes()
    data = data.replace(b"GAEB_DA_XML/DA83/3.2", b"GAEB_DA_XML/DA83/3.3")
    data = data.replace(b"GAEB_DA_XML/DA84/3.2", b"GAEB_DA_XML/DA84/3.3")
    data = data.replace(
        b'<xs:enumeration value="3.2"/>',
        b'<xs:enumeration value="3.2"/><xs:enumeration value="3.3"/>',
    )
    data = data.replace(
        b'<xs:enumeration value="2012-01"/>',
        b'<xs:enumeration value="2012-01"/><xs:enumeration value="2021-05"/>',
    )
    return data


class _SchemaResolver(etree.Resolver):
    """Serve the (patched) included XSDs from the local fixtures dir."""

    def resolve(self, system_url, public_id, context):  # noqa: ANN001, ARG002
        name = system_url.split("/")[-1]
        if (_XSD_DIR / name).exists():
            return self.resolve_string(_patched_schema_bytes(name), context)
        return None


def _load_schema(dp_code: str) -> etree.XMLSchema:
    """Load the GAEB DA XML 3.3 oracle schema for the given DP phase."""
    parser = etree.XMLParser(load_dtd=False, no_network=True)
    parser.resolvers.add(_SchemaResolver())
    root = etree.fromstring(_patched_schema_bytes(_ROOT_XSD[dp_code]), parser)
    return etree.XMLSchema(root)


def test_oracle_accepts_official_pruefdatei() -> None:
    """Sanity-pin the oracle: it must accept the official BVBS 3.3 X84 file."""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb" / "bvbs_pruefdatei_3.3_x84.x84"
    schema = _load_schema("84")
    doc = etree.parse(str(fixture))
    assert schema.validate(doc), "Oracle rejected the official BVBS 3.3 Pruefdatei: " + "; ".join(
        f"{e.line}:{e.message}" for e in schema.error_log[:6]
    )


# ── Demo LV (pure data) ──────────────────────────────────────────────────────


def _pos(ordinal: str, description: str, unit: str, qty: str, rate: str) -> SimpleNamespace:
    q = Decimal(qty)
    r = Decimal(rate)
    total = (q * r).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return SimpleNamespace(
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=q,
        unit_rate=r,
        total=total,
        metadata={},
    )


def _build_demo_boq() -> SimpleNamespace:
    """A two-section LV with a non-integer qty, a lump sum, and a 10% markup."""
    sec1_positions = [
        _pos("01.001", "Mutterboden abtragen", "m3", "250", "12.50"),
        _pos("01.002", "Baugrube aushaeben\nund seitlich lagern", "m3", "480", "18.75"),
    ]
    sec2_positions = [
        _pos("02.001", "Stahlbeton C30/37 Bodenplatte", "m3", "12.5", "168.40"),
        _pos("02.002", "Baustelleneinrichtung", "lsum", "1", "9500.00"),
    ]
    sections = [
        SimpleNamespace(ordinal="01", description="Erdarbeiten", positions=sec1_positions),
        SimpleNamespace(ordinal="02", description="Betonarbeiten", positions=sec2_positions),
    ]
    direct = sum((p.total for sec in sections for p in sec.positions), Decimal("0.00"))
    markup_amount = (direct * Decimal("0.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    markups = [
        SimpleNamespace(
            name="Baustellengemeinkosten",
            markup_type="percentage",
            category="overhead",
            percentage=10.0,
            amount=markup_amount,
            is_active=True,
        ),
    ]
    net = direct + markup_amount
    return SimpleNamespace(
        name="Demo LV",
        sections=sections,
        positions=[],
        markups=markups,
        direct_cost=direct,
        net_total=net,
        grand_total=net,
    )


def _expected_direct() -> Decimal:
    boq = _build_demo_boq()
    return boq.direct_cost.quantize(Decimal("0.01"))


# ── Acceptance tests ─────────────────────────────────────────────────────────


def _assert_validates(boq: SimpleNamespace, gaeb_format: str) -> None:
    xml = build_gaeb_xml(boq, project_name="XSD Demo", project_currency="EUR", gaeb_format=gaeb_format)
    dp_code = "84" if gaeb_format == "x84" else "83"
    schema = _load_schema(dp_code)
    doc = etree.fromstring(xml.encode("utf-8"))
    assert schema.validate(doc), f"Exported {gaeb_format} failed GAEB 3.3 XSD validation: " + "; ".join(
        f"{e.line}:{e.message}" for e in schema.error_log[:12]
    )
    assert doc.tag == f"{{http://www.gaeb.de/GAEB_DA_XML/DA{dp_code}/3.3}}GAEB"


@pytest.mark.parametrize("gaeb_format", ["x83", "x84"])
def test_export_validates_against_gaeb_xsd(gaeb_format: str) -> None:
    """A sectioned demo LV exported as X83/X84 validates against the 3.3 XSD."""
    _assert_validates(_build_demo_boq(), gaeb_format)


@pytest.mark.parametrize("gaeb_format", ["x83", "x84"])
def test_export_flat_boq_validates(gaeb_format: str) -> None:
    """A flat LV (no sections, with a markup) validates against the 3.3 XSD."""
    positions = [
        _pos("0010", "Erdaushub", "m3", "120", "21.40"),
        _pos("0020", "Verfuellen", "m3", "95", "9.80"),
    ]
    direct = sum((p.total for p in positions), Decimal("0.00"))
    markup_amount = (direct * Decimal("0.05")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    boq = SimpleNamespace(
        name="Flat LV",
        sections=[],
        positions=positions,
        markups=[SimpleNamespace(name="Wagnis und Gewinn", percentage=5.0, amount=markup_amount, is_active=True)],
        direct_cost=direct,
        net_total=direct + markup_amount,
        grand_total=direct + markup_amount,
    )
    _assert_validates(boq, gaeb_format)


@pytest.mark.parametrize("gaeb_format", ["x83", "x84"])
def test_export_sections_plus_ungrouped_validates(gaeb_format: str) -> None:
    """Sections AND ungrouped positions (separate category) validate (3.3 XSD)."""
    sec_positions = [_pos("01.001", "Schalung", "m2", "60", "44.00")]
    section = SimpleNamespace(ordinal="01", description="Beton", positions=sec_positions)
    ungrouped = [_pos("90.001", "Sonstiges", "lsum", "1", "1500.00")]
    direct = sec_positions[0].total + ungrouped[0].total
    boq = SimpleNamespace(
        name="Mixed LV",
        sections=[section],
        positions=ungrouped,
        markups=[],
        direct_cost=direct,
        net_total=direct,
        grand_total=direct,
    )
    _assert_validates(boq, gaeb_format)


def test_export_item_money_sums_to_direct_cost() -> None:
    """Sum of exported item <IT> equals the direct cost to the cent (X84)."""
    boq = _build_demo_boq()
    xml = build_gaeb_xml(boq, project_name="XSD Demo", project_currency="EUR", gaeb_format="x84")
    doc = etree.fromstring(xml.encode("utf-8"))
    ns = {"g": doc.tag.split("}")[0].lstrip("{")}

    it_sum = sum(Decimal((el.text or "0").strip()) for el in doc.findall(".//g:Item/g:IT", ns))
    assert it_sum.quantize(Decimal("0.01")) == _expected_direct(), (
        f"Sum of item IT {it_sum} != direct cost {_expected_direct()}"
    )

    # Per-line invariant: round(Qty x UP, 2) == IT for every item.
    for item in doc.findall(".//g:Item", ns):
        qty = Decimal(item.findtext("g:Qty", namespaces=ns) or "0")
        up = Decimal(item.findtext("g:UP", namespaces=ns) or "0")
        it = Decimal(item.findtext("g:IT", namespaces=ns) or "0")
        recomputed = (qty * up).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert recomputed == it, f"Item invariant broken: {qty} x {up} = {recomputed} != IT {it}"


def test_export_markup_not_dropped() -> None:
    """The markup amount is written as a MarkupItem/IT (not silently dropped, X84)."""
    boq = _build_demo_boq()
    xml = build_gaeb_xml(boq, project_name="XSD Demo", project_currency="EUR", gaeb_format="x84")
    doc = etree.fromstring(xml.encode("utf-8"))
    ns = {"g": doc.tag.split("}")[0].lstrip("{")}

    markup_it = [Decimal((el.text or "0").strip()) for el in doc.findall(".//g:MarkupItem/g:IT", ns)]
    assert markup_it, "No MarkupItem/IT in export - markup money was dropped"
    expected = (_expected_direct() * Decimal("0.10")).quantize(Decimal("0.01"))
    assert markup_it[0] == expected, f"Markup {markup_it[0]} != expected {expected}"

    # Reconciliation: Total (direct) + markup == TotalNet in the Totals block.
    total = Decimal(doc.findtext(".//g:BoQInfo/g:Totals/g:Total", namespaces=ns) or "0")
    total_net = Decimal(doc.findtext(".//g:BoQInfo/g:Totals/g:TotalNet", namespaces=ns) or "0")
    assert total == _expected_direct()
    assert total_net == (_expected_direct() + expected)


def test_export_oz_in_rnopart_not_id() -> None:
    """The OZ rides in RNoPart; @ID is an opaque xs:ID handle (never the OZ)."""
    boq = _build_demo_boq()
    xml = build_gaeb_xml(boq, project_name="XSD Demo", project_currency="EUR", gaeb_format="x84")
    doc = etree.fromstring(xml.encode("utf-8"))
    ns = {"g": doc.tag.split("}")[0].lstrip("{")}

    for item in doc.findall(".//g:Item", ns):
        item_id = item.get("ID") or ""
        rnopart = item.get("RNoPart") or ""
        # @ID must be a valid xs:ID (no leading digit) and must not equal the
        # raw dotted OZ.
        assert item_id and not item_id[0].isdigit(), f"Item @ID {item_id!r} is not a valid xs:ID"
        assert "." not in rnopart, f"RNoPart {rnopart!r} must carry a single OZ level"

    # The RNoPart chain rebuilds the original leaf segment.
    leaf_rnoparts = {item.get("RNoPart") for item in doc.findall(".//g:Item", ns)}
    assert "001" in leaf_rnoparts and "002" in leaf_rnoparts


def test_roundtrip_preserves_total_and_count() -> None:
    """Export -> re-import via the GAEB importer preserves total + count to the cent."""
    import asyncio

    from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

    boq = _build_demo_boq()
    # X84 (Angebotsabgabe) is the priced phase that carries UP/IT, so the
    # money round-trip is exercised through it.
    xml = build_gaeb_xml(boq, project_name="XSD Demo", project_currency="EUR", gaeb_format="x84")

    imported = asyncio.run(GAEBXMLImporter.parse(xml.encode("utf-8")))

    priced = [p for p in imported.positions if not getattr(p, "is_section", False)]
    original_count = sum(len(sec.positions) for sec in boq.sections)
    assert len(priced) == original_count, f"Re-import position count {len(priced)} != original {original_count}"

    # Sum quantity * unit_rate over re-imported priced lines == direct cost.
    reimported_direct = sum(
        (Decimal(str(p.quantity)) * Decimal(str(p.unit_rate))).quantize(Decimal("0.01")) for p in priced
    )
    assert reimported_direct == _expected_direct(), (
        f"Re-imported direct cost {reimported_direct} != original {_expected_direct()}"
    )

    # The importer must not silently drop anything: no errors recorded.
    assert imported.errors == [], f"Importer reported errors: {imported.errors}"
