"""Arsiteqi scraper — parse upah harian + borongan from arsiteqi.or.id HTML.

Pure parsing (stdlib + selectolax only, no app.* imports).
"""

from __future__ import annotations

from selectolax.parser import HTMLParser

from app.modules.acap.scraper.base import PriceRecord, parse_price_range


def parse_arsiteqi(html: str, source_url: str) -> list[PriceRecord]:
    """Parse arsiteqi.or.id Batam upah page into ``PriceRecord``\ s.

    Two ``<table>`` elements are expected:
    * Table with header "Jenis Tukang" → ``item_type="upah_harian"``
    * Table with header "Jenis Pekerjaan" → ``item_type="upah_borongan"``

    Each data row: col0=item_name, col1=satuan, col2=single-value price.
    """
    records: list[PriceRecord] = []
    tree = HTMLParser(html)

    for table in tree.css("table"):
        rows = table.css("tr")
        if not rows:
            continue

        # Detect table type from header row text
        header_text = " ".join(td.text(strip=True) for td in rows[0].css("th, td"))
        header_lower = header_text.lower()

        if "jenis tukang" in header_lower:
            item_type = "upah_harian"
        elif "jenis pekerjaan" in header_lower:
            item_type = "upah_borongan"
        else:
            continue  # skip non-data tables

        for row in rows[1:]:  # skip header row
            cells = row.css("td")
            if len(cells) < 3:
                continue

            item_name = cells[0].text(strip=True)
            satuan = cells[1].text(strip=True)
            raw_price = cells[2].text(strip=True)

            if not item_name or not raw_price:
                continue

            low, high = parse_price_range(raw_price)
            records.append(
                PriceRecord(
                    source="arsiteqi.or.id",
                    source_url=source_url,
                    item_type=item_type,
                    item_name=item_name,
                    satuan=satuan or None,
                    price_min=low,
                    price_max=high,
                )
            )

    return records
