# ACAP Studio — Implementation Plan

> **For the executor (opencode, blind execution):** This plan is SELF-CONTAINED — every file path, endpoint signature, schema, and verify command you need is inline. Do not read other docs unless a step names one. REQUIRED behavior: gaspol-execute discipline (TDD per phase, no placeholders).
> **CRITICAL:** This plan specifies real integrations. NEVER substitute placeholders for real data sources. If a data source doesn't exist yet and this plan doesn't define it, STOP and record the blocker in the progress ledger.
> **COMMITS: the executor NEVER commits or pushes.** Supervisor (Claude/Ali) reviews the diff per wave and commits. Per-phase checkpoint = verify commands PASS + progress ledger updated.
> **Progress ledger:** create `.gaspol/progress/acap-studio.md` in Phase 0.1 (template at the bottom of this plan) and update it after EVERY phase (status + verify output summary). Add `.gaspol/` to `.gitignore` if not present.

Design & decisions (approved 2026-07-12): `docs/plans/2026-07-12-acap-studio.md`. Read it once for context; everything operational is repeated here.

## Goal

Build "ACAP Studio" — a guided 7-step flow (Upload gambar → AI Extract → Konfirmasi → RAB → Timeline → 3D → Interior) as the product's front door, wrapping the PROVEN acap engines (RAB Rp 296.5jt pilot, timeline 234 days). New: image upload, Gemini-vision extraction (adapter, key-gated), a first-ever RAB screen, a three.js 3D viewer, interior renders per room. Login lands on `/studio`.

## Architecture Context (ground truth, verified 2026-07-12)

**Backend** (FastAPI, module `backend/app/modules/acap/`):
- Single router `backend/app/modules/acap/router.py`, auto-mounted at prefix **`/api/v1/acap`** by `backend/app/core/module_loader.py:207-211`. New endpoints go in this same router.py.
- Auth on every endpoint: `payload: dict = Depends(get_current_user_payload)` (from `app.dependencies`). Per-project guards called imperatively inside handlers (`backend/app/modules/acap/authz.py`): `await require_project_access(session, project_id, payload)` (read; 404 on denial) / `await require_project_owner(session, project_id, payload)` (write; 403/404).
- Session dependency: local `get_session` in router.py:44-52 (commits on success).
- **FloorPlan schema** (`backend/app/modules/acap/layout/schema.py`, pydantic v2, units METERS, origin SW, x→east y→north):
  - `Point{x: float, y: float}`
  - `ROOM_TYPES` Literal: `kamar_tidur_utama|kamar_tidur|kamar_mandi|dapur|ruang_tamu|ruang_keluarga|ruang_makan|carport|garasi|musholla|gudang|teras|taman|sirkulasi|other`
  - `Room{name: str, type: ROOM_TYPES, polygon: list[Point] (exactly 4 corners CCW, first not repeated), area_m2: float ≥ 0}`
  - `Wall{start: Point, end: Point, thickness_m: float = 0.15}`
  - `Opening{type: "door"|"window", room: str, width_m: float > 0}` (NO coordinates)
  - `Level{level: int ≥ 1, rooms: [], walls: [], openings: []}`
  - `Kavling{width_m > 0, length_m > 0}`
  - `FloorPlan{kavling, levels, requirement_text="", jumlah_lantai≥1=1, generated_by="", notes=""}`
- Validator: `validate_plan(plan)` in `layout/validator.py:115` raises `LayoutValidationError(.reasons)`; non-raising `is_valid(plan) -> tuple[bool, list[str]]` at validator.py:233. Checks: axis-aligned 4-corner rects, shoelace area tolerance 0.05, min area per type, min dim 1.2m, inside kavling, no overlaps, KDB ≤ 0.7.
- Layout persistence: table `oe_acap_floor_plan` (`models/floor_plan.py`), versioned via `next_version(session, project_id)`, unique (project_id, version). `PUT /projects/{id}/layout` (body = FloorPlan) validates then saves status="edited"; `GET /projects/{id}/layout` returns `{version, status, plan}` or 404.
- RAB: `POST /projects/{id}/rab:generate` → `GenerateRabResponse{boq_id, grand_total: str, subtotals_by_kategori: dict[str,str], lines: list[dict], price_missing_lines, curated_lines, not_covered}`. Line dict: `{kode, uraian, unit, quantity, unit_rate, total, price_missing: bool, missing_resources, curated_resources, kategori}`. Engine `rab/generator.py::generate_rab(session, plan, project_id)` — deterministic, Decimal, PRICE_MISSING excluded from grand_total.
- Timeline: `POST /projects/{id}/timeline:generate` → `{total_days, tasks, stages, not_covered}`; `GET /projects/{id}/timeline.csv` (attachment).
- Render (pattern to MIRROR for vision + interior): `render/client.py` — plain httpx REST, env read directly `os.environ.get("GEMINIGEN_API_KEY")`, exists-check `render_service_configured()`, endpoint returns **400** `{"detail": {"detail": "...not configured", "reason": "GEMINIGEN_API_KEY not set"}}` AFTER authz. Provider failure → record `status="failed"`, never raised. Storage: `from app.core.storage import get_storage_backend`; `await storage.put(key, content)`; key pattern `f"acap/renders/{project_id}/{uuid}.png"`. Snapgen client entry: `generate_render_image(prompt, *, model="nano-banana-pro", aspect="4:3", resolution="2K", output_format="png", refs=None, poll_timeout=420.0, poll_interval=6.0, client=None) -> dict` (client.py:122).
- Tables created via SQLAlchemy `Base.metadata.create_all` at startup (main.py:2553) — **no alembic migration needed**; just define the model and ensure it's imported by `backend/app/modules/acap/models/__init__.py` (follow existing imports there).
- Deps: `httpx>=0.28` available. NO google SDK (by design — REST via httpx, mirroring render + `app/modules/ai/ai_client.py`). Declare nothing new.
- Tests: `backend/tests/integration/test_acap_*.py`; run `cd backend && pytest -x -q tests/integration -k acap`. Fixture pattern (test_acap_authz.py:20-35): `from tests._pg import transactional_session`; project factory creates `Project(name=..., currency="IDR", owner_id=...)`. HTTP tests: `create_app()` + `ASGITransport` + `AsyncClient(base_url="http://test")` (test_acap_health.py:10-16).

**Frontend** (React 18 + Vite + TS, `frontend/`):
- Alias `@/` → `frontend/src`. Scripts: `npm run typecheck` (= `tsc --noEmit`), `npm run test` (vitest), `npm run build`.
- **`three@^0.185.0` + `@types/three` ALREADY in package.json**; vite manualChunks already buckets it as `vendor-three`. `@react-three/*` NOT present and NOT to be added — use plain three + `OrbitControls` from `three/addons/controls/OrbitControls.js`.
- acap code lives in `frontend/src/acap/` (pages are **default exports**). API modules use `const PREFIX = '/v1/acap'` + helpers from `@/shared/lib/api`: `apiGet<T>(path)`, `apiPost<T, B>(path, body)`, `apiPut<T, B>(path, body)`, `ApiError` (has `.status`, `.body`); helpers prepend `/api` and attach Bearer from `useAuthStore.getState().accessToken`.
- Multipart upload pattern (mirror `src/features/boq/CreateBOQPage.tsx:114-130`): raw `fetch('/api' + path, { method: 'POST', headers: token ? { Authorization: `Bearer ${token}` } : {}, body: formData })` with `AbortController` timeout.
- Existing acap frontend to REUSE:
  - `floorPlanApi.ts`: `getLatestLayout(projectId)` → `{version, status, plan}` (404 → ApiError.status 404); `saveLayout(projectId, plan)` (422 → `LayoutValidationApiError` with `.reasons`).
  - `FloorPlanEditor.tsx`: `<FloorPlanEditor plan onChange onSave saving saveErrors savedVersion />` (props interface FloorPlanEditor.tsx:118-127).
  - `timelineApi.ts`: `generateTimeline(projectId)`, `downloadTimelineCsv(projectId)`.
  - `GanttChart.tsx`: `<GanttChart tasks stages totalDays />`.
  - `renderApi.ts`: `generateRender`, `listRenders`, `isNotConfiguredError(err)` (checks ApiError 400 + `body.detail.reason === 'GEMINIGEN_API_KEY not set'`).
  - `planTypes.ts`: `FloorPlan` TS type.
- Routing (`src/app/App.tsx`): lazy import `const X = lazy(() => import('@/acap/X'))`; routes as children of the AppShell layout route (auth via `RequireAuth` in AppShell; `P` wrapper only sets header title): existing acap routes at App.tsx:1002-1004. Login: `LoginPage.tsx` computes `nextPath` from `?next=`, **fallback `'/'` at line ~106** — this fallback becomes `'/studio'`.
- Sidebar (`src/app/layout/Sidebar.tsx`): `navGroups` line ~213; overview group items line ~216-223, NavItem shape `{ labelKey, to, icon: LucideIcon, ... }`.
- Stepper precedent to mirror: `src/features/projects/CreateProjectPage.tsx` — `step`/`maxStep` state (456-460), `STEP_COUNT`, `STEP_TITLES` (1112-1118), dot-grid indicator (1186-1218).
- Design tokens (use ONLY these, no new colors): `bg-oe-blue`, `hover:bg-oe-blue-hover`, `text-oe-blue`, `border-oe-blue`, `bg-surface-secondary`, `bg-surface-elevated`, `text-content-primary/secondary/tertiary/quaternary`, `border-border`, `border-border-light`, `text-semantic-error`, `ring-oe-blue/25`, `text-white`. Buttons/cards: mirror RenderPage.tsx (e.g. generate button `rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50`).
- i18n: `useTranslation()`, `t('key', { defaultValue: 'English' })`. New keys under `studio.*`. UI copy: Indonesian defaults are OK for Studio (product is Indonesia-first) — use Indonesian in `defaultValue` directly.
- Tests: vitest, colocated `*.test.ts(x)` (precedent: `src/acap/serialize.test.ts`, `src/acap/renderApi.test.ts`).

## Tech Stack (no additions)

Backend: FastAPI + SQLAlchemy async + httpx (Gemini REST). Frontend: React 18, three (existing), vitest. **Zero new dependencies, front and back.**

## Data Integration Map (CONTRACT)

| Feature | Data Source | Hook/API | Exists? | Action |
|---|---|---|---|---|
| Studio project list | `GET /api/v1/projects/` | `apiGet<Project[]>('/v1/projects/')` (pattern: CreateBOQPage.tsx:57-61) | Yes | Use existing |
| Plan-image upload | new table `oe_acap_plan_image` + `get_storage_backend()` | new `POST /v1/acap/projects/{id}/plan-images` | No | Create real endpoint (Phase 1.1) |
| Vision extract | Gemini REST `generativelanguage.googleapis.com` via httpx, env `GOOGLE_API_KEY` | new `POST /v1/acap/projects/{id}/plan-images/{image_id}/extract` | No | Create real adapter (Phase 1.2), key-gated 400 like render |
| Draft→saved layout | `oe_acap_floor_plan` + `validate_plan` | existing `PUT /v1/acap/projects/{id}/layout` (`saveLayout`) | Yes | Use existing — draft is NEVER persisted by extract |
| RAB numbers | `rab/generator.py` + `oe_acap_material_price` (159 Batam rows) | existing `POST /v1/acap/projects/{id}/rab:generate` | Yes (endpoint) / No (UI) | New RabStep UI only (Phase 2.1) |
| Timeline | `timeline/generator.py` | existing `timelineApi.generateTimeline` + `GanttChart` | Yes | Wrap in TimelineStep (Phase 2.2) |
| 3D geometry | latest saved FloorPlan JSON (client-side) | `getLatestLayout` | Yes (data) / No (viewer) | New pure-TS extruder + three viewer (Phase 3.x) |
| Interior render | snapgen via existing `render/client.py::generate_render_image`, env `GEMINIGEN_API_KEY`, new table `oe_acap_interior_render` | new `POST .../interior:generate` + `GET .../interiors` | No | Create real endpoints reusing render client (Phase 4.1) |
| Interior/render images in UI | `RenderResponse.source_url` (provider URL) | existing pattern (RenderPage gallery) | Yes | Reuse; `ponytail:` provider URLs may expire — upgrade path = streaming proxy route, NOT in this plan |
| Login landing | `LoginPage.tsx` nextPath fallback | — | Yes | Change `'/'` → `'/studio'` (Phase 0.1) |

Anything not in this table that looks missing → STOP, log blocker in ledger. Do not stub.

## Executor rules (apply to every phase)

1. TDD: step 1 of each phase writes the failing test EXACTLY as specified; run it; confirm the expected failure; implement; re-run to green.
2. No placeholders, no `TODO` comments, no mock data outside tests.
3. Never touch: `rab/generator.py` math, `timeline/generator.py`, `layout/validator.py` rules, price tables. Studio CONSUMES engines.
4. Keys (`GOOGLE_API_KEY`, `GEMINIGEN_API_KEY`): `os.environ.get` exists-check only; never log/echo/print key bytes; gate AFTER authz with the exact 400 shape shown in Phase 1.2.
5. All new backend endpoints: authz guard first (`require_project_owner` for writes incl. generate-endpoints, `require_project_access` for reads), mirroring router.py.
6. Verify commands run from repo root unless stated. A phase is DONE only when all its Verification boxes pass; then update `.gaspol/progress/acap-studio.md`.

---

## Wave 0 — Studio shell

### Phase 0.1: Studio home + routing + login landing + sidebar

**Estimated:** 12 min · **Design deliverable:** mirrors existing tokens/list patterns (no new design language)

**Files:**
- Create: `frontend/src/acap/studio/StudioHomePage.tsx` (default export)
- Create: `frontend/src/acap/studio/StudioHomePage.test.tsx`
- Modify: `frontend/src/app/App.tsx` (2 lazy imports + 2 routes)
- Modify: `frontend/src/app/layout/Sidebar.tsx` (1 NavItem)
- Modify: `frontend/src/features/auth/LoginPage.tsx` (nextPath fallback)

**Steps:**
1. Write failing test `StudioHomePage.test.tsx`: renders heading "ACAP Studio" and one project row with a "Buka Studio" link to `/projects/<id>/studio` given a mocked `apiGet` returning `[{id:'p1', name:'Rumah A'}]`. Expected error: `Failed to resolve import "./StudioHomePage"` (module not found).
2. Run `cd frontend && npx vitest run src/acap/studio/StudioHomePage.test.tsx`, confirm module-not-found failure.
3. Implement `StudioHomePage.tsx`: fetch `apiGet<{id:string;name:string}[]>('/v1/projects/')` on mount; page title "ACAP Studio", subtitle "Dari gambar denah ke RAB, timeline, 3D & interior — terpandu."; list projects as Cards (from `@/shared/ui`) each with `Link` "Buka Studio" → `/projects/${id}/studio`; primary button "+ Project Baru" → `/projects/new`; `EmptyState` when no projects. Tokens per vocabulary above.
4. In `App.tsx`: add `const StudioHomePage = lazy(() => import('@/acap/studio/StudioHomePage'));` next to the acap lazy block (~line 495) and route `<Route path="/studio" element={<P title="ACAP Studio"><StudioHomePage /></P>} />` adjacent to the acap routes (inside the AppShell children, near line 1002).
5. In `Sidebar.tsx` overview group items (line ~216), FIRST item: `{ labelKey: 'nav.acap_studio', to: '/studio', icon: Wand2 }` (import `Wand2` from lucide-react alongside existing icon imports). Check how `labelKey` is rendered: grep `nav.dashboard` under `frontend/src` (and `frontend/public`) for the locale JSON(s); add key `nav.acap_studio` = `"ACAP Studio"` to the SAME files (en + id) where `nav.dashboard` lives. If the sidebar renders `t(labelKey, { defaultValue })`-style with an inline default field on the item, use that instead.
6. In `LoginPage.tsx` (~line 106): change the `nextPath` fallback `'/'` → `'/studio'`. Do NOT touch the `?next=` handling or the onboarding branch.
7. Run tests + typecheck, all green.

**Verification:**
- [ ] `cd frontend && npx vitest run src/acap/studio` passes
- [ ] `cd frontend && npx tsc --noEmit` passes
- [ ] `/studio` route present in App.tsx inside AppShell block; sidebar item first in overview group
- [ ] LoginPage fallback is `/studio`; `?next=` param still honored
- [ ] No placeholder/TODO comments

### Phase 0.2: StudioPage stepper shell + step gating

**Estimated:** 15 min · **Design deliverable:** dot-stepper mirroring CreateProjectPage.tsx:1186-1218

**Files:**
- Create: `frontend/src/acap/studio/StudioPage.tsx` (default export), `frontend/src/acap/studio/studioSteps.ts`
- Create: `frontend/src/acap/studio/studioSteps.test.ts`
- Modify: `frontend/src/app/App.tsx` (1 lazy import + 1 route)

**Steps:**
1. Write failing test `studioSteps.test.ts` for pure fn `deriveStepAvailability(input: {hasLayout: boolean}): {maxStep: number}` — `hasLayout:false → maxStep 3` (Upload/Extract/Konfirmasi reachable), `hasLayout:true → maxStep 7`. Expected error: `Cannot find module './studioSteps'`.
2. Run vitest, confirm failure. Implement `studioSteps.ts`: `STEP_COUNT = 7`, `STEP_TITLES` (Indonesian): `['Upload Gambar','AI Extract','Konfirmasi','RAB','Timeline','3D','Interior']`, and `deriveStepAvailability`.
3. Implement `StudioPage.tsx`: `useParams<{projectId}>`; on mount call `getLatestLayout(projectId)` (from `@/acap/floorPlanApi`) — 200 → `hasLayout=true`, ApiError 404 → false; state `step`/`maxStep` mirroring CreateProjectPage pattern; render dot-stepper (copy the dot-grid JSX pattern, STEP_COUNT=7); step body = `switch(step)` rendering placeholder-free minimal bodies for now: steps 1–3 render an inline note card "Langkah ini aktif di Wave 1" ONLY IF the wave-1 components don't exist yet — since waves execute in order, wire the real components as they land; steps 4–7 same for their waves. To keep this phase placeholder-free and testable: render `<StepPending title={STEP_TITLES[i]} />` — a real, styled component (`studio/StepPending.tsx`, card with title + text "Segera di langkah berikutnya alur ini." ) that later phases REPLACE. Buttons Kembali/Lanjut with clamp; "Lanjut" disabled beyond `maxStep`.
4. App.tsx: `const StudioPage = lazy(() => import('@/acap/studio/StudioPage'));` + `<Route path="/projects/:projectId/studio" element={<P title="ACAP Studio"><StudioPage /></P>} />`.
5. Tests + typecheck green.

**Verification:**
- [ ] `npx vitest run src/acap/studio` passes (both test files)
- [ ] `npx tsc --noEmit` passes
- [ ] Stepper shows 7 Indonesian titles; navigation clamped by maxStep; layout presence lifts maxStep to 7

**WAVE 0 GATE:** both phases' boxes green → ledger updated → STOP for supervisor diff review.

---

## Wave 1 — Input: upload → extract → konfirmasi

### Phase 1.1: Backend — plan-image model + upload endpoint  ⚠ security-sensitive (file upload)

**Estimated:** 15 min

**Files:**
- Create: `backend/app/modules/acap/models/plan_image.py`
- Modify: `backend/app/modules/acap/models/__init__.py` (import PlanImageRecord — follow the existing import list)
- Modify: `backend/app/modules/acap/router.py` (upload endpoint)
- Create: `backend/tests/integration/test_acap_plan_image.py`

**Steps:**
1. Write failing test `test_acap_plan_image.py`: async test using `transactional_session` + `_make_project` pattern (copy fixture block from `backend/tests/integration/test_acap_authz.py:20-35`) that constructs the app HTTP client (pattern test_acap_health.py:10-16), logs nothing, and POSTs multipart `file=('rumah.png', b'\x89PNG...' (any ≥16 bytes with PNG magic), 'image/png')` to `/api/v1/acap/projects/{pid}/plan-images` with a monkeypatched `app.core.storage.get_storage_backend` returning a fake with `async put(key, content)` recording calls; expect 200 `{image_id, filename, content_type, size_bytes}` and fake.put called once with key starting `acap/plan-images/{pid}/`. Also: wrong content-type `text/plain` → 400; non-owner JWT → 403/404. Expected error first run: `404 Not Found` (route absent).
2. Run `cd backend && pytest -x -q tests/integration/test_acap_plan_image.py`, confirm 404-route failure.
3. Implement `models/plan_image.py`: `class PlanImageRecord(Base)`, `__tablename__ = "oe_acap_plan_image"`, columns mirroring `models/render.py` style: `project_id` (GUID FK `oe_projects_project.id` ondelete CASCADE, indexed), `filename: String(255)`, `content_type: String(80)`, `size_bytes: Integer`, `storage_key: Text`, `status: String(20) default "uploaded"`. Import it in `models/__init__.py`.
4. Implement endpoint in router.py (place after render endpoints):
   ```python
   @router.post("/projects/{project_id}/plan-images")
   async def upload_plan_image_endpoint(
       project_id: _uuid.UUID,
       file: UploadFile = File(...),
       session: AsyncSession = Depends(get_session),
       payload: dict = Depends(get_current_user_payload),
   ) -> PlanImageResponse:
   ```
   Logic: `await require_project_owner(session, project_id, payload)`; allow content_type in `{"image/png","image/jpeg","image/webp","application/pdf"}` else 400 `{"detail": "Unsupported file type"}`; read bytes, cap 15 MB else 413; `storage = get_storage_backend()`; key `f"acap/plan-images/{project_id}/{uuid4().hex}.{ext}"` (ext from content_type map, NOT from filename); `await storage.put(key, data)`; persist record; return `PlanImageResponse{image_id, filename, content_type, size_bytes}` (pydantic model in router.py alongside the other response models). `python-multipart` is already a FastAPI dep in this fork (BOQ import uses UploadFile) — reuse.
5. Tests green.

**Verification:**
- [ ] `cd backend && pytest -x -q tests/integration/test_acap_plan_image.py` passes (happy, bad-type, authz cases)
- [ ] Security: content-type allowlist + size cap enforced; storage key server-generated (client filename never used in key); authz before any read of the body; no secrets involved
- [ ] Table auto-creates via create_all (model imported in models/__init__.py)

### Phase 1.2: Backend — Gemini vision adapter + extract endpoint  ⚠ security-sensitive (new endpoint, external API key) · LLM phase (eval contract)

**Estimated:** 15 min (adapter) + 10 min (endpoint)

**Files:**
- Create: `backend/app/modules/acap/vision/__init__.py`, `backend/app/modules/acap/vision/client.py`, `backend/app/modules/acap/vision/extractor.py`
- Modify: `backend/app/modules/acap/router.py` (extract endpoint)
- Create: `backend/tests/integration/test_acap_vision.py`
- Create: `docs/evals/plan-image-extract.md`

**Steps:**
1. Write failing test `test_acap_vision.py` with three deterministic cases (NO live API):
   a. `vision_service_configured()` False when `GOOGLE_API_KEY` unset (monkeypatch.delenv), True when set;
   b. `build_draft_plan(extract: dict) -> tuple[dict, bool, list[str]]` — given fixture extract `{"kavling_width_m": 12.32, "kavling_length_m": 12.47, "levels": [{"level": 1, "rooms": [{"name": "Ruang Tamu", "type": "ruang_tamu", "x_m": 0.0, "y_m": 0.0, "width_m": 5.92, "length_m": 4.2}]}]}` returns a FloorPlan-shaped dict whose room polygon is `[(0,0),(5.92,0),(5.92,4.2),(0,4.2)]`, `area_m2 = 24.864`, plus `(valid, reasons)` from `layout.validator.is_valid`;
   c. extract endpoint returns **400 with body detail.reason == "GOOGLE_API_KEY not set"** when key absent (monkeypatch.delenv), for an owner-authorized project+image.
   Expected error first run: `ModuleNotFoundError: No module named 'app.modules.acap.vision'`.
2. Run pytest, confirm import failure.
3. Implement `vision/client.py` mirroring `render/client.py` structure:
   - `_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"`, `DEFAULT_MODEL = "gemini-2.5-flash"` (env override `GOOGLE_VISION_MODEL`).
   - `def vision_service_configured() -> bool: return bool(os.environ.get("GOOGLE_API_KEY"))` (docstring: existence check only; key bytes never returned or logged).
   - `class VisionNotConfiguredError(RuntimeError)`.
   - `async def extract_floor_plan(image_bytes: bytes, mime_type: str, *, client: httpx.AsyncClient | None = None) -> dict`: POST `{base}/models/{model}:generateContent` with header `x-goog-api-key: <key>` (header, NOT query param — keys must never appear in URLs/logs), JSON body:
     ```json
     {"contents":[{"parts":[
        {"inline_data":{"mime_type": mime, "data": "<base64>"}},
        {"text": PROMPT}]}],
      "generationConfig":{"response_mime_type":"application/json","temperature":0.1}}
     ```
     Parse `resp["candidates"][0]["content"]["parts"][0]["text"]` → `json.loads`. One retry on JSONDecodeError appending "Return ONLY valid JSON." to the prompt. Timeout 120s.
   - `PROMPT` (module constant, verbatim):
     ```
     You are extracting a residential floor plan from an image (SketchUp screenshot, drawing, or photo of a plan with dimension labels).
     Return ONLY JSON matching exactly this schema, all dimensions in METERS (convert from cm labels; e.g. "592,00 cm" -> 5.92):
     {"kavling_width_m": float, "kavling_length_m": float,
      "levels": [{"level": int (1 = ground floor),
        "rooms": [{"name": str (Indonesian, e.g. "Kamar Tidur Utama"),
                   "type": one of ["kamar_tidur_utama","kamar_tidur","kamar_mandi","dapur","ruang_tamu","ruang_keluarga","ruang_makan","carport","garasi","musholla","gudang","teras","taman","sirkulasi","other"],
                   "x_m": float, "y_m": float, "width_m": float, "length_m": float}]}],
      "notes": [str]}
     Coordinate system: origin at the SOUTH-WEST (bottom-left) corner of the kavling, x grows east (right), y grows north (up). x_m,y_m are the room's bottom-left corner. Rooms must not overlap and must fit inside the kavling. If a dimension is unreadable, estimate from proportions and add a note. Use "other" for unknown room types.
     ```
4. Implement `vision/extractor.py`: `def build_draft_plan(extract: dict) -> tuple[dict, bool, list[str]]` — map to FloorPlan dict: kavling from extract; each room → `polygon` CCW `[(x,y),(x+w,y),(x+w,y+l),(x,y+l)]`, `area_m2 = round(w*l, 3)`, unknown type → `"other"`; `walls: []`, `openings: []` per level; `jumlah_lantai = len(levels)`; `generated_by = f"vision:{model}"`; `notes = "; ".join(extract.get("notes", []))`. Validate via `FloorPlan.model_validate(draft)` then `is_valid(plan)`; on pydantic error return `(draft_raw, False, [str(e)])`.
5. Extract endpoint in router.py:
   ```python
   @router.post("/projects/{project_id}/plan-images/{image_id}/extract")
   async def extract_plan_image_endpoint(
       project_id: _uuid.UUID, image_id: _uuid.UUID,
       session: AsyncSession = Depends(get_session),
       payload: dict = Depends(get_current_user_payload),
   ) -> ExtractResponse:
   ```
   Order: `require_project_owner` → load PlanImageRecord (404 if absent/mismatched project) → key-gate:
   ```python
   if not vision_service_configured():
       raise HTTPException(status_code=400, detail={
           "detail": "Vision service not configured",
           "reason": "GOOGLE_API_KEY not set",
       })
   ```
   → load bytes from storage (`storage.get(key)` — check `app/core/storage.py` for the read method name (`get`/`read`); use whatever LocalStorageBackend+S3 both expose) → `extract_floor_plan` → `build_draft_plan` → return `ExtractResponse{draft_plan: dict, valid: bool, reasons: list[str], model: str}`. Provider/httpx failure → 502 `{"detail": "Vision extraction failed"}` (no key/stack leakage).
6. Write `docs/evals/plan-image-extract.md`: capability eval (needs `GOOGLE_API_KEY` + a real plan image at `backend/tests/fixtures/plan_sample.png` — file NOT committed by executor; Ali drops his SketchUp export there; eval = run extract, assert ≥5 rooms found, kavling within ±10% of 12.32×12.47m, every room type in enum; pass@2). Regression eval = the deterministic `build_draft_plan` unit tests (always run). Note: `pytest -m ''` skip pattern — capability test decorated `@pytest.mark.skipif(not os.environ.get("GOOGLE_API_KEY") or not FIXTURE.exists(), reason="needs key + fixture")`.
7. All tests green.

**Verification:**
- [ ] `cd backend && pytest -x -q tests/integration/test_acap_vision.py tests/integration/test_acap_plan_image.py` passes
- [ ] Security: key via header only, never logged/echoed; gate AFTER authz; 502 path leaks nothing; extract NEVER writes to `oe_acap_floor_plan` (draft returned only — invariant #1)
- [ ] `docs/evals/plan-image-extract.md` exists with capability + regression sections
- [ ] Grep guard: `grep -rn "GOOGLE_API_KEY" backend/app | grep -v "os.environ"` returns nothing (no literal key handling beyond env read)

### Phase 1.3: Frontend — UploadStep + ConfirmStep

**Estimated:** 15 min + 15 min · **Design deliverable:** upload dropzone mirrors CreateBOQPage file-picker; confirm table mirrors token vocabulary; editor embed reuses FloorPlanEditor as-is

**Files:**
- Create: `frontend/src/acap/studio/studioApi.ts`, `frontend/src/acap/studio/studioApi.test.ts`
- Create: `frontend/src/acap/studio/UploadStep.tsx`, `frontend/src/acap/studio/ConfirmStep.tsx`, `frontend/src/acap/studio/ConfirmStep.test.tsx`
- Modify: `frontend/src/acap/studio/StudioPage.tsx` (wire steps 1–3, replace StepPending; hold draft state)

**Steps:**
1. Write failing test `studioApi.test.ts`: `isVisionNotConfiguredError(err)` true for `ApiError(status 400, body.detail.reason === 'GOOGLE_API_KEY not set')`, false otherwise (mirror `renderApi.test.ts`). Expected error: `Cannot find module './studioApi'`.
2. Implement `studioApi.ts`: `PREFIX = '/v1/acap'`; `uploadPlanImage(projectId, file)` — raw fetch multipart per CreateBOQPage pattern (AbortController 60s) → `{image_id, filename, content_type, size_bytes}`; `extractPlanImage(projectId, imageId)` — `apiPost<ExtractResponse>(...)` with `{ longRunning: true }` init; `isVisionNotConfiguredError`. Types: `ExtractResponse{draft_plan: FloorPlan; valid: boolean; reasons: string[]; model: string}` (FloorPlan from `@/acap/planTypes`).
3. Write failing test `ConfirmStep.test.tsx`: given a draft FloorPlan with one room, renders an editable row (name input value "Ruang Tamu", width 5.92, length 4.2); editing width to 6 calls `onDraftChange` with polygon x extent 6. Expected error: module not found.
4. Implement `UploadStep.tsx`: dropzone button (mirror CreateBOQPage picker styling) accepting `.png,.jpg,.jpeg,.webp,.pdf`; local preview via `URL.createObjectURL` for images; "Upload & Extract" button → `uploadPlanImage` then `extractPlanImage`; states: idle/uploading/extracting/done/not-configured (banner text: "Vision belum dikonfigurasi — set GOOGLE_API_KEY di .env lalu restart backend.", style = RenderPage not-configured banner)/error (toast via `useToastStore`). On success: `onExtracted(resp)` → StudioPage stores draft, advances to step 2 view showing `reasons` list (if `!valid`, amber note card "Perlu dirapikan di langkah Konfirmasi:") then Lanjut → step 3.
5. Implement `ConfirmStep.tsx`: props `{draft: FloorPlan; onDraftChange(p: FloorPlan): void; projectId: string; onSaved(version: number): void}`. Two panes: (a) editable table per level — columns Nama / Tipe (select of the 15 ROOM_TYPES) / X / Y / Lebar (m) / Panjang (m); edits rebuild polygon+area (helper `rectRoom(x,y,w,l)` in studioApi.ts or local util, unit-tested in step 3's test); (b) toggle "Editor 2D" embedding `<FloorPlanEditor plan={draft} onChange={onDraftChange} onSave={handleSave} saving={saving} saveErrors={saveErrors} savedVersion={savedVersion} />`. `handleSave` → `saveLayout(projectId, draft)`; on `LayoutValidationApiError` show `.reasons` as list under the table (`text-semantic-error`); on success toast sukses + `onSaved(version)` → StudioPage sets `hasLayout=true`, `maxStep=7`, advance to step 4.
6. Wire steps 1–3 in StudioPage (draft held in StudioPage state; refresh loses draft — acceptable, `ponytail:` re-upload on reload; saved layouts persist).
7. Tests + typecheck green.

**Verification:**
- [ ] `npx vitest run src/acap/studio` passes (3+ test files)
- [ ] `npx tsc --noEmit` passes
- [ ] Draft only persists via existing `saveLayout` PUT (validator path) — grep ConfirmStep/StudioPage for any other write: none
- [ ] Key-missing shows calm banner (not error toast), mirroring RenderPage

**WAVE 1 GATE:** ledger + supervisor review. Supervisor also sets `GOOGLE_API_KEY` in `.env` + drops `backend/tests/fixtures/plan_sample.png`, runs capability eval manually.

---

## Wave 2 — Angka (RAB + Timeline in Studio)

### Phase 2.1: RabStep — first-ever RAB screen + CSV export

**Estimated:** 15 min · **Design deliverable:** table = existing token vocabulary; money right-aligned; PRICE_MISSING amber badges

**Files:**
- Create: `frontend/src/acap/studio/rabApi.ts`, `frontend/src/acap/studio/rabCsv.ts`, `frontend/src/acap/studio/rabCsv.test.ts`, `frontend/src/acap/studio/RabStep.tsx`
- Modify: `frontend/src/acap/studio/StudioPage.tsx` (wire step 4)

**Steps:**
1. Write failing test `rabCsv.test.ts`: `buildRabCsv(lines)` with 2 fixture lines (one priced, one `price_missing:true, unit_rate:null, total:null`) returns CSV with header `kode;uraian;unit;quantity;unit_rate;total;kategori;price_missing`, semicolon-separated, `""`-quoted uraian, empty cells for null rate/total. Expected error: `Cannot find module './rabCsv'`.
2. Implement `rabCsv.ts` (pure) + `rabApi.ts`: `generateRab(projectId)` → `apiPost<RabResponse>('/v1/acap/projects/${projectId}/rab:generate', {}, { longRunning: true })`; TS types copied from backend shape: `RabResponse{boq_id: string; grand_total: string; subtotals_by_kategori: Record<string,string>; lines: RabLine[]; price_missing_lines: RabLine[]; curated_lines: RabLine[]; not_covered: string[]}`, `RabLine{kode: string; uraian: string; unit: string; quantity: string|number; unit_rate: string|number|null; total: string|number|null; price_missing: boolean; kategori: string; missing_resources: unknown[]; curated_resources: unknown[]}`.
3. Implement `RabStep.tsx`: button "Hitung RAB" → generateRab; render: grand total headline (`MoneyDisplay` from `@/shared/ui` if its props fit a plain string+`IDR`, else `Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR'})`); subtotals per kategori as stat row; lines table grouped by `kategori` (columns Kode/Uraian/Unit/Qty/Harga Satuan/Total); `price_missing` rows amber badge "HARGA BELUM ADA" + list in a warning card ("{n} item belum ada harga Batam — tidak dihitung di total"); `not_covered` info card ("Belum dicakup engine: footplat, sloof, kolom-balok utama, tangga"); button "Export CSV" → `buildRabCsv(lines)` → `new Blob` → `triggerDownload(blob, 'rab-${projectId}.csv')` (import from `@/shared/lib/api`); 404-layout → "Selesaikan langkah Konfirmasi dulu." card.
4. Wire into StudioPage step 4. Tests + typecheck green.

**Verification:**
- [ ] `npx vitest run src/acap/studio/rabCsv.test.ts` passes; `npx tsc --noEmit` passes
- [ ] Grand total renders from `grand_total` string verbatim (no client-side re-summation — engine is the only source of numbers)
- [ ] PRICE_MISSING rows visibly flagged and excluded-from-total note shown

### Phase 2.2: TimelineStep

**Estimated:** 8 min

**Files:**
- Create: `frontend/src/acap/studio/TimelineStep.tsx`
- Modify: `frontend/src/acap/studio/StudioPage.tsx` (wire step 5)

**Steps:**
1. Write failing test (extend `studioSteps.test.ts`): `STEP_TITLES[4] === 'Timeline'` and StudioPage step-5 body renders TimelineStep (shallow: component export exists). Expected error: `TimelineStep is not defined` / module not found.
2. Implement `TimelineStep.tsx`: button "Buat Timeline" → `generateTimeline(projectId)` (existing `@/acap/timelineApi`); render `total_days` headline ("Estimasi durasi: {n} hari kerja") + `<GanttChart tasks={r.tasks} stages={r.stages} totalDays={r.total_days} />` (existing `@/acap/GanttChart`); "Download CSV" → existing `downloadTimelineCsv(projectId)`; 404-layout guard card same as RAB.
3. Wire step 5. Tests + typecheck green.

**Verification:**
- [ ] vitest + tsc pass
- [ ] Reuses `timelineApi` + `GanttChart` verbatim (no reimplementation)

**WAVE 2 GATE:** ledger + supervisor review. Manual check with live stack: Dutamas project → Konfirmasi saved → RAB shows real IDR totals.

---

## Wave 3 — 3D viewer

### Phase 3.1: Pure geometry — planTo3d

**Estimated:** 12 min

**Files:**
- Create: `frontend/src/acap/studio/planTo3d.ts`, `frontend/src/acap/studio/planTo3d.test.ts`

**Steps:**
1. Write failing test `planTo3d.test.ts` for `planToMeshes(plan: FloorPlan): {floors: Slab[]; walls: WallBox[]}` where `Slab{x,y,w,l,z}` and `WallBox{cx,cy,cz,lenX,lenY,height}` (plain data, NO three imports — testable in node): fixture plan (1 level, 2 adjacent rooms sharing an edge) →
   - one slab per room at z=0 with room extents;
   - one WallBox per unique room edge (dedupe shared edges: two rooms sharing edge segment produce ONE wall), thickness 0.15, height 3.0, level 2 walls sit at z base 3.2 (3.0 wall + 0.2 slab).
   Expected error: `Cannot find module './planTo3d'`.
2. Implement `planTo3d.ts` (pure TS, constants `WALL_HEIGHT_M=3.0`, `SLAB_THICKNESS_M=0.2`, `WALL_THICKNESS_M=0.15`): rooms are axis-aligned rects (guaranteed by validator) → edges from polygon pairs; canonicalize edge key (sorted endpoints rounded to 3dp) for dedupe; output boxes centered per edge. `ponytail:` openings (doors/windows) have no coordinates in the schema — walls are solid; upgrade path = punch gaps when Opening gains position fields.
3. Tests green.

**Verification:**
- [ ] `npx vitest run src/acap/studio/planTo3d.test.ts` passes (slab count, wall dedupe, level-2 z-offset)
- [ ] File imports nothing from `three` (pure data — keeps tests jsdom-free)

### Phase 3.2: ThreeDStep viewer

**Estimated:** 15 min · **Design deliverable:** canvas card full-width, neutral material palette (walls #e8e6e1, slabs #d6d3cd, bg surface token)

**Files:**
- Create: `frontend/src/acap/studio/ThreeDStep.tsx`
- Modify: `frontend/src/acap/studio/StudioPage.tsx` (wire step 6)

**Steps:**
1. Write failing test (extend studio tests): rendering ThreeDStep in jsdom (no WebGL) shows fallback text "3D tidak tersedia di browser ini." — assert via testing-library. Expected error: module not found.
2. Implement `ThreeDStep.tsx`: load layout via `getLatestLayout`; `useEffect` builds scene: `WebGLRenderer` in try/catch (catch → set fallback state — this is what jsdom hits), `PerspectiveCamera`, `OrbitControls` from `three/addons/controls/OrbitControls.js`, `HemisphereLight`+`DirectionalLight`, meshes from `planToMeshes` (BoxGeometry per WallBox/Slab, `MeshLambertMaterial`), ground grid (`GridHelper`), camera framed to kavling bounds; render loop via `requestAnimationFrame`; cleanup disposes renderer/geometries on unmount. Buttons: "Reset kamera", level toggle when `jumlah_lantai > 1` (show level 1 / all).
3. Wire step 6. Tests + typecheck green. Confirm chunking: `grep -n "vendor-three" frontend/vite.config.ts` (already configured — three lands in its own chunk; StudioPage stays lazy).

**Verification:**
- [ ] vitest passes (fallback path), `npx tsc --noEmit` passes
- [ ] Renderer + geometry disposal on unmount (no leak); no `@react-three/*` imports anywhere

**WAVE 3 GATE:** ledger + supervisor review (visual check in browser).

---

## Wave 4 — Interior renders

### Phase 4.1: Backend — interior model + prompts + endpoints  ⚠ security-sensitive (new endpoints, external key)

**Estimated:** 15 min

**Files:**
- Create: `backend/app/modules/acap/interior/__init__.py`, `backend/app/modules/acap/interior/prompts.py`
- Create: `backend/app/modules/acap/models/interior_render.py` (+ import in `models/__init__.py`)
- Modify: `backend/app/modules/acap/router.py` (2 endpoints)
- Create: `backend/tests/integration/test_acap_interior.py`

**Steps:**
1. Write failing test `test_acap_interior.py`:
   a. `build_interior_prompt(room_name="Kamar Tidur Utama", room_type="kamar_tidur_utama", area_m2=17.6, style="japandi")` returns a string containing the room name, "17.6", and the japandi style fragment; unknown style raises `ValueError`;
   b. endpoint `POST /api/v1/acap/projects/{pid}/interior:generate` body `{"room_name": "X", "style": "japandi"}` → 404 when project has no saved layout; → 400 `reason == "GEMINIGEN_API_KEY not set"` when layout exists (insert a FloorPlanRecord fixture with a valid plan_json) and key absent; room not in layout → 422.
   Expected error: `ModuleNotFoundError ... acap.interior`.
2. Implement `interior/prompts.py`: `STYLES: dict[str, str]` for `minimalis|skandinavia|japandi|industrial|klasik` (each a 1-2 sentence English style fragment for the image model, e.g. japandi: "Japandi interior: warm wood, low furniture, soft neutral palette, paper lantern lighting, clean lines, subtle wabi-sabi texture"); `ROOM_HINTS: dict[str, str]` keyed by ROOM_TYPES (e.g. kamar_tidur_utama → "master bedroom with queen bed"); `def build_interior_prompt(room_name, room_type, area_m2, style) -> str` composing: photoreal interior render, Indonesian tropical residence in Batam, room hint, `~{area_m2} m2`, style fragment, "eye-level camera, natural daylight, 4:3". Raise ValueError on unknown style.
3. Implement `models/interior_render.py`: `InteriorRenderRecord(Base)`, table `oe_acap_interior_render` — clone RenderRecord columns (`project_id` FK CASCADE indexed, `floor_plan_version int`, `prompt Text`, `model String(80)`, `provider_uuid String(80)`, `source_url Text`, `storage_key Text`, `status String(20) default "pending"`, `error_message Text`) + `room_name: String(120)`, `style: String(40)`.
4. Endpoints in router.py (mirror render endpoints structure exactly):
   - `POST /projects/{project_id}/interior:generate`, body model `InteriorGenerateRequest{room_name: str, style: str}` → `require_project_owner` → load latest FloorPlanRecord (404 "Generate a floor plan first" if none) → find room by name across levels in `FloorPlan.model_validate(record.plan_json)` (422 `{"detail": "Room not found in layout"}` if absent) → key-gate `render_service_configured()` (reuse from `render/client.py`; same 400 shape, reason `"GEMINIGEN_API_KEY not set"`) → `build_interior_prompt(...)` (style ValueError → 422) → call `generate_render_image(prompt)` (import from `render/client.py`); download image (reuse `_download_image` from `render/generator.py` or copy its 8-line body), `storage.put(f"acap/interiors/{project_id}/{uuid}.png", data)`; persist record status completed/failed like `render/generator.py:87-93`; return `InteriorRenderResponse{interior_id, room_name, style, status, prompt, storage_key, source_url, error_message}`.
   - `GET /projects/{project_id}/interiors` (+ optional `room_name` query filter) → `require_project_access` → list ordered `created_at.desc()`.
5. Tests green.

**Verification:**
- [ ] `cd backend && pytest -x -q tests/integration/test_acap_interior.py` passes
- [ ] Security: authz first; key exists-check only; provider errors → status="failed" record, no raw provider payload in HTTP error; prompt contains NO user-supplied free text except room_name (bounded String(120))
- [ ] Interior NEVER touches RAB/timeline paths (decorative — invariant #3)

### Phase 4.2: Frontend — InteriorStep

**Estimated:** 12 min · **Design deliverable:** style picker = 5 selectable cards (aria-pressed pattern from CreateBOQPage start-mode buttons); gallery = grid of `<img src={source_url}>` cards mirroring RenderPage

**Files:**
- Create: `frontend/src/acap/studio/interiorApi.ts`, `frontend/src/acap/studio/InteriorStep.tsx`, `frontend/src/acap/studio/interiorApi.test.ts`
- Modify: `frontend/src/acap/studio/StudioPage.tsx` (wire step 7)

**Steps:**
1. Write failing test `interiorApi.test.ts`: not-configured classifier (400 + reason `GEMINIGEN_API_KEY not set`) mirroring renderApi.test.ts. Expected error: module not found.
2. Implement `interiorApi.ts`: `generateInterior(projectId, {room_name, style})` (`longRunning: true` — render polls up to 7 min), `listInteriors(projectId, roomName?)`, `isRenderNotConfiguredError` (reuse `renderApi.isNotConfiguredError` if importable — it is; re-export).
3. Implement `InteriorStep.tsx`: room dropdown populated from `getLatestLayout` rooms (all levels, label "L{level} · {name}"); 5 style cards (id, Indonesian label, one-line description); "Generate Interior" → generateInterior → prepend to gallery; gallery from `listInteriors` on mount, cards show img (`source_url ?? ''` with `onError` hiding to a "gambar kedaluwarsa" placeholder note), room, style badge, failed status with `error_message`; not-configured banner identical wording pattern to RenderPage ("Render service belum dikonfigurasi — set GEMINIGEN_API_KEY."); no-layout guard card.
4. Wire step 7. Tests + typecheck green.

**Verification:**
- [ ] vitest + tsc pass
- [ ] Long-running UX: button disabled with "Merender… (bisa beberapa menit)" while pending

**WAVE 4 GATE:** ledger + supervisor review.

---

## Wave 5 — Polish + E2E smoke

### Phase 5.1: Copy, defaults, build, smoke

**Estimated:** 15 min

**Files:**
- Modify: any `studio/*.tsx` copy inconsistencies; locale files (the ones found in Phase 0.1) — ensure `nav.acap_studio` exists in en + id
- Create: nothing new

**Steps:**
1. Write failing test (extend studioSteps.test.ts): all 7 `STEP_TITLES` are non-empty and Indonesian set matches `['Upload Gambar','AI Extract','Konfirmasi','RAB','Timeline','3D','Interior']`. Expected: passes immediately IF Wave 0 kept them — if red, fix titles.
2. Sweep all Studio UI strings: Indonesian, consistent tone (no mixed English except technical terms RAB/Timeline/3D). Buttons: Kembali/Lanjut/Hitung RAB/Buat Timeline/Export CSV/Generate Interior.
3. Full gates: `cd frontend && npx tsc --noEmit && npx vitest run src/acap` then production build `NODE_OPTIONS=--max-old-space-size=12288 npm run build` (known RAM need; if OOM, retry 16384 and note in ledger). `cd backend && pytest -x -q tests/integration -k acap`.
4. Append E2E smoke CHECKLIST to the ledger (executed by supervisor+Ali in browser, not by you):
   - [ ] rebuild stack `./scripts/dev_up.sh`; hard-refresh/unregister SW
   - [ ] login → lands `/studio`; sidebar shows "ACAP Studio"
   - [ ] Dutamas project → Studio → upload SketchUp screenshot → extract (key set) → rooms match ±10%
   - [ ] Konfirmasi edits → save OK (validator) → RAB shows real IDR grand total, PRICE_MISSING flags visible
   - [ ] Timeline Gantt + CSV; 3D orbits both floors; Interior japandi render for Kamar Tidur Utama (key set)
5. Mark ledger COMPLETE (all waves), summarize deviations.

**Verification:**
- [ ] All three gates in step 3 pass, outputs pasted into ledger
- [ ] No TODO/placeholder grep hits: `grep -rn "TODO\|PLACEHOLDER\|FIXME" frontend/src/acap/studio backend/app/modules/acap/vision backend/app/modules/acap/interior` → only allowed hits are `ponytail:` comments

---

## Progress ledger template (`.gaspol/progress/acap-studio.md`)

```markdown
# ACAP Studio — progress
Plan: docs/plans/2026-07-12-acap-studio-plan.md
| Phase | Status | Verify output (1 line) | Notes/deviations |
|-------|--------|------------------------|------------------|
| 0.1 | todo | | |
| 0.2 | todo | | |
| 1.1 | todo | | |
| 1.2 | todo | | |
| 1.3 | todo | | |
| 2.1 | todo | | |
| 2.2 | todo | | |
| 3.1 | todo | | |
| 3.2 | todo | | |
| 4.1 | todo | | |
| 4.2 | todo | | |
| 5.1 | todo | | |
Blockers: (none)
```

## Env additions (supervisor does this, NOT the executor)

```bash
# .env (repo root — compose passes through; verify acap-local compose injects it like GEMINIGEN_API_KEY; if not, add to docker-compose.acap-local.yml environment block)
GOOGLE_API_KEY=...        # Gemini vision (extract). Existence-check only in code.
# GEMINIGEN_API_KEY already present (render + interior).
```
