"""GAEB DA XML 3.3 exporter conformance + money round-trip tests.

The exporter must produce documents a GAEB consumer will accept, and those
documents must round-trip (export -> import) without losing a cent or a
position. These tests drive the pure ``build_gaeb_xml`` builder directly
(no app / DB), so they run anywhere lxml is installed.

Two schemas, two different jobs
-------------------------------
**Our profile schema**, ``app/modules/boq/gaeb_profile/``, is written by us
and ships with the product. It describes the subset of GAEB DA XML 3.3 that
this codebase reads and writes, and it is the schema a customer can point at
our output. What it cannot do is settle a conformance question on its own:
it was written from the same understanding of the format as the exporter, so
a mistake present in both would pass. It catches drift and structural
regressions, which is a real job, but it is not an independent opinion.

**The schema set GAEB publishes** is the independent opinion. We do not
redistribute it - docs/standards/GAEB.md explains why - so the tests that use
it skip unless a copy is available locally. Two ways to provide one:

* point ``GAEB_XSD_DIR`` at a directory holding the unpacked 3.3 schema
  files, or
* set ``OCE_GAEB_FETCH_XSD=1`` and let the test fetch the publicly offered
  schema archive once into a cache directory.

Both are opt-in, so an offline run never fails on a network call, and CI
sets the second so the conformance claim is exercised somewhere.

Run::

    cd backend
    python -m pytest tests/unit/test_gaeb_export_xsd.py -v --tb=short
"""

from __future__ import annotations

import os
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

etree = pytest.importorskip("lxml.etree")

from app.modules.boq.router import build_gaeb_xml

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb"
_CONFORMANCE = {
    "83": _FIXTURES / "oce_conformance_x83.x83",
    "84": _FIXTURES / "oce_conformance_x84.x84",
}

# ── Our own profile schema (always available) ────────────────────────────────

_PROFILE_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "boq" / "gaeb_profile"
_PROFILE_XSD = {
    "83": "oce-gaeb-3.3-x83.xsd",
    "84": "oce-gaeb-3.3-x84.xsd",
}


def _load_schema(dp_code: str) -> etree.XMLSchema:
    """Load our GAEB 3.3 profile schema for the given DP phase."""
    parser = etree.XMLParser(load_dtd=False, no_network=True)
    root = etree.parse(str(_PROFILE_DIR / _PROFILE_XSD[dp_code]), parser)
    return etree.XMLSchema(root)


def test_profile_schemas_differ_only_in_the_exchange_phase() -> None:
    """The two profile files must not drift apart.

    They describe the same element model for two exchange phases, so the X84
    file is the X83 file with the phase swapped. Anything else that differs
    is an edit someone made to one and forgot in the other.
    """
    x83 = (_PROFILE_DIR / _PROFILE_XSD["83"]).read_text(encoding="utf-8")
    x84 = (_PROFILE_DIR / _PROFILE_XSD["84"]).read_text(encoding="utf-8")
    swapped = (
        x83.replace("DA83/3.3", "DA84/3.3")
        .replace("phase X83", "phase X84")
        .replace(
            "(Angebotsaufforderung, the unpriced call for bids)",
            "(Angebotsabgabe, the priced bid submission)",
        )
        .replace("3.3 X83.", "3.3 X84.")
    )
    assert swapped == x84, "the X83 and X84 profile schemas have drifted apart"


@pytest.mark.parametrize("dp_code", ["83", "84"])
def test_profile_accepts_our_conformance_fixture(dp_code: str) -> None:
    """The in-house conformance fixtures satisfy the shipped profile."""
    schema = _load_schema(dp_code)
    doc = etree.parse(str(_CONFORMANCE[dp_code]))
    assert schema.validate(doc), f"profile rejected {_CONFORMANCE[dp_code].name}: " + "; ".join(
        f"{e.line}:{e.message}" for e in schema.error_log[:6]
    )


# ── The schema GAEB publishes (opt-in, never redistributed) ──────────────────

_OFFICIAL_XSD = {
    "83": "GAEB_DA_XML_83_3.3_2021-05.xsd",
    "84": "GAEB_DA_XML_84_3.3_2021-05.xsd",
}
# The bill-of-quantities package of the GAEB DA XML 3.3 (2021-05) schema
# release, offered for download by the publisher without registration.
_OFFICIAL_ARCHIVE = "https://www.gaeb.de/wp-content/uploads/2021/06/2021-05_Leistungsverzeichnis.zip"
_SKIP_REASON = (
    "the schema published by GAEB is not in this repository; set GAEB_XSD_DIR to a local copy, "
    "or OCE_GAEB_FETCH_XSD=1 to fetch one"
)


def _fetch_official_schemas(target: Path) -> bool:
    """Download and unpack the published schema archive into ``target``.

    Returns False on any failure. A test that cannot reach the publisher
    skips rather than fails: an unreachable web server says nothing about
    our exporter.
    """
    import io
    import urllib.request
    import zipfile

    try:
        with urllib.request.urlopen(_OFFICIAL_ARCHIVE, timeout=60) as response:  # noqa: S310
            payload = response.read()
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name in archive.namelist():
                if name.endswith(".xsd") and "/" not in name and "\\" not in name:
                    (target / name).write_bytes(archive.read(name))
    except Exception:  # noqa: BLE001 - any failure means "no oracle available"
        return False
    return all((target / name).exists() for name in _OFFICIAL_XSD.values())


def _official_dir() -> Path | None:
    """Locate a local copy of the published 3.3 schema set, or None."""
    configured = os.environ.get("GAEB_XSD_DIR")
    if configured:
        candidate = Path(configured)
        if all((candidate / name).exists() for name in _OFFICIAL_XSD.values()):
            return candidate
        return None

    if os.environ.get("OCE_GAEB_FETCH_XSD", "").lower() not in ("1", "true", "yes"):
        return None

    cache = Path(tempfile.gettempdir()) / "oce-gaeb-xsd-3.3-2021-05"
    if all((cache / name).exists() for name in _OFFICIAL_XSD.values()):
        return cache
    if _fetch_official_schemas(cache):
        return cache
    return None


def _load_official_schema(dp_code: str) -> etree.XMLSchema:
    directory = _official_dir()
    if directory is None:
        pytest.skip(_SKIP_REASON)
    parser = etree.XMLParser(load_dtd=False, no_network=True)
    root = etree.parse(str(directory / _OFFICIAL_XSD[dp_code]), parser)
    return etree.XMLSchema(root)


@pytest.mark.parametrize("dp_code", ["83", "84"])
def test_published_schema_accepts_our_conformance_fixture(dp_code: str) -> None:
    """Our hand-authored fixtures really are conformant GAEB 3.3 documents.

    This is the check that keeps the fixtures honest. We wrote them, so
    nothing else in the suite would notice if they quietly stopped being
    valid GAEB.
    """
    schema = _load_official_schema(dp_code)
    doc = etree.parse(str(_CONFORMANCE[dp_code]))
    assert schema.validate(doc), f"published schema rejected {_CONFORMANCE[dp_code].name}: " + "; ".join(
        f"{e.line}:{e.message}" for e in schema.error_log[:8]
    )


@pytest.mark.parametrize("gaeb_format", ["x83", "x84"])
def test_published_schema_accepts_our_export(gaeb_format: str) -> None:
    """The exporter's output is accepted by the schema GAEB publishes.

    The independent conformance check. The profile tests cannot replace it:
    those compare our writer against our own description of the format.
    """
    dp_code = "84" if gaeb_format == "x84" else "83"
    schema = _load_official_schema(dp_code)
    xml = build_gaeb_xml(_build_demo_boq(), project_name="XSD Demo", project_currency="EUR", gaeb_format=gaeb_format)
    doc = etree.fromstring(xml.encode("utf-8"))
    assert schema.validate(doc), f"published schema rejected the {gaeb_format} export: " + "; ".join(
        f"{e.line}:{e.message}" for e in schema.error_log[:12]
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


@pytest.mark.parametrize("bid_type", ["main", "alternate"])
def test_export_x84_bid_types_validate(bid_type: str) -> None:
    """Both X84 bid types (Hauptangebot / Nebenangebot) stay XSD-valid.

    The alternate branch writes the rationale of flagged positions as a
    ``BidComm`` (Bieter Kommentar) - a real schema element - so the document
    must validate either way. The main branch must carry no BidComm at all.
    """
    boq = _build_demo_boq()
    # Flag one position as an alternate so the branch has something to write.
    boq.sections[0].positions[0].metadata = {
        "alt_parent_ref": "01.001",
        "alt_markup_reason": "Fertigteil statt Ortbeton, kuerzere Bauzeit.",
    }
    xml = build_gaeb_xml(boq, project_name="XSD Demo", project_currency="EUR", gaeb_format="x84", bid_type=bid_type)
    schema = _load_schema("84")
    doc = etree.fromstring(xml.encode("utf-8"))
    assert schema.validate(doc), f"X84 bid_type={bid_type} failed XSD validation: " + "; ".join(
        f"{e.line}:{e.message}" for e in schema.error_log[:12]
    )
    ns = {"g": doc.tag.split("}")[0].lstrip("{")}
    bid_comms = doc.findall(".//g:Item/g:BidComm", ns)
    if bid_type == "alternate":
        assert len(bid_comms) == 1, "flagged position must carry its BidComm rationale"
        assert "Nebenangebot zu Position 01.001" in "".join(bid_comms[0].itertext())
    else:
        assert bid_comms == [], "a plain Hauptangebot must not carry alternate markers"


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


def _build_taxed_demo_boq() -> SimpleNamespace:
    """The demo LV with German VAT added as a second, tax-category markup.

    ``_build_demo_boq`` carries one overhead markup and no tax, which is why
    every existing assertion about ``TotalNet`` passes whether or not the tax
    is subtracted: there is no tax to subtract. A bill that is actually priced
    in Germany carries both, and it is the only shape that can tell the two
    readings of the field apart.
    """
    boq = _build_demo_boq()
    overhead = boq.markups[0]
    taxable = boq.direct_cost + overhead.amount
    vat = (taxable * Decimal("0.19")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    boq.markups = [
        overhead,
        SimpleNamespace(
            name="Umsatzsteuer",
            markup_type="percentage",
            category="tax",
            percentage=19.0,
            amount=vat,
            is_active=True,
        ),
    ]
    boq.net_total = taxable + vat
    boq.grand_total = boq.net_total
    return boq


def test_totalnet_excludes_the_tax_that_net_total_already_carries() -> None:
    """Netto in a German exchange format is the total before VAT.

    ``net_total`` on the bill is the direct cost plus every active markup and a
    VAT line is one of them, so writing that figure under ``TotalNet`` hands a
    German reader a gross number under a net label. The same subtraction was
    made for the PDF exports in 906bd78cc; this is the site that fix did not
    reach.
    """
    boq = _build_taxed_demo_boq()
    overhead, tax = boq.markups
    xml = build_gaeb_xml(boq, project_name="XSD Demo", project_currency="EUR", gaeb_format="x84")
    doc = etree.fromstring(xml.encode("utf-8"))
    ns = {"g": doc.tag.split("}")[0].lstrip("{")}

    total = Decimal(doc.findtext(".//g:BoQInfo/g:Totals/g:Total", namespaces=ns) or "0")
    total_net = Decimal(doc.findtext(".//g:BoQInfo/g:Totals/g:TotalNet", namespaces=ns) or "0")

    # Without a tax worth subtracting the two readings coincide and this test
    # would pass on the defect it exists to catch.
    assert tax.amount > 0, "the fixture carries no tax, so this test proves nothing"
    assert boq.net_total != total_net, (
        "TotalNet equals the tax-inclusive net_total, which is the defect: "
        f"{total_net} was written under a label that means the total before tax"
    )

    assert total == _expected_direct()
    assert total_net == _expected_direct() + overhead.amount
    assert boq.net_total - total_net == tax.amount

    # The tax money is subtracted from the label, not dropped from the file.
    markup_totals = [Decimal((el.text or "0").strip()) for el in doc.findall(".//g:MarkupItem/g:IT", ns)]
    assert tax.amount in markup_totals, f"the VAT line is missing from the export: {markup_totals}"


def test_a_bill_with_no_tax_reads_the_same_under_both_labels() -> None:
    """The subtraction must not move a bill that has no tax on it.

    This is the other direction of the same gate. If the tax split ever starts
    subtracting something that is not tax, this is what notices.
    """
    boq = _build_demo_boq()
    assert all(m.category != "tax" for m in boq.markups), "fixture drifted and now carries a tax"
    xml = build_gaeb_xml(boq, project_name="XSD Demo", project_currency="EUR", gaeb_format="x84")
    doc = etree.fromstring(xml.encode("utf-8"))
    ns = {"g": doc.tag.split("}")[0].lstrip("{")}

    total_net = Decimal(doc.findtext(".//g:BoQInfo/g:Totals/g:TotalNet", namespaces=ns) or "0")
    assert total_net == boq.net_total
