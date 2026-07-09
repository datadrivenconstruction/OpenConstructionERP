# Batam market prices 2026 — NotebookLM research

Source of `backend/app/modules/acap/data/prices/batam_notebooklm_2026.csv`
(loaded via `python -m app.modules.acap.scraper.load_research_csv --commit`,
`source="notebooklm-research"`).

## Method
- Google NotebookLM notebook "Batam Harga Bahan Bangunan & Upah Konstruksi 2026".
- Seeded with the two live-scraper sources (arsiteqi Batam upah, sobatbangun material)
  + **deep web research** → ~70 Batam-grounded sources auto-imported (Tokopedia Batam
  listings for semen Andalas / pasir cor / keramik 40×40, SMS Perkasa besi, brighton /
  99.co borongan, SK-UMK-Batam-2026, "Analisis Estimasi Biaya Konstruksi Batam & Kepri").
- Structured `data-table` artifact → CSV (item_type, item_name, satuan, price_min,
  price_max, source), then validated + curated into the committed CSV.

## Curation (money-path safety — nothing loaded blind)
NotebookLM collapsed multi-source ranges, so several staples had **unit-contaminated
maxes** (pallet / per-1000 / per-truck). These were clipped to realistic Batam ceilings
(domain judgment); the researched min was kept. Junk rows (UMK monthly wage, rumah-lux
borongan) were dropped by per-type bounds.

| Item | raw max | clipped max | why |
|---|---|---|---|
| Bata merah (per buah) | 95,000 | 1,500 | per-1000/pallet leak; ~1,075/pc midpoint |
| Semen (50 kg, per sak) | 200,000 | 110,000 | min also raised 49,500→60,000 |
| Pasir m³ / Cor / urug | up to 11,350,000 | 350k / 400k / 250k | per-truck leak |
| Kerikil | 700,000 | 450,000 | |
| Cat interior / eksterior | 1.2M / 2.5M | 300k / 400k | per-pail leak |

Clean as-researched: all labour rates (incl. **Mandor** — the previously-unpriced gap,
now ~180k/hari midpoint), besi beton 8/10/12 mm, borongan (pasang bata, plesteran,
keramik, beton, atap), keramik.

## Effect on RAB
Re-running the RAB after load: every wall/finish line prices from real market data —
**zero PRICE_MISSING, zero curated fallback** (mandor is now market-priced). Dinding
unit rate dropped (bata 1,800→1,075/pc) while plesteran/acian rose (truer Batam labour).

## Batch 2 — additional categories (sanitair / listrik / kusen / plafon / atap)
A second `data-table` over the same notebook targeted these categories. The raw
output was **much noisier** — SBM government-budget junk (airfare, meeting-room
rental), English/Indonesian duplicate rows across 6+ sources, and absurd values
(LED 100W = Rp 1jt, a pipe-install row with min>max). It was **not** loaded raw.
Instead a hand-curated, deduped, sane subset of **35 material rows** (Indonesian
canonical names, `readymix.co.id` / `smsperkasa.com` / Batam toko-derived) was
appended to the CSV; all jasa-pasang duplicates and junk were dropped. These have
NO AHSP code yet, so they don't affect the RAB — they pre-stock the catalog for
when the foundation/floor/roof/MEP AHSP batch is seeded. CSV now 72 rows total.

## Refresh
Re-run the NotebookLM research + `generate data-table`, re-curate, overwrite the CSV,
re-run the loader. `scraped_at` recency means fresh rows win over older ones in the RAB.
