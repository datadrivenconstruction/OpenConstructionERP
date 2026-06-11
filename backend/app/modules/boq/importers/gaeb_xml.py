"""GAEB DA XML 3.3 importer (DACH).

Native parser for the German/Austrian/Swiss tender exchange format.
Phase (Datenaustauschphase, DP) semantics per the official GAEB DA XML
Fachdokumentation:

* **X81 / DP 81** - Leistungsverzeichnis (BOQ skeleton, unpriced)
* **X82 / DP 82** - Kostenanschlag
* **X83 / DP 83** - Angebotsaufforderung (call for bids, unpriced)
* **X84 / DP 84** - Angebotsabgabe (priced bid submission - carries UP/IT,
  legally omits Qty/QU/Description which come from the X83)
* **X85 / DP 85** - Nebenangebot (alternative bid)
* **X86 / DP 86** - Auftragserteilung (order award)

Namespace-agnostic: matches by tag local-name so files from any
mainstream GAEB authoring tool import without pre-normalisation.

Security: parses via ``defusedxml`` - XXE, billion-laughs and DTD-based
attacks are rejected up-front.

Round-trip integrity (FA-GAEB-001): an X84 carries the binding position
total in ``<IT>`` and the unit price in ``<UP>`` but no ``<Qty>``. The
importer reconstructs an exact quantity from ``IT / UP`` so the persisted
``quantity * unit_rate`` reproduces ``IT`` to the cent, and stamps the
authoritative ``IT`` under ``metadata["gaeb_it"]``. Any amount the importer
cannot reconcile is reported as a warning or error with a count - never
dropped silently.

Hierarchy: the ``<BoQCtgy>`` tree is preserved as section header rows that
mirror the LV structure, and the full OZ (Ordnungszahl) is built from the
``RNoPart`` chain (plus ``RNoIndex``) per the project's ``BoQBkdn`` mask -
never the opaque ``Item@ID`` (xs:ID).

Epic I12 adds preservation of GAEB ``<DescrTxc>`` rich-text blocks under
``metadata["descr_txc"]`` so the editor can re-render the original
formatting on export.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from app.modules.boq.importers._base import (
    ImportedBOQ,
    ImportedPosition,
    ImporterParseError,
)

logger = logging.getLogger(__name__)


# GAEB unit code → internal token. Single source of truth for round-trip
# import/export (matches the inverse map used by the GAEB exporter).
_GAEB_TO_INTERNAL: dict[str, str] = {
    "stk": "pcs",
    "st": "pcs",
    "psch": "lsum",
    "jahr": "year",
    "mo": "month",
}

# DP (Datenaustauschphase) number → DA-kind token. The previous map only
# covered 81/83/84/86 and returned "x" for DP80/82/85 (FA-GAEB-005, the
# X86/DP80 file detected as "x"). Cover the full DP80..DP86 range.
_DP_TO_KIND: dict[str, str] = {
    "80": "x80",
    "81": "x81",
    "82": "x82",
    "83": "x83",
    "84": "x84",
    "85": "x85",
    "86": "x86",
}


def _local(tag: str) -> str:
    """Strip ``{namespace}`` prefix from an ET tag."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    """Namespace-agnostic single-child lookup by local name."""
    for child in parent:
        if _local(child.tag) == name:
            return child
    return None


def _find_all_descendants(parent: ET.Element, name: str) -> list[ET.Element]:
    """Walk the entire subtree, collect elements whose local name matches."""
    found: list[ET.Element] = []
    for el in parent.iter():
        if _local(el.tag) == name:
            found.append(el)
    return found


def _text_of(parent: ET.Element, name: str) -> str:
    child = _find_child(parent, name)
    return (child.text or "").strip() if child is not None else ""


def _normalize_unit(unit: str) -> str:
    """Map a GAEB unit code to the internal token, or pass through."""
    key = (unit or "").strip().lower()
    return _GAEB_TO_INTERNAL.get(key, unit.strip()) if key else ""


def _to_decimal(raw: str) -> Decimal | None:
    """Parse a GAEB numeric field (UP/IT/Qty) as an exact ``Decimal``.

    GAEB always writes these fields with a ``.`` decimal separator and no
    thousand grouping (Fachdok 3.x), so a direct ``Decimal`` parse is both
    correct and cent-exact. Returns ``None`` for blank / unparseable input.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


# Marker labels that GAEB exporters drop into their own ``<p>`` paragraphs
# inside the long text. They are position-type annotations (Provis flags,
# Remark kinds), not part of the human description - strip them so the
# editor does not show ``Normalposition`` fused onto every row.
_TEXT_NOISE_MARKERS: frozenset[str] = frozenset(
    {
        "normalposition",
        "bedarfsposition",
        "bedarfsposition mit gesamtbetrag",
        "bedarfsposition ohne gesamtbetrag",
        "eventualposition",
        "grundposition",
        "alternativposition",
        "zuschlagsposition",
        "withtotal",
        "withouttotal",
        "no",
        "yes",
        "·",
    }
)


def _paragraph_text(node: ET.Element) -> str:
    """Render one GAEB ``<p>`` / ``<Text>`` paragraph to a single line.

    Joins the inner ``<span>`` runs (and any bare paragraph text) with
    single spaces, collapsing whitespace. Drops paragraphs that are pure
    annotation markers (``Normalposition`` etc.) so they don't pollute the
    description.
    """
    parts: list[str] = []
    if node.text and node.text.strip():
        parts.append(node.text.strip())
    for child in node.iter():
        if child is node:
            continue
        if _local(child.tag) == "span":
            if child.text and child.text.strip():
                parts.append(child.text.strip())
        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())
    line = " ".join(parts)
    return " ".join(line.split())


def _extract_descr_txc(item: ET.Element) -> dict[str, Any] | None:
    """Capture the GAEB rich-text ``<DescrTxc>`` / ``<DescriptTxc>`` block.

    Epic I12: preserved as a serialised XML snippet (round-trip) plus a
    plain-text view (editor preview). Returns ``None`` if absent.
    """
    for name in ("DescrTxc", "DescriptTxc", "OutlineTxc"):
        node = _find_child(item, name)
        if node is None:
            desc = _find_child(item, "Description")
            if desc is not None:
                node = _find_child(desc, name)
        if node is not None:
            try:
                raw_xml = ET.tostring(node, encoding="unicode")
            except Exception:  # noqa: BLE001 - best-effort capture
                raw_xml = ""
            plain_text = "".join(node.itertext()).strip()
            return {"raw_xml": raw_xml, "plain_text": plain_text}
    return None


def _extract_long_text(item: ET.Element) -> str:
    """Pull the human-readable long text (Langtext) from an item.

    Reads the FIRST ``Description / CompleteText / DetailTxt / Text`` block
    and joins its paragraphs cleanly, dropping annotation markers. This
    replaces the old ``itertext()`` concatenation that fused quantity, unit,
    UP, IT, Provis flags and Remark text into one polluted string
    (FA-STD-033). Returns ``""`` when the item carries no Text block (an
    X84 priced line legitimately omits the description).
    """
    desc = _find_child(item, "Description")
    text_node: ET.Element | None = None
    if desc is not None:
        complete = _find_child(desc, "CompleteText")
        container = complete if complete is not None else desc
        detail = _find_child(container, "DetailTxt")
        text_node = _find_child(detail, "Text") if detail is not None else None
        if text_node is None:
            text_node = _find_child(container, "Text")
    if text_node is None:
        # Some toolchains place <Text> directly under the item.
        text_node = _find_child(item, "Text")

    if text_node is not None:
        paragraphs: list[str] = []
        # The text node may itself hold <p> children, or be a flat <span>
        # run / bare string.
        p_nodes = [c for c in text_node if _local(c.tag) == "p"]
        sources = p_nodes if p_nodes else [text_node]
        for p in sources:
            line = _paragraph_text(p)
            if not line:
                continue
            if line.strip().lower() in _TEXT_NOISE_MARKERS:
                continue
            paragraphs.append(line)
        if paragraphs:
            return "\n".join(paragraphs)
    return ""


def _label_text(node: ET.Element | None) -> str:
    """Render a GAEB label node (``LblTx`` / ``OutlTxt``) to one line.

    Handles both the bare-text shape (``<LblTx>Erdarbeiten</LblTx>``) and
    the nested ``<p><span>…</span></p>`` shape the official BVBS files use.
    """
    if node is None:
        return ""
    if node.text and node.text.strip():
        return node.text.strip()
    return _paragraph_text(node)


def _extract_short_text(item: ET.Element) -> str:
    """Pull the Kurztext (short label) from ``OutlineText / OutlTxt`` or
    a category's ``LblTx``. Handles bare-text and nested ``<p><span>``."""
    desc = _find_child(item, "Description")
    for container in (desc, item):
        if container is None:
            continue
        outline = _find_child(container, "OutlineText")
        if outline is not None:
            txt = _find_child(outline, "OutlTxt")
            target = txt if txt is not None else outline
            line = _label_text(_find_child(target, "Text") or target)
            if line:
                return line
        for name in ("OutlTxt", "LblTx"):
            line = _label_text(_find_child(container, name))
            if line:
                return line
    return ""


def _extract_description(item: ET.Element) -> str:
    """Best human-readable description: Kurztext, else Langtext.

    Always a plain string; rich text lives in ``metadata["descr_txc"]``.
    """
    short = _extract_short_text(item)
    if short:
        return short
    return _extract_long_text(item)


def _detect_da_kind(root: ET.Element) -> str:
    """Return ``"x80".."x86"`` or ``"x"`` (unknown DA phase).

    Reads the ``<Award><DP>`` (or ``<DPType>``) phase number first, then
    falls back to the ``DA<nn>`` token embedded in the GAEB root namespace
    (``.../GAEB_DA_XML/DA84/3.3``). The old probe matched ``DPNo`` / ``DP``
    interchangeably and only mapped four phases, so DP80 files came back as
    ``"x"`` (FA-GAEB-005).
    """
    for el in root.iter():
        tag = _local(el.tag)
        if tag in ("DP", "DPType"):
            text = (el.text or "").strip().lower().lstrip("x")
            kind = _DP_TO_KIND.get(text)
            if kind:
                return kind
    # Namespace fallback: DA<nn> in the root tag's namespace URI.
    ns = root.tag.split("}", 1)[0].lstrip("{") if "}" in root.tag else ""
    marker = "/DA"
    idx = ns.find(marker)
    if idx != -1:
        digits = ns[idx + len(marker) : idx + len(marker) + 2]
        kind = _DP_TO_KIND.get(digits)
        if kind:
            return kind
    return "x"


def _ozmask_separators(root: ET.Element) -> tuple[list[str], str]:
    """Read the OZ-Maske (``BoQBkdn``) - the level lengths and the index flag.

    Returns ``(level_lengths, index_align)`` where ``level_lengths`` is the
    ordered list of zero-padded widths for the BoQLevel/Item parts and
    ``index_align`` is the alignment hint for the optional RNoIndex. The
    mask is only used to zero-pad parts that arrive un-padded; GAEB files
    usually carry already-padded ``RNoPart`` values, so this is defensive.
    """
    lengths: list[str] = []
    index_align = "left"
    for bkdn in _find_all_descendants(root, "BoQBkdn"):
        bk_type = _text_of(bkdn, "Type")
        if bk_type in ("BoQLevel", "Item"):
            lengths.append(_text_of(bkdn, "Length"))
        elif bk_type == "Index":
            index_align = _text_of(bkdn, "Alignment") or "left"
    return lengths, index_align


def _build_oz(rno_parts: list[str], rno_index: str, lengths: list[str]) -> str:
    """Compose the full OZ from the RNoPart chain plus optional RNoIndex.

    ``rno_parts`` is the ordered list of ``RNoPart`` values from the
    enclosing BoQCtgy chain down to the item. They are joined with ``.`` and
    the index (if any) is appended as ``.<index>`` (Fachdok 3.x OZ display).
    Already-padded parts pass through unchanged; un-padded parts are padded
    to the matching mask width when available.
    """
    padded: list[str] = []
    for depth, part in enumerate(rno_parts):
        width_str = lengths[depth] if depth < len(lengths) else ""
        if part.isdigit() and width_str.isdigit():
            padded.append(part.zfill(int(width_str)))
        else:
            padded.append(part)
    oz = ".".join(p for p in padded if p)
    if rno_index:
        oz = f"{oz}.{rno_index}" if oz else rno_index
    return oz


class GAEBXMLImporter:
    """Importer for GAEB DA XML 3.3 files (X81/X83/X84/X86)."""

    format_id: ClassVar[str] = "gaeb_xml"
    extensions: ClassVar[tuple[str, ...]] = (".x81", ".x83", ".x84", ".x86", ".xml")
    display_name: ClassVar[str] = "GAEB DA XML 3.3"
    rule_packs: ClassVar[tuple[str, ...]] = ("gaeb", "din276", "boq_quality")

    @classmethod
    def detect(cls, head_bytes: bytes, filename: str) -> bool:
        """GAEB files always start with an XML prolog and a ``<GAEB`` root
        within the first 2 KB. The extension check is the cheap path; the
        content sniff catches ``.xml`` uploads with a GAEB payload.
        """
        if not head_bytes:
            return False
        name = filename.lower()
        if any(name.endswith(ext) for ext in (".x81", ".x83", ".x84", ".x86")):
            return True
        if not name.endswith(".xml"):
            return False
        try:
            head_text = head_bytes[:2048].decode("utf-8", errors="ignore").lower()
        except Exception:  # noqa: BLE001 - best-effort sniff
            return False
        return "<gaeb" in head_text or "gaeb_award" in head_text

    @classmethod
    async def parse(cls, content: bytes, *, locale: str = "en") -> ImportedBOQ:
        """Parse a GAEB XML buffer into :class:`ImportedBOQ`."""
        from defusedxml.ElementTree import fromstring as _safe_fromstring

        if not content:
            raise ImporterParseError("GAEB XML upload is empty")

        try:
            root = _safe_fromstring(content)
        except ET.ParseError as exc:
            raise ImporterParseError(f"Failed to parse GAEB XML: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ImporterParseError(f"GAEB XML rejected by security parser: {exc}") from exc

        da_kind = _detect_da_kind(root)
        priced_phase = da_kind in ("x84", "x86")
        mask_lengths, _index_align = _ozmask_separators(root)
        # Integer view of the mask widths for validation threading; only the
        # all-numeric prefix is meaningful as level widths.
        oz_mask_widths: list[int] = [int(w) for w in mask_lengths if w.isdigit()]

        # Locate the top-level <BoQBody> directly inside <BoQ>.
        top_body: ET.Element | None = None
        for el in root.iter():
            if _local(el.tag) == "BoQ":
                top_body = _find_child(el, "BoQBody")
                if top_body is not None:
                    break
        if top_body is None:
            raise ImporterParseError("No <BoQBody> element found. Is this a valid GAEB DA XML?")

        # Currency from <Award><Cur> with <AwardInfo><Cur> fallback (3.3
        # nests it under AwardInfo).
        award: ET.Element | None = None
        for el in root.iter():
            if _local(el.tag) == "Award":
                award = el
                break
        currency = ""
        if award is not None:
            currency = _text_of(award, "Cur")
            if not currency:
                award_info = _find_child(award, "AwardInfo")
                if award_info is not None:
                    currency = _text_of(award_info, "Cur")

        award_meta: dict[str, Any] = {}
        if award is not None:
            for field_name in (
                "OrderNo",
                "ContractNo",
                "DateOfContract",
                "DateOfOffer",
                "Bidder",
            ):
                val = _text_of(award, field_name)
                if val:
                    award_meta[field_name] = val

        result = ImportedBOQ(source_format="gaeb", currency=currency)

        # Walk the BoQCtgy tree, emitting section header rows that mirror the
        # LV hierarchy and item rows underneath. ``rno_chain`` accumulates the
        # RNoPart of every enclosing BoQCtgy so each item gets its full OZ.
        sections_seen: list[dict[str, str]] = []
        markup_items: list[dict[str, str]] = []
        unmapped_money = 0
        derived_qty = 0

        def _emit_item(item: ET.Element, rno_chain: list[str], section_oz: str) -> None:
            nonlocal unmapped_money, derived_qty
            rno_part = (item.get("RNoPart") or "").strip()
            rno_index = (item.get("RNoIndex") or "").strip()
            if rno_part:
                ordinal = _build_oz(rno_chain + [rno_part], rno_index, mask_lengths)
            else:
                # No RNoPart: the OZ lives in @ID for these toolchains. Use it
                # verbatim (already the full dotted OZ) rather than the opaque
                # section chain.
                item_id = (item.get("ID") or "").strip()
                ordinal = (f"{item_id}.{rno_index}" if rno_index else item_id) if item_id else ""

            unit_raw = _text_of(item, "QU")
            qty_dec = _to_decimal(_text_of(item, "Qty"))
            up_dec = _to_decimal(_text_of(item, "UP"))
            it_dec = _to_decimal(_text_of(item, "IT"))

            description = _extract_description(item)

            # ── Money reconstruction ──────────────────────────────────────
            # X83/X81 carry Qty(+optionally UP). X84/X86 carry UP and IT but
            # no Qty - the binding total is IT. Reconstruct an exact quantity
            # so quantity * unit_rate == IT to the cent (FA-GAEB-001).
            quantity: float
            unit_rate_dec: Decimal
            if qty_dec is not None:
                quantity = float(qty_dec)
                unit_rate_dec = up_dec if up_dec is not None else Decimal("0")
            elif it_dec is not None and up_dec is not None and up_dec != 0:
                ratio = it_dec / up_dec
                # Exact iff (ratio quantised back through UP) reproduces IT.
                if (ratio * up_dec).quantize(Decimal("0.01")) == it_dec.quantize(Decimal("0.01")):
                    quantity = float(ratio)
                    unit_rate_dec = up_dec
                    derived_qty += 1
                else:
                    # Cannot reconcile UP*Qty to IT exactly: keep the binding
                    # total lossless by carrying it as a lump (qty 1 x IT) and
                    # warn so the value is never silently distorted.
                    quantity = 1.0
                    unit_rate_dec = it_dec
                    result.warnings.append(
                        {
                            "ordinal": ordinal,
                            "warning": (
                                f"X84 item {ordinal}: IT {it_dec} not exactly divisible by "
                                f"UP {up_dec}; stored as lump-sum total to preserve the amount."
                            ),
                        }
                    )
            elif it_dec is not None:
                # IT present but no usable UP - store the binding total as a
                # lump-sum (qty 1) so no money is lost.
                quantity = 1.0
                unit_rate_dec = it_dec
                derived_qty += 1
            else:
                quantity = float(qty_dec) if qty_dec is not None else 0.0
                unit_rate_dec = up_dec if up_dec is not None else Decimal("0")
                if it_dec is None and up_dec is None and qty_dec is None and priced_phase:
                    unmapped_money += 1

            unit = _normalize_unit(unit_raw) or ("lsum" if (qty_dec is None and it_dec is not None) else "pcs")

            if not description and qty_dec is None and it_dec is None and up_dec is None:
                # Nothing usable at all - skip but count it.
                result.skipped += 1
                return

            if not (0 <= quantity <= 1e9):
                result.errors.append({"ordinal": ordinal, "error": f"Quantity out of range: {quantity}"})
                return
            if not (Decimal("0") <= unit_rate_dec <= Decimal("1e8")):
                result.errors.append({"ordinal": ordinal, "error": f"Unit rate out of range: {unit_rate_dec}"})
                return

            classification: dict[str, Any] = {}
            if section_oz:
                classification["gaeb_section"] = section_oz

            metadata: dict[str, Any] = {
                "gaeb_ordinal": ordinal,
                "gaeb_section": section_oz,
                "gaeb_unit_original": unit_raw,
                "gaeb_currency": currency,
                "gaeb_da_kind": da_kind,
            }
            if oz_mask_widths:
                metadata["gaeb_oz_mask"] = oz_mask_widths
            # Provis = Bedarfs-/Eventualposition (optional scope). Such a line
            # may legitimately carry a zero or missing Einheitspreis, so flag
            # it for the validators (FA-STD-044).
            provis = _text_of(item, "Provis").strip()
            if provis:
                metadata["gaeb_provis"] = provis
            if it_dec is not None:
                # Authoritative binding total straight from the file.
                metadata["gaeb_it"] = str(it_dec)
            if rno_index:
                metadata["gaeb_rno_index"] = rno_index
            long_text = _extract_long_text(item)
            if long_text and long_text != description:
                metadata["gaeb_long_text"] = long_text
            descr_txc = _extract_descr_txc(item)
            if descr_txc is not None:
                metadata["descr_txc"] = descr_txc

            result.positions.append(
                ImportedPosition(
                    description=description or ordinal,
                    ordinal=ordinal,
                    unit=unit,
                    quantity=quantity,
                    unit_rate=float(unit_rate_dec),
                    classification=classification,
                    source="gaeb_import",
                    metadata=metadata,
                )
            )

        def _emit_markup(mk: ET.Element, rno_chain: list[str]) -> None:
            """Surface a Zuschlagsposition (MarkupItem) - never drop silently."""
            rno_part = (mk.get("RNoPart") or "").strip()
            oz = _build_oz(rno_chain + ([rno_part] if rno_part else []), "", mask_lengths)
            it_dec = _to_decimal(_text_of(mk, "IT"))
            it_markup = _to_decimal(_text_of(mk, "ITMarkup"))
            pct = _text_of(mk, "Markup")
            markup_items.append(
                {
                    "ordinal": oz or (mk.get("ID") or "").strip(),
                    "it": str(it_dec) if it_dec is not None else "",
                    "it_markup_base": str(it_markup) if it_markup is not None else "",
                    "percentage": pct,
                }
            )
            result.warnings.append(
                {
                    "ordinal": oz,
                    "warning": (
                        f"Markup position (Zuschlagsposition) {oz}: IT {it_dec} on base "
                        f"{it_markup} at {pct}% is recorded in metadata but not yet applied "
                        f"as a BOQ markup line."
                    ),
                }
            )

        def _walk(body: ET.Element, rno_chain: list[str], section_oz: str) -> None:
            for child in body:
                tag = _local(child.tag)
                if tag == "BoQCtgy":
                    # OZ part from RNoPart; fall back to @ID for files that
                    # carry the ordinal there (some authoring tools) - never
                    # invent one.
                    part = (child.get("RNoPart") or child.get("ID") or "").strip()
                    child_chain = rno_chain + ([part] if part else [])
                    child_oz = _build_oz(child_chain, "", mask_lengths)
                    label = _extract_short_text(child)
                    sections_seen.append({"ordinal": child_oz, "label": label or child_oz})
                    # Emit a section header row mirroring the LV tree.
                    result.positions.append(
                        ImportedPosition(
                            description=label or child_oz or "Section",
                            ordinal=child_oz,
                            unit="section",
                            quantity=0.0,
                            unit_rate=0.0,
                            classification={"gaeb_section": child_oz} if child_oz else {},
                            source="gaeb_import",
                            is_section=True,
                            metadata={
                                "gaeb_ordinal": child_oz,
                                "gaeb_da_kind": da_kind,
                                "gaeb_is_section": True,
                            },
                        )
                    )
                    inner = _find_child(child, "BoQBody")
                    if inner is not None:
                        _walk(inner, child_chain, child_oz)
                elif tag == "Itemlist":
                    for entry in child:
                        etag = _local(entry.tag)
                        if etag == "Item":
                            _emit_item(entry, rno_chain, section_oz)
                        elif etag == "MarkupItem":
                            _emit_markup(entry, rno_chain)
                elif tag in ("Item",):
                    _emit_item(child, rno_chain, section_oz)
                elif tag == "MarkupItem":
                    _emit_markup(child, rno_chain)
                elif tag == "BoQBody":
                    _walk(child, rno_chain, section_oz)

        _walk(top_body, [], "")

        if unmapped_money:
            result.warnings.append(
                {
                    "ordinal": "",
                    "warning": (
                        f"{unmapped_money} priced position(s) carried no Qty, UP or IT and could "
                        f"not be valued - imported with zero amount."
                    ),
                }
            )

        result.metadata = {
            "sections": sections_seen,
            "da_kind": da_kind,
            "award": award_meta,
            "markup_items": markup_items,
            "derived_quantity_count": derived_qty,
            "unmapped_money_count": unmapped_money,
            # OZ-Maske level widths so downstream validation checks the OZ
            # against the file's real mask instead of a single hardcoded shape.
            "gaeb_oz_mask": oz_mask_widths,
        }
        return result
