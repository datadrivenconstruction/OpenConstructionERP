# AI Civil Architecture Platform — Implementation Plan

> **For Claude:** REQUIRED SKILL: Use gaspol-execute to implement this plan.
> **CRITICAL:** This plan specifies real integrations. During execution,
> NEVER substitute placeholders for real data sources without explicit
> user approval. If a data source doesn't exist yet, STOP and ask.

**Date:** 2026-07-09 · **Planner:** Claude (Fable 5) via gaspol-plan
**Inputs:** [Brainstorm 2026-05-25](2026-05-25-ai-civil-architecture-platform.md) + [Review 2026-07-09](../reviews/2026-07-09-review-platform-brainstorm.md) (BLOCKING findings resolved via locked decisions below)

## Goal

Platform untuk arsitek + interior designer: input requirement klien → generate floor plan (data terstruktur + visual), RAB berbasis SNI/AHSP dengan harga Batam riil, timeline pengerjaan dari koefisien tenaga kerja AHSP, export PDF. Fork OpenConstructionERP sebagai fondasi (BOQ engine, BIM ingest, cost DB infra). Pilot: renovasi rumah Ali di Batam.

## Locked Decisions (2026-07-09, user)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| D1 | Layout generation | **LLM → structured floor plan JSON** (source of truth) → **indusia-image-gen** render visual | Raster image TIDAK PERNAH jadi sumber qty RAB. Qty dihitung deterministik dari JSON geometry. Image-gen = visual layer saja. Tidak perlu diffusion model / ILP solver di MVP — placement rectangle deterministik sederhana. `ponytail:` simple rect-packer, upgrade ke constraint solver kalau layout kompleks (L-shape, split-level) dibutuhkan |
| D2 | Pricing region | **Batam-only** untuk MVP | Schema tetap punya kolom `region_id` + provenance (source, scraped_at) — data cuma Batam, struktur tidak perlu rework saat ekspansi |
| D3 | Interior | **Layer fase lanjut** | BOQ schema include kategori interior (finishing/furniture/fixture) dari Phase 1; UI furniture placement + render per-ruang = post-MVP |
| D4 | Render engine | indusia-image-gen (bukan Gemini direct, bukan AIStudioFloorPlan) | Solve legal blocker C2 (AIStudioFloorPlan no-license). AIStudioFloorPlan = reference pattern only, zero code reuse |
| D5 | Timeline | Deterministik dari koefisien tenaga kerja AHSP Permen PUPR 1/2022 | `durasi = volume × koef_OH / crew_size`, tanpa AI |

## Architecture Context

Repo saat ini KOSONG (hanya `docs/` + `graphify-out/`) — belum ada CLAUDE.md project, belum ada kode. Phase 0 menciptakan codebase (fork). Fondasi fork (verified 2026-07-09): OpenConstructionERP 474★, push 2026-07-08, AGPL-3.0, Python/FastAPI + React/TS, BOQ hierarchical editor, cad2data (IFC/RVT/DWG), PaddleOCR takeoff, 55k cost DB (di-strip, ganti SNI/AHSP + Batam), PyPI `openconstructionerp` v10.8.0.

**Konsekuensi AGPL:** repo publik `github.com/alisadikinma/ai-civil-architecture` dari commit pertama, LICENSE AGPL-3.0, README disclose fork origin.

## Tech Stack

- **Backend:** Python 3.12 + FastAPI (dari fork), PostgreSQL 16, MinIO (files), APScheduler (cron scraper)
- **Frontend:** React 18 + TS + Vite (dari fork), open3dFloorplan (MIT — embed/port utk edit hasil generate), Three.js/IFC.js viewer (dari fork)
- **AI:** Claude API (Fable 5/Sonnet 5 — layout JSON generation, structured output), indusia-image-gen service (visual render)
- **Qdrant/LanceDB dari fork:** `ponytail:` JANGAN aktifkan di MVP — cost matching cukup SQL exact + trigram match dulu; vector search kalau fuzzy matching terbukti perlu
- **Deploy:** Docker Compose + Traefik, server Batam / VPS

## Data Integration Map

| Feature | Data Source | Hook/API | Exists? | Action |
|---------|-------------|----------|---------|--------|
| BOQ items + editor | Postgres `boq_items` (fork schema) | fork REST API | ✅ in fork | Use as-is |
| Koefisien SNI/AHSP | Postgres `ahsp_coefficients` — seed dari PDF AHSP Permen PUPR 1/2022 (Bidang Umum + Cipta Karya, free download) + SNI 2835/2836/2837/7395 | new tables + seed YAML | ❌ | Phase 1 — manual parse ke YAML version-controlled, loader script. Termasuk `koef_tenaga_kerja` (OH) per pekerjaan utk timeline |
| Harga material/upah Batam | Scrape arsiteqi.or.id, sobatbangun.com, mbdkontraktor.com → Postgres `material_prices` (region_id, source, scraped_at) | new scraper module + APScheduler weekly | ❌ | Phase 2 — Firecrawl extract per-site adapter; fallback Claude HTML→JSON |
| Floor plan structured | Postgres `floor_plans` JSONB — schema: rooms[] {name, type, polygon[[x,y]], area_m2}, walls[], openings[], floor_level | new | ❌ | Phase 3 — JSON = SINGLE SOURCE OF TRUTH utk editor, render, qty |
| Layout generation | Claude API structured output (requirement text → floor plan JSON) | new `layout_generator` service, ANTHROPIC_API_KEY | ❌ | Phase 3 — validasi geometri post-gen (no overlap, min-dim, total ≤ luas kavling); regenerate on fail (max 3), lalu STOP + surface error |
| 2D editor | open3dFloorplan (MIT) load/save floor plan JSON | embed + JSON adapter | ✅ repo (62★) | Phase 4 — adapter dua arah JSON kita ↔ format editor |
| Qty takeoff | **Deterministik dari floor plan JSON** (shoelace area, keliling dinding, count openings) — BUKAN LLM | new `takeoff.py` pure functions | ❌ | Phase 5 — LLM hanya utk mapping pekerjaan→kode AHSP, angka dari geometri |
| RAB output | qty × koefisien AHSP × harga Batam → `boq_items` fork | new `rab_generator` service | ❌ | Phase 5 |
| Timeline | `boq_items` volume × `koef_tenaga_kerja` / crew → man-days → urutan tahapan (tanah→pondasi→struktur→dinding→atap→MEP→finishing) → Gantt JSON | new `timeline_generator` | ❌ | Phase 6 |
| Visual render | indusia-image-gen service (floor plan JSON → prompt+referensi → image), output ke MinIO + `renders` table | ⚠️ MCP exists utk Claude session; platform backend butuh DIRECT endpoint ke service di baliknya | ⚠️ partial | Phase 7 — **STOP & tanya Ali**: endpoint/API-key service indusia-image-gen utk server-side call. Jangan stub |
| Auth multi-tenant | Supabase Auth + RLS Postgres (tenant per project) | supabase-py + fork user model | ❌ | Phase 8 |
| Export PDF | fork export module (BOQ) + tambah lembar floor plan image + Gantt | ✅ partial in fork | Extend Phase 5/6 |
| Audit log | fork `audit_log` | ✅ in fork | Use as-is |

## Phases

**Urutan by risk:** koefisien+harga (bahan baku) → layout gen (jantung produk) → RAB → timeline → render → auth → deploy. Phase 2 ∥ Phase 3 (independen — kandidat gaspol-parallel).

---

### Phase 0: Fork + stack hidup lokal

**Estimated:** 60 min
**Files:** repo baru (fork), `docker-compose.yml`, `.env.example`, `README.md` (AGPL disclosure)

**Steps:**
1. Fork `datadrivenconstruction/OpenConstructionERP` → `alisadikinma/ai-civil-architecture`, clone, pin ke tag/commit terbaru (catat SHA di README — basis cherry-pick bulanan)
2. `docker compose up` stack fork (Postgres, backend, frontend); matikan service yang MVP tak pakai (Qdrant/LanceDB) dari compose
3. Smoke test: buka UI, buat project dummy, buat 1 BOQ item manual
4. Write failing test for healthcheck endpoint kita sendiri (`tests/test_health.py`). Expected error: `404 /api/v1/acap/health`
5. Implement `/api/v1/acap/health` (namespace module kita terpisah dari fork core), test pass
6. Commit: "chore: fork base + acap module namespace + docker stack"

**Verification:**
- [ ] `docker compose up` → UI + API hidup
- [ ] BOQ item manual bisa dibuat via UI fork
- [ ] Test suite fork masih pass (regression baseline)
- [ ] `/api/v1/acap/health` 200
- [ ] LICENSE AGPL-3.0 + README fork disclosure ada

---

### Phase 1: Seed koefisien SNI/AHSP (+ tenaga kerja)

**Estimated:** ~1 minggu kalender (manual parse PDF), coding 90 min
**Files:** Create `acap/data/ahsp/*.yaml`, `acap/models/coefficients.py`, `acap/seed.py`, `tests/test_coefficients.py`

**Steps:**
1. Download PDF AHSP Bidang Umum + Cipta Karya (Permen PUPR 1/2022; cek update SE 68/SE/Dk/2024). Pilih subset pekerjaan rumah tinggal 2 lantai (~80-150 item: tanah, pondasi, beton, dinding, plesteran, lantai, atap, plafon, cat, sanitair, listrik) — `ponytail:` subset dulu, bukan seluruh AHSP; tambah item saat RAB riil butuh
2. Write failing test for YAML schema loader (`test_coefficients.py`: load 1 sample YAML → objek dengan material[], upah[] {koef OH}, alat[]). Expected error: `ModuleNotFoundError: acap.models.coefficients`
3. Implement model + loader, test pass
4. Parse manual PDF → YAML per kategori (`{kode_ahsp, uraian, satuan, bahan[{nama, satuan, koef}], tenaga[{jabatan, koef_oh}], alat[]}`), version-controlled
5. Write failing test for seed idempotency (run 2× → row count sama). Expected error: `AssertionError: duplicate rows`
6. Implement `seed.py` upsert by `kode_ahsp`, test pass
7. Spot-check 5 item vs PDF asli (angka koefisien exact match)
8. Commit per kategori YAML + "feat: AHSP coefficient DB + seed"

**Verification:**
- [ ] ≥80 pekerjaan ter-seed, termasuk koef tenaga kerja (bekal Phase 6)
- [ ] Kategori interior (finishing/cat/lantai/plafon) ada (D3 — schema akomodasi interior)
- [ ] Seed idempotent, spot-check 5 item = PDF
- [ ] tests pass

---

### Phase 2: Batam price scraper

**Estimated:** 120 min
**Files:** Create `acap/scraper/{base,arsiteqi,sobatbangun,mbd}.py`, `acap/models/prices.py`, `tests/test_scraper.py`

**Steps:**
1. Write failing test for price model provenance (insert tanpa `source`/`region_id`/`scraped_at` → error). Expected error: `IntegrityError: NOT NULL`
2. Implement `material_prices` (region_id FK → `regions` seed: Batam; D2: satu region, schema region-aware), test pass
3. Write failing test for arsiteqi adapter parsing (fixture HTML tersimpan → list upah). Expected error: `ModuleNotFoundError: acap.scraper.arsiteqi`
4. Implement adapter arsiteqi (upah tukang) via Firecrawl extract / httpx+selectolax, test pass vs fixture
5. Ulangi pola 3-4 untuk sobatbangun (material) + mbdkontraktor (material)
6. Fallback: kalau parse gagal → Claude HTML→JSON (log `extraction_method`)
7. APScheduler weekly job + alert Telegram on failure rate >50% (`ponytail:` alert = simple bot sendMessage, no monitoring stack)
8. Run scrape riil sekali, spot-check 10 harga vs situs
9. Commit: "feat: Batam price scraper (3 sites, weekly)"

**Verification:**
- [ ] 3 adapter jalan vs fixture + 1 run riil sukses
- [ ] Tiap row punya provenance (source, scraped_at, region=Batam)
- [ ] Scheduler terdaftar; kegagalan ter-log + alert
- [ ] tests pass

---

### Phase 3: Layout Generator (requirement → floor plan JSON) — JANTUNG PRODUK

**Estimated:** 180 min + eval iterasi
**Files:** Create `acap/layout/{schema.py,generator.py,validator.py}`, `acap/api/layout.py`, `tests/test_layout.py`, `docs/evals/layout-generator.md`

**Steps:**
1. Write failing test for floor plan JSON schema (pydantic: rooms[{name,type,polygon,area_m2}], walls, openings, levels; polygon closed & CCW). Expected error: `ModuleNotFoundError: acap.layout.schema`
2. Implement schema, test pass
3. Write failing test for geometric validator (2 room overlap → invalid; kamar < 6m² → invalid; total > kavling → invalid). Expected error: `NameError: validate_plan`
4. Implement validator (shapely — cek dep di fork dulu, kalau ada pakai itu), test pass
5. Write failing test for generator retry loop (mock LLM return invalid 3× → raises `LayoutGenerationError`, TIDAK return plan rusak). Expected error: `NameError: generate_layout`
6. Implement generator: Claude API structured output. Prompt encode norma rumah Indonesia: KDB/KLB, min-dim kamar (SNI), carport, musholla opsional, service area, sirkulasi. Input: requirement text + dimensi kavling + jumlah lantai. Output: floor plan JSON per lantai. Validate → retry max 3 → fail loud
7. **Eval (gaspol-eval, non-deterministic phase):** tulis `docs/evals/layout-generator.md` — 10 fixture requirement riil (termasuk rumah Ali: 2 lantai, renovasi) → assert: valid geometry 10/10, room yang diminta ada, luas ±10% dari requirement. Target pass@3 ≥ 8/10
8. API endpoint `POST /api/v1/acap/projects/{id}/layout:generate` (simpan ke `floor_plans`, versioned — generate ulang = versi baru, tidak overwrite)
9. Commit: "feat: layout generator (LLM structured → validated floor plan JSON)"

**Verification:**
- [ ] Invalid geometry TIDAK PERNAH tersimpan (validator gate)
- [ ] Eval pass@3 ≥ 8/10 fixture
- [ ] Requirement rumah Ali → layout masuk akal (review manual Ali)
- [ ] Versioning: regenerate tidak menghapus versi lama
- [ ] tests + `mypy`/`ruff` pass

---

### Phase 4: 2D editor (edit hasil generate)

**Estimated:** 120 min
**Files:** Create `frontend/src/acap/FloorPlanEditor.tsx`, `frontend/src/acap/planAdapter.ts`, test `planAdapter.test.ts`

**Steps:**
1. Write failing test for adapter round-trip (floor plan JSON → format open3dFloorplan → balik → deep-equal). Expected error: `Cannot find module './planAdapter'`
2. Implement adapter dua arah, test pass
3. Embed open3dFloorplan (MIT): `ponytail:` iframe + postMessage dulu, port React hanya kalau iframe UX terbukti gagal
4. Load layout hasil Phase 3 → edit (geser dinding, resize room) → save = versi floor plan baru via API
5. Commit: "feat: 2D editor embed, edit generated layout"

**Verification:**
- [ ] Layout generate → tampil di editor → edit → save → reload konsisten
- [ ] Round-trip adapter lossless (test)
- [ ] Attribution MIT open3dFloorplan di README
- [ ] tsc --noEmit pass

**Design deliverable:** layout viewer/editor page — invoke `gaspol-design` saat execute (tokens dari fork UI, jangan bikin design system baru).

---

### Phase 5: RAB Generator (geometry → qty → harga)

**Estimated:** 150 min
**Files:** Create `acap/takeoff.py`, `acap/rab/generator.py`, `tests/test_takeoff.py`, `tests/test_rab.py`

**Steps:**
1. Write failing test for takeoff pure functions (fixture floor plan JSON kamar 3×4 → luas lantai 12 m², keliling dinding, luas dinding − openings, luas plafon/atap). Expected error: `ModuleNotFoundError: acap.takeoff`
2. Implement takeoff deterministik (shoelace, perimeter, opening subtraction) — **ZERO LLM di jalur angka**, test pass exact
3. Write failing test for RAB assembly (qty × koef AHSP × harga Batam terbaru → line items + subtotal per kategori + total; harga hilang → item flagged `PRICE_MISSING`, BUKAN qty=0 / harga tebakan). Expected error: `NameError: generate_rab`
4. Implement: mapping jenis-pekerjaan ← ruang/elemen. LLM hanya untuk map elemen→kode AHSP (structured, dari daftar kode ter-seed — closed vocabulary, invalid code = validation error); angka 100% dari takeoff × koefisien × harga. Simpan sebagai `boq_items` fork (hierarki: kategori→pekerjaan)
5. Test pass; hitung RAB 1 fixture manual di spreadsheet → bandingkan (toleransi 0%: deterministik harus exact)
6. Export PDF via module fork + lembar ringkasan
7. Commit: "feat: RAB generator — deterministic takeoff, AHSP pricing"

**Verification:**
- [ ] Qty match hitungan manual spreadsheet EXACT
- [ ] Item tanpa harga → flagged, tidak silent
- [ ] RAB muncul di BOQ editor fork (edit manual tetap bisa)
- [ ] PDF export jalan
- [ ] tests pass

---

### Phase 6: Timeline Generator

**Estimated:** 90 min
**Files:** Create `acap/timeline/generator.py`, `acap/data/task_sequence.yaml`, `tests/test_timeline.py`, frontend Gantt view

**Steps:**
1. Write failing test for duration calc (volume 100 m² plesteran, koef 0.3 OH/m², crew 3 → 10 hari). Expected error: `ModuleNotFoundError: acap.timeline`
2. Implement `durasi = volume × koef_oh / crew_size` (crew default per jenis pekerjaan, configurable), test pass
3. Write failing test for sequencing (pondasi selesai sebelum struktur mulai; pekerjaan independen paralel). Expected error: `NameError: build_schedule`
4. Implement urutan via `task_sequence.yaml` statis (tahapan konstruksi rumah: persiapan→tanah→pondasi→struktur→dinding→atap→MEP→plesteran→lantai→plafon→cat→finishing) — `ponytail:` dependency template statis, bukan CPM solver; upgrade kalau proyek non-rumah masuk
5. Output Gantt JSON + render frontend (`ponytail:` cek chart lib yang SUDAH ada di fork dulu; kalau tak ada → frappe-gantt, satu dep kecil)
6. Commit: "feat: timeline from AHSP labor coefficients"

**Verification:**
- [ ] Durasi match hitung manual
- [ ] Urutan tahapan valid (test dependency)
- [ ] Gantt tampil dari RAB rumah fixture
- [ ] tests pass

---

### Phase 7: Visual render via indusia-image-gen (D1/D4)

**Estimated:** 120 min — **GATE: butuh input Ali dulu**
**Files:** Create `acap/render/service.py`, `acap/api/render.py`, `tests/test_render.py`

**Steps:**
1. **STOP — tanya Ali:** endpoint + auth service di balik MCP indusia-image-gen untuk dipanggil server-side dari FastAPI (MCP session Claude ≠ akses backend platform). Tanpa ini phase tidak mulai. JANGAN stub
2. Write failing test for prompt builder (floor plan JSON → prompt deskriptif: denah top-down / isometric / photoreal eksterior; room list + dims masuk prompt verbatim). Expected error: `ModuleNotFoundError: acap.render`
3. Implement prompt builder + client service indusia-image-gen, test pass (client di-mock di unit test; 1 integration test riil)
4. Simpan output → MinIO + `renders` (project_id, floor_plan_version, prompt, model, url) — render terikat VERSI floor plan
5. Cache by hash(prompt+version) — regenerate hanya kalau plan berubah
6. UI: tombol render di halaman layout, gallery per versi
7. Commit: "feat: visual render via indusia image-gen service"

**Verification:**
- [ ] 1 render riil sukses dari floor plan rumah fixture
- [ ] Render ter-link ke versi floor plan; cache hit saat repeat
- [ ] Failure service → error jelas di UI, bukan spinner abadi
- [ ] Secrets di env, bukan source (security line)

---

### Phase 8: Multi-tenant auth (Supabase) — SECURITY-SENSITIVE

**Estimated:** 150 min
**Files:** Modify fork auth layer, Create `acap/auth/`, RLS migrations, `tests/test_tenant_isolation.py`

**Steps:**
1. Write failing test for tenant isolation (user A query project user B → 403/empty). Expected error: `NameError: tenant fixture`
2. Setup Supabase project + supabase-py; JWT verify middleware FastAPI
3. Postgres RLS: `tenant_id` di projects/floor_plans/boq_items/renders; policy per tenant — **authz server-side, bukan filter frontend**
4. Test isolation pass (positif + negatif)
5. Migrasi data existing (project pilot Ali) ke tenant pertama
6. Commit: "feat: multi-tenant auth + RLS isolation"

**Verification:**
- [ ] Cross-tenant access DITOLAK (test membuktikan)
- [ ] Inputs validated, queries parameterized, no secrets in source, authz server-side
- [ ] `gaspol-security-review` dijalankan (auto via gaspol-execute Step 3.6)
- [ ] Login → project switcher jalan end-to-end

---

### Phase 9: Deploy (server Batam / VPS)

**Estimated:** 90 min
**Files:** `docker-compose.prod.yml`, Traefik config, backup script

**Steps:**
1. Compose prod: Traefik (Let's Encrypt) + Postgres + API + frontend + MinIO; scraper scheduler aktif
2. Deploy, smoke test HTTPS end-to-end (generate layout → RAB → timeline → render)
3. `pg_dump` nightly cron + restore drill 1× (data-loss guard — bukan optional)
4. Commit: "chore: production deploy config"

**Verification:**
- [ ] HTTPS valid, semua flow jalan di prod
- [ ] Restore drill sukses (backup terbukti bisa balik)
- [ ] Weekly scrape jalan di prod (cek log minggu pertama)

---

### Phase 10: Pilot — rumah Ali (end-to-end acceptance)

**Estimated:** sesi dengan Ali
**Steps:**
1. Input requirement renovasi rumah 2 lantai Batam riil → generate layout → Ali edit di 2D editor → RAB → timeline → render
2. Bandingkan RAB vs penawaran kontraktor riil (kalau ada) — kalibrasi harga/koefisien
3. Catat gap → backlog (kandidat: interior layer D3, multi-region D2, IFC export)

**Verification:**
- [ ] Ali dapat dokumen lengkap (layout PDF + RAB + Gantt + render) untuk renovasi riil
- [ ] Deviasi RAB vs realita dicatat sebagai kalibrasi issue

---

## Parallelization

| Wave | Phases | Note |
|---|---|---|
| 1 | 0 | fondasi |
| 2 | 1 ∥ 2 ∥ 3 | koefisien, scraper, layout-gen independen (file-isolated) |
| 3 | 4 ∥ 5 | editor (frontend) ∥ RAB (backend) — 5 depend 1+3 |
| 4 | 6 ∥ 7 | timeline ∥ render — 7 gated input Ali |
| 5 | 8 → 9 → 10 | sequential |

## Cut dari MVP (YAGNI — catat, jangan bangun)

- Multi-region pricing (D2) — schema siap, data belakangan
- Interior UI layer (D3) — schema siap
- Diffusion/solver layout canggih — upgrade path di D1
- Qdrant/LanceDB vector search — SQL dulu
- IFC export dari editor — fork sudah bisa import glTF kalau perlu
- Real-time collaboration — fitur marginal di fork (review M3), jangan diandalkan

## Next Step

`gaspol-execute` per phase (executor sesuai mode sesi; review + commit tetap di brain), atau `gaspol-parallel` untuk Wave 2.
