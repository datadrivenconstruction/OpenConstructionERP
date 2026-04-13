"""BIMQ JSON parser for BIM requirements.

Parses JSON exports from the BIMQ platform (bim-q.de) into
UniversalRequirement rows.
"""

import json
import logging
from pathlib import Path
from typing import Any

from app.modules.bim_requirements.parsers.base import (
    BaseRequirementParser,
    ParseResult,
    UniversalRequirement,
)

logger = logging.getLogger(__name__)


class BIMQParser(BaseRequirementParser):
    """Parser for BIMQ JSON exports."""

    FORMAT_NAME = "BIMQ"
    SUPPORTED_EXTENSIONS = [".json"]

    def parse(self, source: Path | str | bytes) -> ParseResult:
        """Parse a BIMQ JSON file into universal requirements."""
        result = ParseResult()
        result.metadata["format"] = self.FORMAT_NAME

        try:
            data = self._read_json(source)
        except Exception as exc:
            result.errors.append(
                {"row": 0, "field": "json", "msg": f"Cannot parse JSON: {exc}"}
            )
            return result

        # Navigate BIMQ structure: concept_tree -> elements
        concept_tree = data.get("concept_tree", data)
        elements = concept_tree.get("elements", [])

        if not elements:
            result.warnings.append(
                {"row": 0, "field": "elements", "msg": "No elements found in BIMQ JSON"}
            )
            return result

        result.metadata["element_count"] = len(elements)

        for elem_idx, element in enumerate(elements):
            try:
                self._parse_element(element, elem_idx, result)
            except Exception as exc:
                result.errors.append(
                    {
                        "row": elem_idx,
                        "field": "element",
                        "msg": f"Error parsing element: {exc}",
                    }
                )

        logger.info(
            "BIMQ parsed: %d requirements from %d elements",
            len(result.requirements),
            len(elements),
        )
        return result

    def _read_json(self, source: Path | str | bytes) -> dict[str, Any]:
        """Read and parse JSON from various source types."""
        if isinstance(source, Path):
            return json.loads(source.read_text(encoding="utf-8"))
        if isinstance(source, bytes):
            return json.loads(source.decode("utf-8"))
        return json.loads(source)

    def _parse_element(
        self, element: dict[str, Any], elem_idx: int, result: ParseResult
    ) -> None:
        """Parse a single BIMQ element with its property groups."""
        ifc_class_raw = element.get("ifc_class", "")
        element_name = element.get("name", "")

        element_filter: dict[str, Any] = {}
        if ifc_class_raw:
            element_filter["ifc_class"] = self._normalize_ifc_class(ifc_class_raw)
        if element_name and not ifc_class_raw:
            element_filter["name"] = element_name

        property_groups = element.get("property_groups", [])
        for pg in property_groups:
            pg_name = pg.get("name", "")
            properties = pg.get("properties", [])

            for prop in properties:
                prop_name = prop.get("code") or prop.get("name", "")
                if not prop_name:
                    continue

                constraint_def: dict[str, Any] = {}
                datatype = prop.get("datatype", "")
                if datatype:
                    dt_upper = datatype.upper()
                    if not dt_upper.startswith("IFC"):
                        dt_upper = f"IFC{dt_upper}"
                    constraint_def["datatype"] = dt_upper

                allowed_values = prop.get("allowed_values", [])
                if allowed_values:
                    constraint_def["enum"] = allowed_values

                unit = prop.get("unit")
                if unit:
                    constraint_def["unit"] = unit

                constraint_def["cardinality"] = "required"

                context: dict[str, Any] = {}
                actors = prop.get("actors", [])
                if actors:
                    context["actor"] = ", ".join(actors)
                phases = prop.get("phases", [])
                if phases:
                    context["phase"] = ", ".join(phases)
                use_cases = prop.get("use_cases", [])
                if use_cases:
                    context["use_case"] = ", ".join(use_cases)

                result.requirements.append(
                    UniversalRequirement(
                        element_filter=dict(element_filter),
                        property_group=pg_name or None,
                        property_name=prop_name,
                        constraint_def=constraint_def,
                        context=context if context else None,
                    )
                )
