"""Revit Shared Parameters (.txt) parser.

Parses the TAB-delimited Revit shared parameter file format into
UniversalRequirement rows.
"""

import logging
from pathlib import Path
from typing import Any

from app.modules.bim_requirements.parsers.base import (
    BaseRequirementParser,
    ParseResult,
    UniversalRequirement,
)

logger = logging.getLogger(__name__)

# Revit datatype -> IFC datatype mapping
_REVIT_DATATYPE_MAP: dict[str, str] = {
    "TEXT": "IFCTEXT",
    "INTEGER": "IFCINTEGER",
    "NUMBER": "IFCREAL",
    "LENGTH": "IFCLENGTHMEASURE",
    "AREA": "IFCAREAMEASURE",
    "VOLUME": "IFCVOLUMEMEASURE",
    "ANGLE": "IFCPLANEANGLEMEASURE",
    "URL": "IFCTEXT",
    "MATERIAL": "IFCLABEL",
    "YESNO": "IFCBOOLEAN",
    "YES/NO": "IFCBOOLEAN",
    "FORCE": "IFCFORCEMEASURE",
    "CURRENCY": "IFCMONETARYMEASURE",
}


class RevitSPParser(BaseRequirementParser):
    """Parser for Revit Shared Parameters .txt files."""

    FORMAT_NAME = "RevitSP"
    SUPPORTED_EXTENSIONS = [".txt"]

    def parse(self, source: Path | str | bytes) -> ParseResult:
        """Parse a Revit Shared Parameters file."""
        result = ParseResult()
        result.metadata["format"] = self.FORMAT_NAME

        try:
            text = self._read_source(source)
        except Exception as exc:
            result.errors.append(
                {"row": 0, "field": "file", "msg": f"Cannot read file: {exc}"}
            )
            return result

        lines = text.splitlines()
        groups: dict[int, str] = {}
        params: list[dict[str, Any]] = []

        for line_num, line in enumerate(lines, start=1):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("*"):
                continue

            parts = line.split("\t")
            if not parts:
                continue

            record_type = parts[0].strip()

            if record_type == "GROUP" and len(parts) >= 3:
                try:
                    group_id = int(parts[1].strip())
                    group_name = parts[2].strip()
                    groups[group_id] = group_name
                except (ValueError, IndexError):
                    result.warnings.append(
                        {"row": line_num, "field": "GROUP", "msg": f"Invalid GROUP line: {line}"}
                    )

            elif record_type == "PARAM" and len(parts) >= 6:
                try:
                    param = {
                        "guid": parts[1].strip().strip("{}"),
                        "name": parts[2].strip(),
                        "datatype": parts[3].strip(),
                        "datacategory": parts[4].strip() if len(parts) > 4 else "",
                        "group_id": int(parts[5].strip()) if len(parts) > 5 and parts[5].strip() else 0,
                        "visible": parts[6].strip() if len(parts) > 6 else "1",
                        "description": parts[7].strip() if len(parts) > 7 else "",
                        "usermodifiable": parts[8].strip() if len(parts) > 8 else "1",
                        "line_num": line_num,
                    }
                    params.append(param)
                except (ValueError, IndexError) as exc:
                    result.warnings.append(
                        {"row": line_num, "field": "PARAM", "msg": f"Invalid PARAM line: {exc}"}
                    )

            elif record_type == "META":
                # Store metadata version
                if len(parts) >= 2:
                    result.metadata["version"] = parts[1].strip()

        # Convert params to UniversalRequirement
        for param in params:
            group_name = groups.get(param["group_id"], "")
            ifc_datatype = _REVIT_DATATYPE_MAP.get(
                param["datatype"].upper(), param["datatype"]
            )

            constraint_def: dict[str, Any] = {
                "datatype": ifc_datatype,
                "cardinality": "optional",  # Revit SP doesn't specify cardinality
            }

            context: dict[str, Any] = {}
            if param["guid"]:
                context["guid"] = param["guid"]
            if param["description"]:
                context["description"] = param["description"]

            result.requirements.append(
                UniversalRequirement(
                    element_filter={},  # Revit SP has no element binding
                    property_group=group_name or None,
                    property_name=param["name"],
                    constraint_def=constraint_def,
                    context=context if context else None,
                )
            )

        result.metadata["group_count"] = len(groups)
        result.metadata["param_count"] = len(params)

        logger.info(
            "Revit SP parsed: %d parameters in %d groups",
            len(params),
            len(groups),
        )
        return result

    def _read_source(self, source: Path | str | bytes) -> str:
        """Read source into a string."""
        if isinstance(source, bytes):
            return source.decode("utf-8")
        if isinstance(source, Path):
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                try:
                    return source.read_text(encoding=encoding)
                except UnicodeDecodeError:
                    continue
            return source.read_text(encoding="latin-1", errors="replace")
        return source
