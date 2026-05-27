"""‌⁠‍Generic Excel/CSV parser for BIM requirements.

Handles arbitrary spreadsheets by auto-detecting column roles via synonym
matching. No AI mapping in this implementation -- pure heuristic approach.
"""

import csv
import io
import logging
import re
from pathlib import Path
from typing import Any

from app.modules.bim_requirements.parsers.base import (
    BaseRequirementParser,
    ParseResult,
    UniversalRequirement,
)

logger = logging.getLogger(__name__)

# Column synonym map: universal column -> list of synonyms (lowercase)
COLUMN_SYNONYMS: dict[str, list[str]] = {
    "element_filter": [
        "element",
        "bauteil",
        "ifc class",
        "ifc entity",
        "ifc-klasse",
        "object type",
        "element type",
        "category",
        "kategorie",
        "uniclass",
        "omniclass",
        "assembly code",
        "type name",
        "ifc_class",
        "ifcclass",
        "entity",
    ],
    "property_group": [
        "property set",
        "pset",
        "propertyset",
        "merkmalsgruppe",
        "attribute group",
        "group",
        "gruppe",
        "namespace",
        "property_group",
        "propertygroup",
    ],
    "property_name": [
        "property",
        "attribute",
        "parameter",
        "merkmal",
        "attribut",
        "field",
        "feld",
        "name",
        "property name",
        "attribute name",
        "property_name",
        "propertyname",
    ],
    "constraint": [
        "value",
        "values",
        "allowed values",
        "constraint",
        "restriction",
        "wert",
        "wertebereich",
        "data type",
        "datentyp",
        "type",
        "format",
        "unit",
        "einheit",
        "range",
        "constraint_def",
    ],
    "context": [
        "phase",
        "stage",
        "milestone",
        "leistungsphase",
        "lph",
        "actor",
        "responsible",
        "akteur",
        "verantwortlich",
        "use case",
        "anwendungsfall",
        "purpose",
        "zweck",
        "lod",
        "loi",
        "level of detail",
    ],
    "cardinality": [
        "required",
        "mandatory",
        "pflicht",
        "cardinality",
        "obligation",
        "erforderlich",
    ],
    "unit": [
        "unit",
        "einheit",
        "uom",
        "unit of measure",
    ],
    "datatype": [
        "data type",
        "datatype",
        "datentyp",
        "ifc data type",
    ],
}

# IFC datatype normalization
_DATATYPE_MAP: dict[str, str] = {
    "text": "IFCTEXT",
    "string": "IFCTEXT",
    "label": "IFCLABEL",
    "real": "IFCREAL",
    "number": "IFCREAL",
    "integer": "IFCINTEGER",
    "boolean": "IFCBOOLEAN",
    "yes/no": "IFCBOOLEAN",
    "length": "IFCLENGTHMEASURE",
    "area": "IFCAREAMEASURE",
    "volume": "IFCVOLUMEMEASURE",
}


def _normalize_datatype(raw: str) -> str:
    """‌⁠‍Normalize a raw datatype string to IFC datatype."""
    clean = raw.strip().lower()
    if clean in _DATATYPE_MAP:
        return _DATATYPE_MAP[clean]
    if clean.upper().startswith("IFC"):
        return clean.upper()
    return raw.strip()


# A locale-tolerant numeric literal: optional sign, digits, with either a
# ``.`` or ``,`` decimal separator (German/EU spreadsheets use the comma).
# Thousands grouping is deliberately NOT accepted so a real enum like
# "A,B" is never mistaken for a number.
_NUM = r"[+-]?\d+(?:[.,]\d+)?"


def _to_float(token: str) -> float | None:
    """Parse a single numeric token tolerant of a comma decimal separator.

    ``"0,24"`` -> ``0.24``; ``"2.5"`` -> ``2.5``. A grouped token (more than
    one separator, e.g. ``"1.234,56"``) is refused rather than mis-scaled.
    """
    t = token.strip()
    if not t:
        return None
    if t.count(".") + t.count(",") > 1:
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def _parse_constraint_value(raw: str) -> dict[str, Any]:
    """‌⁠‍Parse a constraint value string into structured constraint_def fields.

    Handles patterns like:
        "REI60; REI90; REI120"   -> enum
        ">= 2.5 m" / ">= 0,24 m"  -> min + unit  (comma decimals supported)
        "0.1 - 1.0" / "0,1 - 1,0" -> min + max (range)
        "TEXT" / "STRING"        -> datatype
        "^[A-Z]{2}"             -> pattern (regex)
        "required" / "Pflicht"   -> cardinality

    Number parsing is locale-tolerant: a German decimal comma must NOT be
    treated as an enum separator (E-I18N-005). Numeric forms (range /
    comparison) are matched *before* the comma-enum fallback.
    """
    result: dict[str, Any] = {}
    text = raw.strip()
    if not text:
        return result

    # Semicolons are an unambiguous enum separator -- check first.
    if ";" in text:
        enums = [v.strip() for v in text.split(";") if v.strip()]
        if len(enums) > 1:
            result["enum"] = enums
            return result

    # Range pattern: "0.1 - 1.0", "0,1 - 1,0", "0.1-1.0" (comma decimals OK).
    # Matched BEFORE the comma-enum fallback so a German range is not split
    # into a garbage enumeration (E-I18N-005).
    range_match = re.match(rf"^({_NUM})\s*[-–]\s*({_NUM})$", text)
    if range_match:
        lo = _to_float(range_match.group(1))
        hi = _to_float(range_match.group(2))
        if lo is not None and hi is not None:
            result["min"] = lo
            result["max"] = hi
            return result

    # Comparison: ">= 2.5 m", ">= 0,24 m", "<= 100" (comma decimals OK).
    comp_match = re.match(rf"^([<>]=?)\s*({_NUM})\s*(.*)$", text)
    if comp_match:
        op = comp_match.group(1)
        val = _to_float(comp_match.group(2))
        if val is not None:
            unit = comp_match.group(3).strip()
            if ">=" in op or ">" in op:
                result["min"] = val
            else:
                result["max"] = val
            if unit:
                result["unit"] = unit
            return result

    # Comma-separated enum fallback -- only reached when the value is NOT a
    # numeric range/comparison. Guard against splitting a lone comma-decimal
    # scalar ("0,24") into bogus enum members (E-I18N-005).
    if "," in text:
        parts = [v.strip() for v in text.split(",") if v.strip()]
        if len(parts) > 1 and not all(_to_float(p) is not None for p in parts):
            result["enum"] = parts
            return result
        single = _to_float(text)
        if single is not None:
            result["value"] = single
            return result

    # Check for regex pattern
    if text.startswith("^") or text.startswith("(?"):
        result["pattern"] = text
        return result

    # Check for datatype keywords
    lower = text.lower()
    if lower in _DATATYPE_MAP:
        result["datatype"] = _DATATYPE_MAP[lower]
        return result

    # Check for cardinality keywords
    cardinality_map = {
        "required": "required",
        "mandatory": "required",
        "pflicht": "required",
        "optional": "optional",
        "prohibited": "prohibited",
    }
    if lower in cardinality_map:
        result["cardinality"] = cardinality_map[lower]
        return result

    # Default: treat as a simple value
    result["value"] = text
    return result


class ExcelCSVParser(BaseRequirementParser):
    """Parser for generic Excel (.xlsx) and CSV files."""

    FORMAT_NAME = "Excel"
    SUPPORTED_EXTENSIONS = [".xlsx", ".xls", ".csv"]

    def parse(self, source: Path | str | bytes) -> ParseResult:
        """Parse an Excel or CSV file into universal requirements."""
        result = ParseResult()
        result.metadata["format"] = self.FORMAT_NAME

        try:
            if isinstance(source, Path):
                if source.suffix.lower() == ".csv":
                    rows = self._read_csv_file(source)
                else:
                    rows = self._read_excel_file(source)
            elif isinstance(source, (str, bytes)):
                rows = self._read_csv_string(source)
            else:
                result.errors.append({"row": 0, "field": "source", "msg": "Unsupported source type"})
                return result
        except Exception as exc:
            result.errors.append({"row": 0, "field": "file", "msg": f"Cannot read file: {exc}"})
            return result

        if not rows:
            result.errors.append({"row": 0, "field": "data", "msg": "File is empty"})
            return result

        # First row is headers
        headers = [str(h).strip() for h in rows[0]]
        data_rows = rows[1:]

        if not data_rows:
            result.warnings.append({"row": 0, "field": "data", "msg": "File has headers but no data rows"})
            return result

        # Auto-map columns
        col_mapping = self._auto_map_columns(headers)
        result.metadata["column_mapping"] = col_mapping
        result.metadata["headers"] = headers
        result.metadata["row_count"] = len(data_rows)

        # Check minimum required mappings
        if "property_name" not in col_mapping.values():
            # Try to find any column that could be property_name
            result.warnings.append(
                {
                    "row": 0,
                    "field": "mapping",
                    "msg": "Could not detect a 'property_name' column; using first unmapped column",
                }
            )

        # Parse each row
        for row_idx, row in enumerate(data_rows, start=2):
            try:
                req = self._parse_row(row, headers, col_mapping, row_idx)
                if req:
                    result.requirements.append(req)
            except Exception as exc:
                result.errors.append({"row": row_idx, "field": "", "msg": f"Error parsing row: {exc}"})

        logger.info(
            "Excel/CSV parsed: %d requirements from %d rows, %d errors",
            len(result.requirements),
            len(data_rows),
            len(result.errors),
        )
        return result

    def _read_excel_file(self, path: Path) -> list[list[Any]]:
        """Read an Excel file using openpyxl."""
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            return []
        rows: list[list[Any]] = []
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
        wb.close()
        return rows

    # Candidate field delimiters, in priority order. Comma is the default
    # (US/UK Excel and the historical behaviour); semicolon is the default
    # for German/French Excel "Save as CSV"; pipe and tab are common in
    # data-exchange exports. Hard-coding the comma collapsed those files
    # into a single column with ZERO rows and no error (E-I18N-006).
    _CSV_DELIMITERS = (",", ";", "|", "\t")

    @classmethod
    def _sniff_delimiter(cls, text: str) -> str:
        """Pick the delimiter that best splits the header/first data rows.

        Deterministic (``csv.Sniffer`` is unreliable on short inputs): for
        each candidate, parse the first few non-empty lines and score it by
        how many columns it yields consistently. The comma wins ties so
        single-column / already-comma files behave exactly as before.
        """
        sample_lines = [ln for ln in text.splitlines() if ln.strip()][:10]
        if not sample_lines:
            return ","

        best_delim = ","
        best_score = -1.0
        for delim in cls._CSV_DELIMITERS:
            try:
                rows = list(csv.reader(io.StringIO("\n".join(sample_lines)), delimiter=delim))
            except csv.Error:
                continue
            rows = [r for r in rows if r]
            if not rows:
                continue
            col_counts = [len(r) for r in rows]
            max_cols = max(col_counts)
            if max_cols < 2:
                continue  # this delimiter does not split the data at all
            # Reward many columns + consistent column count across rows.
            consistent = sum(1 for c in col_counts if c == max_cols) / len(col_counts)
            score = max_cols + consistent
            if score > best_score:
                best_score = score
                best_delim = delim
        return best_delim

    def _read_csv_file(self, path: Path) -> list[list[Any]]:
        """Read a CSV file with encoding + delimiter detection."""
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(path, encoding=encoding, newline="") as f:
                    text = f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
            delim = self._sniff_delimiter(text)
            return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delim)]
        return []

    def _read_csv_string(self, source: str | bytes) -> list[list[Any]]:
        """Read CSV from a string or bytes (delimiter auto-detected)."""
        text = source.decode("utf-8") if isinstance(source, bytes) else source
        delim = self._sniff_delimiter(text)
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        return [list(row) for row in reader]

    def _auto_map_columns(self, headers: list[str]) -> dict[int, str]:
        """Map column indices to universal column names via synonym matching.

        Returns:
            Dict mapping column index -> universal column name.
        """
        mapping: dict[int, str] = {}
        used_universals: set[str] = set()

        for col_idx, header in enumerate(headers):
            header_lower = header.lower().strip()
            if not header_lower:
                continue

            best_match: str | None = None
            best_score = 0

            for universal, synonyms in COLUMN_SYNONYMS.items():
                if universal in used_universals:
                    # Allow multiple context/constraint columns
                    if universal not in ("context", "constraint", "unit", "datatype", "cardinality"):
                        continue

                for synonym in synonyms:
                    # Exact match
                    if header_lower == synonym:
                        score = 100
                    # Header contains synonym
                    elif synonym in header_lower:
                        score = 80
                    # Synonym contains header
                    elif header_lower in synonym:
                        score = 60
                    else:
                        continue

                    if score > best_score:
                        best_score = score
                        best_match = universal

            if best_match and best_score >= 60:
                mapping[col_idx] = best_match
                used_universals.add(best_match)

        return mapping

    def _parse_row(
        self,
        row: list[Any],
        headers: list[str],
        col_mapping: dict[int, str],
        row_idx: int,
    ) -> UniversalRequirement | None:
        """Parse a single data row into a UniversalRequirement."""
        # Collect values by universal column
        values: dict[str, list[str]] = {}
        for col_idx, universal in col_mapping.items():
            if col_idx < len(row) and row[col_idx] is not None:
                val = str(row[col_idx]).strip()
                if val:
                    values.setdefault(universal, []).append(val)

        # We need at least a property_name
        property_name = ""
        if "property_name" in values:
            property_name = values["property_name"][0]
        if not property_name:
            # Skip empty rows silently
            return None

        # Build element_filter
        element_filter: dict[str, Any] = {}
        if "element_filter" in values:
            ef_raw = values["element_filter"][0]
            if ef_raw.upper().startswith("IFC"):
                element_filter["ifc_class"] = self._normalize_ifc_class(ef_raw)
            else:
                element_filter["ifc_class"] = ef_raw

        # Property group
        property_group = values.get("property_group", [None])[0]

        # Build constraint_def
        constraint_def: dict[str, Any] = {}
        if "constraint" in values:
            for cv in values["constraint"]:
                constraint_def.update(_parse_constraint_value(cv))
        if "cardinality" in values:
            constraint_def["cardinality"] = self._normalize_cardinality(values["cardinality"][0])
        if "datatype" in values:
            constraint_def["datatype"] = _normalize_datatype(values["datatype"][0])
        if "unit" in values:
            constraint_def["unit"] = values["unit"][0]

        # Build context
        context: dict[str, Any] = {}
        if "context" in values:
            # For context, try to detect sub-fields
            for cv in values["context"]:
                context["value"] = cv

        return UniversalRequirement(
            element_filter=element_filter,
            property_group=property_group,
            property_name=property_name,
            constraint_def=constraint_def,
            context=context if context else None,
        )
