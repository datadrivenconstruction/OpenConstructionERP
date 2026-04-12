"""Base classes for BIM requirement parsers.

Defines UniversalRequirement, ParseResult, and the BaseRequirementParser ABC
that every format-specific parser must extend.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class UniversalRequirement:
    """Normalized BIM requirement -- the 5-column universal model.

    Attributes:
        element_filter: Which element (IFC class, classification, ...).
        property_group: Property set / group name (None for direct IFC attrs).
        property_name:  The specific property or attribute name.
        constraint_def: Constraint definition (datatype, cardinality, enum, ...).
        context:        When/who/why (phase, actor, use_case, source, ...).
        raw_source:     Original data before normalization (for debugging).
    """

    def __init__(
        self,
        element_filter: dict[str, Any],
        property_name: str,
        constraint_def: dict[str, Any],
        property_group: str | None = None,
        context: dict[str, Any] | None = None,
        raw_source: dict[str, Any] | None = None,
    ) -> None:
        self.element_filter = element_filter
        self.property_group = property_group
        self.property_name = property_name
        self.constraint_def = constraint_def
        self.context = context or {}
        self.raw_source = raw_source or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "element_filter": self.element_filter,
            "property_group": self.property_group,
            "property_name": self.property_name,
            "constraint_def": self.constraint_def,
            "context": self.context,
        }


class ParseResult:
    """Aggregated result from a parser run.

    Collects requirements, errors, warnings, and metadata.
    A parser should never raise exceptions -- it adds errors here instead.
    """

    def __init__(self) -> None:
        self.requirements: list[UniversalRequirement] = []
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}

    @property
    def success(self) -> bool:
        """True if at least one requirement was parsed."""
        return len(self.requirements) > 0

    @property
    def has_errors(self) -> bool:
        """True if there are parsing errors."""
        return len(self.errors) > 0


class BaseRequirementParser(ABC):
    """Abstract base for all BIM requirement parsers.

    Subclasses must set FORMAT_NAME, SUPPORTED_EXTENSIONS and implement parse().
    """

    FORMAT_NAME: str = ""
    SUPPORTED_EXTENSIONS: list[str] = []

    def can_parse(self, file_path: Path) -> bool:
        """Check if this parser supports the given file extension."""
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    @abstractmethod
    def parse(self, source: Path | str | bytes) -> ParseResult:
        """Parse the source and return a ParseResult.

        Args:
            source: Path to a file, raw string content, or raw bytes.

        Returns:
            ParseResult with normalized requirements and any errors/warnings.
        """
        raise NotImplementedError

    def _normalize_ifc_class(self, raw: str) -> str:
        """Normalize an IFC class name to uppercase with IFC prefix."""
        clean = raw.strip().upper()
        if not clean.startswith("IFC"):
            clean = f"IFC{clean}"
        return clean

    def _normalize_cardinality(self, raw: str) -> str:
        """Normalize cardinality string to required/optional/prohibited."""
        mapping = {
            "required": "required",
            "mandatory": "required",
            "pflicht": "required",
            "muss": "required",
            "optional": "optional",
            "kann": "optional",
            "prohibited": "prohibited",
            "verboten": "prohibited",
            "not allowed": "prohibited",
        }
        return mapping.get(raw.lower().strip(), "optional")
