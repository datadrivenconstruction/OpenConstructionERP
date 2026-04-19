# 00 — Inventory

> Full inventory of DokuFluss (Phase 1, read-only). Build date: 2026-04-17.

## Stack & versions

### Backend (`backend/`)
- Python 3.12 (slim), FastAPI **0.115.6**, Uvicorn 0.34.0 (prod 4 workers)
- SQLAlchemy **2.0.36** (async), Alembic 1.14.1, asyncpg 0.30.0, aiosqlite 0.20.0 (dev mode)
- Pydantic **2.10.4** + pydantic-settings 2.7.1
- Celery 5.4.0 + Redis 5.2.1 (broker `/1`, result `/2`)
- Temporal Python SDK — configured (`localhost:7233`, queue `dokufluss-tasks`), **no active workflows yet**
- JWT HS256 (python-jose 3.3.0) + bcrypt 4.2.1 (passlib 1.7.4); 30-min access, 7-day refresh
- OCR: ocrmypdf 16.7.2 + Tesseract (deu+eng); Gotenberg sidecar; ClamAV (optional)
- Storage: boto3 1.36.2 + aioboto3 13.3.3 (S3/MinIO); dev mode → local FS
- Search: Meilisearch client 0.31.6
- German tax: custom `sepa.py`, `xrechnung.py`, `elster.py`, `datev.py`, `einvoice_validator.py`
- AI providers (pluggable via `LLMProvider`): Mock, Claude (Anthropic), OpenAI, Gemini, Mistral, Ollama, OpenRouter
- Entry point: `backend/app/main.py` — lifespan init, middleware chain `Security → RateLimit → Audit → CORS`, `ORJSONResponse`

### Frontend (`frontend/`)
- React **18.3.1**, TypeScript **5.6.0** (strict: `noUnusedLocals`, `noUncheckedIndexedAccess`)
- Vite **6.0.0** (⚠ CLAUDE.md says Vite 5 — drift)
- Ant Design **5.22.0** + @ant-design/cssinjs 1.22.0
- Zustand **5.0.0** (+ persist middleware) — 7 slices, ~1677 LOC
- @tanstack/react-query **5.62.0** (staleTime 5 min, retry 1)
- axios 1.7.0 — single client `src/api/client.ts` (token interceptor + refresh queue + 5xx retry)
- framer-motion 11.12.0, lucide-react 0.460.0, react-router-dom 6.28.0, react-window 1.8.10
- Charts: @nivo/* 0.99.0, recharts 3.8.1, reactflow 11.11.0 (workflow designer)
- i18n: react-i18next 15.1.0 + i18next 24.1.0 + http-backend 3.0.0 + browser-languagedetector 8.0.0
- Testing: vitest 2.1.0 (jsdom), @playwright/test **1.58.2**
- Entry: `main.tsx` → `App.tsx` (QueryClientProvider → ThemeProvider → ErrorBoundary → Router)

### Infrastructure
- Docker Compose dev stack: `app`, `worker`, `scheduler`, `db` (postgres:17), `redis:7`, `search` (meili 1.11), `storage` (minio), `temporal` + UI + worker, `gotenberg`
- VPS deployment: `31.97.123.81:7777` (Ubuntu, docker cp via `deploy_to_vps.py`)
- Demo account: `admin@demo.de` / `Demo2026!` (verified 2026-04-17)

---

## Modules (business-domain grouping — ~17)

Backend route files: **88** (+ router aggregator). Frontend pages: **56** (54 protected + 2 public + 404).

| # | Domain | Backend routes | Frontend pages | Tables owned |
|---|--------|----------------|----------------|--------------|
| 1 | **Auth/Identity** | auth, sso, ldap, mfa, sessions, ip_whitelist, organizations | Login, Register, ForgotPassword, ResetPassword, AcceptInvitation | Organization, User, Group, Role, UserGroup, UserRole, Invitation |
| 2 | **Documents** | documents, cabinets, document_links, document_similarity, annotations, signatures, sharing, tags, duplicates, ocr_templates | Documents, DocumentDetail, Cabinets, Signatures, Favourites | Document, FileCabinet, DocumentMetadata, DocumentKeyword, DocumentSection, DocumentRelation, Annotation, Stamp, DocumentStamp, ShareLink, Tag, DocumentTag |
| 3 | **Search & AI** | search, ai, ai_copilot, ai_email, embeddings, saved_searches, smart_accounting | Search, AISettings | SavedSearch |
| 4 | **Invoicing** | invoices, recurring_invoices, invoice_templates, payment_reminders, abschlag, einvoice, peppol, serienbrief, sales, orders | Invoices, InvoiceCreator, Dunning, EInvoice, Serienbrief, SalesPipeline, Orders | Invoice, InvoiceLineItem, InvoiceNumberSequence, PaymentRecord, RecurringInvoiceTemplate |
| 5 | **Accounting** | accounting, kontierung, gdpdu, elster_eric, elster_submission, uid | Accounting, DATEVExport | AccountingEntry, SKRAccount, Kostenstelle, TaxPeriod |
| 6 | **Banking** | banking, fints, reconciliation | Banking | BankAccount, BankTransaction |
| 7 | **Cashbook/Expenses** | kassenbuch, expenses | Kassenbuch, Expenses | KassenbuchEntry |
| 8 | **Contacts/CRM** | contacts, communications, customer_portal | Contacts, CustomerPortal | Contact, Communication |
| 9 | **Contracts** | contracts, nachtraege, abnahme | Contracts, Nachtraege, Abnahmeprotokoll | (Contract), Nachtrag, Abnahmeprotokoll |
| 10 | **Projects & Construction** | projects, bautagebuch, aufmass, subcontractors, resources | Projects, Bautagebuch, Aufmass, Subcontractor, Resources | Subcontractor |
| 11 | **Tasks/PM** | tasks, wiedervorlage, workflows, forms, sla | Tasks, Wiedervorlage, Workflows, WorkflowDesigner, Forms, FormDesigner | Workflow, WorkflowInstance, WorkflowTask, Form, FormSubmission, SLAConfig, Wiedervorlage |
| 12 | **Time & HR** | timetracking, attendance, leave, payroll, badges | TimeTracking, Attendance, Leave, Payroll | Employee, Payslip |
| 13 | **Inventory/Assets** | inventory_api, assets | Inventory, AssetManagement | Asset, DepreciationEntry |
| 14 | **Compliance** | compliance, audit, audit_access, retention, gdpr, whistleblower_api, verfahrensdoku, qm, sop_templates | Compliance, QM, Whistleblower | AuditLog, RetentionPolicy, RetentionHold |
| 15 | **Notifications** | notifications, push, email_templates, email_capture | (embedded widgets) | EmailCaptureConfig, EmailImportLog |
| 16 | **Cashflow/KPI** | cashflow_prediction, anomalies, kpi, currency | Dashboard, Calendar | (analytics; no primary models) |
| 17 | **Admin/Settings** | admin, templates, health, marketplace? | Admin, Settings, Templates, Marketplace, Inbox | CustomDocumentType |

⚠ Orphans: `MarketplacePage.tsx` — no backend `/marketplace` endpoint (verify). `currency.py` — small, possibly mergeable.

---

## API endpoint counts (top 30)

| Endpoints | Module | Prefix |
|-----------|--------|--------|
| 31 | documents | /documents |
| 27 | admin | /admin |
| 22 | invoices | /invoices |
| 14 | contracts | /contracts |
| 14 | ai | /ai |
| 14 | accounting | /accounting |
| 12 | contacts | /contacts |
| 11 | workflows | /workflows |
| 11 | payroll | /payroll |
| 10 | subcontractors | /subcontractors |
| 10 | sales | /sales |
| 10 | orders | /orders |
| 10 | nachtraege | /nachtraege |
| 10 | forms | /forms |
| 10 | expenses | /expenses |
| 10 | auth | /auth |
| 9 | notifications, cabinets, banking | ... |
| 8 | tasks, retention, recurring_invoices, inventory, assets | ... |
| 7 | wiedervorlage, timetracking, payment_reminders, leave, fints, email_templates | ... |

**Total endpoints: ~850+** across 88 route files. 137 gated by `Depends(get_current_user)`, with `require_permission()`/`require_role()` on sensitive ops.

---

## Frontend routes (56 pages)

All lazy-loaded via `React.lazy`. All protected wrapped in `ProtectedRoute` → `OnboardingGate` → `AppLayout` → `AnimatedPage` → `ErrorBoundary`.

**Public (8):** `/login`, `/register`, `/forgot-password`, `/reset-password`, `/accept-invitation`, `/portal/:token`, `/f/:token`, `*` (404)

**Protected (48):** `/` (Dashboard), `/inbox`, `/documents`, `/documents/:id`, `/cabinets`, `/search`, `/tasks`, `/workflows`, `/workflows/:id/designer`, `/forms`, `/forms/:id/designer`, `/admin`, `/settings`, `/marketplace`, `/compliance`, `/datev-export`, `/e-invoice`, `/favourites`, `/bautagebuch`, `/qm`, `/dunning`, `/signatures`, `/ai-settings`, `/banking`, `/invoices`, `/invoices/new`, `/invoices/:id`, `/invoices/:id/edit`, `/accounting`, `/contacts`, `/contracts`, `/kassenbuch`, `/assets`, `/timetracking`, `/projects`, `/attendance`, `/aufmass`, `/nachtraege`, `/calendar`, `/sales-pipeline`, `/subcontractors`, `/abnahme`, `/payroll`, `/leave`, `/expenses`, `/whistleblower`, `/resources`, `/inventory`, `/orders`, `/templates`, `/wiedervorlage`, `/serienbrief`

---

## CRUD operations (summary)

Each business domain exposes standard CRUD. Details per-domain live in `modules/<domain>/02-functional.md` (Phase 3). High-level CRUD coverage:

| Domain | Create | Read (list+detail) | Update | Delete | Soft? |
|--------|:---:|:---:|:---:|:---:|:---:|
| Documents | ✓ | ✓ | ✓ versioning | ✓ soft | ✓ |
| Invoices | ✓ | ✓ | ✓ (draft only) | ✓ (status=cancelled) | ✓ |
| Contacts | ✓ | ✓ | ✓ | ✓ | ✓ |
| Contracts | ✓ | ✓ | ✓ | ✓ | ✓ |
| Projects | ✓ | ✓ | ✓ | ✓ | ? |
| Tasks | ✓ | ✓ | ✓ | ✓ | — |
| Workflows | ✓ | ✓ | ✓ | ✓ | ✓ |
| Forms | ✓ | ✓ | ✓ | ✓ | ✓ |
| Banking (account) | ✓ | ✓ | — | ✓ | ✓ |
| Banking (txn) | ✓ (import) | ✓ | (match only) | (none) | — |
| Accounting entries | ✓ | ✓ | ✓ | ✓ | ✓ |
| Time tracking | ✓ | ✓ | ✓ | ✓ | — |
| Payroll | ✓ | ✓ | ✓ | — | ✓ |
| Assets | ✓ | ✓ | ✓ | — | ✓ |
| Inventory | ✓ | ✓ | ✓ | ✓ | — |

Full CRUD tables per-module in Phase 3 reports.

---

## External integrations

| Integration | Files | Purpose | Config env vars |
|-------------|-------|---------|-----------------|
| **IMAP Email Capture** | `email_capture.py`, `archive_email_service.py` | Auto-import invoices from mailbox | per-config `imap_host/port/user/pass` |
| **SMTP** | `notifications.py`, `email_templates.py` | Transactional email | `SMTP_HOST/PORT/USER/PASSWORD` |
| **Tesseract OCR** | `vision_ocr_service.py`, `ocrmypdf` wrapper | PDF text extraction (de+en) | container sidecar |
| **Gotenberg** | PDF/HTML conversion | invoice & template PDF render | `GOTENBERG_URL` |
| **ClamAV** | `antivirus_service.py` | Upload scan | `CLAMAV_HOST/PORT` |
| **DocuSeal** | signatures module | E-signature collection | `DOCUSEAL_URL`, `DOCUSEAL_API_KEY` |
| **FinTS** | `fints_service.py` | Bank account sync | credentials encrypted per-config |
| **SEPA** | `integrations/sepa.py` | pain.001.003.03 + MT940 | — |
| **XRechnung / ZUGFeRD** | `integrations/xrechnung.py`, `einvoice.py`, `einvoice-validator` sidecar | EN 16931 e-invoice | `EINVOICE_VALIDATOR_URL` |
| **Peppol** | `peppol_service.py` | PEPPOL network submission | `PEPPOL_*` |
| **ELSTER** | `integrations/elster.py`, `elster_eric.py`, `elster_submission.py` | UStVA + ZM XML for ERiC | — (XML export only) |
| **DATEV** | `integrations/datev.py`, `datev_bds_service.py`, `datev_rds_service.py` | BDS/RDS export | — |
| **GDPdU** | `gdpdu.py` | Tax audit export | — |
| **MinIO/S3** | `storage_service.py` | Document files | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_DOCUMENTS` |
| **Meilisearch** | `search_service.py`, `embedding_service.py` | Full-text + semantic | `MEILISEARCH_URL`, `MEILISEARCH_API_KEY` |
| **Celery/Redis** | `workers/celery_app.py` | ocr / email / export / default queues | `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` |
| **Temporal** | `temporal_worker` (sidecar) | Reserved for future durable workflows | `TEMPORAL_HOST/NAMESPACE/TASK_QUEUE` — currently unused |
| **AI Providers** | `ai_service.py`, `ai_orchestrator.py` | Classification, RAG, copilot | `AI_PROVIDER/MODEL/API_KEY` + provider-specific (`CLAUDE_API_KEY`, `OPENAI_API_KEY`, …) |
| **LDAP/AD** | `ldap.py` | User directory sync | `LDAP_*` |
| **SSO (SAML/OIDC)** | `sso.py` | External IdP (placeholder) | `SSO_*` |

---

## Component stats (frontend)

- **164 components** across 25 categories
- **77 custom hooks** (likely over-fragmented — e.g. 3 AI-related hooks: `useAI`, `useAICopilot`, `useAIEmail`)
- 7 Zustand stores: authStore (332 LOC), moduleStore (599), aiStore (348), notificationStore (158), timerStore (145), toastStore (51), favouritesStore (44)
- 1 React Context: `ThemeContext` (light/dark/system)
- Total src LOC: **23 415**

### Largest files (candidates for split — tracked in Phase 3/5 findings)
| LOC | File |
|-----|------|
| 2702 | `pages/DashboardPage.tsx` |
| 2647 | `pages/SettingsPage.tsx` |
| 2117 | `pages/AdminPage.tsx` |
| 2055 | `pages/EInvoicePage.tsx` |
| 2053 | `pages/ContactsPage.tsx` |
| 1876 | `components/ai/AIChatSidebar.tsx` |
| 1727 | `components/documents/UploadModal.tsx` |
| 1665 | `components/layout/AppLayout.tsx` |
| 1290 | `components/ai/BusinessCopilot.tsx` |
| 1123 | `components/inbox/InboxProcessingPanel.tsx` |

---

## i18n coverage

10 languages in `frontend/public/locales/<lang>/translation.json`:

| Lang | Keys | vs DE |
|------|-----:|------:|
| de | 5892 | baseline |
| en | 5892 | 0 |
| tr | 5807 | −85 |
| ar | 5754 | −138 |
| ru | 5753 | −139 |
| pl | 5753 | −139 |
| ro | 5753 | −139 |
| hr | 5753 | −139 |
| it | 5753 | −139 |
| fr | 5753 | −139 |

⚠ 7 languages missing **~139 keys** (likely newest AI/compliance/FinTS features untranslated).

---

## Testing

### Backend
- pytest 8.3.4 + pytest-asyncio 0.25.0 + pytest-cov 6.0.0
- Tests in `backend/tests/` — **not walked yet** (see Phase 3)

### Frontend
- Vitest unit tests: ~10 files (authStore, favouritesStore, toastStore, useCabinets, useDocuments, EmptyState, FavouriteButton, FileIcon, StatusBadge, app.test.tsx)
- **Playwright e2e: 47 test files + 4 helpers** (17 smoke + 30 deep, covering auth, dashboard, documents, cabinets, invoices, compliance, spotlight, dark mode, responsive, i18n, designers, scenarios, visual QA)

---

## Unknowns

- `app/api/v1/_register_new_routes.py` — dynamic router registration; purpose to be confirmed in Phase 3.
- `app/compliance/` directory internals — not yet walked.
- `app/middleware/` (security, rate_limit, audit) — exist but detail TBD.
- `app/schemas/` (40+ Pydantic files) — not exhaustively inventoried; implicit from endpoints.
- Vector DB backend for `embedding_service` — unknown (Weaviate/Qdrant/Pinecone/none?).
- Push notification channel (WS / FCM / polling) — unknown.
- `MarketplacePage.tsx` backend — none found.
- Serienbrief model lives in `models/nachtrag.py` — architectural smell, flagged for Phase 4.
- Temporal sidecar active but no workflows defined — dead compose service?
