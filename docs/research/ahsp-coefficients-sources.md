# AHSP Coefficient Sources & Provenance (Phase 1 subset)

**Date collected:** 2026-07-09 · **Method:** firecrawl markdown scrape (statusCode 200 verified per page) → manual extraction. Values cross-checked against canonical SNI ranges.

> **Data-integrity note.** The first extraction attempt used firecrawl *JSON* mode on two URLs that returned **HTTP 404**; the extractor **fabricated** plausible-looking coefficients (e.g. bata "kepala tukang 1.0 OH, pasir 0.8 m³/m²" — physically impossible). Those were **discarded**. Every value below comes from a **statusCode 200** page read as raw markdown and hand-verified. This is why the seed is a small, checked subset rather than a bulk auto-extract.

## Scope of this subset

House-building structural + wall + finishing chain — enough to drive Phase 5 (RAB) and Phase 6 (timeline) end-to-end. **Not** the full AHSP: `cat`, `lantai keramik`, `atap`, `plafon`, `sanitair`, `listrik`, and the interior layer (D3) are the **next batch**, to be parsed from the official AHSP Permen PUPR No. 1/2022 PDF (Ali) — see plan Phase 1 (~1 week manual parse).

## Sources (all rumahmaterial.com — reproduces SNI / Permen PUPR AHSP format tables)

| Category | URL | statusCode | Standard |
|---|---|---|---|
| Tanah (earthwork) | /2020/11/analisa-harga-satuan-pekerjaan-tanah.html | 200 | SNI 2835 / AHSP |
| Pondasi (foundation) | /2020/11/analisa-harga-satuan-pondasi-sni.html | 200 | SNI 2836 / AHSP |
| Beton (concrete K100–K350) | /2020/11/analisa-harga-satuan-beton-sni.html | 200 | SNI 7394 / AHSP A.4.1.1.x |
| Dinding bata merah 1:2–1:5 | /2014/09/analisa-harga-satuan-pasangan-dinding.html | 200 | SNI 6897 |
| Plesteran + acian 1:2–1:5 | /2015/01/analisa-harga-satuan-plesteran-dan.html | 200 | SNI 2837 |

## Unit normalisation

- **Semen**: sources for dinding/plesteran quote cement in **sak 50 kg**; normalised to **kg** in the YAML (`sak × 50`). Beton/pondasi already quote cement in kg.
- **Labour**: coefficient unit is **OH** (orang-hari / man-day) throughout — this feeds Phase 6 timeline (`durasi = volume × koef_OH / crew`).
- Prices on the source pages are illustrative only and are **ignored** — pricing comes from Phase 2 (Batam scraper). Only coefficients are seeded.

## Spot-check anchors (verify seed against these)

- Galian tanah biasa 1 m /m³: Pekerja **0.75**, Mandor **0.025**.
- Pondasi batu belah 1:4 /m³: Pekerja **1.5**, Tukang batu **0.75**, Kepala tukang **0.075**, Mandor **0.075**; semen **163 kg**, pasir pasang **0.52 m³**, batu belah **1.2 m³**.
- Beton K175 /m³: Pekerja **1.65**, Tukang batu **0.275**, Kepala **0.028**, Mandor **0.083**; semen **326 kg**, pasir beton **760 kg**, kerikil **1029 kg**, air **215 L**.
- Dinding bata merah 1:4 /m²: bata **72 bh**, semen **11.15 kg** (0.223 sak), pasir **0.028 m³**; Pekerja **0.30**, Tukang batu **0.15**, Kepala **0.015**, Mandor **0.008**.
- Plesteran 1:4 t=2.5cm /m²: semen **10.0 kg** (0.200 sak), pasir **0.025 m³**; Pekerja **0.25**, Tukang batu **0.125**, Kepala **0.013**, Mandor **0.007**.
- Acian /m²: semen **3.8 kg** (0.076 sak); Pekerja **0.12**, Tukang batu **0.06**, Kepala **0.006**, Mandor **0.003**.

---

## Batch 2 — full-house completion via NotebookLM (2026-07-09)

**Method:** the "next batch" this doc anticipated. Grounded a NotebookLM notebook
(`AHSP Koefisien Bidang Cipta Karya`) on the **official Permen PUPR No. 1/2022
Lampiran IV PDF** (860 pp, `maspetruk.dpubinmarcipka.jatengprov.go.id`), extracted
coefficient tables via `notebooklm ask`, then **verified every line against the
source PDF with pypdf** (page-dump cross-check). Across **24 candidate analyses in
4 groups, NotebookLM matched the source table EXACTLY on every coefficient** — zero
fabrication, zero drift (only a few ±1 page-citation slips, values perfect). This is
the dual-source loop: NotebookLM as the fast semantic index into 860 pages, pypdf as
the authoritative verifier. Seeded **22 codes** (5 files `10_`–`14_`); 2 candidates
folded (pembesian Ø<12/≥12 → 1 code, identical bahan+tenaga; cat plafon reuses
`ACAP.CAT.TEMBOK_BARU`).

| Group | Codes | Source § (hal.) |
|---|---|---|
| Beton bertulang | PEMBESIAN, BEKISTING SLOOF/KOLOM/BALOK/PLAT | §2.2.1.1.3-4 (102), §2.2.1.3.3-6 (107-109) |
| Kusen/pintu/jendela | KUSEN.ALUMINIUM, PINTU.PANEL_KAYU, JENDELA.KACA_KAYU, KACA.POLOS_5 | §3.11.3.1 (298), §3.11.1.11 (294), §3.11.1.9 (293), §3.12.3 (313) |
| Finishing lanjut | PLAFON.RANGKA_HOLLOW, DINDING.KERAMIK_10_20, ATAP.GENTENG_BETON, WATERPROOFING.MEMBRAN, CAT.KAYU_BESI | §3.5.3.1 (211), §3.10.1.3 (278), §3.1.1.4 (177), §3.4.1 (203), §3.8.4 (234) |
| Sanitair + MEP | KLOSET_DUDUK/JONGKOK, WASTAFEL, KRAN, FLOOR_DRAIN, PIPA AIR_BERSIH_HALF/AIR_KOTOR_2, LISTRIK.TITIK_LAMPU | §3.18.* (326-333), §6.4.1.1/19 (587,593), §5.3.1.1 (466) |

**Total AHSP codes now: 53** (31 → 53). Full rumah-tinggal WBS coverage:
tanah → pondasi → beton (mix + bertulang) → dinding → plesteran/acian → lantai →
plafon (rangka + penutup) → atap (baja ringan/seng/genteng) → kusen/pintu/jendela →
cat → sanitair → perpipaan → listrik.

**Not yet wired into RAB output** (same state as the batch-1 finish codes): needs
`ELEMENT_KODE_MAP` + takeoff qty formulas + `price_map.py` aliases for the new
materials, **and Batam prices for 3 new trades** (`tukang_aluminium`, `tukang_pipa`,
`tukang_listrik`) — else those lines flag `PRICE_MISSING`. Follow-on wiring task.
