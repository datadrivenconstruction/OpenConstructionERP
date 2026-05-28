/**
 * Changelog — Compact two-column release log on the /about page.
 *
 * Each entry is a single glass-style card with version, date, a short summary
 * line, and an optional tag badge. The card list is rendered as CSS columns
 * (`columns-1 md:columns-2`) so entries of variable height pack into the
 * shorter column automatically — there's no need to manually balance the
 * two columns, and a single tall summary doesn't leave the other side blank.
 *
 * Source-of-truth: a single hard-coded `CHANGELOG` array (see below). Entries
 * are kept to ≤ 90-char one-liners per the user's "коротко" request — the
 * full prose lives in repo-root CHANGELOG.md.
 */

import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { APP_VERSION } from '@/shared/lib/version';

type Tag = 'NEW' | 'FIX' | 'BETA' | 'SECURITY' | 'MILESTONE';

interface ChangelogEntry {
  version: string;
  date: string;
  /** One short line, ≤ 90 chars. Proper-noun-heavy → kept in English. */
  summary: string;
  tag?: Tag;
}

// Sorted newest → oldest. Sort is enforced at runtime below (semver-aware) so
// out-of-order entries here still display correctly.
const CHANGELOG: ChangelogEntry[] = [
  // ── v5.x — second stable major ───────────────────────────────────────────
  { version: '5.4.3', date: '2026-05-28', tag: 'FIX',       summary: '/geo mode-picker no longer dumps user out to /projects — soft-disabled tabs open in-page picker dialog. Address autocomplete shows "Searching…" row while Nominatim resolves (was perceived empty during 5–10s cold cache)' },
  { version: '5.4.2', date: '2026-05-28', tag: 'FIX',       summary: 'Converter UX simplification — inline 1-click DWG install on /dwg-takeoff conversion failure, BIM out-of-date overlay shows clean human message (raw stderr hidden behind "Show technical details" disclosure)' },
  { version: '5.4.1', date: '2026-05-28', tag: 'SECURITY',  summary: '20-wave deep audit landings: 13 security fixes (3+ HIGH), 5 silent-miscalc bugs, 8 race/FSM hardenings, GDPR PII scrub extension, Cesium /geo canvas-collapse fix (postage-stamp regression)' },
  { version: '5.4.0', date: '2026-05-27', tag: 'NEW',       summary: 'Quality wave — match-quality (IFC classifier + BGE rerank blend + non-billable gate), WCAG-AA round 2 (theme-aware blue-text token + secondary contrast bump), useLLMRun hook + formatters lift, dark-mode button-bg revert' },
  { version: '5.3.0', date: '2026-05-27', tag: 'NEW',       summary: 'Geo Hub round 2 (storage sweep + 10km accuracy cap + 100dvh), Brazil Tier-1 (BRL + NBR 12721 + RPS PDF), /login dark-mode, /reporting renderer, Daily Diary delete, WCAG-AA contrast pass on 51 files, dashboard rollup' },
  { version: '5.2.8', date: '2026-05-27', tag: 'FIX',       summary: '/geo tabs reliability + /markups → /takeoff deep-link + /resources inline edit + danger-styled delete' },
  { version: '5.2.7', date: '2026-05-27', tag: 'NEW',       summary: 'Project-detail widget grid (responsive 1/2/3-col) + one-click in-app upgrade with captured pip log' },
  { version: '5.2.0', date: '2026-05-26', tag: 'NEW',       summary: 'International BOQ exchange (GAEB X83/X84 + BC3 + NRM Excel + MasterFormat Excel) — Epic I Phase 1' },
  { version: '5.1.1', date: '2026-05-26', tag: 'NEW',       summary: 'Deep coordination Wave 1 — file versioning + notifications dispatcher + universal audit trail' },
  { version: '5.0.0', date: '2026-05-26', tag: 'MILESTONE', summary: 'Second stable major — AI providers (Kimi/Ollama/vLLM), BIM degraded-viewable status, Vector DB row engine label, community PRs landed on main' },

  // ── v4.x — stable major ──────────────────────────────────────────────────
  { version: '4.1.0', date: '2026-05-21', tag: 'NEW',       summary: 'P1 wave rollup — BIM diagnostic UX, CPM Slice 1, Assembly Library, PWA installable, marketing-site i18n complete' },
  { version: '4.0.1', date: '2026-05-20', tag: 'FIX',       summary: 'BIM ViewCube orbit-lock fix, marketing forms migrated off formsubmit, denser module cards' },
  { version: '4.0.0', date: '2026-05-20', tag: 'MILESTONE', summary: 'Stable 4.0 — production-ready; 103 modules; legal/IP audit passed; machine-readable license inventories' },

  // ── v3.x — pro-grade waves, BOQ/BIM rebuild, /match-elements ─────────────
  { version: '3.12.1', date: '2026-05-20', tag: 'FIX', summary: 'BIM serve-time magic-byte validation, /match-elements catalogue picker, BI starter pack, marketing 34-card grid' },
  { version: '3.12.0', date: '2026-05-20',             summary: 'Wave 5/6/7 pro-grade — BOQ + Cost Intelligence + Clash A4 + BIM viewpoints + Files CDE + Takeoff PDF/Excel' },
  { version: '3.11.0', date: '2026-05-20',             summary: 'Wave 3/4 modules + Validation@Import (GAEB/Excel) + GAEB X84 writer + RVT diagnostics + /about redesign' },
  { version: '3.10.1', date: '2026-05-19',             summary: '/match-elements "how it works" collapsed by default' },
  { version: '3.10.0', date: '2026-05-19',             summary: '/files ACC-grade wave + Clash collab/metadata + match-elements polish' },
  { version: '3.9.1',  date: '2026-05-19', tag: 'FIX', summary: 'Clash model labels read as models, not projects' },
  { version: '3.9.0',  date: '2026-05-19',             summary: 'BOQ section-scoped add + AI model auto-recovery + toolbar polish + dashboard customize + PDF compare' },
  { version: '3.8.0',  date: '2026-05-19',             summary: 'Clash coordination depth + Match-Elements UX & lifecycle hardening + match determinism fix' },
  { version: '3.7.0',  date: '2026-05-19',             summary: 'Clash Detection module + GitHub issue sweep + file-manager polish + correctness fixes' },
  { version: '3.6.1',  date: '2026-05-18', tag: 'FIX', summary: 'Visible nested BOQ hierarchy (recursive parent_id walk), collision-free ordinals, pdf_export float fix' },
  { version: '3.6.0',  date: '2026-05-18',             summary: 'Multi-level BOQ hierarchy (depth 8) + resource-code dedup + match 7-stage pipeline restored + takeoff h-scroll' },
  { version: '3.5.0',  date: '2026-05-18',             summary: 'Pipeline Builder (v3037) + BOQ FX-correct CSV/Excel exports + Currency column + frozen FX appendix + reuse codes' },
  { version: '3.4.1',  date: '2026-05-17', tag: 'FIX', summary: 'Project photos and file thumbnails load reliably; demo projects include Revit + IFC models' },
  { version: '3.4.0',  date: '2026-05-17',             summary: 'Professional showcase BOQs + colored real-IFC hero BIM + viewer z-fight fix; force-seed on shared prod DB' },
  { version: '3.3.1',  date: '2026-05-17',             summary: '7-project localized showcase committed as prebuilt snapshot, auto-seeded on fresh install' },
  { version: '3.3.0',  date: '2026-05-16',             summary: 'Reusable BOQ codes — linked positions, master/instance badges, one-click unlink + deep correctness pass' },
  { version: '3.2.0',  date: '2026-05-16', tag: 'FIX', summary: 'Clean-install fix (dynamic create_all for 18 modules) + Planning/Field-Ops 10-module audit + 62-page verify' },
  { version: '3.1.0',  date: '2026-05-15',             summary: 'Deep logic & correctness sweep across 23 modules over 10 waves' },
  { version: '3.0.9',  date: '2026-05-15',             summary: 'Project setup wizard UI (Slice 2) + converter PE-header integrity gate (closes WinError 216 class)' },
  { version: '3.0.8',  date: '2026-05-15', tag: 'FIX', summary: 'O_BINARY converter-download fix (WinError 216 root cause) + project setup wizard backend + visible match pipeline' },
  { version: '3.0.7',  date: '2026-05-14',             summary: 'Resource-based cost-DB import — docs, templates, downloads' },
  { version: '3.0.6',  date: '2026-05-14',             summary: 'DWG upload responsiveness + 6 new HF regions + sidebar branding' },
  { version: '3.0.5',  date: '2026-05-14', tag: 'FIX', summary: 'Match-elements correctness pass (4 root-cause bugs) + full Mongolian (2300 keys, 99.2%) + 9 vitest repairs' },
  { version: '3.0.4',  date: '2026-05-13',             summary: 'Polish pass + community contributor flow' },
  { version: '3.0.3',  date: '2026-05-13',             summary: 'FSM engine + IFC parser ISO 16739-1:2024 + Ed25519 manifest signing + sidebar collapse + WideModal sweep' },
  { version: '3.0.1',  date: '2026-05-13',             summary: '18-Modules Wave + India stability (ezdxf, Devanagari OCR, lakh-crore parser, UTM43N/44N + 16 regions)' },
  { version: '3.0.0',  date: '2026-05-12', tag: 'MILESTONE', summary: 'v3 milestone — rolled up v2.x, deploy procedure validated, 71 modules loaded' },

  // ── v2.9.x — pre-v3 rapid iteration ──────────────────────────────────────
  { version: '2.9.42', date: '2026-05-12',             summary: 'Dashboard backdrop trap fix (relative-isolate stacking context) + style polish' },
  { version: '2.9.39', date: '2026-05-11',             summary: '12 African catalogues (registry 30→42) + ranker monkeypatch fixes' },
  { version: '2.9.38', date: '2026-05-11',             summary: '11 classification standards data-driven (was 3) + 80-entry macro bridge + 28 YAML region groups' },
  { version: '2.9.37', date: '2026-05-11',             summary: 'Africa pack (19 currencies, 24 regions), Apple dashboard backdrop, /match-elements one-click EN install' },
  { version: '2.9.36', date: '2026-05-10',             summary: '/match-elements 10-pass polish — a11y, perf, toasts, UX' },
  { version: '2.9.35', date: '2026-05-10',             summary: 'Closed v3 §10 Gap 4 — analytics endpoint + dashboard' },
  { version: '2.9.34', date: '2026-05-10',             summary: 'Versions bumped, dist built — handover mid-session save' },
  { version: '2.9.32', date: '2026-05-08',             summary: '/match-elements Phase A — BIM + vector/lexical/resources matchers + UX' },
  { version: '2.9.26', date: '2026-05-07',             summary: 'v3 Qdrant migration backend — SearchPlan + 29 hard/soft filters + BGE rerank + recall benchmark' },
  { version: '2.9.25', date: '2026-05-07', tag: 'FIX', summary: '/costs perf index for no-region search + estimator role normalization + dev-DB cleanup' },
  { version: '2.9.24', date: '2026-05-07',             summary: 'Wave A correctness + DWG one-click install + BIM panel polish' },
  { version: '2.9.20', date: '2026-05-07',             summary: 'i18n perf split — 5.5 MB → 26 lazy chunks (~96% boot reduction EN)' },
  { version: '2.9.19', date: '2026-05-07',             summary: 'Bid comparison sticky column + photo MIME hardening (HEIC/HEIF/AVIF/TIFF magic-byte)' },
  { version: '2.9.18', date: '2026-05-07',             summary: '3-way invoice match + risk owner picker + Gantt resize' },
  { version: '2.9.17', date: '2026-05-07',             summary: 'Procurement→finance subscriber + CO→budget delta + PO numbering retry + 9-locale tasks importer' },
  { version: '2.9.16', date: '2026-05-06',             summary: 'Finance correctness + ProjectBudget currency_code + 9 comm subscribers + 22-locale files.* backfill' },
  { version: '2.9.15', date: '2026-05-06', tag: 'SECURITY', summary: 'Cross-category IDOR sweep (~73 endpoints) — Planning + Communication + Procurement + Documents' },
  { version: '2.9.14', date: '2026-05-06', tag: 'SECURITY', summary: 'Wave 5 P0 IDOR fixes (risk + changeorders + contacts export) + Settings UI redesign' },
  { version: '2.9.13', date: '2026-05-06',             summary: 'DDC converter version display on /bim + /quantities, force-update reinstall' },
  { version: '2.9.12', date: '2026-05-06', tag: 'FIX', summary: 'Upload caps removed (10 routers), webp MIME fix, BOQ 404s, /files i18n in 9 langs' },
  { version: '2.9.1',  date: '2026-05-05',             summary: 'Multi-currency BOQ (#88) + file manager (#109) + DWG button (#110) + BIM viewer DDC redirect' },
  { version: '2.9.0',  date: '2026-05-05',             summary: 'CDE deep audit, ISO 19650, suitability lookup, audit log, Gate B' },

  // ── v2.8.x — per-project catalogue binding ───────────────────────────────
  { version: '2.8.3', date: '2026-05-04', tag: 'FIX', summary: 'Clean-install fixes — version label skew, /projects/{id}/boq 404, /costs auto-region' },
  { version: '2.8.2', date: '2026-05-04',             summary: 'Per-project CWICR catalogue binding shipped — v280–v282 migrations reached prod' },

  // ── v2.7.x — stable rollup ───────────────────────────────────────────────
  { version: '2.7.0', date: '2026-05-03', tag: 'SECURITY', summary: 'IDOR batch 4 (markups), N+1 fixes (meetings/fieldreports/punchlist/tasks), 53/53 routes clean' },

  // ── v2.6.x — IDOR sweep, dashboards, compliance ──────────────────────────
  { version: '2.6.50', date: '2026-05-02', tag: 'SECURITY', summary: 'IDOR batch 4 (markups), N+1 fixes, module-loaded probe, ReactFlow handles fix' },
  { version: '2.6.7',  date: '2026-04-27',             summary: 'Annotation persistence to backend; full 10-type whitelist in takeoff/schemas.py' },
  { version: '2.6.4',  date: '2026-04-27',             summary: 'T00–T13 dashboards/compliance backlog complete (5 patches v2.6.0→v2.6.4)' },
  { version: '2.6.0',  date: '2026-04-26',             summary: 'BCF I/O re-allowed (issues / viewpoints / validation reports) — earlier ban lifted' },

  // ── v2.5.x — observability + DWG/PDF takeoff hardening ───────────────────
  { version: '2.5.0', date: '2026-04-25', tag: 'FIX', summary: 'PDF takeoff page indicator fix (stale closure), alembic v232 merge, viewer state-leak hardening' },

  // ── v2.4.x → 2.0.x ───────────────────────────────────────────────────────
  { version: '2.4.0', date: '2026-04-22',             summary: 'Observability — reporting, takeoff, BOQ wildcard; GAEB rule set 1→5; i18n for 42 validation rules' },
  { version: '2.3.1', date: '2026-04-22',             summary: 'Pluggable EmailBackend (console/smtp/noop/memory); Contact.tenant_id; cache error logging' },
  { version: '2.3.0', date: '2026-04-22',             summary: 'Forgot-password reset link delivery wired end-to-end' },
  { version: '2.2.0', date: '2026-04-21',             summary: 'Mid-cycle release between 2.1 and 2.3' },
  { version: '2.1.0', date: '2026-04-20',             summary: 'DWG + PDF takeoff per-tool shortcuts, undo/redo, snap modes; BIM 5D cost colour mode; CAD-BI URL state' },
  { version: '2.0.0', date: '2026-04-20', tag: 'MILESTONE', summary: 'AI Chat SSE reliability, AI settings encryption, DDC provenance markers, 61/61 tests green' },

  // ── v1.9.x — security emergency sprint + DWG ─────────────────────────────
  { version: '1.9.7', date: '2026-04-19', tag: 'SECURITY', summary: 'Security sprint — 10 critical auth/input-validation holes closed (JWT type, user existence, viewer-default)' },
  { version: '1.9.6', date: '2026-04-19', tag: 'SECURITY', summary: 'defusedxml GAEB import, magic-byte file validator, Decimal money arithmetic end-to-end' },
  { version: '1.9.5', date: '2026-04-18',             summary: 'API drift normalised (Submittals, Meetings, Safety, Inspections, NCR) + i18n modernisation' },
  { version: '1.9.4', date: '2026-04-18',             summary: 'Transmittals edit/delete, DWG scale 1:N, Line/Polyline/Circle tools, security: markdown rejects js:/data:' },
  { version: '1.9.3', date: '2026-04-18',             summary: 'DWG background uploads, right-click → Create task / Link, Export PDF from Summary tab' },
  { version: '1.9.2', date: '2026-04-18',             summary: 'BIM duplicate Link-to-BOQ removed; 4D Schedule disabled with coming-soon tooltip' },
  { version: '1.9.1', date: '2026-04-18',             summary: 'DWG ranked hit-test, Power-BI slicers + Recharts, SavedViews, Meetings 50k-char minutes' },
  { version: '1.9.0', date: '2026-04-17',             summary: 'BOQ optimistic add, React Query offline-first, Quantity Rules reliably listed' },

  // ── v1.8.x — BOQ ↔ PDF/DWG deep linking ──────────────────────────────────
  { version: '1.8.3', date: '2026-04-17',             summary: 'BOQ Linked Geometry "Apply to BOQ" redesign + cross-link module uploads → Documents' },
  { version: '1.8.2', date: '2026-04-17',             summary: 'Documents file-type routing (PDF/DWG/RVT/IFC) + deep-links + filmstrip taller cards' },
  { version: '1.8.1', date: '2026-04-17',             summary: 'DWG Takeoff full "Link to BOQ" picker + summary bar + CSV export of measurements' },
  { version: '1.8.0', date: '2026-04-17',             summary: 'BOQ ↔ PDF Takeoff deep linking, quantity auto-transfers, red/amber link icons' },

  // ── v1.7.x — BIM + DWG + cross-module ────────────────────────────────────
  { version: '1.7.2', date: '2026-04-16',             summary: 'BIM Viewer toolbar shift, Linked Geometry 3-column popover, Σ vs = aggregation semantics' },
  { version: '1.7.1', date: '2026-04-16',             summary: 'BIM landing redesign, Tasks filter fix, 56 hardcoded colors → semantic tokens, 20+ i18n strings' },
  { version: '1.7.0', date: '2026-04-15',             summary: 'BIM linked-BOQ panel, DWG polygon measurements, Assemblies JSON I/O, Tasks Kanban' },

  // ── v1.6.x → v1.0 ────────────────────────────────────────────────────────
  { version: '1.6.0', date: '2026-04-15',             summary: 'BIM Linked Geometry Preview in BOQ grid + Quantity Picker + DWG polyline area/perimeter' },
  { version: '1.5.2', date: '2026-04-14', tag: 'FIX', summary: 'Unit dropdown selection fix in BOQ editor, ezdxf compatibility in Docker builds' },
  { version: '1.5.1', date: '2026-04-14', tag: 'FIX', summary: 'Tendering deadline column truncation, BOQ description editing replaced broken autocomplete' },
  { version: '1.5.0', date: '2026-04-13', tag: 'SECURITY', summary: '4 vulnerabilities + 2 concurrency bugs fixed; IFC4x3 civil (30+ entities); 185 backend + 55 E2E tests' },
  { version: '1.4.8', date: '2026-04-11',             summary: 'Real-time collaboration L1 — soft locks + presence; BOQ row-level locking during cell editing' },
  { version: '1.4.7', date: '2026-04-11',             summary: 'BIM determinate progress, converter preflight + auto-install, vector routes factory (-105 LOC)' },
  { version: '1.4.6', date: '2026-04-11', tag: 'SECURITY', summary: 'Contacts IDOR fix, collaboration permission checks, notifications subscriber framework' },
  { version: '1.4.5', date: '2026-04-11',             summary: 'Cross-module integrity audit, 135 new vector-adapter tests, requirements PATCH + bulk-delete' },
  { version: '1.4.4', date: '2026-04-11', tag: 'FIX', summary: 'Vector auto-backfill memory hazard, Python 3.14 datetime.utcnow() sweep' },
  { version: '1.4.3', date: '2026-04-11',             summary: 'Requirements ↔ BIM cross-linking (5th link type), 8th vector collection, Global Search facet' },
  { version: '1.4.2', date: '2026-04-11', tag: 'SECURITY', summary: 'SQL injection guard in LanceDB id-quoting, Qdrant payload mutation fix, frontend deep links' },
  { version: '1.4.1', date: '2026-04-11',             summary: 'Validation + Chat vector adapters, auto-backfill on startup, Semantic Search Status panel' },
  { version: '1.4.0', date: '2026-04-11',             summary: 'Semantic memory — 7 vector collections, multilingual embedding (50+ langs), Global Search (Cmd+Shift+K)' },
  { version: '1.3.32', date: '2026-04-10',            summary: 'BIM health-stats banner, smart-filter chips, 3 new color-by compliance modes at 60 fps' },
  { version: '1.3.22', date: '2026-04-11',            summary: 'BIM ↔ BOQ linking full E2E UI, Quick Takeoff bulk-link, BIM Quantity Rules page' },
  { version: '1.3.18', date: '2026-04-10', tag: 'FIX', summary: 'BIM COLLADA materials, camera fit, delete file cleanup; markups in PDF units; zip-slip validation' },
  { version: '1.3.16', date: '2026-04-10', tag: 'SECURITY', summary: 'validation/tendering/PI ownership checks, AI keys encrypted at rest with Fernet' },
  { version: '1.3.15', date: '2026-04-10', tag: 'SECURITY', summary: 'BIM/finance/contacts/RFQ permission checks, project analytics scoped by owner' },
  { version: '1.3.13', date: '2026-04-10',            summary: 'pandas/pyarrow in base deps; BIM geometry visible on first load; demo-mode banner' },
  { version: '1.3.10', date: '2026-04-10', tag: 'FIX', summary: 'Windows Anaconda startup crash, lazy vector DB loading (-30s startup), SPA routing for prod' },
  { version: '1.3.8',  date: '2026-04-10',            summary: 'BIM filter panel + element explorer + fast mesh visibility toggle for 16k+ elements' },
  { version: '1.3.6',  date: '2026-04-10', tag: 'FIX', summary: 'BIM geometry loads (token auth for ColladaLoader), /chat 404 (duplicate prefix removed)' },
  { version: '1.3.0',  date: '2026-04-10',            summary: 'AI Chat full-page workspace with 11 ERP tools, BIM Viewer redesign, DDC Community Converter' },
  { version: '1.2.0',  date: '2026-04-09',            summary: 'Project Completion Intelligence (AI co-pilot), Architecture Map, Dashboard KPI cards' },
  { version: '1.1.0',  date: '2026-04-09',            summary: 'Bridge release between 1.0 milestone and 1.2 PCI features' },
  { version: '1.0.0',  date: '2026-04-08', tag: 'MILESTONE', summary: 'Interconnected modules across 30+ packages; 14 integrations; 5 demo projects; SVG Gantt + Three.js BIM' },

  // ── v0.x — early development ─────────────────────────────────────────────
  { version: '0.9.1', date: '2026-04-07',             summary: 'Discord webhook + Integration Hub (n8n, Zapier, Make, Google Sheets, Power BI cards)' },
  { version: '0.9.0', date: '2026-04-07',             summary: '30 backend modules + 13 frontend pages; 35 currencies, 198 countries, 20 languages' },
  { version: '0.8.0', date: '2026-04-07',             summary: 'Custom BOQ columns (7 presets), one-click renumber, Project Health bar, strong-password policy' },
  { version: '0.7.0', date: '2026-04-07',             summary: 'Multi-level BOQ sections, Excel import preserves columns, formula engine for assemblies' },
  { version: '0.6.0', date: '2026-04-07',             summary: 'Resource quantities scale with positions, auto unit-rate, drag-and-drop between sections' },
  { version: '0.5.0', date: '2026-04-06',             summary: 'PDF Takeoff, professional Excel + PDF export with cover/signature, CAD/BIM pivot → BOQ' },
  { version: '0.4.0', date: '2026-04-06',             summary: 'Quick modal dialogs for projects/BOQs/assemblies, BOQ list filters by header project' },
  { version: '0.3.0', date: '2026-04-05',             summary: 'Data Explorer with CSV export, Field Reports, Photo Gallery, Markups, Punch List' },
  { version: '0.2.1', date: '2026-04-04', tag: 'FIX', summary: 'Stronger document download checks, CORS hardening, login enumeration fix, 9 deps bumped' },
  { version: '0.1.1', date: '2026-04-01', tag: 'FIX', summary: 'Settings page freeze, DELETE project 500, XSS sanitization in project names, requirements.txt' },
  { version: '0.1.0', date: '2026-03-27', tag: 'NEW', summary: 'Initial release — 18 validation rules, AI estimation, 55K cost items, 20 languages, AG Grid BOQ' },
];

/**
 * Parse a semver-ish version string into a comparable tuple. Falls back to
 * lexical compare for malformed input — that keeps a typo from blowing up
 * the whole list render.
 */
function parseVersion(v: string): number[] {
  return v.split('.').map(part => {
    const n = parseInt(part, 10);
    return Number.isFinite(n) ? n : 0;
  });
}

function compareVersionsDesc(a: ChangelogEntry, b: ChangelogEntry): number {
  const av = parseVersion(a.version);
  const bv = parseVersion(b.version);
  for (let i = 0; i < Math.max(av.length, bv.length); i += 1) {
    const ai = av[i] ?? 0;
    const bi = bv[i] ?? 0;
    if (ai !== bi) return bi - ai;
  }
  return 0;
}

// Older releases (> 6 months ago relative to "today") fade slightly so the
// recent ones pop. We use a stable date constant, not Date.now(), so the
// muted band doesn't silently drift between builds.
const TODAY = new Date('2026-05-21T00:00:00Z');
const FRESH_WINDOW_DAYS = 30 * 6;
function isStale(date: string): boolean {
  const d = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return false;
  const ageDays = (TODAY.getTime() - d.getTime()) / 86_400_000;
  return ageDays > FRESH_WINDOW_DAYS;
}

const TAG_VARIANT: Record<Tag, 'success' | 'blue' | 'warning' | 'error' | 'neutral'> = {
  NEW: 'success',
  FIX: 'warning',
  BETA: 'blue',
  SECURITY: 'error',
  MILESTONE: 'blue',
};

export function Changelog() {
  const { t } = useTranslation();

  const entries = [...CHANGELOG].sort(compareVersionsDesc);
  // Latest 7 versions get visible tag chips; older ones drop the tag to keep
  // the card list calm. The tag is still encoded in the data, just not shown.
  const FRESH_TAG_COUNT = 7;

  const tagLabel = (tag: Tag): string => {
    switch (tag) {
      case 'NEW':       return t('about.changelog_tag_new', { defaultValue: 'NEW' });
      case 'FIX':       return t('about.changelog_tag_fix', { defaultValue: 'FIX' });
      case 'BETA':      return t('about.changelog_tag_beta', { defaultValue: 'BETA' });
      case 'SECURITY':  return t('about.changelog_tag_security', { defaultValue: 'SECURITY' });
      case 'MILESTONE': return t('about.changelog_tag_milestone', { defaultValue: 'MILESTONE' });
    }
  };

  return (
    <div id="changelog">
      <div className="flex items-baseline justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-content-primary">
          {t('about.changelog_title', { defaultValue: 'Changelog' })}
        </h2>
        <span className="text-2xs text-content-tertiary tabular-nums">
          {t('about.changelog_count', {
            defaultValue: '{{count}} releases',
            count: entries.length,
          })}
        </span>
      </div>

      {/*
        CSS columns layout — packs variable-height cards into the shorter
        column automatically without the gymnastics of a manual two-list
        split. `break-inside-avoid` on each card keeps a single entry from
        being torn across the column boundary.
      */}
      <div className="columns-1 md:columns-2 gap-4 [column-fill:_balance]">
        {entries.map((entry, idx) => {
          const isCurrent = entry.version === APP_VERSION;
          const stale = !isCurrent && isStale(entry.date);
          const showTag = entry.tag && idx < FRESH_TAG_COUNT;
          return (
            <article
              key={`${entry.version}-${entry.date}`}
              className={[
                'mb-3 break-inside-avoid rounded-xl border px-3.5 py-2.5',
                'bg-white/60 backdrop-blur-xl border-white/40',
                'dark:bg-slate-900/40 dark:border-white/[0.05]',
                'transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md hover:bg-white/80 dark:hover:bg-slate-900/60',
                isCurrent ? 'ring-1 ring-emerald-500/50 bg-emerald-50/60 dark:bg-emerald-900/15 dark:ring-emerald-400/40' : '',
                stale ? 'opacity-70' : '',
              ].join(' ')}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant={isCurrent ? 'success' : 'blue'} size="sm">
                  v{entry.version}
                </Badge>
                <span className={`font-mono text-2xs tabular-nums ${stale ? 'text-content-quaternary' : 'text-content-tertiary'}`}>
                  {entry.date}
                </span>
                {isCurrent && (
                  <span className="text-2xs font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                    {t('about.current_version', { defaultValue: 'Current' })}
                  </span>
                )}
                {showTag && entry.tag && (
                  <Badge variant={TAG_VARIANT[entry.tag]} size="sm">
                    {tagLabel(entry.tag)}
                  </Badge>
                )}
              </div>
              <p className={`mt-1.5 text-xs leading-snug ${stale ? 'text-content-tertiary' : 'text-content-secondary'}`}>
                {entry.summary}
              </p>
            </article>
          );
        })}
      </div>
    </div>
  );
}
