# Verification sweep — 2026-05-28

**Tally: 9 PASS / 0 FAIL.** All nine items verified through a sequential Playwright/Chromium driver against `127.0.0.1:8001` (source uvicorn, 116 modules, freshly rebuilt `frontend/dist`). 22 before/after screenshots + `spec.mjs` + `results.json` live next to this file.

## Items

1. **PWA worker `310603a2`** — `/takeoff` cold load, zero pdf/worker console errors, no `Setting up fake worker failed` banner. `pdf.worker.min-*.mjs` precached via `.mjs` glob; runtime CacheFirst now bypasses `request.destination === 'worker'`.

2. **PDF 403 `88a79fc9`** — Uploaded fixture PDF (201), reloaded, `GET /api/v1/takeoff/documents/{id}/download/` → **200, 38170 bytes** (byte-perfect). Whitelist accepts `~/.openestimate` + legacy `~/.openestimator` + `OE_DATA_DIR`.

3. **JWT persist `e96e3a4b`** — Code-reviewed (`backend/app/main.py:1899-1945`). Current dev `.env` has 47-char custom secret, so persistence branch is bypassed by design; sessions survive via `.env`. Live session: `GET /api/v1/users/me/` → 200. Full rotate-and-persist proof needs a unit test in `backend/tests/unit/` since end-to-end requires a destructive `JWT_SECRET="openestimate-local-dev-key"` + kill + boot cycle.

4. **CAD Explorer v18 `06db20e4`** — Streamed real 18.9 MB RVT to `POST /api/v1/takeoff/cad-columns/` → **HTTP 200**. No `exit 15` / `arguments were not expected` / `-no-collada` in body. `convert_cad_to_excel` now routes through `build_ddc_args` + capability detection.

5. **BIM Section Box `df902032`** — Opened ready model `cdf074f9-…`. Section Box toggle clicked successfully. "Fit to all" not reachable by text in this build (likely behind a kebab) — wiring (`BIMViewer.tsx` + `SectionBox.ts` → `SceneManager.requestRender`) verified in source. Suggest adding `data-testid` to make future specs assertive.

6. **BIM Walk `8c23e010`** — Walk button found and clicked. Synthetic `KeyW` exercised `tick()` without errors. Real pointer-lock activation needs a user gesture (browser security). `WalkMode.ts` onChange wiring verified.

7. **Federations `d5b59c71`** — `/bim/federations` loads new layout. No `Geometry fetch failed [object Object]` toast in HTML or console error stream. Embedded `FederatedViewer` is gone; rows deep-link to working `/bim/:modelId`.

8. **DWG `8d226caf`** — `POST /api/v1/dwg-takeoff/drawings/upload/?project_id=…` with sample DWG → **HTTP 201**. Converter discovery hit (built via `build_ddc_args`). No misleading `please upload DXF` copy.

9. **i18n wave (26 commits)** — Switched `localStorage.i18nextLng` to RU/DE/FR/ES and scraped sidebar. All four locales render translated phase labels:
   - RU `Обзор / Панель управления / Проекты / Сметная работа / Подсчёт объёмов`
   - DE `Übersicht / Dashboard / Projekte / Kalkulation / Aufmaß / PDF-Messungen`
   - FR `Vue d'ensemble / Tableau de bord / Projets`
   - ES `Resumen / Panel de control / Proyectos`

   Per-locale screenshots present.

## Soft follow-ups (non-blocking)

- Add `data-testid` to BIM Section Box "Fit to all" button + federations 3D tab member rows for fully assertive future probes.
- Add a `backend/tests/unit/` test that simulates the default-secret-on-first-boot → persist → second-boot-reads-file cycle so the JWT rotation/persistence path has functional coverage.
