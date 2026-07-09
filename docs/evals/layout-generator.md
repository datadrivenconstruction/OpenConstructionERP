# Layout Generator Evaluation

## Method

The eval harness (`backend/app/modules/acap/layout/eval.py`) measures the
ACAP layout generator's pass@3 rate — how often the LLM produces a valid
floor-plan within 3 generation passes.

**Each fixture** is a plain-language requirement (e.g. "Rumah minimalis type 36")
plus a kavling size and floor count.  The harness runs up to 3 LLM calls per
fixture; a fixture PASSES if any call produces:

1. A `FloorPlan` that passes `validate_plan()` (axis-aligned rects, no overlap,
   all rooms within kavling bounds, KDB ≤70%, min areas/dimensions).
2. All `expect_room_types` are present in the plan.
3. (Optional) Total room area within ±10% of `expect_total_area_m2`.

## Fixtures (10)

| # | Name | Kavling | Lantai | Key room types |
|---|------|---------|--------|----------------|
| 1 | rumah_minimalis_1lt_36 | 6×12 | 1 | ruang_tamu, 2 kamar tidur, kamar_mandi, dapur, ruang_keluarga, carport |
| 2 | rumah_minimalis_1lt_45 | 6×15 | 1 | ruang_tamu, ruang_keluarga, 2 kamar tidur, kamar_mandi, dapur, ruang_makan, carport |
| 3 | rumah_2lt_keluarga | 8×15 | 2 | ruang_tamu, ruang_keluarga, dapur, ruang_makan, carport, 3 kamar tidur, 2 kamar_mandi, sirkulasi |
| 4 | rumah_murah_batam_1lt | 6×10 | 1 | ruang_tamu, 2 kamar tidur, kamar_mandi, dapur, teras |
| 5 | rumah_ali_2lantai_renovasi | 8×15 | 2 | ruang_tamu, dapur, ruang_makan, kamar_mandi, gudang, carport, 2 kamar tidur, ruang_keluarga, teras, sirkulasi |
| 6 | rumah_kost_4_kamar | 8×14 | 1 | 4 kamar tidur, 2 kamar_mandi, dapur, ruang_tamu, sirkulasi |
| 7 | rumah_tropis_modern_2lt | 10×16 | 2 | ruang_tamu, ruang_keluarga, dapur, ruang_makan, 3 kamar tidur, 3 kamar_mandi, carport, taman, musholla, sirkulasi |
| 8 | rumah_kecil_1lt_sempit | 4.5×10 | 1 | kamar_tidur, kamar_mandi, dapur, ruang_tamu |
| 9 | rumah_mewah_modern_1lt | 12×20 | 1 | ruang_tamu, ruang_keluarga, ruang_makan, dapur, 3 kamar tidur, 3 kamar_mandi, carport, teras, taman, musholla |
| 10 | rumah_garasi_workshop | 8×18 | 1 | ruang_tamu, 2 kamar tidur, kamar_mandi, dapur, garasi, gudang |

## Target

**pass@3 ≥ 8/10**

## Requirements

- **AI key**: The eval uses the fork's `resolve_provider_key_model` which
  reads `ANTHROPIC_API_KEY` from the environment (or
  `~/.openestimate/config.json`, or the DB `AISettings` table).
- Run: `python -m app.modules.acap.layout.eval` from the `backend/` directory
  with `PYTHONPATH=.`
