# RAB full-wiring spec — layout → whole-house rupiah

**Goal:** extend the RAB so a FloorPlan produces line items for the whole house
(struktur praktis + finishing + bukaan + sanitair + MEP + atap), not just
dinding/plesteran/acian. All money-path decisions (unit factors, price aliases,
estimator assumptions) are FIXED below by the reviewer — the implementer must copy
them EXACTLY, no re-derivation, no rounding, no "improvement". Every constant that
encodes an engineering assumption goes in a named module constant with a comment.

Touch ONLY: `backend/app/modules/acap/takeoff.py`,
`backend/app/modules/acap/rab/generator.py`,
`backend/app/modules/acap/rab/price_map.py`, and their tests under
`backend/tests/`. Do NOT touch schema.py, models, router, or seed data.

Money-path contract is UNCHANGED and MUST hold: Decimal throughout; a resource with
no price → whole line `price_missing`, excluded from grand_total, surfaced. Never
substitute 0 or a guess. `curated_resources` semantics unchanged.

---

## 1. price_map.py — RESOURCE_ALIAS additions (EXACT, money gate)

Add these entries. `unit_factor` converts price-unit → koef-unit; `Decimal(1)/Decimal(N)`.
Keep the existing entries. Where a real upah row now exists, drop the curated fallback.

MATERIALS (tipe "bahan" → "material"):
- ("bahan","Besi beton") → "Besi beton 10 mm", factor 1/7.4   # price per 12m batang, D10=7.4kg; koef in kg
- ("bahan","Kawat beton") → "Kawat beton", factor 1
- ("bahan","Semen warna") → "Semen putih", factor 1/50        # koef kg, price per 50kg sak
- ("bahan","Pasir beton") → "Pasir beton", factor 1
- ("bahan","Kerikil") → "Kerikil", factor 1
- ("bahan","Keramik lantai 40x40") → "Keramik Lantai 40×40", factor 1/6   # price per Dus=6pc; koef in bh. NOTE the × (U+00D7) in the price name
- ("bahan","Keramik dinding 10x20") → "Keramik dinding", factor 1/25       # ASSUMPTION: dus=25pc for 10x20; koef in bh
- ("bahan","Gypsum board 9mm") → "Gypsum board 9mm", factor 1
- ("bahan","Paku sekrup") → "Paku biasa", factor 1
- ("bahan","Besi hollow 40x40") → "Rangka hollow", factor 1/4   # price per 4m batang; koef in m'
- ("bahan","Baja ringan C75") → "Baja ringan kanal C75", factor 1   # both per batang
- ("bahan","Seng gelombang") → "Seng gelombang", factor 1
- ("bahan","Seng pelat") → "Seng pelat", factor 1
- ("bahan","Genteng beton") → "Genteng beton", factor 1
- ("bahan","Kaca polos 5 mm") → "Kaca 5 mm", factor 1
- ("bahan","Kabel NYM 3x2.5 mm2") → "Kabel NYM 3x2.5 mm2", factor 1
- ("bahan","Cat dasar") → "Cat dasar/plamir", factor 1
- ("bahan","Cat penutup") → "Cat interior", factor 1/5   # ASSUMPTION: kaleng≈5kg; koef in kg
- ("bahan","Membran bakar") → "Membran bakar", factor 1
- ("bahan","Cairan primer") → "Cairan primer", factor 1
- ("bahan","Profil aluminium 4 inch") → "Profil aluminium 4 inch", factor 1
- ("bahan","Pipa PVC AW 1/2 inch") → "Pipa PVC AW 1/2 inch", factor 1
- ("bahan","Pipa PVC D 2 inch") → "Pipa PVC D 2 inch", factor 1
- ("bahan","Kayu kelas III") → "Kayu kelas III", factor 1
- ("bahan","Papan kayu kelas III") → "Papan kayu kelas III", factor 1
- ("bahan","Balok kayu 6/12") → "Balok kayu 6/12", factor 1
- ("bahan","Balok kayu kelas II") → "Balok kayu kelas II", factor 1
- ("bahan","Plywood 12mm") → "Plywood 12mm", factor 1
- ("bahan","Dolken kayu 8-10 cm") → "Dolken kayu 8-10 cm", factor 1
- ("bahan","Minyak bekisting") → "Minyak bekisting", factor 1
- ("bahan","Lem kayu") → "Lem kayu", factor 1
- ("bahan","Bata roster") → "Bata roster", factor 1
- ("bahan","Kunci tanam biasa") → "Kunci tanam biasa", factor 1
- ("bahan","Engsel pintu") → "Engsel pintu", factor 1
- ("bahan","Kait angin") → "Kait angin", factor 1
- ("bahan","Kloset duduk") → "Kloset duduk", factor 1
- ("bahan","Kloset jongkok") → "Kloset jongkok", factor 1
- ("bahan","Wastafel lengkap") → "Wastafel", factor 1
- ("bahan","Kran air") → "Kran air", factor 1
- ("bahan","Floor drain") → "Floor drain", factor 1
- ("bahan","Saklar") → "Saklar tunggal", factor 1
- ("bahan","MCB box") → "MCB box", factor 1
- ("bahan","Pompa jet 27 lpm") → "Pompa jet 27 lpm", factor 1
- ("bahan","Tangki toren 0.7 m3") → "Tangki toren 0.7 m3", factor 1
- Low-value consumables named identically already direct-match (Paku 5-10 cm, Paku 5-12 cm,
  Paku 10 cm, Paku biasa, T dus, Socket conduit 20 mm, Klem 20 mm, Fischer S6 + sekrup,
  Elbow, Lasdop, Isolasi, Conduit HI 20 mm, Flexible conduit 20 mm, Flexible hose,
  Sealant, Silicone sealant 300 ml, Sekrup fixer, Sealtape, Kuas, Ampelas, Plamur,
  Pengencer, Menie, Semen portland, Pasir pasang, Kawat las) — add explicit aliases ONLY
  where the price item_name differs in case/spelling from the AHSP nama; otherwise leave to
  the direct-match fallback. Paku variants (5-10/5-12/10 cm) → "Paku biasa".

TRADES (tipe "tenaga" → "upah_harian"):
- ("tenaga","tukang_kayu") → "Tukang kayu", ("tenaga","tukang_besi") → "Tukang besi",
  ("tenaga","tukang_cat") → "Tukang cat", ("tenaga","tukang_listrik") → "Tukang listrik",
  ("tenaga","tukang_aluminium") → "Tukang aluminium", ("tenaga","tukang_pipa") → "Tukang pipa",
  ("tenaga","tukang") → "Tukang Batu"   # generic tukang priced at the batu rate
- ("tenaga","mandor") → "Mandor" WITHOUT curated_rate IF a "Mandor" upah_harian row exists
  (it now does). Verify with a query; if present, drop the curated fallback so mandor is
  market-sourced.

## 2. takeoff.py — new pure quantities (all assumptions = named constants)

Add constants: ROOF_PITCH_FACTOR=1.20; KOLOM_PRAKTIS_SPACING_M=3.5; KM_TILE_HEIGHT_M=2.0;
LAMPU_PER_ROOM=1; STOPKONTAK_PER_ROOM=2; SAKLAR_PER_ROOM=1; DOOR_HINGES=3; WINDOW_HINGES=2;
PIPA_BERSIH_PER_FIXTURE_M=6.0; PIPA_KOTOR_PER_KM_M=8.0; RISER_M=10.0.
INDOOR excludes {teras, taman, carport, garasi}. WET rooms = {kamar_mandi}.
PONDASI_SECTION_M2=0.6 (batu belah trapezoid, per m').

Extend `takeoff(plan)` per-level dict AND add a plan-level aggregate the generator can use.
New per-level fields (pure geometry, floats):
- floor_area_indoor_m2 (sum of INDOOR room areas)
- roof_footprint_m2 (sum of ALL room areas this level)  [roof qty uses top level only]
- exterior_perimeter_m (wall_length is the deduped total; also expose it)
- wet_room_count, indoor_room_count, room_count
- wet_floor_area_m2, wet_wall_perimeter_m (perimeter of kamar_mandi polygons)
- openings: door_count, window_count, door_kusen_len_m (Σ 2*(w+2.1) per door),
  window_kusen_len_m (Σ 2*(w+1.2)), door_leaf_area_m2 (Σ w*2.1), window_leaf_area_m2 (Σ w*1.2),
  glass_area_m2 (= window_leaf_area_m2)

## 3. generator.py — ELEMENT_KODE_MAP + qty_by_element

Replace NOT_COVERED shrinkage: only truly-uncovered (main structural beton needing a
structural model: footplat/sloof-beton/main kolom-balok/tangga) stays in NOT_COVERED.
Everything below becomes real lines. Some elements map to the SAME kode as another with a
different qty — key ELEMENT_KODE_MAP by a unique element label, value = kode; compute qty per
label. Multiple labels may share a kode (that's fine).

Element → kode → qty (summed across levels unless noted):
- dinding → BATA_MERAH_1_4 → net_wall_area
- plesteran → PLESTERAN.1_4 → net_wall_area * 2
- acian → ACIAN.STANDAR → net_wall_area * 2
- cat_tembok → CAT.TEMBOK_BARU → net_wall_area * 2
- lantai_keramik → LANTAI.KERAMIK_40 → floor_area_indoor
- plafon_rangka → PLAFON.RANGKA_HOLLOW → floor_area_indoor
- plafon_gypsum → PLAFON.GYPSUM_9 → floor_area_indoor
- cat_plafon → CAT.PLAFON → floor_area_indoor
- atap_rangka → ATAP.RANGKA_BAJARINGAN_C75 → roof_footprint(top level) * ROOF_PITCH_FACTOR
- atap_penutup → ATAP.GENTENG_BETON → roof_footprint(top level) * ROOF_PITCH_FACTOR
- listplank → ATAP.LISTPLANK → exterior_perimeter(top level)
- kolom_praktis → BETON.KOLOM_PRAKTIS → (wall_length / KOLOM_PRAKTIS_SPACING_M) * WALL_HEIGHT_M
- ring_praktis → BETON.RING_PRAKTIS → wall_length
- pondasi → PONDASI.BATU_BELAH_1_4 → wall_length(level 1) * PONDASI_SECTION_M2   # m³
- kusen_pintu → KUSEN.ALUMINIUM → door_kusen_len_m
- daun_pintu → PINTU.PANEL_KAYU → door_leaf_area_m2
- kunci → HARDWARE.KUNCI_TANAM → door_count
- engsel → HARDWARE.ENGSEL → door_count*DOOR_HINGES + window_count*WINDOW_HINGES
- kusen_jendela → KUSEN.ALUMINIUM → window_kusen_len_m   (2nd label, same kode)
- daun_jendela → JENDELA.KACA_KAYU → window_leaf_area_m2
- kaca → KACA.POLOS_5 → glass_area_m2
- kait_angin → HARDWARE.KAIT_ANGIN → window_count
- km_kloset → SANITAIR.KLOSET_DUDUK → wet_room_count
- km_kran → SANITAIR.KRAN → wet_room_count
- km_floor_drain → SANITAIR.FLOOR_DRAIN → wet_room_count
- km_keramik_dinding → DINDING.KERAMIK_10_20 → wet_wall_perimeter * KM_TILE_HEIGHT_M
- km_waterproofing → WATERPROOFING.MEMBRAN → wet_floor_area
- listrik_lampu → LISTRIK.TITIK_LAMPU → indoor_room_count * LAMPU_PER_ROOM
- listrik_stopkontak → LISTRIK.STOP_KONTAK → indoor_room_count * STOPKONTAK_PER_ROOM
- listrik_saklar → LISTRIK.SAKLAR → indoor_room_count * SAKLAR_PER_ROOM
- listrik_mcb → LISTRIK.MCB_BOX → 1
- pipa_bersih → PIPA.AIR_BERSIH_HALF → (wet_room_count*2 + ... fixtures)*PIPA_BERSIH_PER_FIXTURE_M + RISER_M
    (fixtures = km_kloset+km_kran counts; keep it simple: wet_room_count*2*PIPA_BERSIH_PER_FIXTURE_M + RISER_M)
- pipa_kotor → PIPA.AIR_KOTOR_2 → wet_room_count * PIPA_KOTOR_PER_KM_M
- pompa → POMPA.JET_27 → 1
- toren → TANDON.TOREN_700 → 1

Elements whose qty is 0 (no wet rooms, no openings, etc.) → SKIP the line entirely
(don't emit a zero line). MCB/pompa/toren emit 1 only if the plan has ≥1 indoor room.

Keep the existing per-line dict shape; `kategori` comes from the coefficient. persist_rab
already groups by kategori — no change needed there.

## 4. Tests (backend/tests/integration/test_rab.py or a new test file)

- Unit-factor tests: assert the exact rate for at least LANTAI.KERAMIK_40 (keramik ÷6),
  BETON.KOLOM_PRAKTIS (besi ÷7.4), PLAFON.RANGKA_HOLLOW (hollow ÷4) against hand-computed
  Decimals using seeded coefficients + a seeded price fixture.
- A whole-plan test: a 2-room + 1-KM plan with a door + window → assert the RAB has lines for
  lantai, plafon, atap, kusen, kaca, kloset, listrik, pompa; grand_total > 0; zero price_missing.
- Keep existing tests green (adjust the dinding-only assertions to the new multi-line output).
- Run against the disposable Postgres the existing suite uses. All green before done.

## GATE (hard, for the executor)
Implement ALL of the above with REAL code — no placeholder, no TODO, no stubbed qty.
Every unit_factor EXACTLY as written (they are money). Write AND run the tests to green.
Do NOT commit. Report: files changed, test output, and any resource that still resolves
to price_missing (list them — the reviewer needs to see the residual gaps).
