"""Sobatbangun scraper — parse material prices from sobatbangun.com HTML.

Pure parsing (stdlib + selectolax only, no app.* imports).
"""

from __future__ import annotations

from selectolax.parser import HTMLParser

from app.modules.acap.scraper.base import PriceRecord, parse_price_range


def _normalize(name: str) -> str:
    """Lowercase + strip for dedup."""
    return name.strip().lower()


def parse_sobatbangun(html: str, source_url: str) -> list[PriceRecord]:
    """Parse sobatbangun.com material price page into ``PriceRecord``\ s.

    Two ``<table>`` elements expected:
    * 2025 table: header "Estimasi Harga (2025)" — 2 cols
    * 2026 table: header "Estimasi Harga (2026)" — 3 cols

    To avoid duplicate item_names, the 2026 table is preferred: if
    both are present, any 2025 row whose *normalized* item_name
    already appears in the 2026 data is skipped.
    """
    records: list[PriceRecord] = []
    seen_2026_names: set[str] = set()
    temp_2025: list[PriceRecord] = []
    tree = HTMLParser(html)

    for table in tree.css("table"):
        rows = table.css("tr")
        if not rows:
            continue

        header_text = " ".join(td.text(strip=True) for td in rows[0].css("th, td"))
        header_lower = header_text.lower()

        if "estimasi harga" not in header_lower:
            continue

        is_2026 = "2026" in header_text
        has_3_cols = "satuan" in header_lower

        for row in rows[1:]:
            cells = row.css("td")
            if len(cells) < 2:
                continue

            item_name = cells[0].text(strip=True)
            if not item_name:
                continue

            if has_3_cols and len(cells) >= 3:
                satuan = cells[1].text(strip=True)
                raw_price = cells[2].text(strip=True)
            else:
                satuan = None
                raw_price = cells[1].text(strip=True)

            if not raw_price:
                continue

            low, high = parse_price_range(raw_price)
            rec = PriceRecord(
                source="sobatbangun.com",
                source_url=source_url,
                item_type="material",
                item_name=item_name,
                satuan=satuan or None,
                price_min=low,
                price_max=high,
            )

            if is_2026:
                records.append(rec)
                seen_2026_names.add(_normalize(item_name))
            else:
                temp_2025.append(rec)

    # Append 2025 rows not shadowed by a 2026 row
    for rec in temp_2025:
        if _normalize(rec.item_name) not in seen_2026_names:
            records.append(rec)

    return records
