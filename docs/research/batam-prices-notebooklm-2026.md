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

## Batch 3 — full-WBS material completion (2026-07-09)
Paired with the AHSP Batch-2 coefficient seed (53 codes, full rumah WBS). Gap analysis
listed every material + trade the 22 new codes consume that had NO Batam price; a
targeted `notebooklm ask` over this notebook priced them. **37 rows appended** (35
material + 2 upah_harian: tukang aluminium, tukang pipa). item_names deliberately match
the AHSP bahan names so the RAB price join is direct.

Money-path curation (nothing blind-loaded — NotebookLM honored "tulis '-' jika tak tahu"
and did NOT hallucinate unknowns):
- **Grounded as-returned** (Batam / BP-Batam-SSH / Tokopedia): papan kayu III 1.6jt/m³,
  plywood 12mm 155-233k, dolken 16k, minyak bekisting 41.8k, primer 19.8k, pipa AW ½"
  8.8k/m, pipa D 2" 22.4k/m, kawat bendrat 30k, kawat las 16k, paku 20k, thinner 19.9k,
  menie 79.6k, conduit 3.7k/m, sekrup fixer 5k, tukang aluminium/pipa 155-167k/OH.
- **Curated (domain judgment, flagged in source_url)**: *Profil aluminium 4"* NBLM 20-35k/m'
  was too low (per-kg/thin-profile confusion) → 45-85k/m' (Batam YKK/Alexindo, FTZ). *Genteng
  beton* NBLM 9.5-14.5k/pc skewed to premium/keramik → 6-9k/pc (flat concrete tile). These
  are the money-material items (roof ~880 pcs), so mis-pricing would move the RAB Rp-millions.
- **retail-nasional (marked)**: low-value stable consumables NBLM had no Batam data for
  (kuas, ampelas, sealtape, klem, t-dus, socket, fischer, elbow, lasdop, isolasi, flexible
  hose/conduit, silicone, lem kayu, plamur, kabel NYM 3×2.5, membran bakar) — tiny RAB impact.

Balok kayu kelas II capped at 4.8jt/m³ (loader material bound is 5jt; kamper/meranti raw was
3.4-5.6jt). Total prices in DB: **148** (research 109 · scraped 39). Still handled in wiring,
not priced: `pasangan bata 1PC:3PS` (composite → references bata code), `semen warna` (→ semen
putih), generic `tukang` (→ tukang_batu rate).

## Refresh
Re-run the NotebookLM research + `generate data-table`, re-curate, overwrite the CSV,
re-run the loader. `scraped_at` recency means fresh rows win over older ones in the RAB.
