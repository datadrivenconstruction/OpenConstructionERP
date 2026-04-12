"""IDS XML exporter -- produces valid buildingSMART IDS v1.0 XML.

Groups requirements by element_filter + context into specifications,
then writes each requirement as a <property> or <attribute> facet.
"""

import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any

from app.modules.bim_requirements.parsers.base import UniversalRequirement

logger = logging.getLogger(__name__)

_IDS_NS = "http://standards.buildingsmart.org/IDS"
_XS_NS = "http://www.w3.org/2001/XMLSchema"


def _make_simple_value(parent: ET.Element, tag: str, value: str) -> ET.Element:
    """Create a child element with a <simpleValue> text child."""
    el = ET.SubElement(parent, tag)
    sv = ET.SubElement(el, "simpleValue")
    sv.text = value
    return el


def _add_restriction(value_el: ET.Element, constraint: dict[str, Any]) -> None:
    """Add xs:restriction children to a <value> element."""
    restriction = ET.SubElement(value_el, f"{{{_XS_NS}}}restriction")

    if "enum" in constraint:
        for enum_val in constraint["enum"]:
            enum_el = ET.SubElement(restriction, f"{{{_XS_NS}}}enumeration")
            enum_el.set("value", str(enum_val))

    if "pattern" in constraint:
        pattern_el = ET.SubElement(restriction, f"{{{_XS_NS}}}pattern")
        pattern_el.set("value", constraint["pattern"])

    if "min" in constraint:
        min_el = ET.SubElement(restriction, f"{{{_XS_NS}}}minInclusive")
        min_el.set("value", str(constraint["min"]))

    if "max" in constraint:
        max_el = ET.SubElement(restriction, f"{{{_XS_NS}}}maxInclusive")
        max_el.set("value", str(constraint["max"]))


def _grouping_key(req: UniversalRequirement) -> str:
    """Build a grouping key from element_filter + context for specification grouping."""
    ef = req.element_filter or {}
    ctx = req.context or {}
    parts = [
        ef.get("ifc_class", ""),
        ef.get("predefined_type", ""),
        str(ef.get("classification", "")),
        ctx.get("ifc_version", ""),
        ctx.get("use_case", ""),
    ]
    return "|".join(parts)


def export_ids_xml(
    requirements: list[UniversalRequirement],
    title: str = "BIM Requirements",
    ifc_version: str = "IFC4",
) -> str:
    """Export a list of UniversalRequirement to IDS XML string.

    Args:
        requirements: List of universal requirements to export.
        title: Title for the IDS document info section.
        ifc_version: Default IFC version if not specified in context.

    Returns:
        XML string of the IDS document.
    """
    # Register namespaces for clean output
    ET.register_namespace("ids", _IDS_NS)
    ET.register_namespace("xs", _XS_NS)

    root = ET.Element(f"{{{_IDS_NS}}}ids")

    # Info section
    info = ET.SubElement(root, f"{{{_IDS_NS}}}info")
    title_el = ET.SubElement(info, f"{{{_IDS_NS}}}title")
    title_el.text = title

    # Group requirements by element_filter + context
    groups: dict[str, list[UniversalRequirement]] = defaultdict(list)
    for req in requirements:
        key = _grouping_key(req)
        groups[key].append(req)

    # Specifications container
    specs = ET.SubElement(root, f"{{{_IDS_NS}}}specifications")

    for group_key, group_reqs in groups.items():
        # Use context from first requirement for specification attributes
        first = group_reqs[0]
        ctx = first.context or {}
        ef = first.element_filter or {}

        spec = ET.SubElement(specs, f"{{{_IDS_NS}}}specification")
        spec_name = ctx.get("use_case", "Requirements")
        spec.set("name", spec_name)
        spec.set("ifcVersion", ctx.get("ifc_version", ifc_version))
        if ctx.get("instructions"):
            spec.set("instructions", ctx["instructions"])

        # Applicability
        applicability = ET.SubElement(spec, f"{{{_IDS_NS}}}applicability")
        ifc_class = ef.get("ifc_class")
        if ifc_class:
            entity = ET.SubElement(applicability, f"{{{_IDS_NS}}}entity")
            _make_simple_value(entity, f"{{{_IDS_NS}}}name", ifc_class)
            predef = ef.get("predefined_type")
            if predef:
                _make_simple_value(entity, f"{{{_IDS_NS}}}predefinedType", predef)

        classif = ef.get("classification")
        if isinstance(classif, dict):
            classif_el = ET.SubElement(applicability, f"{{{_IDS_NS}}}classification")
            if "system" in classif:
                _make_simple_value(classif_el, f"{{{_IDS_NS}}}system", classif["system"])
            if "value" in classif:
                _make_simple_value(classif_el, f"{{{_IDS_NS}}}value", classif["value"])

        # Requirements
        reqs_el = ET.SubElement(spec, f"{{{_IDS_NS}}}requirements")
        for req in group_reqs:
            if req.property_group is not None:
                _add_property_facet(reqs_el, req)
            else:
                _add_attribute_facet(reqs_el, req)

    # Serialize to string
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    import io

    buf = io.StringIO()
    tree.write(buf, encoding="unicode", xml_declaration=True)
    return buf.getvalue()


def _add_property_facet(parent: ET.Element, req: UniversalRequirement) -> None:
    """Add a <property> facet element."""
    cd = req.constraint_def or {}
    prop = ET.SubElement(parent, f"{{{_IDS_NS}}}property")

    if cd.get("datatype"):
        prop.set("dataType", cd["datatype"])
    if cd.get("cardinality"):
        prop.set("cardinality", cd["cardinality"])

    # PropertySet
    if req.property_group:
        _make_simple_value(prop, f"{{{_IDS_NS}}}propertySet", req.property_group)

    # BaseName
    _make_simple_value(prop, f"{{{_IDS_NS}}}baseName", req.property_name)

    # Value with restrictions
    has_value_constraint = any(
        k in cd for k in ("value", "enum", "pattern", "min", "max")
    )
    if has_value_constraint:
        value_el = ET.SubElement(prop, f"{{{_IDS_NS}}}value")
        if "value" in cd and "enum" not in cd and "pattern" not in cd:
            sv = ET.SubElement(value_el, "simpleValue")
            sv.text = str(cd["value"])
        if any(k in cd for k in ("enum", "pattern", "min", "max")):
            _add_restriction(value_el, cd)


def _add_attribute_facet(parent: ET.Element, req: UniversalRequirement) -> None:
    """Add an <attribute> facet element."""
    cd = req.constraint_def or {}
    attr = ET.SubElement(parent, f"{{{_IDS_NS}}}attribute")

    if cd.get("cardinality"):
        attr.set("cardinality", cd["cardinality"])

    _make_simple_value(attr, f"{{{_IDS_NS}}}name", req.property_name)

    has_value_constraint = any(
        k in cd for k in ("value", "enum", "pattern", "min", "max")
    )
    if has_value_constraint:
        value_el = ET.SubElement(attr, f"{{{_IDS_NS}}}value")
        if "value" in cd and "enum" not in cd and "pattern" not in cd:
            sv = ET.SubElement(value_el, "simpleValue")
            sv.text = str(cd["value"])
        if any(k in cd for k in ("enum", "pattern", "min", "max")):
            _add_restriction(value_el, cd)
