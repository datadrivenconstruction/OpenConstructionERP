# ACAP Studio — pintu depan terpandu: gambar → layout → RAB → timeline → 3D → interior

**Status:** Design approved 2026-07-12 (brainstorm Fable 5 + Ali). Implementation plan (self-contained, 6 wave / 12 fase): **`docs/plans/2026-07-12-acap-studio-plan.md`** (di-split karena >500 baris).

## Design

### Masalah

Engine ACAP (fase 0–10) **selesai & terbukti** — pilot rumah Ali: RAB Rp 296,5 jt (35 baris, 0 `PRICE_MISSING`), timeline 234 hari. Tapi produk **tidak kepake**: satu-satunya UI adalah dashboard ERP OpenConstructionERP (RFI/HSE/NCR/BOQ/BIM) yang membingungkan bahkan di Simple mode. Halaman acap (layout/timeline/render) hanya reachable via URL manual; **tidak ada layar RAB sama sekali**; tidak ada jalur input dari gambar denah yang sudah dimiliki user.

### Keputusan (decision log, 2026-07-12)

| # | Keputusan | Pilihan Ali |
|---|---|---|
| 1 | Nasib shell ERP | **Bungkus** — bangun pintu depan ACAP Studio, ERP mundur ke "Advanced". TIDAK rombak total, TIDAK terusin prune menu. |
| 2 | Default setelah login | **ACAP Studio** (UI simple), bukan dashboard ERP. |
| 3 | Input denah | **Upload gambar → AI extract otomatis** (Gemini vision) + langkah konfirmasi/edit wajib. |
| 4 | Scope | **Semua 5 tahap dalam satu plan**, dieksekusi berurutan per wave dengan gate verify. |
| 5 | Bentuk 3D | **3D interaktif** — three.js extrude floor-plan JSON, orbit/walkthrough di browser. Client-side, deterministik. |
| 6 | Interior | **AI render interior per ruang** (pilih ruang + gaya → gambar). Dekoratif. |
| 7 | Vision model | **Gemini vision** (Google API key, key-gated), dibungkus adapter swappable. |

### Alur produk (stepper 7 langkah per project)

```
LOGIN → /studio (home: daftar project + [Mulai Estimasi])
→ pilih/buat project → /projects/:id/studio — stepper:

① Upload Gambar  drag-drop denah (JPG/PNG/PDF; screenshot SketchUp OK) → MinIO
② AI Extract     Gemini vision → draft rooms[] {nama, ukuran, bukaan}
③ Konfirmasi     tabel ruang+ukuran EDITABLE + link ke editor 2D existing;
                 Confirm → floor-plan JSON via geometric validator existing
④ RAB            engine RAB existing → tabel per kategori + total + flag
                 PRICE_MISSING + export CSV   ← layar BARU (belum pernah ada)
⑤ Timeline       engine timeline existing → Gantt (komponen existing) + CSV
⑥ 3D             three.js viewer: extrude floor-plan JSON (dinding, bukaan,
                 lantai), orbit + walkthrough. Read-only.
⑦ Interior       pilih ruang + gaya preset → render AI per ruang (engine
                 geminigen existing), galeri per ruang
```

Progress step **diderive dari keberadaan data** (ada gambar? ada layout? ada RAB?) — tanpa tabel state baru (ponytail).

### Invariant (tidak boleh dilanggar — warisan produk)

1. **Vision TIDAK PERNAH menulis langsung ke jalur angka.** extract → konfirmasi user → geometric validator → baru engine. LLM/vision tetap di luar jalur RAB.
2. **RAB 100% deterministik** — takeoff × koef AHSP × harga Batam. Harga hilang → `PRICE_MISSING`, bukan tebakan/0.
3. **Render & interior dekoratif** — gambar tidak pernah balik jadi angka.
4. **Authz server-side per-project** di setiap endpoint baru (pola Phase-8).
5. **API key** (Google/GeminiGen) exists-check only, tidak pernah di-log/echo; UI degrade anggun saat key absen (pola RenderPage).

### Data Integration Map

| Komponen | Sumber data | Existing? | Catatan |
|---|---|---|---|
| Upload gambar | MinIO via backend | bucket ada (dipakai render) | prefix/route baru `plan-images` |
| AI extract | Gemini vision API | **BARU** | env `GOOGLE_API_KEY` (bukan GeminiGen/snapgen); adapter interface; structured output rooms[] |
| Layout + validator | `backend/app/modules/acap/` layout | ✅ | konfirmasi menghasilkan layout via jalur existing |
| Editor 2D | `frontend/src/acap/FloorPlanEditor*` | ✅ | dipanggil dari step ③ |
| RAB engine | `backend/app/modules/acap/rab/` + 159 baris harga Batam | ✅ terbukti | frontend RAB page **BARU** |
| Timeline engine | modul acap timeline + `GanttChart.tsx` | ✅ terbukti | dibungkus step ⑤ |
| 3D viewer | floor-plan JSON, client-side | **BARU** | dep baru: `three` (+ renderer React) — satu-satunya dependency baru |
| Interior render | client geminigen existing | engine ✅ | prompt template gaya (minimalis/skandinavia/japandi/industrial/klasik) **BARU** |
| Studio shell + redirect | React Router existing | routing baru | login → `/studio`; ERP tetap di route lama via link "Advanced" |

### Wave eksekusi (1 plan, gate verify per wave)

- **W0 — Shell:** route `/studio` + `/projects/:id/studio` (stepper kosong ber-guard), login redirect → `/studio`, nav "ACAP Studio".
- **W1 — Input:** upload → MinIO; endpoint extract (Gemini adapter); step konfirmasi/edit → floor-plan JSON tersimpan via validator.
- **W2 — Angka:** halaman RAB (baru) + Timeline dibungkus ke stepper. Ini payoff inti — angka Batam nyata di UI.
- **W3 — 3D:** three.js viewer dari floor-plan JSON.
- **W4 — Interior:** preset gaya + render per ruang + galeri.
- **W5 — Polish:** default route final, label bahasa Indonesia, smoke test end-to-end pakai project "Dutamas my dream house".

### Risiko & mitigasi

| Risiko | Mitigasi |
|---|---|
| Gemini salah baca ukuran | Step ③ konfirmasi wajib; angka tidak jalan sebelum user confirm; validator geometri existing |
| Vite build RAM (≥12 GB, isu lama) | three.js lazy-loaded route; build flag `NODE_OPTIONS=--max-old-space-size` didokumentasi di plan |
| snapgen/GeminiGen down (interior/render) | key-gate + pesan anggun (pola RenderPage existing); W4 tidak memblok W0–W3 |
| Scope besar (7 step) | wave berurutan + gate verify per wave; W0–W2 sudah menghasilkan produk kepake |

### Out of scope (eksplisit)

- Furniture placement editor (interior = render gambar saja).
- Estimasi biaya interior ke RAB (butuh data harga baru — backlog).
- Multi-region pricing, IFC export, deploy VPS (backlog lama, tidak disentuh).
- Menghapus/merombak modul ERP (hanya demote dari default route).
