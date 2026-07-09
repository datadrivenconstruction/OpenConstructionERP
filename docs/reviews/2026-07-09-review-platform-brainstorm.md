# Review: 2026-05-25-ai-civil-architecture-platform.md

**Date:** 2026-07-09 · **Reviewer:** Claude (Fable 5) via gaspol-review · **Verdict:** ⛔ **BLOCKING — doc tidak lagi match visi produk. 3 Critical, 3 Important. Wajib brainstorm-delta sebelum gaspol-plan.**

Visi baru (user, 2026-07-09): *platform arsitektur paling canggih untuk arsitek + interior designer — input requirement user → generate layout, 2D, 3D design, RAB, timeline pengerjaan, harga material berdasarkan lokasi bangunan.*

Semua temuan Critical/Important diverifikasi 2 research agent (GitHub API/README/PyPI live + web research per 2026-07-09).

---

## Gap Matrix: visi baru vs doc

| # | Visi | Di doc? | Gap |
|---|---|---|---|
| 1 | Requirement → **generate layout** | ❌ | Doc hanya 2D **editor** manual. Modul generatif tidak ada sama sekali |
| 2 | 2D design | ⚠️ | Editor ada (open3dFloorplan), generatif tidak |
| 3 | 3D design | ✅ | IFC.js viewer + photoreal render |
| 4 | RAB | ✅ | BOQ engine + SNI/AHSP — tapi qty takeoff via LLM (lihat I3) |
| 5 | **Timeline pengerjaan** | ❌ | Tidak ada modul |
| 6 | Harga material **per lokasi** | ⚠️ | Batam-only, 3 situs scrape; region = multiplier stub |
| 7 | Target: arsitek + interior designer pro | ⚠️ | Framing doc = renovasi rumah Ali; interior cuma render |

---

## Findings

### 🔴 C1 — Modul inti visi baru (generative layout) tidak ada — CONFIRMED
Value prop berubah dari "alat gambar + hitung" ke "AI generatif requirement→design". Doc tidak punya modul, tech, maupun phase untuk ini. Ini modul TERSULIT sekaligus diferensiator utama.

**SOTA 2026 (verified):**
- Open-source model: **GSDiff** (AAAI 2025, github.com/SizheHu/GSDiff — terbaru/terkuat), **MaskPLAN** (CVPR 2024, ETH, partial-constraint input), HouseDiffusion (baseline). Semua train di **RPLAN** (apartemen Asia) → domain gap rumah Indonesia (carport, musholla, KDB/KLB).
- Pattern LLM→graph→solver tervalidasi literatur (HouseLLM, ChatHouseDiffusion, Co-Layout 2025 = LLM emit constraints → ILP solver) tapi **tidak ada repo production-grade** — glue bikin sendiri.
- Komersial pembanding langsung: **Maket.ai** (hidup, text → multiple dimensioned layouts ±60s) — efektifnya productize rute solver.

**Fix:** modul baru `Layout Generator` — pipeline hybrid:
1. LLM structured-output: requirement → room list + adjacency graph + constraint (encode norma Indonesia: KDB/KLB, min-dim kamar, carport, musholla, area servis)
2. Geometry via **constraint solver deterministik** (BSP/rectangular-dualization/ILP à la Co-Layout) dalam envelope kavling — fully controllable, dimensioned, editable. GSDiff/MaskPLAN maksimal sebagai *seed* variasi yang solver regularize (diffusion tidak patuh dimensi eksak — fatal untuk produk berbasis RAB)
3. Output parametric vector (room = polygon + dims) → langsung feed qty takeoff RAB
Butuh riset spike phase tersendiri sebelum commit arsitektur.

### 🔴 C2 — AIStudioFloorPlan TANPA LISENSI — legal blocker — CONFIRMED
Repo exists (28★, stale sejak 2025-09) tapi **tidak ada LICENSE file → all-rights-reserved**. Doc bilang "Adapt AIStudioFloorPlan pattern" — meniru pola OK, reuse/fork kode **ilegal**. **Fix:** tulis modul render Gemini sendiri dari nol (polanya trivial: floor plan image + prompt → Gemini image API); hapus repo ini dari fork list, demote ke "reference only".

### 🔴 C3 — Timeline pengerjaan tidak ada — CONFIRMED (dan solusinya murah)
Requirement baru, absen total di doc. Kabar baik (verified): **AHSP Permen PUPR 1/2022** (+ SE 68/SE/Dk/2024, SE 182/SE/Dk/2025) memuat **Koefisien Tenaga Kerja** (OH per satuan volume) berlaku nasional → `durasi = volume × koefisien / jumlah crew`. Deterministik, tanpa AI tambahan. **Fix:** modul `Timeline Generator` — BOQ items (sudah punya volume + kode AHSP) → man-days → CPM/dependency sederhana antar pekerjaan (tanah→pondasi→struktur→arsitektur→MEP→finishing) → Gantt. Sinergi penuh dengan RAB engine, effort kecil, value besar.

### 🟠 I1 — Pricing per-lokasi: strategi nasional tidak ada — CONFIRMED
Doc = scrape 3 situs Batam + multiplier per region. Tidak scale ke "harga berdasarkan lokasi bangunan". Sumber riil (verified):
- **SIPASTI** (sipasti.pu.go.id): katalog harga satuan per wilayah, tapi login-gated untuk PPK pemerintah, **no public API/bulk download** — bukan sumber programatik
- **SSH/HSPK per pemda** (mandat Permendagri 90/2019 via SIPD): banyak pemda publish publik — MAS PETRUK Jateng (HSD+HSPK 35 kab/kota, browsable), Bangun Jakarta HSP, PDF/Excel BPKAD kabupaten. Fragmented tapi nyata → per-region ingestion adapter
- **BPS Web API** (webapi.bps.go.id): indeks IHPB bahan bangunan — untuk **interpolasi** region tanpa data dari anchor city
- Commercial API: **tidak ada** — layanan harga per-kota harus dibangun sendiri (justru moat)

**Fix:** schema multi-region dari hari 1 dengan **provenance per harga** (source, survey date, region) — bukan multiplier. Adapter pattern: scraper/importer per sumber. Launch Batam → ekspansi per provinsi via SSH publik + interpolasi BPS.

### 🟠 I2 — Interior design scope tipis
Visi menyebut interior designer sebagai persona utama; doc cuma punya photoreal render. **Fix:** tambah furniture/finish layer di floor plan + kategori BOQ interior (finishing, furniture, fixture) + render per-ruang. Minimal masuk backlog fase 2 dengan schema yang sudah mengakomodasi.

### 🟠 I3 — Qty takeoff RAB via LLM = risiko money-path
Doc: "Claude Opus tool-use: floor plan IFC → BOQ items + qty + total". LLM menghitung kuantitas = halusinasi angka di jalur uang. Apalagi setelah C1, layout hasil generate = parametric vector → luas/volume **dihitung deterministik dari geometri**. LLM hanya untuk mapping pekerjaan→kode AHSP + narasi. Catatan: "verify via PaddleOCR cross-check" tidak koheren (OCR memvalidasi PDF, bukan logika qty) — hapus.

### 🟡 Minor
- **M1:** Star count stale: OpenConstructionERP kini **474★, push 2026-07-08, AGPL-3.0 confirmed** — fork base makin sehat, klaim README (55k cost DB CWICR, PaddleOCR+YOLOv11, 4D/5D, cad2data) confirmed via README+PyPI v10.8.0 (belum diverifikasi dengan run kode)
- **M2:** aboen/rab = repo mati (last commit 2015, 0★, no license) — demote ke "contoh domain", bukan "schema reference"
- **M3:** "Real-time collaboration ✅ Keep" oversold — 1 mention di README 79KB, fitur marginal; jangan jadi dependency
- **M4:** Model AI stale: Opus 4.7/Sonnet 4.6 → Opus 4.8 / Fable 5 / Sonnet 5; cite SE 68/2024 + SE 182/2025 di bagian AHSP

### 💡 Recommendations
- **R1 — Reposisi produk:** framing "renovasi rumah Ali" → "platform pro untuk arsitek/interior designer, rumah Ali = pilot project & end-to-end test". AGPL tetap OK untuk SaaS (wajib publish source — sudah diterima di doc), tapi sadari kompetitor bisa fork.
- **R2 — Phase order baru (usulan):**
  0. Fork + Docker stack ✅ (tetap)
  1. Strip cost DB + seed SNI/AHSP + **koefisien tenaga kerja** (bekal timeline)
  2. **Riset spike: Layout Generator** (LLM→graph→solver, prototype 1 tipe rumah) ← paling berisiko, validasi paling awal
  3. Pricing multi-region: schema + adapter Batam + 1 provinsi SSH publik (bukti scale)
  4. Multi-tenant auth
  5. 2D editor (open3dFloorplan) sebagai **editor hasil generate**, bukan alat gambar utama
  6. RAB Generator (qty deterministik + LLM mapping AHSP)
  7. **Timeline Generator** (koefisien AHSP → Gantt)
  8. 3D + AI render (modul Gemini sendiri, bukan AIStudioFloorPlan)
  9. Interior layer
  10. Deploy + pilot rumah Batam

---

## Next step
Status doc "Design locked — ready for gaspol-plan" **dicabut**. Jalur: `gaspol-brainstorm` delta (lock keputusan C1 solver-vs-model, I1 strategi region, I2 scope interior) → update doc ini → baru `gaspol-plan`.
