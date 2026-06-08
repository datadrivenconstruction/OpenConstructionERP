"""GAEB DA XML 3.3 importer (DACH).

Native parser for the German/Austrian/Swiss tender exchange format:

* **X81 / DP 81** - Leistungsverzeichnis (BOQ skeleton)
* **X83 / DP 83** - Angebotsabgabe (bid submission)
* **X84 / DP 84** - Nebenangebote (alternative bids)
* **X86 / DP 86** - Auftragserteilung (order award) - Epic I11.

Namespace-agnostic: matches by tag local-name so files from any
mainstream GAEB authoring tool import without pre-normalisation.

Security: parses via ``defusedxml`` - XXE, billion-laughs and DTD-based
attacks are rejected up-front.

Epic I12 adds preservation of GAEB ``<DescrTxc>`` (or ``DescriptTxc``,
toolchain-dependent) rich-text blocks under
``metadata["descr_txc"]`` so the editor can re-render the original
formatting on export. The plain-text fallback used for the BOQ row's
``description`` is unchanged.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, ClassVar

from app.modules.boq.importers._base import (
    ImportedBOQ,
    ImportedPosition,
    ImporterParseError,
)
from app.modules.boq.importers._encoding import safe_float

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


def _extract_descr_txc(item: ET.Element) -> dict[str, Any] | None:
    """Capture the GAEB rich-text ``<DescrTxc>`` / ``<DescriptTxc>`` block.

    Epic I12: GAEB lets exporters attach a structured rich-text block -
    typically nested ``<p>`` / ``<span>`` elements with formatting hints.
    We preserve it as a serialised XML snippet so the editor can
    re-render the original layout on export. Returns ``None`` if no
    rich-text block is present.

    Format: ``{"raw_xml": "<DescrTxc>…</DescrTxc>", "plain_text": "…"}``
    - both views are useful (raw XML for round-trip, plain text for the
    editor's preview pane).
    """
    for name in ("DescrTxc", "DescriptTxc", "OutlineTxc"):
        node = _find_child(item, name)
        if node is None:
            # Could be nested under <Description>.
            desc = _find_child(item, "Description")
            if desc is not None:
                node = _find_child(desc, name)
        if node is not None:
            try:
                raw_xml = ET.tostring(node, encoding="unicode")
            except Exception:  # noqa: BLE001 - best-effort capture
                raw_xml = ""
            # Concatenate all text content from the rich-text block.
            plain_text = "".join(node.itertext()).strip()
            return {"raw_xml": raw_xml, "plain_text": plain_text}
    return None


def _extract_description(item: ET.Element) -> str:
    """Pull a human-readable single-line description.

    Falls back through GAEB's nested ``Description / CompleteText /
    DetailTxt / Text`` shapes. Always returns a plain string - the
    rich-text view lives in ``metadata["descr_txc"]``.
    """
    # Prefer the first non-empty <Text> anywhere in the item subtree.
    for text_el in _find_all_descendants(item, "Text"):
        if text_el.text and text_el.text.strip():
            return text_el.text.strip()
    # Fall back to OutlineText / Outline / LblTx (GAEB short labels).
    for name in ("OutlineText", "OutlTxt", "LblTx"):
        val = _text_of(item, name)
        if val:
            return val
    # Last resort: itertext() the entire item subtree (lossy but better
    # than dropping the row silently).
    return "".join(item.itertext()).strip()[:500]


def _detect_da_kind(root: ET.Element) -> str:
    """Return ``"x81" | "x83" | "x84" | "x86" | "x"`` (unknown DA).

    GAEB DA files carry a top-level ``<GAEB><GAEBInfo><DPType>83</DPType></GAEBInfo>``
    style header. We probe a few common shapes - some integrated 5D
    estimating suites put the DP number on the ``<Award>`` element instead.
    """
    for el in root.iter():
        tag = _local(el.tag)
        if tag in ("DPType", "DP", "DPNr"):
            text = (el.text or "").strip().lower()
            if text in ("81", "x81"):
                return "x81"
            if text in ("83", "x83"):
                return "x83"
            if text in ("84", "x84"):
                return "x84"
            if text in ("86", "x86"):
                return "x86"
    # Award/X86 fallback: if the root contains ``<Award>`` with an
    # explicit award type or order reference, treat as X86.
    award = None
    for el in root.iter():
        if _local(el.tag) == "Award":
            award = el
            break
    if award is not None:
        # GAEB X86 typically carries <OrderNo>, <ContractCondition>,
        # or a <DateOfOffer> alongside <DateOfContract>.
        for child in award:
            tag = _local(child.tag)
            if tag in ("OrderNo", "DateOfContract", "ContractNo"):
                return "x86"
    return "x"


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
        # For generic .xml uploads, sniff the first 2 KB for the GAEB root.
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
        # defusedxml import is deferred so importer module can be loaded
        # in environments without the dep (unit tests of the registry).
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

        # Locate the top-level <BoQBody> - directly inside <BoQ>. A GAEB
        # tree nests BoQBody recursively under each BoQCtgy, so iterating
        # all descendants would double-visit every Item.
        top_body: ET.Element | None = None
        for el in root.iter():
            if _local(el.tag) == "BoQ":
                top_body = _find_child(el, "BoQBody")
                if top_body is not None:
                    break
        if top_body is None:
            raise ImporterParseError("No <BoQBody> element found. Is this a valid GAEB DA XML?")

        # Capture currency from <Award><Cur> for round-trip metadata.
        award: ET.Element | None = None
        for el in root.iter():
            if _local(el.tag) == "Award":
                award = el
                break
        currency = (_text_of(award, "Cur") if award is not None else "") or ""

        # Capture X86-specific award metadata (Epic I11) so the route can
        # surface "this is an order award" in the UI / response.
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

        # Collect every Item anywhere in the BoQBody subtree, attribute
        # each to the nearest ancestor BoQCtgy's ID for the section ordinal.
        def _ancestor_ctgy_id(ancestors: list[ET.Element]) -> str:
            for anc in reversed(ancestors):
                if _local(anc.tag) == "BoQCtgy":
                    return (anc.get("ID") or "").strip()
            return ""

        def _walk_and_collect(el: ET.Element, ancestors: list[ET.Element]) -> list[tuple[ET.Element, str]]:
            found: list[tuple[ET.Element, str]] = []
            for child in el:
                if _local(child.tag) == "Item":
                    found.append((child, _ancestor_ctgy_id(ancestors + [el])))
                else:
                    found.extend(_walk_and_collect(child, ancestors + [el]))
            return found

        collected = _walk_and_collect(top_body, [])

        # Collect section labels for the response summary.
        sections_seen: list[dict[str, str]] = []
        for ctgy in _find_all_descendants(top_body, "BoQCtgy"):
            ord_ = (ctgy.get("ID") or "").strip()
            label = _text_of(ctgy, "LblTx") or "Section"
            sections_seen.append({"ordinal": ord_, "label": label})

        result = ImportedBOQ(source_format="gaeb", currency=currency)
        auto_counter = 0
        for item, section_ordinal in collected:
            auto_counter += 1
            pos_ordinal = (item.get("ID") or "").strip() or str(auto_counter)
            description = _extract_description(item)
            if not description:
                result.skipped += 1
                continue

            unit_raw = _text_of(item, "QU")
            unit = _normalize_unit(unit_raw) or "pcs"
            quantity = safe_float(_text_of(item, "Qty"), default=0.0)
            unit_rate = safe_float(_text_of(item, "UP"), default=0.0)

            # Sanity caps - same bounds as the legacy inline parser.
            if not (0 <= quantity <= 1e9):
                result.errors.append({"ordinal": pos_ordinal, "error": f"Quantity out of range: {quantity}"})
                continue
            if not (0 <= unit_rate <= 1e8):
                result.errors.append({"ordinal": pos_ordinal, "error": f"Unit rate out of range: {unit_rate}"})
                continue

            classification: dict[str, Any] = {}
            if section_ordinal:
                classification["gaeb_section"] = section_ordinal

            metadata: dict[str, Any] = {
                "gaeb_ordinal": pos_ordinal,
                "gaeb_section": section_ordinal,
                "gaeb_unit_original": unit_raw,
                "gaeb_currency": currency,
                "gaeb_da_kind": da_kind,
            }
            # Epic I12: preserve rich-text DescrTxc verbatim.
            descr_txc = _extract_descr_txc(item)
            if descr_txc is not None:
                metadata["descr_txc"] = descr_txc

            result.positions.append(
                ImportedPosition(
                    description=description,
                    ordinal=pos_ordinal,
                    unit=unit,
                    quantity=quantity,
                    unit_rate=unit_rate,
                    classification=classification,
                    source="gaeb_import",
                    metadata=metadata,
                )
            )

        result.metadata = {
            "sections": sections_seen,
            "da_kind": da_kind,
            "award": award_meta,
        }
        return result
