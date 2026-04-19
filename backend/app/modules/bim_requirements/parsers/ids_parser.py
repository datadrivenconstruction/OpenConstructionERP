"""IDS XML parser -- buildingSMART Information Delivery Specification.

Parses IDS v1.0 XML files into UniversalRequirement rows.
Stdlib ``xml.etree.ElementTree`` is kept for types + tree traversal; all
untrusted-input parsing is routed through ``defusedxml`` so XXE /
billion-laughs / DTD-fetch attacks are rejected before the document
reaches the traversal code below.

Spec reference: https://github.com/buildingSMART/IDS
"""

import logging
import xml.etree.ElementTree as ET  # noqa: S405 — types + traversal only; parse calls use defusedxml
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as safe_ET

from app.modules.bim_requirements.parsers.base import (
    BaseRequirementParser,
    ParseResult,
    UniversalRequirement,
)

logger = logging.getLogger(__name__)

# IDS namespaces
_IDS_NS = "http://standards.buildingsmart.org/IDS"
_XS_NS = "http://www.w3.org/2001/XMLSchema"

_NS = {
    "ids": _IDS_NS,
    "xs": _XS_NS,
}


def _find(element: ET.Element, path: str) -> ET.Element | None:
    """Namespace-aware find helper."""
    return element.find(path, _NS)


def _findall(element: ET.Element, path: str) -> list[ET.Element]:
    """Namespace-aware findall helper."""
    return element.findall(path, _NS)


def _simple_value(element: ET.Element | None) -> str | None:
    """Extract text from a <simpleValue> child, or the element itself."""
    if element is None:
        return None
    sv = _find(element, "ids:simpleValue")
    if sv is not None and sv.text:
        return sv.text.strip()
    # Also try without namespace (some IDS files omit it)
    sv = element.find("simpleValue")
    if sv is not None and sv.text:
        return sv.text.strip()
    # Direct text content
    if element.text and element.text.strip():
        return element.text.strip()
    return None


def _parse_restriction(value_el: ET.Element | None) -> dict[str, Any]:
    """Parse xs:restriction children into constraint fields."""
    result: dict[str, Any] = {}
    if value_el is None:
        return result

    # Check for simpleValue first
    sv = _simple_value(value_el)
    if sv:
        result["value"] = sv

    # Look for xs:restriction in any namespace variant
    restriction = _find(value_el, "xs:restriction")
    if restriction is None:
        restriction = value_el.find(
            "{http://www.w3.org/2001/XMLSchema}restriction"
        )
    if restriction is None:
        # Try without namespace
        restriction = value_el.find("restriction")

    if restriction is not None:
        enums = []
        for enum_el in restriction.findall(
            f"{{{_XS_NS}}}enumeration"
        ):
            val = enum_el.get("value")
            if val:
                enums.append(val)
        # Also try without namespace
        for enum_el in restriction.findall("enumeration"):
            val = enum_el.get("value")
            if val:
                enums.append(val)
        if enums:
            result["enum"] = enums

        pattern_el = restriction.find(f"{{{_XS_NS}}}pattern")
        if pattern_el is None:
            pattern_el = restriction.find("pattern")
        if pattern_el is not None:
            result["pattern"] = pattern_el.get("value", "")

        min_el = restriction.find(f"{{{_XS_NS}}}minInclusive")
        if min_el is None:
            min_el = restriction.find("minInclusive")
        if min_el is not None:
            try:
                result["min"] = float(min_el.get("value", "0"))
            except ValueError:
                result["min"] = min_el.get("value", "")

        max_el = restriction.find(f"{{{_XS_NS}}}maxInclusive")
        if max_el is None:
            max_el = restriction.find("maxInclusive")
        if max_el is not None:
            try:
                result["max"] = float(max_el.get("value", "0"))
            except ValueError:
                result["max"] = max_el.get("value", "")

    return result


class IDSParser(BaseRequirementParser):
    """Parser for buildingSMART IDS XML files."""

    FORMAT_NAME = "IDS"
    SUPPORTED_EXTENSIONS = [".ids", ".xml"]

    def parse(self, source: Path | str | bytes) -> ParseResult:
        """Parse an IDS XML file or string into universal requirements."""
        result = ParseResult()
        result.metadata["format"] = self.FORMAT_NAME

        try:
            xml_content = self._read_source(source)
            root = safe_ET.fromstring(xml_content)
        except ET.ParseError as exc:
            result.errors.append({"row": 0, "field": "xml", "msg": f"Invalid XML: {exc}"})
            return result
        except Exception as exc:
            result.errors.append({"row": 0, "field": "file", "msg": f"Cannot read file: {exc}"})
            return result

        # Detect IDS namespace in root tag
        if _IDS_NS not in root.tag and "ids" not in root.tag.lower():
            # Try parsing anyway -- some files use default namespace
            pass

        # Extract info element metadata
        info = _find(root, "ids:info")
        if info is not None:
            title = _find(info, "ids:title")
            if title is not None and title.text:
                result.metadata["title"] = title.text.strip()

        # Find all specifications
        specs_container = _find(root, "ids:specifications")
        if specs_container is None:
            # Try without namespace
            specs_container = root.find("specifications")
        if specs_container is None:
            specs_container = root  # specs might be direct children

        specifications = _findall(specs_container, "ids:specification")
        if not specifications:
            specifications = specs_container.findall("specification")

        if not specifications:
            result.warnings.append(
                {"row": 0, "field": "specifications", "msg": "No specifications found in IDS file"}
            )
            return result

        result.metadata["specification_count"] = len(specifications)

        for spec_idx, spec in enumerate(specifications):
            try:
                self._parse_specification(spec, spec_idx, result)
            except Exception as exc:
                result.errors.append(
                    {
                        "row": spec_idx,
                        "field": "specification",
                        "msg": f"Error parsing specification {spec_idx}: {exc}",
                    }
                )

        logger.info(
            "IDS parsed: %d requirements, %d errors, %d warnings",
            len(result.requirements),
            len(result.errors),
            len(result.warnings),
        )
        return result

    def _read_source(self, source: Path | str | bytes) -> str:
        """Read source into a string for XML parsing."""
        if isinstance(source, bytes):
            return source.decode("utf-8")
        if isinstance(source, Path):
            return source.read_text(encoding="utf-8")
        return source

    def _parse_specification(
        self, spec: ET.Element, spec_idx: int, result: ParseResult
    ) -> None:
        """Parse a single <specification> into one or more UniversalRequirement rows."""
        spec_name = spec.get("name", f"Specification {spec_idx + 1}")
        ifc_version = spec.get("ifcVersion", "")
        instructions = spec.get("instructions", "")

        # Build context from specification-level attributes
        context: dict[str, Any] = {}
        if ifc_version:
            context["ifc_version"] = ifc_version
        if spec_name:
            context["use_case"] = spec_name
        if instructions:
            context["instructions"] = instructions

        # Parse applicability -> element_filter
        element_filter = self._parse_applicability(spec)

        # Parse requirements facets
        reqs_container = _find(spec, "ids:requirements")
        if reqs_container is None:
            reqs_container = spec.find("requirements")
        if reqs_container is None:
            result.warnings.append(
                {
                    "row": spec_idx,
                    "field": "requirements",
                    "msg": f"Specification '{spec_name}' has no requirements section",
                }
            )
            return

        # Process <property> facets (namespaced first, fallback to non-namespaced)
        prop_els = _findall(reqs_container, "ids:property")
        if not prop_els:
            prop_els = reqs_container.findall("property")
        for prop_el in prop_els:
            req = self._parse_property_facet(prop_el, element_filter, context)
            if req:
                result.requirements.append(req)

        # Process <attribute> facets (namespaced first, fallback to non-namespaced)
        attr_els = _findall(reqs_container, "ids:attribute")
        if not attr_els:
            attr_els = reqs_container.findall("attribute")
        for attr_el in attr_els:
            req = self._parse_attribute_facet(attr_el, element_filter, context)
            if req:
                result.requirements.append(req)

    def _parse_applicability(self, spec: ET.Element) -> dict[str, Any]:
        """Extract element_filter from the <applicability> section."""
        element_filter: dict[str, Any] = {}

        appl = _find(spec, "ids:applicability")
        if appl is None:
            appl = spec.find("applicability")
        if appl is None:
            return element_filter

        # Entity
        entity = _find(appl, "ids:entity")
        if entity is None:
            entity = appl.find("entity")
        if entity is not None:
            name_el = _find(entity, "ids:name")
            if name_el is None:
                name_el = entity.find("name")
            name_val = _simple_value(name_el)
            if name_val:
                element_filter["ifc_class"] = self._normalize_ifc_class(name_val)

            predef = _find(entity, "ids:predefinedType")
            if predef is None:
                predef = entity.find("predefinedType")
            predef_val = _simple_value(predef)
            if predef_val:
                element_filter["predefined_type"] = predef_val.upper()

        # Classification
        classif = _find(appl, "ids:classification")
        if classif is None:
            classif = appl.find("classification")
        if classif is not None:
            system_el = _find(classif, "ids:system")
            if system_el is None:
                system_el = classif.find("system")
            value_el = _find(classif, "ids:value")
            if value_el is None:
                value_el = classif.find("value")

            classif_data: dict[str, str] = {}
            sys_val = _simple_value(system_el)
            if sys_val:
                classif_data["system"] = sys_val
            val_val = _simple_value(value_el)
            if val_val:
                classif_data["value"] = val_val
            if classif_data:
                element_filter["classification"] = classif_data

        return element_filter

    def _parse_property_facet(
        self,
        prop_el: ET.Element,
        element_filter: dict[str, Any],
        context: dict[str, Any],
    ) -> UniversalRequirement | None:
        """Parse a <property> facet into a UniversalRequirement."""
        # Property set
        pset_el = _find(prop_el, "ids:propertySet")
        if pset_el is None:
            pset_el = prop_el.find("propertySet")
        property_group = _simple_value(pset_el)

        # Base name
        name_el = _find(prop_el, "ids:baseName")
        if name_el is None:
            name_el = prop_el.find("baseName")
        property_name = _simple_value(name_el)
        if not property_name:
            return None

        # Constraint definition
        constraint_def: dict[str, Any] = {}

        data_type = prop_el.get("dataType", "")
        if data_type:
            constraint_def["datatype"] = data_type.upper()

        cardinality = prop_el.get("cardinality", "")
        if cardinality:
            constraint_def["cardinality"] = self._normalize_cardinality(cardinality)

        # Value restrictions
        value_el = _find(prop_el, "ids:value")
        if value_el is None:
            value_el = prop_el.find("value")
        restriction = _parse_restriction(value_el)
        constraint_def.update(restriction)

        return UniversalRequirement(
            element_filter=dict(element_filter),
            property_group=property_group,
            property_name=property_name,
            constraint_def=constraint_def,
            context=dict(context),
        )

    def _parse_attribute_facet(
        self,
        attr_el: ET.Element,
        element_filter: dict[str, Any],
        context: dict[str, Any],
    ) -> UniversalRequirement | None:
        """Parse an <attribute> facet into a UniversalRequirement."""
        name_el = _find(attr_el, "ids:name")
        if name_el is None:
            name_el = attr_el.find("name")
        property_name = _simple_value(name_el)
        if not property_name:
            return None

        constraint_def: dict[str, Any] = {}
        cardinality = attr_el.get("cardinality", "")
        if cardinality:
            constraint_def["cardinality"] = self._normalize_cardinality(cardinality)

        value_el = _find(attr_el, "ids:value")
        if value_el is None:
            value_el = attr_el.find("value")
        restriction = _parse_restriction(value_el)
        constraint_def.update(restriction)

        return UniversalRequirement(
            element_filter=dict(element_filter),
            property_group=None,  # Attributes are direct IFC attributes
            property_name=property_name,
            constraint_def=constraint_def,
            context=dict(context),
        )
