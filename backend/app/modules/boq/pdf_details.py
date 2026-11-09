"""Per-project details printed on the estimate PDF.

The estimate PDF names the project and the bill but not who the estimate is for,
where the work is, or how it is paid. Those belong to the project, not to one
bill, so they are stored once on the project (``metadata["boq_pdf"]``) and every
bill of the project prints them. No column was added: the project already
carries a free metadata object, and nothing else queries these values.

Nothing prints that was not filled in, so a project that never opens the panel
gets the same document as before.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator
from reportlab.platypus import Flowable, Paragraph

#: Key of the project metadata object that holds the settings.
METADATA_KEY = "boq_pdf"

#: Columns a recipient may not need. Description and total always print; the
#: position number is the reference the reader follows between pages.
OPTIONAL_COLUMNS: tuple[str, ...] = ("qty_unit", "rate")


def _clean_text(value: Any, cap: int, *, multiline: bool = False) -> str:
    """Strip control characters, keep newlines only where a block is meant."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    kept = [ch for ch in text if ch == "\n" or (ch >= " " and ch != "\x7f")]
    out = "".join(kept)
    if not multiline:
        out = " ".join(out.split())
    else:
        out = "\n".join(line.rstrip() for line in out.split("\n")).strip("\n")
    return out.strip()[:cap]


class PdfDetails(BaseModel):
    """What the estimate PDF prints about the client, the site and the payment."""

    client_name: str = Field(default="", max_length=200)
    client_address: str = Field(default="", max_length=500)
    project_number: str = Field(default="", max_length=60)
    site_address: str = Field(default="", max_length=500)
    payment_terms: str = Field(default="", max_length=2000)
    hidden_columns: list[str] = Field(default_factory=list)

    @field_validator("client_name", "project_number", mode="before")
    @classmethod
    def _one_line(cls, value: Any, info: Any) -> str:
        return _clean_text(value, 200 if info.field_name == "client_name" else 60)

    @field_validator("client_address", "site_address", mode="before")
    @classmethod
    def _block(cls, value: Any) -> str:
        return _clean_text(value, 500, multiline=True)

    @field_validator("payment_terms", mode="before")
    @classmethod
    def _terms(cls, value: Any) -> str:
        return _clean_text(value, 2000, multiline=True)

    @field_validator("hidden_columns", mode="before")
    @classmethod
    def _columns(cls, value: Any) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        seen: list[str] = []
        for item in value:
            if item in OPTIONAL_COLUMNS and item not in seen:
                seen.append(item)
        return seen

    @property
    def has_header_block(self) -> bool:
        """Whether any of the client / project / site lines was filled in."""
        return any((self.client_name, self.client_address, self.project_number, self.site_address))


def read_details(metadata: Any) -> PdfDetails:
    """The settings stored in a project's metadata; defaults when absent or malformed."""
    raw = metadata.get(METADATA_KEY) if isinstance(metadata, dict) else None
    if not isinstance(raw, dict):
        return PdfDetails()
    try:
        return PdfDetails.model_validate(raw)
    except ValueError:
        return PdfDetails()


def merged_metadata(metadata: Any, details: PdfDetails) -> dict[str, Any]:
    """A new metadata object with the settings replaced; the other keys are kept."""
    base = dict(metadata) if isinstance(metadata, dict) else {}
    base[METADATA_KEY] = details.model_dump()
    return base


def drop_columns(table_data: list[list[Any]], widths: list[float], hidden: list[str]) -> list[float]:
    """Remove the hidden columns from the BOQ table rows in place; returns the new widths.

    The table is Pos | Description | Unit | Qty | Rate | Total. Total rows carry
    their caption in the unit cell, so before the unit and quantity columns go,
    a caption sitting there moves into the empty description cell. The width of
    the removed columns goes to the description.
    """
    if not hidden or not table_data or len(widths) != 6:
        return widths
    drop: set[int] = set()
    if "qty_unit" in hidden:
        drop.update((2, 3))
        for row in table_data[1:]:
            if len(row) == 6 and row[0] == "" and row[1] == "" and row[2] != "":
                row[1], row[2] = row[2], ""
    if "rate" in hidden:
        drop.add(4)
    freed = sum(widths[i] for i in drop)
    for row in table_data:
        if len(row) == 6:
            # A page mark (a bare flowable, not text) must survive: the
            # table of contents reads it to find the section's page.
            for i in sorted(drop):
                cell = row[i]
                if isinstance(cell, Flowable) and not isinstance(cell, Paragraph):
                    spare = [j for j in range(5, -1, -1) if j not in drop and row[j] == ""]
                    if spare:
                        row[spare[0]] = cell
            row[:] = [cell for i, cell in enumerate(row) if i not in drop]
    kept = [w for i, w in enumerate(widths) if i not in drop]
    kept[1] += freed
    return kept
