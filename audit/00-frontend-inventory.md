# Frontend Inventory — OpenConstructionERP

Generated: 2026-04-18
Source: `frontend/src/app/App.tsx` + feature tree scan
Scope: React + TypeScript SPA (Vite, React Router v6, Zustand, React Query, i18next)

---

## Summary at a glance

- **Routes defined in `App.tsx`**: 86 (80 real routes + 6 redirect aliases)
- **Plugin module routes (dynamic, from `MODULE_REGISTRY`)**: 33 routes from 34 modules (one module, `assemblies`, has empty `routes: []`)
- **Page components found**: 63 `*Page.tsx` files under `frontend/src/features/**`
- **Zustand stores**: 17 (in `frontend/src/stores/`)
- **Backup/duplicate files**: 1 (`DashboardPage.backup.tsx`, 2 667 LOC)
- **Giant files (>2 000 LOC)**: 18 (.tsx files) + 1 huge i18n file (`i18n-fallbacks.ts`, 50 513 LOC)

---

## Route table (from `frontend/src/app/App.tsx`)

All app routes are wrapped in `<RequireAuth><AppLayout>…</AppLayout></RequireAuth>` via the `<P>` helper (auth required + chrome). Auth pages and `/onboarding` bypass the AppLayout. Heavy pages are `React.lazy()`-loaded.

| Path | Component | Public? | Lazy? |
|---|---|---|---|
| `/login` | `LoginPage` | public | no |
| `/register` | `RegisterPage` | public | no |
| `/forgot-password` | `ForgotPasswordPage` | public | no |
| `/onboarding` | `OnboardingWizard` | auth (no layout) | no |
| `/` | `DashboardPage` | auth | no |
| `/ai-estimate` | `QuickEstimatePage` | auth | no |
| `/advisor` | `AdvisorPage` | auth | **lazy** |
| `/chat` | `ERPChatPage` | auth | **lazy** |
| `/cad-takeoff` | redirect → `/data-explorer` | auth | — |
| `/data-explorer` | `CadDataExplorerPage` | auth | **lazy** |
| `/bim` | `BIMPage` | auth | **lazy** |
| `/bim/rules` | `BIMQuantityRulesPage` | auth | **lazy** |
| `/bim/:modelId` | `BIMPage` | auth | **lazy** |
| `/projects/:projectId/bim` | `BIMPage` | auth | **lazy** |
| `/projects/:projectId/bim/:modelId` | `BIMPage` | auth | **lazy** |
| `/projects` | `ProjectsPage` | auth | no |
| `/projects/new` | `CreateProjectPage` | auth | no |
| `/projects/:projectId` | `ProjectDetailPage` | auth | no |
| `/projects/:projectId/boq/new` | `CreateBOQPage` | auth | no |
| `/boq` | `BOQListPage` | auth | no |
| `/boq/:boqId` | `BOQEditorPage` | auth | **lazy** |
| `/templates` | `TemplatesPage` | auth | no |
| `/costs` | `CostsPage` | auth | no |
| `/costs/import` | `ImportDatabasePage` | auth | no |
| `/catalog` | `CatalogPage` | auth | **lazy** |
| `/assemblies` | `AssembliesPage` | auth | no |
| `/assemblies/new` | `CreateAssemblyPage` | auth | no |
| `/assemblies/:assemblyId` | `AssemblyEditorPage` | auth | no |
| `/validation` | `ValidationPage` | auth | no |
| `/quantities` | `QuantitiesPage` | auth | no |
| `/takeoff` | `TakeoffPage` | auth | **lazy** |
| `/dwg-takeoff` | `DwgTakeoffPage` | auth | **lazy** |
| `/schedule` | `SchedulePage` | auth | **lazy** |
| `/5d` | `CostModelPage` | auth | **lazy** |
| `/analytics` | `AnalyticsPage` | auth | **lazy** |
| `/reports` | `ReportsPage` | auth | **lazy** |
| `/reporting` | `ReportingPage` | auth | **lazy** |
| `/tendering` | `TenderingPage` | auth | **lazy** |
| `/changeorders` | `ChangeOrdersPage` | auth | **lazy** |
| `/documents` | `DocumentsPage` | auth | **lazy** |
| `/photos` | `PhotoGalleryPage` | auth | **lazy** |
| `/risks` | `RiskRegisterPage` | auth | **lazy** |
| `/requirements` | redirect → `/bim/rules` | auth | — |
| `/markups` | `MarkupsPage` | auth | **lazy** |
| `/punchlist` | `PunchListPage` | auth | **lazy** |
| `/field-reports` | `FieldReportsPage` | auth | **lazy** |
| `/finance` | `FinancePage` | auth | **lazy** |
| `/projects/:projectId/finance` | `FinancePage` | auth | **lazy** |
| `/procurement` | `ProcurementPage` | auth | **lazy** |
| `/projects/:projectId/procurement` | `ProcurementPage` | auth | **lazy** |
| `/safety` | `SafetyPage` | auth | **lazy** |
| `/projects/:projectId/safety` | `SafetyPage` | auth | **lazy** |
| `/contacts` | `ContactsPage` | auth | **lazy** |
| `/tasks` | `TasksPage` | auth | **lazy** |
| `/projects/:projectId/tasks` | `TasksPage` | auth | **lazy** |
| `/rfi` | `RFIPage` | auth | **lazy** |
| `/projects/:projectId/rfi` | `RFIPage` | auth | **lazy** |
| `/submittals` | `SubmittalsPage` | auth | **lazy** |
| `/projects/:projectId/submittals` | `SubmittalsPage` | auth | **lazy** |
| `/correspondence` | `CorrespondencePage` | auth | **lazy** |
| `/projects/:projectId/correspondence` | `CorrespondencePage` | auth | **lazy** |
| `/cde` | `CDEPage` | auth | **lazy** |
| `/projects/:projectId/cde` | `CDEPage` | auth | **lazy** |
| `/transmittals` | `TransmittalsPage` | auth | **lazy** |
| `/projects/:projectId/transmittals` | `TransmittalsPage` | auth | **lazy** |
| `/meetings` | `MeetingsPage` | auth | **lazy** |
| `/projects/:projectId/meetings` | `MeetingsPage` | auth | **lazy** |
| `/inspections` | `InspectionsPage` | auth | **lazy** |
| `/projects/:projectId/inspections` | `InspectionsPage` | auth | **lazy** |
| `/ncr` | `NCRPage` | auth | **lazy** |
| `/projects/:projectId/ncr` | `NCRPage` | auth | **lazy** |
| `/users` | `UserManagementPage` | auth | **lazy** |
| `/modules` | `ModulesPage` | auth | no |
| `/setup/databases` | `DatabaseSetupPage` | auth | no |
| `/settings` | `SettingsPage` | auth | no |
| `/integrations` | `IntegrationsPage` | auth | no |
| `/about` | `AboutPage` | auth | no |
| `/project-intelligence` | `ProjectIntelligencePage` | auth | **lazy** |
| `/architecture` | `ArchitectureMapPage` | auth | **lazy** |
| `/dashboard` | redirect → `/` | auth | — |
| `/change-orders` | redirect → `/changeorders` | auth | — |
| `/punch-list` | redirect → `/punchlist` | auth | — |
| `/variations` | redirect → `/changeorders` | auth | — |
| `/estimates` | redirect → `/boq` | auth | — |
| `/profile` | redirect → `/settings` | auth | — |
| `/notifications` | redirect → `/settings` | auth | — |
| `*` | `NotFoundPage` (or redirect to `/login`) | auth | — |

### Plugin module routes (dynamic, mounted via `useModuleRouteElements`)

Defined in `frontend/src/modules/_registry.ts` (34 modules). These only render when the module is enabled via `useModuleStore`. All plugin routes are lazy-loaded (each manifest uses `React.lazy`).

| Path | Module |
|---|---|
| `/benchmarks` | `cost-benchmark` |
| `/collaboration` | `collaboration` |
| `/risk-analysis` | `risk-analysis` |
| `/sustainability` | `sustainability` |
| `/takeoff-viewer` | `pdf-takeoff` (`TakeoffViewerModule`) |
| `/gaeb-exchange` | `gaeb-exchange` |
| `/uk-nrm-exchange` | `uk-nrm-exchange` |
| `/us-masterformat-exchange` | `us-masterformat-exchange` |
| `/fr-dpgf-exchange` | `fr-dpgf-exchange` |
| `/uae-boq-exchange` | `uae-boq-exchange` |
| `/au-boq-exchange` | `au-boq-exchange` |
| `/ca-boq-exchange` | `ca-boq-exchange` |
| `/nordic-ns3420-exchange` | `nordic-ns3420-exchange` |
| `/cz-boq-exchange` | `cz-boq-exchange` |
| `/de-din276-exchange` | `de-din276-exchange` |
| `/cn-boq-exchange` | `cn-boq-exchange` |
| `/in-boq-exchange` | `in-boq-exchange` |
| `/br-sinapi-exchange` | `br-sinapi-exchange` |
| `/es-pbc-exchange` | `es-pbc-exchange` |
| `/ru-gesn-exchange` | `ru-gesn-exchange` |
| `/tr-birimfiyat-exchange` | `tr-birimfiyat-exchange` |
| `/jp-sekisan-exchange` | `jp-sekisan-exchange` |
| `/it-computo-exchange` | `it-computo-exchange` |
| `/nl-stabu-exchange` | `nl-stabu-exchange` |
| `/pl-knr-exchange` | `pl-knr-exchange` |
| `/kr-boq-exchange` | `kr-boq-exchange` |
| `/modules` (ddc-ifc-converter nav only) | `ddc-ifc-converter` |
| `/modules` (ddc-rvt-converter nav only) | `ddc-rvt-converter` |

Modules registered but with **no routes** (nav/visual-only, or routes declared in core `App.tsx`): `assemblies`, `validation`, `schedule`, `5d-cost-model`, `tendering`, `reports`. These are effectively flags for the sidebar nav toggle.

---

## Page inventory (feature pages)

Column key:
- **LOC**: raw line count incl. blanks and JSX
- **i18n?**: file imports `useTranslation` from `react-i18next`
- **RQ?**: file uses `useQuery` / `useMutation` / `useInfiniteQuery` from React Query
- **L/E/E?**: has at least one of `isLoading`, `isPending`, `isError`, `SkeletonTable`, `EmptyState` visible in source

| Feature | Path | LOC | i18n? | RQ? | L/E/E? | Notes |
|---|---|---|---|---|---|---|
| About | `frontend/src/features/about/AboutPage.tsx` | 472 | yes | no | no | Static content; version banner + team info |
| AI Advisor | `frontend/src/features/ai/AdvisorPage.tsx` | 526 | yes | no | no | Conversational cost advisor UI |
| AI Quick Estimate | `frontend/src/features/ai/QuickEstimatePage.tsx` | **3 506** | yes | yes | yes | **Giant** — full AI estimator flow, 5 tabs |
| Analytics | `frontend/src/features/analytics/AnalyticsPage.tsx` | 636 | yes | yes | yes | Charts + drill-down |
| Architecture Map | `frontend/src/features/architecture/ArchitectureMapPage.tsx` | 1 393 | yes | no | yes | System overview diagram page |
| Assemblies | `frontend/src/features/assemblies/AssembliesPage.tsx` | 1 187 | yes | yes | yes | Assembly library list |
| Assembly Editor | `frontend/src/features/assemblies/AssemblyEditorPage.tsx` | 1 068 | yes | yes | yes | Recipe/components editor |
| Create Assembly | `frontend/src/features/assemblies/CreateAssemblyPage.tsx` | 285 | yes | yes | yes | New assembly form |
| Forgot Password | `frontend/src/features/auth/ForgotPasswordPage.tsx` | 184 | yes | no | no | Public route |
| Login | `frontend/src/features/auth/LoginPage.tsx` | 563 | yes | no | yes | Public; handles token + remember me |
| Register | `frontend/src/features/auth/RegisterPage.tsx` | 446 | yes | no | no | Public route |
| BIM Viewer | `frontend/src/features/bim/BIMPage.tsx` | **2 543** | yes | yes | yes | **Giant** — Three.js-backed viewer |
| BIM Quantity Rules | `frontend/src/features/bim/BIMQuantityRulesPage.tsx` | **2 501** | yes | yes | yes | **Giant** — merged with `/requirements` |
| BOQ Editor | `frontend/src/features/boq/BOQEditorPage.tsx` | **3 136** | yes | yes | yes | **Giant** — AG Grid block editor |
| BOQ List | `frontend/src/features/boq/BOQListPage.tsx` | 940 | yes | yes | yes | Cross-project BOQ roster |
| Create BOQ | `frontend/src/features/boq/CreateBOQPage.tsx` | 183 | yes | yes | yes | Modal-like form |
| BOQ Templates | `frontend/src/features/boq/TemplatesPage.tsx` | 526 | yes | yes | yes | Template gallery |
| CAD Data Explorer | `frontend/src/features/cad-explorer/CadDataExplorerPage.tsx` | **2 829** | yes | yes | yes | **Giant** — DDC cad2data browser |
| Catalog | `frontend/src/features/catalog/CatalogPage.tsx` | **2 463** | yes | yes | yes | **Giant** — resource catalog |
| CDE | `frontend/src/features/cde/CDEPage.tsx` | 1 441 | yes | yes | yes | Common data env |
| Change Orders | `frontend/src/features/changeorders/ChangeOrdersPage.tsx` | 1 291 | yes | yes | yes | Aliased `/variations` + `/change-orders` |
| Contacts | `frontend/src/features/contacts/ContactsPage.tsx` | 1 225 | yes | yes | yes | People + orgs directory |
| Correspondence | `frontend/src/features/correspondence/CorrespondencePage.tsx` | 948 | yes | yes | yes | Letters/emails log |
| Cost Model (5D) | `frontend/src/features/costmodel/CostModelPage.tsx` | **2 545** | yes | yes | yes | **Giant** — 5D cost model |
| Costs | `frontend/src/features/costs/CostsPage.tsx` | **2 197** | yes | yes | yes | **Giant** — cost database browser |
| Import Cost DB | `frontend/src/features/costs/ImportDatabasePage.tsx` | 1 635 | yes | yes | yes | CWICR/CSV importer |
| Dashboard | `frontend/src/features/dashboard/DashboardPage.tsx` | **2 433** | yes | yes | yes | **Giant** — widget grid |
| Documents | `frontend/src/features/documents/DocumentsPage.tsx` | 1 617 | yes | yes | yes | File browser + upload |
| Photo Gallery | `frontend/src/features/documents/PhotoGalleryPage.tsx` | 1 294 | yes | yes | yes | Project photos |
| DWG Takeoff | `frontend/src/features/dwg-takeoff/DwgTakeoffPage.tsx` | **3 715** | yes | yes | yes | **Biggest page** — DXF viewer + measure |
| ERP Chat | `frontend/src/features/erp-chat/full-page/ChatFullPage.tsx` | 133 | no | no | no | Thin wrapper, delegates to chat widget |
| Field Reports | `frontend/src/features/fieldreports/FieldReportsPage.tsx` | 1 502 | yes | yes | yes | Daily reports |
| Finance | `frontend/src/features/finance/FinancePage.tsx` | **2 346** | yes | yes | yes | **Giant** — invoices, cost ledger |
| Inspections | `frontend/src/features/inspections/InspectionsPage.tsx` | 1 059 | yes | yes | yes | Safety/QA inspections |
| Integrations | `frontend/src/features/integrations/IntegrationsPage.tsx` | 1 121 | yes | yes | yes | Third-party connectors list |
| Markups | `frontend/src/features/markups/MarkupsPage.tsx` | 1 504 | yes | yes | yes | Drawing annotations |
| Meetings | `frontend/src/features/meetings/MeetingsPage.tsx` | **2 482** | yes | yes | yes | **Giant** — agenda + minutes |
| Modules | `frontend/src/features/modules/ModulesPage.tsx` | 1 508 | yes | yes | yes | Plugin marketplace |
| NCR | `frontend/src/features/ncr/NCRPage.tsx` | 1 072 | yes | yes | yes | Non-conformance reports |
| Procurement | `frontend/src/features/procurement/ProcurementPage.tsx` | 931 | yes | yes | yes | POs, RFQs |
| Project Intelligence | `frontend/src/features/project-intelligence/ProjectIntelligencePage.tsx` | 533 | yes | no | no | AI project insights |
| Create Project | `frontend/src/features/projects/CreateProjectPage.tsx` | 719 | yes | yes | yes | New project wizard |
| Project Detail | `frontend/src/features/projects/ProjectDetailPage.tsx` | **2 338** | yes | yes | yes | **Giant** — hub view |
| Projects | `frontend/src/features/projects/ProjectsPage.tsx` | 919 | yes | yes | yes | Project list |
| Punch List | `frontend/src/features/punchlist/PunchListPage.tsx` | 1 292 | yes | yes | yes | Snag list |
| Quantities | `frontend/src/features/quantities/QuantitiesPage.tsx` | 1 109 | yes | yes | yes | Manual quantities UI |
| Reporting | `frontend/src/features/reporting/ReportingPage.tsx` | 1 025 | yes | no | yes | Dashboards |
| Reports | `frontend/src/features/reports/ReportsPage.tsx` | 1 558 | yes | no | yes | Document-style exports |
| Requirements | `frontend/src/features/requirements/RequirementsPage.tsx` | **2 269** | yes | yes | yes | **DEAD** — route now redirects to `/bim/rules`; still in bundle |
| RFI | `frontend/src/features/rfi/RFIPage.tsx` | 1 249 | yes | yes | yes | Requests for info |
| Risk Register | `frontend/src/features/risk/RiskRegisterPage.tsx` | 649 | yes | yes | yes | Risk list + matrix |
| Safety | `frontend/src/features/safety/SafetyPage.tsx` | 1 577 | yes | yes | yes | Safety module |
| Schedule | `frontend/src/features/schedule/SchedulePage.tsx` | **2 129** | yes | yes | yes | **Giant** — 4D schedule |
| Settings | `frontend/src/features/settings/SettingsPage.tsx` | 1 091 | yes | yes | yes | User prefs + profile |
| Database Setup | `frontend/src/features/setup/DatabaseSetupPage.tsx` | 660 | yes | yes | yes | Cost DB bootstrap |
| Submittals | `frontend/src/features/submittals/SubmittalsPage.tsx` | 1 272 | yes | yes | yes | Material submittals |
| Sustainability | `frontend/src/features/sustainability/SustainabilityPage.tsx` | 545 | yes | yes | yes | **PHANTOM (route)** — no core route, only reachable via plugin `/sustainability` |
| Takeoff | `frontend/src/features/takeoff/TakeoffPage.tsx` | 1 758 | yes | yes | yes | PDF takeoff |
| Tasks | `frontend/src/features/tasks/TasksPage.tsx` | 1 841 | yes | yes | yes | Task board |
| Tendering | `frontend/src/features/tendering/TenderingPage.tsx` | 1 168 | yes | yes | yes | Bid packages |
| Transmittals | `frontend/src/features/transmittals/TransmittalsPage.tsx` | 1 386 | yes | yes | yes | Formal transmittals |
| User Management | `frontend/src/features/users/UserManagementPage.tsx` | 870 | yes | yes | yes | Admin user CRUD |
| Validation | `frontend/src/features/validation/ValidationPage.tsx` | 787 | yes | yes | yes | Validation dashboard |

Totals: **63 pages**, **62 with i18n** (only `ChatFullPage.tsx` skips it because it's a thin delegate), **52 with React Query**, **55 with explicit L/E/E state**.

Pages that use React Query but have **no visible loading/error/empty UI**: none — every RQ-using page had at least one of `isLoading`/`isPending`/`isError`/`EmptyState`/`SkeletonTable`. A handful (`AdvisorPage`, `ProjectIntelligencePage`, `AboutPage`, `ReportingPage`, `ReportsPage`, `ArchitectureMapPage`, `QuickEstimatePage` peripheries) are visually rich but do not fetch from React Query — they either talk directly via `fetch`/`apiGet` or render static/computed data.

Pages that do **NOT** call React Query at all (11):
`AboutPage`, `AdvisorPage`, `ArchitectureMapPage`, `ChatFullPage`, `ForgotPasswordPage`, `LoginPage`, `ProjectIntelligencePage`, `RegisterPage`, `ReportingPage`, `ReportsPage`, `SustainabilityPage`-adjacent helpers. (Login/Register/Forgot use bespoke `fetch`; Advisor/Chat stream via SSE.)

---

## Zustand stores (`frontend/src/stores/`)

17 stores. "Persisted" means the store uses the `zustand/middleware` `persist` wrapper OR manually reads/writes `localStorage`/`sessionStorage`.

| Store | Purpose (from header) | Persisted? |
|---|---|---|
| `useAnalysisStateStore.ts` | Cross-tab analysis state for the CAD Data Explorer — slicers, chart config, saved views | **yes (persist)** |
| `useAuthStore.ts` | JWT access/refresh tokens + decoded role; remember-me toggle | **yes (manual `localStorage`/`sessionStorage`)** |
| `useBIMLinkSelectionStore.ts` | Cross-highlight bus between BOQ editor and BIM viewer | **yes (persist, tiny)** |
| `useBIMUploadStore.ts` | Global BIM upload queue — survives unmount during long RVT/IFC uploads | no (in-memory, intentional) |
| `useBIMViewerStore.ts` | Per-viewer UI state: per-category opacity, Tools tab flag | no |
| `useCostDatabaseStore.ts` | Active region filter shared by cost search + BOQ autocomplete | **yes (persist)** |
| `useDwgUploadStore.ts` | Global DWG upload queue — mirrors BIM upload store | no |
| `useGlobalSearchStore.ts` | Cmd+K semantic search modal state + last query | no |
| `useModuleStore.ts` | Which optional modules are enabled/disabled (manifest-driven) | **yes (persist on toggles — check impl)** |
| `usePreferencesStore.ts` | User preferences: currency, measurement system, date/number format | **yes (persist)** |
| `useProjectContextStore.ts` | Active project + BOQ across pages | **yes (persist, heavy use)** |
| `useRecentStore.ts` | Recent visited entities (projects, BOQs, RFIs, tasks) for sidebar Recent list | **yes (persist)** |
| `useThemeStore.ts` | Light/dark/system theme + `init()` for DOM class toggle | **yes (persist)** |
| `useToastStore.ts` | Toast/notification queue | no |
| `useUploadQueueStore.ts` | Generic upload/CAD conversion progress queue | no |
| `useViewModeStore.ts` | Simple vs Advanced UI mode | no (but likely desired to persist) |
| `useWidgetSettingsStore.ts` | Client-side widget feature flags (separate from `useModuleStore`) | **yes (persist)** |

Stores that really should be persisted but are not: `useViewModeStore`, `useToastStore` (ok), `useUploadQueueStore` (ok — shouldn't survive reload).

Note: three stores have co-located tests (`useAuthStore.test.ts`, `usePreferencesStore.test.ts`, `useProjectContextStore.test.ts`).

---

## Giant files (>2 000 LOC)

18 `.tsx` giants + 1 massive `.ts` (fallback i18n bundle). Risk: long rebuilds, hard to review, high cognitive load.

| LOC | File |
|---|---|
| 50 513 | `frontend/src/app/i18n-fallbacks.ts` (bundled translations — acceptable but consider splitting) |
| 3 715 | `frontend/src/features/dwg-takeoff/DwgTakeoffPage.tsx` |
| 3 506 | `frontend/src/features/ai/QuickEstimatePage.tsx` |
| 3 142 | `frontend/src/modules/pdf-takeoff/TakeoffViewerModule.tsx` |
| 3 137 | `frontend/src/shared/ui/BIMViewer/BIMViewer.tsx` |
| 3 136 | `frontend/src/features/boq/BOQEditorPage.tsx` |
| 2 829 | `frontend/src/features/cad-explorer/CadDataExplorerPage.tsx` |
| 2 667 | `frontend/src/features/dashboard/DashboardPage.backup.tsx` *(backup)* |
| 2 545 | `frontend/src/features/costmodel/CostModelPage.tsx` |
| 2 543 | `frontend/src/features/bim/BIMPage.tsx` |
| 2 501 | `frontend/src/features/bim/BIMQuantityRulesPage.tsx` |
| 2 482 | `frontend/src/features/meetings/MeetingsPage.tsx` |
| 2 463 | `frontend/src/features/catalog/CatalogPage.tsx` |
| 2 433 | `frontend/src/features/dashboard/DashboardPage.tsx` |
| 2 346 | `frontend/src/features/finance/FinancePage.tsx` |
| 2 338 | `frontend/src/features/projects/ProjectDetailPage.tsx` |
| 2 269 | `frontend/src/features/requirements/RequirementsPage.tsx` *(dead code — route redirects)* |
| 2 197 | `frontend/src/features/costs/CostsPage.tsx` |
| 2 129 | `frontend/src/features/schedule/SchedulePage.tsx` |

Several additional files sit just under 2 000 LOC (`tasks/TasksPage.tsx` at 1 841; `onboarding/OnboardingWizard.tsx` at 1 809; `bim/BIMFilterPanel.tsx` at 1 775; `takeoff/TakeoffPage.tsx` at 1 758; `boq/grid/cellRenderers.tsx` at 1 696; `shared/ui/BIMViewer/ElementManager.ts` at 1 667; `costs/ImportDatabasePage.tsx` at 1 635; `documents/DocumentsPage.tsx` at 1 617; `boq/BOQGrid.tsx` at 1 611) — worth watching.

---

## Duplicate / backup files

| File | LOC | Action |
|---|---|---|
| `frontend/src/features/dashboard/DashboardPage.backup.tsx` | 2 667 | **Delete** — pre-refactor backup of `DashboardPage.tsx` (which is now 2 433 LOC, the active version). Ships in dev builds but is not imported anywhere. |

No other `*_old.*`, `*_v2.*`, `*.backup.*` or similar copies were found under `frontend/src/`.

Not backups but worth flagging:
- `frontend/src/features/requirements/RequirementsPage.tsx` — the `/requirements` route was replaced by a `<Navigate to="/bim/rules">` but the file (2 269 LOC) still exists and is not imported from `App.tsx`. Verify no other referrer then delete or move behind a feature flag.
- `frontend/e2e/_pro-*.spec.ts` + `_pro-preview.spec.ts` (marketing preview specs, untracked) and `frontend/e2e/bim-selection-diagnostic.spec.ts` (untracked) — dev scaffolding, not part of inventory but present in `git status`.

---

## Possible phantom routes (frontend exists, backend unclear)

Cross-referenced against `backend/app/modules/` directory listing. Paths flagged when a confident backend module with a matching name was NOT found. **These are candidates — many might use shared endpoints (e.g., `/api/v1/documents` for multiple features). Verify before acting.**

| Route | Frontend page | Backend module (best match) | Verdict |
|---|---|---|---|
| `/advisor` | `AdvisorPage` | `ai` | OK — AI advisor endpoints under `ai` |
| `/ai-estimate` | `QuickEstimatePage` | `ai` | OK |
| `/analytics` | `AnalyticsPage` | — (no `analytics` module) | **Suspicious** — pulls data from multiple sources? confirm. |
| `/architecture` | `ArchitectureMapPage` | `architecture_map` | OK |
| `/catalog` | `CatalogPage` | `catalog` | OK |
| `/chat` | `ChatFullPage` | `erp_chat` | OK |
| `/data-explorer` | `CadDataExplorerPage` | `cad` | OK (DDC cad2data) |
| `/modules` | `ModulesPage` | — (static registry + possibly `integrations`) | **Client-side only** (module toggles persist in Zustand) — backend optional. Confirm. |
| `/photos` | `PhotoGalleryPage` | `documents` | OK (documents module handles photos) |
| `/quantities` | `QuantitiesPage` | `takeoff` | Likely OK — verify. |
| `/reporting` | `ReportingPage` | `reporting` | OK |
| `/reports` | `ReportsPage` | `reporting` | OK |
| `/requirements` | (redirected away) | `requirements` | Route removed but backend module still exists. **Consolidate or deprecate the backend module** to match frontend. |
| `/risks` | `RiskRegisterPage` | `risk` | OK |
| `/setup/databases` | `DatabaseSetupPage` | `costs` | OK |
| `/templates` | `TemplatesPage` | `boq` | OK (BOQ templates) |
| `/takeoff-viewer` | `TakeoffViewerModule` (plugin) | `takeoff` | OK |
| `/about` | `AboutPage` | — | Static content only, no backend. OK. |
| `/project-intelligence` | `ProjectIntelligencePage` | `project_intelligence` | OK |

The three clearest flags:
1. **`/analytics`** — no `analytics` backend module; page likely stitches together data from several modules. Confirm no missing API surface.
2. **`/modules`** — UI is purely Zustand-driven. Fine for MVP but will need a backend once plugins install/update via marketplace.
3. **`/requirements`** — route removed but **`backend/app/modules/requirements/`** is still present. Align naming or merge into `bim_requirements`.

Exchange-pack plugin routes (`/gaeb-exchange`, `/uk-nrm-exchange`, `/us-masterformat-exchange`, …, 26 total) don't have 1-to-1 backend modules — they are region-specific import/export wizards. That's intentional; they share the `boq` + `costs` backend and convert formats client-side or via shared endpoints. Flag only if E2E import fails.

---

## Observations & risks

1. **Routing spread thin** — 80+ real routes declared in a single `App.tsx` (434 LOC). Consider a `routes.tsx` extraction or per-feature route manifests to mirror module pattern.
2. **Giant pages are concentrated in estimation workflow** — BOQ Editor, DWG Takeoff, BIM, Cost Model, Dashboard, Catalog, Costs, Schedule. All could benefit from splitting into feature hooks + sub-components.
3. **i18n compliance is excellent** (62/63 pages use `useTranslation`). Only `ChatFullPage` skips — probably fine, it's a thin wrapper.
4. **React Query coverage is good** (53/63 pages). Auth pages and a few AI pages skip — expected.
5. **Loading/error/empty is present on 55/63 pages** — missing mostly on static/public pages.
6. **Dead code**: `DashboardPage.backup.tsx` (2 667 LOC) and `RequirementsPage.tsx` (2 269 LOC) are unused. Combined ~5 000 LOC cleanup opportunity.
7. **Backend module `requirements/` vs frontend `requirements/` redirect** — mismatch worth reconciling.
