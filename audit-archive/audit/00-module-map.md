# 00 — Module Dependency Map

> Cross-module links: imports, foreign keys, API calls. Phase 1 output.

## Legend

- **import** — Python `from app.services.X` / TypeScript `import from 'api/X'`
- **fk** — DB foreign key across domain boundary
- **api** — runtime call to another module's HTTP endpoint

---

## Cross-domain edges

| Source | → Target | Type | Reference |
|--------|---|:---:|-----------|
| Invoicing | Accounting | import | `AccountingEntry` referenced when booking invoice |
| Invoicing | Contacts | fk | `Invoice.contact_id → contacts.id` |
| Invoicing | Banking | api | Payment matching uses `BankTransaction.matched_invoice_id` |
| Invoicing | Documents | fk | `AccountingEntry.document_id` (optional attach) |
| Invoicing | Search & AI | api | `smart_accounting_service` AI kontierung suggestions |
| Invoicing | Notifications | api | `PaymentReminderService` dispatches via notifications |
| Invoicing | Communications | fk | `CommunicationEntry.invoice_id` |
| Contracts | Invoicing | fk | `Nachtrag.original_invoice_id`, `Nachtrag.resulting_invoice_id` |
| Contracts | Contacts | api | Change orders tied to project/contact |
| Projects | Invoicing | api | Project costs posted as invoice lines |
| Projects | Contacts | fk | `Subcontractor.contact_id` |
| Documents | Search & AI | import | `embedding_service.embed_document()`; `search_service.index()` |
| Documents | Compliance | fk | `FileCabinet.retention_policy_id → retention_policies.id` |
| Tasks/PM | Documents | fk | `WorkflowInstance.document_id` |
| Tasks/PM | Contacts | fk | `SLAConfig` → workflow can reference contact |
| Time & HR | Contacts | api | `Employee` enriches user directory |
| Banking | Invoicing | api | Reconciliation of `BankTransaction.reference` → `Invoice.invoice_number` |
| Contacts | Communications | fk | `CommunicationEntry.contact_id` |
| Cashflow/KPI | Invoicing | api | Aggregates invoice stats for dashboard |
| Cashflow/KPI | Banking | api | Aggregates cash flow |
| Search & AI | Documents | import | `document_intelligence_service` reads OCR text |
| Auth/Identity | **ALL** | fk | `AuditLog.user_id`; all models carry `org_id` + `AuditMixin` |

---

## Shared infrastructure (cross-cutting)

| Infrastructure | Consumers | Owner |
|---------------|-----------|-------|
| **AuditService / AuditLog** | Every write in every domain (30+ services) | Compliance |
| **RBAC (permissions/roles)** | All protected endpoints via `require_permission()` | Auth/Identity |
| **Notifications (push/email/in-app)** | Invoicing, Tasks, Documents, Compliance, Contacts | Notifications |
| **Celery queue** | Documents (OCR), Invoicing (PDF render, Mahnwesen dispatch), Search (indexing), Notifications (SMTP) | Workers |
| **Meilisearch index** | Documents, Invoicing, Contacts, Saved Search | Search & AI |
| **Storage (S3/MinIO)** | Documents (primary), Invoicing (PDFs), Compliance (exports), Payroll (payslips), Banking (MT940 imports) | Documents |
| **Document Intelligence (OCR+AI)** | Documents (classify), Invoicing (field extract), Contracts (parse), Banking (parse MT940/CAMT) | Search & AI |
| **`org_id` multi-tenancy** | Every model | Auth/Identity |

---

## High-fanout (imports > 5)

- `AuditService` — imported by ~30 services (expected)
- `NotificationService` — imported by ~12 services
- `StorageService` — imported by ~10 services
- `PermissionChecker` — imported by ~20 routes
- `MeilisearchClient` — imported by ~6 services

---

## Architectural observations

1. **Invoicing is the hub.** 5 outbound edges (Accounting, Contacts, Banking, Docs, AI, Notifications). Changes here ripple widely.
2. **Documents + Search/AI are foundational.** Most domains enrich documents via OCR/classification.
3. **German-specific coupling.** Nachtrag ↔ Invoice, Abschlag ↔ Invoice, Bautagebuch ↔ Project — tight by business requirement, not accidental.
4. **Audit + Auth are universal cross-cuts.** Every write is logged, every table has `org_id`.

---

## Orphans / smells

| Finding | Where | Severity (provisional) |
|---------|-------|------------------------|
| `MarketplacePage.tsx` — no backend counterpart | `frontend/src/pages/` | medium |
| `Serienbrief` + `PushSubscription` models live in `models/nachtrag.py` | `backend/app/models/nachtrag.py` | low (smell) |
| Temporal sidecar runs but no workflows defined | `docker-compose.yml` + `workers/` | medium (dead infra) |
| `components/stamps/` directory empty | `frontend/src/components/stamps/` | low |
| `merge_service.py`, `datev_bds_service.py`, `datev_rds_service.py` — no direct routes | `backend/app/services/` | low (internal utilities) |
| 3 AI hooks (`useAI`, `useAICopilot`, `useAIEmail`) likely over-fragmented | `frontend/src/hooks/` | low |
| 7 i18n languages missing ~139 recent keys | `frontend/public/locales/*/translation.json` | high (user-visible gap) |

---

## What this map does NOT yet cover (tracked for Phase 4)

- Cascade behaviors (`ON DELETE CASCADE` vs block) per FK
- Transactional boundaries across domains (does invoice-booking roll back on accounting failure?)
- Currency/rounding consistency across Invoicing / Banking / Accounting / Cashbook
- Report aggregation parity (Dashboard totals vs detail sums)
- Dead API endpoints (no frontend consumer)
