# Modules - Guide and Catalog

How to build, install, and publish modules for OpenConstructionERP, plus a
map of every module that ships in the box.

OpenConstructionERP is modular by design: every business feature (BOQ, BIM,
takeoff, schedule, CDE, regional BOQ packs and more) is a self-contained
module that can be enabled, disabled, installed, or replaced without touching
the core. The current build loads 194 modules. You enable only the parts you
need.

This file is the single entry point. Deeper material lives alongside the code
it describes, and the links point there.

---

## 1. The module catalog

All 194 modules that load in the current build, grouped by what they do for a
construction team. The bold name is the module's display name; the code label
is its backend folder under `backend/app/modules/`. The count is every directory
under `backend/app/modules/` carrying a `manifest.py`, which is exactly what the
loader discovers; a directory without one is a shared library, not a module, and
does not load. Recount it that way rather than trusting this line.

Jump to a group:
[Estimating and BOQ](#estimating-and-boq) -
[Cost and resource data](#cost-and-resource-data) -
[Quantity takeoff and drawings](#quantity-takeoff-and-drawings) -
[BIM, CAD and coordination](#bim-cad-and-coordination) -
[Tendering and procurement](#tendering-and-procurement) -
[Planning and schedule](#planning-and-schedule) -
[Cost control, EVM and risk](#cost-control-evm-and-risk) -
[Change, variations and claims](#change-variations-and-claims) -
[Field and site](#field-and-site) -
[Quality, safety and compliance](#quality-safety-and-compliance) -
[Documents and CDE](#documents-and-cde) -
[Collaboration and communication](#collaboration-and-communication) -
[Reporting, dashboards and intelligence](#reporting-dashboards-and-intelligence) -
[AI and search](#ai-and-search) -
[Sustainability, assets and operations](#sustainability-assets-and-operations) -
[CRM and client engagement](#crm-and-client-engagement) -
[Regional packs](#regional-packs) -
[Platform, admin and framework](#platform-admin-and-framework)

Note: each manifest also carries a `category` tag (core, business, extension,
enterprise, integration, regional, infra, controls). That tag is a packaging
label used by the loader. The groups below are by function, so a module's
group here will not always equal its manifest `category`.

### Estimating and BOQ

Build and price the bill of quantities.

- **Bill of Quantities** `boq` - core hierarchical BOQ editor with positions, quantities and cost roll-up.
- **Assemblies & Calculations** `assemblies` - composite rates built from cost-database items with factors and regional adjustment.
- **Estimating Methodologies** `methodology` - per-country BOQ hierarchies, analytical dimensions and cascading markups.
- **Conceptual Estimate** `rom_estimate` - order-of-magnitude cost from building type, floor area, quality and region.
- **AI Estimate Builder** `ai_estimator` - drafts a full priced estimate from your data for a person to confirm.
- **AI Estimation** `ai` - cost suggestions from a text description or a photo.
- **Basis of Estimate** `estimate_basis` - auto-drafts the inclusions, exclusions and assumptions behind an estimate.
- **Estimate Rollup** `estimate_rollup` - one headline number from the BOQ base, preliminaries and allowances.
- **Allowances & Contingency** `allowances` - register of provisional sums, prime-cost sums and contingencies with drawdown.
- **Preliminaries** `preliminaries` - prices general conditions as time-related and fixed one-off items.
- **Formwork** `formwork` - formwork catalogue and per-BOQ assignments with reuse-aware unit cost.
- **Waste Factors** `waste_factors` - net-to-gross quantity adjustment with waste, lap and coverage factors.
- **Production-Norm Expansion** `norm_expansion` - expands a work item into labour, plant and material demand from norm coefficients.
- **Labor & Crew Rates** `labor_rates` - all-in labour rate build-up and composite crew rates.
- **Resource Summary** `resource_summary` - rolls resource splits across the estimate into a procurement-ready statement.
- **Design Options** `design_options` - compare alternative designs side by side, each with its own priced BOQ.
- **Post-calculation** `postcalc` - reconciles the estimate against site actuals into productivity factors that feed the next estimate.

### Cost and resource data

Rate databases, catalogs, matching and currency.

- **Cost Database** `costs` - cost items and rate databases (CWICR and regional catalogues) with bulk import.
- **Product & Resource Catalog** `catalog` - materials, plant, labour and operators drawn from the cost databases.
- **Cost Explorer** `cost_explorer` - search-first workspace to find priced work and compare scope across regional bases.
- **Cost Match** `cost_match` - matches material layers to cost items, exact first then semantic.
- **Element Match** `match` - returns ranked cost-position candidates for a BIM, PDF, DWG or photo element.
- **CAD-BIM Match to Cost** `match_elements` - maps model and drawing elements to cost positions and loads scaled resources into the BOQ.
- **Currency / FX** `fx` - live exchange rates and optional purchasing-power conversion for multi-currency work.
- **Price Index Adjustment** `price_index` - moves costs between base and target period and region using index series.
- **Supplier Catalogs & Vendor Management** `supplier_catalogs` - vendor master, price lists, POs, goods receipts and stock control.

### Quantity takeoff and drawings

Measure quantities off drawings and models.

- **Quantity Takeoff** `takeoff` - manual and assisted quantity takeoff from drawings and models.
- **DWG Takeoff** `dwg_takeoff` - 2D DWG/DXF viewer with measurements, annotations and BOQ linking.
- **Markups & Annotations** `markups` - drawing markups, scale calibration and stamp templates.
- **Rebar Schedule** `rebar_schedule` - reinforcement bending schedules in the ABS interchange format, validated against the format rules and summarised by bar diameter.

### BIM, CAD and coordination

Convert, view, coordinate and clash-check models. CAD and BIM are always
converted through DDC cad2data to the canonical format, never IfcOpenShell.

- **CAD Import** `cad` - imports and converts DWG, DGN, RVT and IFC through the canonical pipeline.
- **BIM Hub** `bim_hub` - model and element store with BOQ linking, quantity maps and model diffs.
- **BIM Requirements** `bim_requirements` - import and export of BIM requirement formats (IDS, COBie, Excel/CSV).
- **Clash Detection** `clash` - geometric interference and clearance checks with a discipline matrix and BCF export.
- **Clash AI Triage** `clash_ai_triage` - assisted clash triage with confidence scores and a tunable prompt, saved for audit.
- **Clash Cost Impact** `clash_cost_impact` - estimates rework cost per clash and rolls up open impact for the project.
- **Coordination Hub** `coordination_hub` - read-only rollup of federations, clashes, views and BCF activity with cost impact.
- **Smart Views** `smart_views` - rule-based BIM viewer presets that re-evaluate against element properties at load time.
- **BCF Issues & Viewpoints** `bcf` - server-backed BCF 2.1 and 3.0 topics, comments and viewpoints with .bcfzip roundtrip.
- **OpenCDE API** `opencde_api` - OpenCDE Foundation and BCF API compliance layer.
- **Geo Hub** `geo_hub` - geospatial anchors, a 3D Tiles pipeline, imagery and terrain, plus GeoJSON and KML I/O.
- **Point Cloud / Reality Capture** `pointcloud` - ingests laser-scan and photogrammetry exports into confirmed quantities and progress.
- **BIM-LV Container** `bimlv` - reads and writes DIN SPEC 91350 containers linking a GAEB bill of quantities to model elements.

### Tendering and procurement

Package work, invite bids and buy it.

- **Tendering** `tendering` - bid package management, distribution, collection and comparison.
- **Bid Management** `bid_management` - bid packages, invitations, Q&A, submissions, levelling and award.
- **RFQ & Bidding** `rfq_bidding` - request-for-quotation with bid submission, evaluation and award.
- **Procurement** `procurement` - purchase orders, goods receipts and vendor management.
- **Subcontractor Management** `subcontractors` - prequalification, agreements, payment applications, retention and rating.
- **Contract Types Engine** `contracts` - lump-sum, GMP, cost-plus, T&M, unit-price and design-build with claims and retention.

### Planning and schedule

Plan the programme and track how it runs.

- **4D Schedule** `schedule` - links BOQ positions to a construction timeline.
- **Schedule Advanced (Last Planner)** `schedule_advanced` - phase plans, look-ahead, constraints, weekly plans and PPC tracking.
- **Resource Planning** `resources` - people, crews, plant and subs with skills, availability and conflict detection.
- **Progress Tracking** `progress` - percent-complete per BOQ position, period deltas, S-curves and geo-tagged field entries.
- **Tasks** `tasks` - tasks, topics, decisions and personal items with checklists and assignment.
- **Portfolio** `portfolio` - programme tree of projects with cross-schedule links and CPM scheduling across a subtree.

### Cost control, EVM and risk

Keep the commercial picture honest.

- **Finance** `finance` - invoicing, payments, budgets and earned value.
- **Full EVM** `full_evm` - earned value with forecasting, S-curves and TCPI analysis.
- **5D Cost Model** `costmodel` - S-curves, cash flow projection, earned value and budget tracking.
- **Cost-Value Reconciliation & Cashflow** `cvr` - monthly reconciliation of cost against value earned with a cashflow forecast.
- **Project Controls** `project_controls` - executive read-only dashboard of cost, schedule, quality, safety, risk and change.
- **Value Realized** `value` - a single project view of value from change exposure, cost recovery and time saved.
- **Risk Register** `risk` - track risks, score probability and impact, manage mitigation.

### Change, variations and claims

Manage change and defend the record.

- **Change Orders** `changeorders` - scope changes, cost impact and approval workflow.
- **Variations & Site Measurements** `variations` - notice to variation order, site measurement, daywork and claim lifecycle.
- **Management of Change** `moc` - propose, review, approve and implement engineering or scope changes with an audit trail.
- **Change Intelligence** `change_intelligence` - analytical view across the change family showing what waits on whom.
- **Claims Evidence** `claims_evidence` - assembles an ordered, content-addressable evidence pack for a claim or dispute.
- **Event Reconciliation** `reconciliation` - stitches one real event back together across modules and channels.
- **Cost Recovery** `cost_recovery` - records back-charges and rolls them up per responsible party.

### Field and site

Capture what happens on site.

- **Daily Site Diary** `daily_diary` - weather, entries, photos, video and reality capture in a signed archive.
- **Field Diary** `field_diary` - lightweight field-worker diary with PIN-gated magic-link access.
- **Field Time** `field_time` - cost-coded, signed timesheets for labour and plant.
- **Field Reports** `fieldreports` - daily site reports covering weather, workforce, delays and safety.
- **Payroll** `payroll` - drafts payroll batches from field labour hours.
- **Forms & Checklists** `forms` - template builder and library for the forms site teams fill in every day.
- **Voice Capture** `voice` - turns a spoken or typed site note into a structured draft the worker confirms.
- **Phone Log** `phonelog` - captures calls and verbal instructions as dispute-ready records.
- **Site Logistics & Delivery** `site_logistics` - access gates, laydown zones and a delivery booking board.
- **Equipment & Fleet Management** `equipment` - owned and rented plant with telemetry, maintenance and internal rental billing.
- **Site Mobilisation Readiness** `site_prep` - tracks pre-construction mobilisation items by category and derives the commencement gate status.
- **Site Inventory** `site_inventory` - records material movements on site and derives stock on hand, waste ratio and cost variance.
- **Site Supervision** `site_supervision` - plans and records design-team supervision visits, raising observations and feeding instructions into the change route.

### Quality, safety and compliance

Prove the work meets the standard.

- **Quality Inspections** `inspections` - inspection management with checklists and pass/fail workflows.
- **Non-Conformance Reports** `ncr` - material, workmanship and design non-conformances with root cause and corrective action.
- **Punch List** `punchlist` - deficiencies and snags with photo evidence and verification.
- **Quality Management System (QMS)** `qms` - unified ITP, inspections, NCR, punch list and audits with quality-cost analytics.
- **Construction Control** `construction_control` - QA/QC engine: acceptance criteria, inspections, material passports and as-built records.
- **Safety Management** `safety` - incident and observation tracking with risk scoring and corrective actions.
- **HSE Advanced** `hse_advanced` - job hazard analysis, permits, toolbox talks, PPE, audits and safety KPIs.
- **Commissioning (Cx)** `commissioning` - prefunctional and functional checklists, an issue log and readiness scoring.
- **Compliance DSL** `compliance` - author validation rules as YAML or JSON without writing Python.
- **Compliance AI** `compliance_ai` - a natural-language rule builder that compiles into the validation engine.
- **Compliance Documents** `compliance_docs` - track expiring insurance, permits, bonds and certifications.
- **Certified Payroll** `certified_payroll` - weekly certified payroll for public works: wage determination, trade classification, hours by day and the signed statement of compliance.
- **Requirements & Quality Gates** `requirements` - extract, validate and track construction requirements.
- **Temporary Works Register** `temporary_works` - governs the safety-critical lifecycle of temporary works from design check through permit to load and strike.
- **Credentials Registry** `credentials` - tracks professional licences and certifications with validity windows and reports who may not work today.
- **Review Authority** `review_authority` - runs the external review cycle with an approving authority, from submission through remarks to decision.
- **Work-type Route Classifier** `project_route` - classifies a project's work type into a delivery and permit route that gates the project once confirmed.

### Documents and CDE

The document backbone and file manager.

- **Document Management** `documents` - upload, categorise and manage project documents with tagging and search.
- **Common Data Environment (ISO 19650)** `cde` - ISO 19650 containers, revisions, state transitions and suitability codes.
- **Transmittals** `transmittals` - formal document transmittals with recipients, acknowledgements and responses.
- **Correspondence** `correspondence` - letters, emails and notices with direction, contacts and cross-references.
- **Document Connectors** `connectors` - pull files from watched folders in as first-class, deduplicated project documents.
- **Inbound Email** `inbound_email` - imports exported .eml messages into the project record.
- **Inbound Capture Gateway** `inbound_capture` - normalises forwarded email, chat and SMS into one message shape.
- **File Versioning** `file_versions` - version chains across all file kinds with restore-any-version.
- **File Approvals** `file_approvals` - multi-step file approval with stamp burning on final sign-off.
- **File Comments** `file_comments` - threaded comments and PDF markup pins across file kinds.
- **File Distribution** `file_distribution` - cross-project search and reusable distribution lists.
- **File Favourites** `file_favorites` - per-user star and pin for the file manager.
- **File References** `file_references` - ISO 19650 filename validation and cross-entity links.
- **File Saved Views** `file_saved_views` - saved smart-folder filters for the file manager.
- **File Search** `file_search` - OCR-backed full-text search across documents and drawings.
- **File Tags** `file_tags` - project-scoped tags for every file kind with discipline and phase defaults.
- **File Transmittals** `file_transmittals` - send-records with an auto-numbered cover sheet.
- **Recycle Bin** `file_trash` - soft-delete and restore across the file manager kinds.
- **Plan Room** `plan_room` - composites defect pins, markups, measurements and photos as read-only overlays on a document page.
- **E-Signature Registry** `signing` - models who must sign a document and records attestations, hash staleness and certificate expiry.
- **Record Publishing** `record_publishing` - publishes a project record as one signed PDF and distributes it to recipients who acknowledge receipt.
- **Source Data Register** `source_data` - registers prerequisite source documents with validity windows, renewal reminders and a schedule-blocking flag.
- **Authority Submission Factory** `authority_submission` - generates structured authority submissions from jurisdiction profiles for tenders, expertise packages and handover registers.

### Collaboration and communication

Talk, ask and decide around the work.

- **Comments & Viewpoints** `collaboration` - threaded comments with mentions and viewpoints on any entity.
- **Real-time collaboration locks** `collaboration_locks` - soft locks and presence so two people do not overwrite the same row.
- **Meetings** `meetings` - agendas, attendees, action items and status.
- **Requests for Information** `rfi` - RFI questions, responses and cost or schedule impact.
- **Register Workflow** `register_workflow` - RFI / RFQ / order / variation registers with per-job references, server-enforced gates and routes, and side-by-side quote compare with an award gate.
- **Comms Intelligence** `comms_intelligence` - classifies correspondence on the register, extracts prices, quote numbers and deadlines, and drafts replies; a person confirms every suggestion.
- **Outlook Bridge** `outlook_bridge` - opens any register email as a signed Outlook draft or an editable .eml; sending stays human and no mailbox is read.
- **Team Standup & Delivery Board** `team_standup` - the project team's daily entries (activities, blockers, attachments) and a stage-driven task board whose rails live server-side.
- **Submittals** `submittals` - shop drawings, product data and samples with review and approval.
- **Notifications** `notifications` - in-app notifications with per-user preferences.
- **Contacts Directory** `contacts` - unified directory of clients, subcontractors, suppliers and consultants.
- **Interface Register** `interface_management` - coordinates handshakes between work packages, contractors and disciplines with owners, status and closing actions.
- **Deadlines** `deadlines` - sweeps overdue items across modules, notifying owners and escalating to managers on repeat.

### Reporting, dashboards and intelligence

See where the project stands.

- **Reporting & Dashboards** `reporting` - KPI snapshots, report templates and generated project reports.
- **Dashboards** `dashboards` - analytical cards over Parquet snapshots with filters and 3D viewer sync.
- **Dashboard Rollup** `dashboard` - single aggregation endpoint feeding the project dashboard widgets.
- **BI Dashboards & Reporting** `bi_dashboards` - role-based dashboards, a KPI library and a custom report builder.
- **Project Intelligence** `project_intelligence` - project completion analysis, scoring and guided recommendations.
- **Project Timeline** `timeline` - a filterable, newest-first feed of significant project events.

### AI and search

Find things and let assistants help.

- **AI Agents** `ai_agents` - a reason-act agent loop with a tool registry and per-run history.
- **Semantic Search** `search` - cross-collection vector search fused across BOQ, documents, tasks and more.
- **Find Records** `retrieval` - claim-grade retrieval across documents, correspondence and change records with provenance.
- **ERP Chat** `erp_chat` - chat over ERP data with tool-calling.

### Sustainability, assets and operations

Carbon, ESG and the building after handover.

- **Carbon & Sustainability** `carbon` - embodied and operational carbon, an EPD database and sustainability reporting.
- **ESG Site Performance** `esg` - site energy, water, waste, local labour and safety tracked against targets.
- **Asset Operations** `assets` - an operational-phase asset register with warranty, maintenance and lifecycle health.
- **Service & Maintenance** `service` - service contracts, tickets, work orders and SLA tracking.
- **Handover & Closeout** `closeout` - digital handover package assembly with a checklist and evidence binding.
- **Property Development** `property_dev` - developments, plots, house types, buyer selections and handover.
- **Accommodation** `accommodation` - worker camps, rental apartments and hotels with rooms, bookings and charges.
- **Off-site / Prefab / DfMA** `prefab` - tracks manufactured units through the production lifecycle to installation.
- **Defects Liability Register** `defects_liability` - tracks post-handover warranties and defect notices per subcontractor and flags entries clear for retention release.

### CRM and client engagement

Win work and keep clients close.

- **CRM Sales Pipeline** `crm` - accounts, leads, opportunities, activities and win/loss analytics.
- **Webhook Leads** `webhook_leads` - secure inbound webhooks that create CRM leads from external sources.
- **Client & Partner Portal** `portal` - an external portal for clients, investors, consultants and suppliers with magic-link access.

### Regional packs

Country and region standards, forms and tax rules. Enable the pack for where
you work.

- **Regional Pack - DACH (DE/AT/CH)** `dach_pack` - GAEB exchange formats, VOB terms, DIN 276 cost groups and HOAI fees.
- **Regional Pack - United Kingdom** `uk_pack` - JCT and NEC4 forms, NRM2 measurement, CIS tax and interim valuations.
- **Regional Pack - United States** `us_pack` - AIA G702 applications, MasterFormat divisions, imperial units and USD.
- **Regional Pack - California** `us_ca_pack` - district sales tax stack, state prevailing wage, retention caps and the statutory payment and lien clocks, on top of the US pack.
- **Regional Pack - Texas** `us_tx_pack` - lump sum against separated contract sales tax, local prevailing wage, public works retainage caps and the statutory payment and lien clocks, on top of the US pack.
- **Regional Pack - India** `india_pack` - IS codes, CPWD and MES rate references, multi-rate GST and INR.
- **Regional Pack - Latin America** `latam_pack` - SINAPI (Brazil), NTDIF (Mexico) and regional currencies.
- **Regional Pack - Mexico** `mexico_pack` - APU unit-price analysis under LOPSRM public-works rules with IVA.
- **Regional Pack - Middle East & GCC** `middle_east_pack` - FIDIC forms, Islamic calendar, GCC VAT and bilingual PDFs.
- **Regional Pack - Asia-Pacific** `asia_pac_pack` - AU, NZ, Japan and Singapore standards with regional currencies.
- **Regional Pack - China** `china_pack` - GB 50500 bill of quantities valuation, the GB 50854-50862 measurement family, national and provincial quotas, VAT and CNY.
- **Regional Pack - South Africa** `sa_pack` - SANS 1200 and ASAQS measurement, CIDB grading and preferential procurement.
- **Regional Pack - Russia & CIS** `russia_pack` - GESN, FER and TER cost databases, VAT rates and local contract templates.
- **Payment Clock** `payment_clock` - computes statutory payment notice dates and reports the legal consequence when a deadline passes unanswered.
- **Withholding Tax** `tax_withholding` - computes statutory construction withholding deductions and reverse-charge VAT determinations on payments and invoices.
- **E-invoice clearance** `einvoice_clearance` - registers and tracks the government clearance state of electronic invoices on national authority platforms.

### Platform, admin and framework

The plumbing every other module builds on.

- **Projects** `projects` - project management with regional settings, classification standards and validation configuration.
- **Users & Authentication** `users` - user management, JWT authentication, API keys and role-based access control.
- **Team Visibility** `teams` - team-based entity visibility and access control within projects.
- **Validation Engine** `validation` - data-quality validation with configurable rule sets (DIN 276, GAEB, NRM, MasterFormat, BOQ quality).
- **EAC v2 Engine** `eac` - a single-kernel rules engine for takeoff, validation and clash outputs over canonical Parquet.
- **Approval Routes** `approval_routes` - a generic multi-step approval engine with ordered approvers and per-step decisions.
- **Enterprise Workflows** `enterprise_workflows` - configurable approval workflows for invoices, POs, variations and BOQs.
- **Pipeline Builder** `pipelines` - visual node-graph automation over the job runner, validation engine and module services.
- **Background Jobs** `jobs` - status, listing and cancellation for the platform job runner.
- **Saved Views** `saved_views` - save a filter against any entity and reuse it as a list, count, tile or export.
- **Internationalization Foundation** `i18n_foundation` - exchange rates, a country registry, work calendars and tax configuration.
- **Integrations** `integrations` - chat connectors, outgoing webhooks, email and calendar feeds.
- **Backup & Restore** `backup` - export and import user data backups.
- **Direct Uploads** `uploads` - a signed direct upload endpoint for the storage backend.
- **Resumable Uploads** `resumable_uploads` - chunked, resumable uploads for large CAD and PDF files.
- **Client Error Sink** `client_errors` - receives anonymised frontend error reports into the logging pipeline.
- **Admin** `admin` - gated operator endpoints for QA pipelines and fixtures.
- **Architecture Map** `architecture_map` - an interactive visual map of the system architecture.
- **Module Builder** `module_builder` - describes a module in a few steps and has the platform build and install it after review.
- **Onboarding** `onboarding` - runs first-run provisioning such as cost-base import and sample project install in the background.
- **Cases** `cases` - lets a team author, start and pin its own walkthroughs of how work is done on a project.

---

## 2. What is a module?

A module is a self-contained unit that may contribute any of:

| Surface       | Where it lives                                  | Registered by            |
|---------------|-------------------------------------------------|--------------------------|
| REST routes   | `backend/app/modules/<name>/router.py`          | `manifest.py`            |
| DB models     | `backend/app/modules/<name>/models.py`          | auto-discovered          |
| Business code | `backend/app/modules/<name>/service.py`         | imported from router     |
| UI pages      | `frontend/src/modules/<name>/manifest.ts`       | `_registry.ts`           |
| i18n strings  | `manifest.ts` + `i18n-fallbacks.ts`             | runtime i18next          |
| Validation    | `backend/app/modules/<name>/validators.py`      | central validation engine |

A module that only adds UI (for example a regional BOQ exchange) can live purely
in `frontend/src/modules/`. A module that only adds API logic (for example a new
connector) can live purely in `backend/app/modules/`. Most full-stack features
have both.

---

## 3. Backend module, 5-minute walkthrough

**Start from the template**:

```bash
cp -r modules/oe-module-template backend/app/modules/my_module
```

Then edit `backend/app/modules/my_module/manifest.py`:

```python
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_my_module",        # unique, snake_case, oe_ prefix
    version="0.1.0",
    display_name="My Module",
    description="One-line description",
    author="Your Name",
    category="business",         # e.g. core, business, extension, integration, regional, enterprise
    depends=["oe_projects"],     # other modules this needs
    auto_install=False,          # False = user enables it from /modules
    enabled=True,
)
```

**Minimum viable file set**:

```
backend/app/modules/my_module/
├── __init__.py
├── manifest.py          # REQUIRED, metadata
├── router.py            # FastAPI router, auto-mounted at /api/v1/my_module/*
├── models.py            # SQLAlchemy models (optional)
├── schemas.py           # Pydantic request/response models
├── service.py           # Business logic (stateless, sync or async)
└── tests/
```

**Router convention** (`router.py`):

```python
from fastapi import APIRouter

router = APIRouter(prefix="/my_module", tags=["my_module"])

@router.get("/")
async def list_items():
    return {"items": []}
```

The prefix is mounted under `/api/v1/`, so the endpoint becomes
`GET /api/v1/my_module/`. The module loader wires this automatically, with no
need to edit `main.py`.

**Migrations**: if you add models, put Alembic migrations under
`backend/app/modules/my_module/migrations/` and run `make migrate`.

**Validation rules**: drop a file under
`backend/app/core/validation/rules/my_module.py` that subclasses
`ValidationRule`. The engine auto-registers it.

Reference implementations: `backend/app/modules/boq/`, `backend/app/modules/projects/`.

---

## 4. Frontend module, 5-minute walkthrough

Full guide lives at:
**[`frontend/src/modules/MODULE_DEVELOPMENT_GUIDE.md`](frontend/src/modules/MODULE_DEVELOPMENT_GUIDE.md)**

**Short version**:

```bash
mkdir frontend/src/modules/my-feature
```

Create `frontend/src/modules/my-feature/manifest.ts`:

```ts
import { lazy } from 'react';
import { Sparkles } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const MyFeatureModule = lazy(() => import('./MyFeatureModule'));

export const manifest: ModuleManifest = {
  id: 'my-feature',
  name: 'My Feature',
  description: 'What this module does in one line',
  version: '1.0.0',
  icon: Sparkles,
  category: 'tools',           // estimation | planning | procurement | tools
  defaultEnabled: false,
  depends: ['boq'],

  routes: [{ path: '/my-feature', title: 'My Feature', component: MyFeatureModule }],

  navItems: [{
    labelKey: 'nav.my_feature',
    to: '/my-feature',
    icon: Sparkles,
    group: 'tools',
    advancedOnly: true,
  }],
};
```

Then register in `frontend/src/modules/_registry.ts`:

```ts
import { manifest as myFeature } from './my-feature/manifest';
export const MODULE_REGISTRY = [/* ... */, myFeature];
```

All nav and routes appear automatically once registered.

---

## 5. Installing a third-party module

Two supported paths:

**Zip install** (recommended for distribution):

```bash
openconstructionerp module install path/to/my-module-1.0.0.zip
```

**Manual install** (development):

```bash
cp -r downloaded-module backend/app/modules/
# restart backend, the module loader picks it up
```

Then enable it from the UI: **Settings, Modules & Marketplace, System Modules**.

---

## 6. Core rules (enforced in PR review)

1. **i18n everywhere** - every user-visible string goes through `t()`. No
   hardcoded English. Fallbacks live in `frontend/src/app/i18n-fallbacks.ts`.
2. **No IfcOpenShell, no native IFC parsing** - CAD and BIM are always converted
   through DDC cad2data to the canonical JSON format. BCF is allowed as an open
   I/O format for issues, viewpoints and validation reports. See
   [`docs/adr/002-no-ifcopenshell-ddc-canonical-only.md`](docs/adr/002-no-ifcopenshell-ddc-canonical-only.md).
3. **Validation is not optional** - any module that ingests data must declare
   validation rules. See `backend/app/core/validation/`.
4. **Suggestions are confirmed by a person** - any suggested value must show a
   confidence score and require user confirmation before it mutates data.
5. **AGPL-3.0 compliance** - contributions are dual-licensed (AGPL plus
   Commercial). See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## 7. Quick reference

| I need to...                        | Look at...                                                               |
|-------------------------------------|--------------------------------------------------------------------------|
| Browse all modules by function      | [The module catalog](#1-the-module-catalog)                              |
| Scaffold a backend module           | `modules/oe-module-template/`                                            |
| Full frontend module spec           | [`frontend/src/modules/MODULE_DEVELOPMENT_GUIDE.md`](frontend/src/modules/MODULE_DEVELOPMENT_GUIDE.md) |
| Backend module quickstart           | [`docs/module-development/quickstart.md`](docs/module-development/quickstart.md) |
| Real-world backend example          | `backend/app/modules/boq/`                                               |
| Real-world frontend example         | `frontend/src/modules/pdf-takeoff/`                                      |
| Add validation rules                | `backend/app/core/validation/rules/`                                     |
| Hook into events                    | `backend/app/core/events.py` and `<your_module>/events.py`               |
| Add or override translations        | `frontend/src/app/i18n-fallbacks.ts`                                     |
| How the platform fits together      | [`docs/platform/how-it-works-for-builders.md`](docs/platform/how-it-works-for-builders.md) |
| Architecture decisions              | [`docs/adr/README.md`](docs/adr/README.md)                               |
| User guides by workflow             | [`docs/user-guide/README.md`](docs/user-guide/README.md)                 |
| Contribute back                     | [`CONTRIBUTING.md`](CONTRIBUTING.md)                                     |

---

## 8. Notes for automated scaffolding and agents

If you scaffold a module on behalf of a user:

- Copy the template, do not start from scratch. The manifest contract changes
  faster than this doc.
- Read the module's `manifest.py` and any local `README` before modifying it.
- Run `npm run build` (frontend) and `ruff check` plus `pytest` (backend)
  before reporting the module done.
- Never edit the `frontend/src/modules/_types.ts` or `_registry.ts` contract.
  Only add to the registry array.
- If a module needs a new translation key, add the English fallback to
  `i18n-fallbacks.ts` in every locale block you touch. Never leave a raw
  English string in TSX code.
