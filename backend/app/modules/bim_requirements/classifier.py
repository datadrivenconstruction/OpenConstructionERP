"""Format classifier for BIM requirement files.

Auto-detects the file format from extension and content sniffing.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class FormatClassifier:
    """Automatically detect the format of a BIM requirements file."""

    def classify(self, file_path: Path) -> str:
        """Classify the file format.

        Args:
            file_path: Path to the file to classify.

        Returns:
            Format string: 'IDS', 'COBie', 'BIMQ', 'Excel', 'RevitSP', 'PlainText',
            'GenericXML', or raises ValueError for unsupported formats.
        """
        ext = file_path.suffix.lower()

        if ext in (".ids", ".xml"):
            return self._classify_xml(file_path)
        elif ext in (".xlsx", ".xls"):
            return self._classify_excel(file_path)
        elif ext == ".csv":
            return "Excel"
        elif ext == ".txt":
            return self._classify_txt(file_path)
        elif ext == ".json":
            return self._classify_json(file_path)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def _classify_xml(self, path: Path) -> str:
        """Classify an XML file by sniffing namespace declarations."""
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")[:2048]
        except Exception:
            return "GenericXML"

        if "buildingsmart.org/IDS" in content or "buildingsmart.org/ids" in content:
            return "IDS"
        if "buildingsmart.org/mvd" in content:
            return "MVD"
        if "archicad" in content.lower():
            return "ArchiCAD"
        return "GenericXML"

    def _classify_excel(self, path: Path) -> str:
        """Classify an Excel file by checking sheet names for COBie/BIMQ patterns."""
        try:
            import openpyxl

            wb = openpyxl.load_workbook(path, read_only=True)
            sheets = [s.lower() for s in wb.sheetnames]
            wb.close()

            # COBie detection: has standard COBie sheets
            cobie_sheets = {"component", "type", "floor", "space", "zone", "attribute"}
            if len(cobie_sheets.intersection(sheets)) >= 2:
                return "COBie"

            if "concept_tree" in str(sheets).lower():
                return "BIMQ"

        except Exception:
            logger.debug("Could not inspect Excel sheets for classification", exc_info=True)

        return "Excel"

    def _classify_txt(self, path: Path) -> str:
        """Classify a text file by checking for Revit SP header."""
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")[:500]
        except Exception:
            return "PlainText"

        if "This is a Revit shared parameter file" in content:
            return "RevitSP"
        return "PlainText"

    def _classify_json(self, path: Path) -> str:
        """Classify a JSON file by checking for BIMQ structure."""
        try:
            import json

            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict) and (
                "concept_tree" in data or "elements" in data
            ):
                return "BIMQ"
        except Exception:
            logger.debug("Could not inspect JSON for classification", exc_info=True)

        return "GenericJSON"
