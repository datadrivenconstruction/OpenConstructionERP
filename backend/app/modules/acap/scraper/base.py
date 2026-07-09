"""Pure parsing helpers (stdlib only — no app.* imports, testable in isolation)."""

from __future__ import annotations

import re
from dataclasses import dataclass


def parse_rupiah(text: str) -> int:
    """Strip ``Rp``, dots (thousands separators), spaces, and non-digits → int.

    ``"Rp. 175.000"`` → 175000
    ``"Rp 65.000"`` → 65000
    """
    cleaned = re.sub(r"[Rr][Pp]\s*\.?\s*", "", text)
    cleaned = cleaned.replace(".", "").replace(" ", "")
    cleaned = re.sub(r"[^0-9]", "", cleaned)
    if not cleaned:
        return 0
    return int(cleaned)


def parse_price_range(text: str) -> tuple[int, int]:
    """Parse a price cell that may contain a single value or a range.

    Splits on en-dash ``–`` or hyphen ``-``; ``Rp`` prefixes are stripped
    from each side.  Single value → ``(v, v)``.

    ``"Rp 65.000 – Rp 105.000"`` → ``(65000, 105000)``
    ``"Rp. 175.000"``          → ``(175000, 175000)``
    """
    # Split on en-dash or hyphen (but not minus signs inside numbers)
    parts = re.split(r"\s*[–\-—]\s*", text.strip(), maxsplit=1)
    if len(parts) == 2:
        low = parse_rupiah(parts[0])
        high = parse_rupiah(parts[1])
        return (min(low, high), max(low, high))
    return (parse_rupiah(text), parse_rupiah(text))


@dataclass
class PriceRecord:
    """Normalised price record extracted from a scraper adapter."""

    source: str
    source_url: str
    item_type: str  # 'upah_harian' | 'upah_borongan' | 'material'
    item_name: str
    satuan: str | None
    price_min: int
    price_max: int
    extraction_method: str = "selectolax"
