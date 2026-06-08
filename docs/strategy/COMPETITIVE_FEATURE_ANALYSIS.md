# Competitive Feature Gap Analysis

OpenConstructionERP versus an integrated 5D estimating suite, a 5D design-to-delivery platform, a construction management platform, and a field-and-financials construction platform.

Author: DataDrivenConstruction
Scope: cost management, estimating, project controls, BIM-to-cost, field and document workflows.
Method: full inventory of our 117 backend modules and the React sidebar route map, benchmarked against current 2025-2026 capabilities of the four reference platforms plus reference points from a PDF takeoff and markup tool, a model-based takeoff tool, a 4D sequencing tool and a construction CDE platform.

This document is deliberately specific to our codebase. Every recommendation names the real modules it touches and whether we already have infrastructure to build on. The goal is to find true gaps, not to produce a generic checklist.

---

## 1. What we already have

We are not starting from zero. The platform is unusually broad for its stage. The honest summary by domain:

| Domain | Modules we own | State |
|---|---|---|
| Estimating / BOQ | `boq`, `assemblies`, `match_elements`, `match`, `ai` (AI estimate) | Strong. Hierarchical BOQ, assemblies, reusable positions, AI-assisted matching to cost catalogues. |
| Cost databases | `costs`, `catalog`, `supplier_catalogs`, CWICR seed (55k items, 9 languages) | Strong and a genuine differentiator. Open data, multi-region. |
| Quantity takeoff | `takeoff` (PDF), `dwg_takeoff`, AI takeoff via `cv-pipeline`, symbol detection | Good 2D coverage. Comparable to leading PDF takeoff tools on PDF measurement. |
| BIM / IFC | `bim_hub`, `cad`, `data-explorer`, `bim_requirements`, `eac` engine over DDC canonical Parquet | Good. Conversion via DDC cad2data, not IfcOpenShell. Federations, smart views, requirements. |
| Clash and coordination | `clash`, `clash_ai_triage`, `clash_cost_impact`, `coordination_hub` | Good. Clash with AI triage and cost impact is ahead of many mid-market tools. |
| Geo / GIS | `geo_hub` (Cesium 3D tiles, tile proxy, DWG/PDF overlay) | Good and unusual at this tier. |
| Scheduling / CPM | `schedule`, `schedule_advanced` (CPM, resource leveling), `tasks`, 4D service | Solid. CPM and leveling exist. 4D linking of activities to BIM elements exists. |
| Cost control / EVM | `costmodel` (5D), `full_evm`, `eac`, `progress` | Present but shallow on data flow (see gaps). Manual snapshot entry, not auto-derived. |
| Finance | `finance` (invoices, payments, budgets by WBS), Brazil invoice PDF | Present. Transactional, not yet a controls cockpit. |
| Procurement / RFQ | `procurement`, `rfq_bidding`, `bid_management`, `tendering` | Good coverage of the bid-to-award path. |
| Contracts | `contracts` (prime + commitment, schedule of values, retention, fee, gainshare, LD clauses, progress claims) | Surprisingly deep data model. Under-surfaced in the UI. |
| Variations / change orders | `variations`, `changeorders` (cost + schedule impact, construction-platform-style approval chain) | Good. |
| RFI / submittals | `rfi`, `submittals` (with linked BOQ item ids), `transmittals`, `correspondence` | Good coverage of the paperwork primitives. |
| CDE / documents | `cde`, `documents`, `file_versions`, `file_approvals`, `file_comments`, `file_distribution`, `file_transmittals`, `markups`, `opencde_api`, `bcf` | Broad. Versioning and approvals exist. Drawing compare is the gap. |
| Field | `daily_diary`, `field_diary`, `fieldreports`, `inspections`, `punchlist`, `photos` | Present on desktop. Offline mobile is design-only. |
| Safety / quality / ESG | `safety`, `hse_advanced`, `qms`, `ncr`, `moc`, `inspections`, `carbon` | Broad. |
| Risk / CRM / dev | `risk`, `crm`, `property_dev`, `accommodation` | Present. |
| Validation / compliance | `validation` engine, regional rule packs (DIN 276, GAEB, NRM, MasterFormat, ONORM and more), `compliance`, `compliance_docs`, `compliance_ai` | A genuine differentiator. Validation is first-class. |
| Reporting / BI | `reporting`, `bi_dashboards`, `dashboards`, `project_intelligence` | Present. |
| AI | `ai`, `ai_agents`, `erp_chat`, `clash_ai_triage`, `compliance_ai`, `project_intelligence` | A differentiator. AI woven across modules, human-confirmed. |
| Platform | partner packs, 27 locales, multi-currency with fx_rates, embedded PostgreSQL zero-setup, approval routes, webhooks, integrations | Strong platform story. |

Conclusion from the inventory: our breadth already matches or exceeds the leading construction management platforms on module count. The weakness is not coverage. It is depth of the connective tissue that turns separate modules into one system of record. That is exactly where the incumbents earn their price.

---

## 2. What the benchmarks actually lead on

A condensed read of where each competitor sets the bar as of 2025-2026.

### Integrated 5D estimating suite (DACH-strong)
DACH estimating plus full AVA (Ausschreibung, Vergabe, Abrechnung over GAEB and ONORM). BIM-compliant bills of quantities generated directly from IFC models. The headline is a seamless process-oriented flow from technical planning into financial management, so cost calculation, tendering, scheduling and billing share one data basis. Bid comparison and subcontractor billing are native.

### 5D design-to-delivery suite
The reference implementation of true 5D. The 3D model carries cost (5D) and time (4D) together for design-to-delivery control. Estimating uses a flexible line-item structure that can follow traditional methods or be driven by model objects, work packages or time-based breakdowns. Costing flows into procurement, resource planning and scheduling. Schedulers assign schedule info to model objects and run a 5D simulation that forecasts and resequences before site. This is the gold standard we are closest to in ambition.

### Construction management platform (documents and models)
Document and drawing management with version control and markups, model coordination with clashes and issues linked to object tables, model-based and symbol-detection takeoff, specifications linked across files, sheets, RFIs and submittals, custom submittal review workflows, and cost management with budgets, change orders, and an estimate-to-budget handoff. The differentiator is traceability: a spec, a model object, an RFI and a cost line are linked, not loose.

### Field-and-financials construction platform
The financials and field execution leader. Budget, prime and commitment contracts, change orders, commitment and prime payment applications (pay apps) with gross or net or retainage columns, forecasting, plus RFIs, submittals, drawings, daily logs, photos, quality and safety, field productivity, analytics, and a large app marketplace. The differentiator is a complete commercial loop (budget to commitment to pay app to forecast) and a deep field app.

### Reference points
A PDF takeoff and markup tool: best-in-class PDF takeoff and live multi-user markup sessions, push quantities to Excel. A model-based takeoff tool: live-linked 2D and 3D or BIM model takeoff against cost libraries. A 4D sequencing tool: 4D construction sequencing. A construction CDE platform: enterprise CDE with rigorous version control, transmittals and no file-size limits.

---

## 3. Gap analysis and recommendations

For each gap: what it is, who has it, how it connects our existing modules, the tier, rough effort, and the infrastructure we can build on. Effort is S (days), M (1-2 weeks), L (multi-week).

### Tier 1: Table stakes to be taken seriously as a professional tool

These are the items a professional buyer assumes exist. Missing or shallow today.

#### 1.1 Payment applications / progress billing (pay apps)
What: a periodic application for payment against a contract schedule of values, with this-period and to-date quantities, retention or retainage, approval, and certified-amount output. Standard AIA G702/G703 in the US, valuation certificates in the UK, Abschlagsrechnung in DACH.
Who: field-and-financials construction platform (prime and commitment pay apps), construction management platform cost management, integrated 5D estimating suite (Abrechnung).
How it connects us: this is the single highest-value piece of connective tissue we are missing, and we already own most of the parts. `contracts` already has `ContractLine` as a schedule of values, `RetentionSchedule`, and even `ProgressClaim` plus `ProgressClaimLine` models. `finance` has invoices and payments. `schedule`/`progress` has percent-complete per activity. The gap is a workflow that ties them together: pull SoV from `contracts`, draw this-period progress from `progress` or `schedule`, apply retention from `contracts`, route approval through `approval_routes`, post the certified invoice into `finance`, and reflect it as actual cost in `costmodel`. We are not building from scratch, we are wiring four modules into one screen.
Tier: 1. Effort: M (models largely exist). Touches: contracts, finance, schedule/progress, approval_routes, changeorders, costmodel.

#### 1.2 Unified project-financials cockpit (budget to commitment to actual to forecast)
What: one budget view per project where original budget, approved changes, revised budget, committed cost (contracts and POs), actual cost (invoices), and forecast-to-complete sit on the same cost-code rows with variance. This is the field-and-financials construction platform's center of gravity.
Who: field-and-financials construction platform (budget tool), construction management platform cost management.
How it connects us: `costmodel` already has `BudgetLine` keyed to `boq_position_id`, a `category`, and committed and actual and forecast fields, and `aggregate_by_project`. `finance` holds invoices keyed to WBS. `contracts` holds commitments. `changeorders` holds approved change cost. Today these do not roll up into one reconciled budget grid. Build a budget grid that: seeds rows from `boq` or `costs` cost codes, links commitments from `contracts`, pulls actuals from `finance` invoices, overlays approved `changeorders` as budget transfers, and computes forecast. This is the screen that makes us a controls tool rather than a collection of registers.
Tier: 1. Effort: L. Touches: costmodel, finance, contracts, changeorders, boq, costs, reporting.

#### 1.3 Drawing and document version compare with overlay
What: side-by-side and superimposed compare of two revisions of a sheet or PDF, with changed-area highlight, plus carrying markups across revisions. PDF takeoff tools, the construction management platform and the construction CDE platform all treat this as basic.
Who: construction management platform docs, a PDF takeoff and markup tool, a construction CDE platform.
How it connects us: we have `file_versions` (751 v1 rows backfilled historically), `markups`, `cde` and `documents`. We confirmed there is no overlay or visual diff today (the only compare in `markups` is an owner-id check). Add a compare view in `cde`/`markups` that renders two `file_versions` of the same document and a difference overlay, and re-anchors `markups` and `file_comments` to the latest revision. This closes a visible, demo-critical gap for any drawing-led buyer.
Tier: 1. Effort: M. Touches: file_versions, markups, cde, documents, file_comments.

#### 1.4 Submittals and RFI tied into approval routes and the CDE, with spec linkage
What: submittal and RFI review that runs through configurable approval chains, links to the source drawing or spec and the affected BOQ items, and notifies the ball-in-court party. The construction management platform just shipped custom submittal review workflows and spec-to-RFI-to-submittal linkage.
Who: construction management platform, field-and-financials construction platform.
How it connects us: `submittals` already carries `linked_boq_item_ids`, `ball_in_court`, reviewer and approver fields. `rfi` exists. `approval_routes` exists as a generic engine. We confirmed no module currently imports `approval_routes` (it is unused connective tissue). Wire `submittals` and `rfi` (and `changeorders`) to drive their state machine through `approval_routes`, attach `cde` documents and `markups`, and fire `notifications`. This turns three separate registers into one governed review workflow and finally activates the approval engine we already built.
Tier: 1. Effort: M. Touches: submittals, rfi, approval_routes, cde, markups, notifications, changeorders.

#### 1.5 Offline field PWA for diary, photos and punchlist
What: a phone and tablet surface for site staff to log diary entries, capture geotagged photos and close punchlist and inspection items, that keeps working with no signal and syncs later.
Who: field-and-financials construction platform (field app is a core selling point), construction management platform build mobile.
How it connects us: the design exists (`docs/architecture/FIELD_WORKER_MOBILE_DESIGN.md`), the IndexedDB queue (`offlineStore.ts` with `apiCache` and `mutationQueue`) exists, and the backend modules exist (`daily_diary`, `field_diary`, `fieldreports`, `punchlist`, `inspections`, `photos`). The gap is execution: a `field_worker` role, a thumb-zone mobile shell, and offline sync wired to those endpoints. Without a credible field app we lose every contractor evaluation against the field-and-financials construction platform on day one.
Tier: 1. Effort: L. Touches: daily_diary, fieldreports, punchlist, inspections, photos, users (RBAC), the existing offline store.

### Tier 2: High-impact differentiators (our edge: AI plus 5D plus connective tissue)

These are where we can leapfrog rather than catch up, because we already have the unusual parts (open data, DDC conversion, validation engine, AI agents).

#### 2.1 True 5D cockpit: BIM element to BOQ position to schedule activity to cost, in one place
What: a single linked model where selecting a model element shows its BOQ position, its schedule activity, its budget line and its earned value, and a 4D plus 5D simulation plays the sequence with cost accruing over time. This is the 5D design-to-delivery suite's flagship.
Who: 5D design-to-delivery suite, integrated 5D estimating suite (model to BOQ), a 4D sequencing tool (4D only).
How it connects us: every link already exists in isolation. `schedule.Activity` carries `boq_position_ids`, `bim_element_ids`, and `cost_planned`/`cost_actual`. `costmodel.BudgetLine` carries `boq_position_id` and `activity_id`. The `eac` engine resolves BIM elements to activities over DDC canonical Parquet. `match_elements` links BIM to catalogue. What is missing is the unifying surface and the bidirectional navigation that makes it feel like one model. Build a 5D workspace that joins these four keys and a time-stepped cost simulation on top of the existing 4D service. This is the most defensible thing we can build, because we already paid for the hard plumbing.
Tier: 2 (could be argued Tier 1 for the BIM-led segment). Effort: L. Touches: bim_hub, boq, schedule, costmodel, eac, match_elements, clash_cost_impact.

#### 2.2 Auto-derived earned value and forecasting (kill the manual snapshot)
What: EVM where PV, EV and AC are computed from real data, not typed in. PV from the cost-loaded schedule baseline, EV from `progress` percent-complete against budget, AC from `finance` invoices and `contracts` pay apps, with EAC and TCPI forecasts.
Who: 5D design-to-delivery suite, field-and-financials construction platform (forecasting), enterprise CPM scheduling.
How it connects us: `costmodel` and `full_evm` already compute SPI, CPI, EAC, VAC and TCPI and store snapshots, but the service confirms the numbers are entered manually (auto-compute only fills the indices from typed PV/EV/AC). The 4D service already knows how to derive PV and AC when the schedule is cost-loaded. Connect the dots: a scheduled job that builds each period snapshot from `schedule` baseline plus `progress` plus `finance` plus `contracts`, so EVM becomes a live readout. Pair it with the AI layer for anomaly and overrun prediction via `project_intelligence`.
Tier: 2. Effort: M. Touches: costmodel, full_evm, schedule, progress, finance, contracts, project_intelligence.

#### 2.3 Estimate-to-budget-to-procurement handoff (one cost spine)
What: a one-click flow that turns an approved BOQ estimate into the project budget, then into procurement packages and commitments, so a single cost code identity flows estimate to control to buy. The construction management platform just productized this (estimate-to-build), and the integrated 5D estimating suites treat it as core.
Who: integrated 5D estimating suite, 5D design-to-delivery suite, construction management platform.
How it connects us: `boq` is the estimate, `costmodel.BudgetLine` is the budget (already keyed to `boq_position_id`), `procurement` and `rfq_bidding` are the buy, `contracts` is the commitment. The handoff is not automated today. Build the promote-estimate-to-budget action and carry the cost-code identity through procurement into commitments. This is the spine that makes 1.2, 1.1 and 2.2 coherent.
Tier: 2. Effort: M. Touches: boq, costmodel, procurement, rfq_bidding, contracts, costs.

#### 2.4 AI submittal, RFI and spec assistant grounded in our data
What: AI that drafts RFI and submittal responses, suggests the affected BOQ items and spec section, and flags risk, using our embeddings and catalogue. A natural extension of our existing AI agents.
Who: emerging across the construction management platform and the field-and-financials construction platform via copilots, none deeply grounded in an open cost database the way we can be.
How it connects us: `ai_agents`, `erp_chat`, `compliance_ai` and `project_intelligence` already exist, and we have CWICR plus pgvector or Qdrant. Ground the assistant in `submittals`, `rfi`, `cde` and `costs` so its suggestions are confirmable with confidence scores (our human-confirmed principle). This leans on a strength competitors cannot easily copy: an open, multilingual cost corpus.
Tier: 2. Effort: M. Touches: ai_agents, erp_chat, rfi, submittals, cde, costs, project_intelligence.

#### 2.5 Cross-module project controls dashboard (the single pane)
What: one executive board joining cost (budget vs committed vs actual vs forecast), schedule (SPI, critical path slip), quality and safety (open NCR, incidents), change exposure (pending variations value), and risk, with drill-down to source.
Who: field-and-financials construction platform analytics, construction management platform insight, 5D design-to-delivery suite dashboards.
How it connects us: `bi_dashboards`, `reporting`, `dashboards` and `project_intelligence` exist, as does a `dashboard` rollup endpoint that already reduced per-widget fan-out. The gap is a single controls board that joins the now-connected cost spine (2.2, 1.2) with schedule, `ncr`, `safety`, `variations` and `risk`. This is the payoff screen that makes the connected modules legible to a project director.
Tier: 2. Effort: M (once 1.2 and 2.2 land). Touches: bi_dashboards, reporting, project_intelligence, costmodel, schedule, ncr, safety, variations, risk.

### Tier 3: Nice to have

Worth doing once the cost spine and field app are solid.

| Item | What and who | Connects | Effort |
|---|---|---|---|
| 4D sequence player UI | Visual time-step sequencing over the model, like a 4D sequencing tool. We have 4D data and BIM viewer. | bim_hub, schedule | M |
| Live multi-user markup session | Co-markup sessions, like a PDF markup studio. We have markups plus Yjs experience. | markups, collaboration | M |
| Bid leveling and scorecard depth | Side-by-side bid comparison matrix with normalization. We have bid_management and tendering. | bid_management, tendering, rfq_bidding | S |
| Resource histogram and cash-flow S-curve polish | We have leveling and cash_flow models, surface them better. | schedule_advanced, costmodel | S |
| Two-way schedule exchange (XER, MS Project XML) | Enterprise CPM scheduling and desktop scheduling tool interop expected by enterprise planners. | schedule, schedule_advanced | M |
| Mobile model viewer | View BIM on tablet on site. We have bim_hub. | bim_hub, field PWA | L |
| Marketplace and integration depth | The leading construction platforms have a large app store. We have partner packs and webhooks to build on. | integrations, webhook_leads, partner packs | L |

---

## 4. Our unique strengths, and how to frame them

We should not position as a cheaper construction management platform. We should position on four things the incumbents structurally cannot match.

1. Open data and open standards as the foundation. CWICR with 55k items in 9 languages, native GAEB, DIN 276, NRM, MasterFormat, ONORM, and full data export. The integrated 5D estimating suites lock you into their data world. The construction management platforms are closed SaaS. Frame: your cost data is yours, in open formats, forever.

2. CAD and BIM agnostic via DDC conversion, no IfcOpenShell lock-in. Every format becomes one canonical model that BOQ, validation, clash and 5D all read. Frame: one pipeline, any source, no per-format viewer tax.

3. Validation and compliance as a first-class, configurable engine. Regional rule packs gate every import. No incumbent makes compliance a built-in pipeline step the way we do. Frame: estimates that are checked against DIN, GAEB, NRM and your own rules before they ever reach a client.

4. AI woven through, human-confirmed, grounded in open cost data. Matching, clash triage, compliance and estimation assistance with confidence scores. Our open corpus makes our AI suggestions more grounded than a closed copilot. Frame: AI that proposes, you confirm, with the numbers traceable to an open database.

Plus two adoption advantages: embedded PostgreSQL means zero-setup install with no Docker and no DBA, and 27 locales plus real multi-currency (fx_rates, convert within a project, group by currency across projects) make us genuinely global where the incumbents are regionally strong but globally uneven.

Positioning line: the incumbents win on depth of one loop each (the integrated 5D estimating suite on DACH AVA, the 5D design-to-delivery suite on 5D, the construction management platform on documents and models, the field-and-financials construction platform on financials and field). We win by connecting all of those loops on open data with AI, at a price and setup cost they cannot reach. The work in Tier 1 and Tier 2 is what makes that claim true rather than aspirational.

---

## 5. Recommended sequence

The dependency-aware order, because several items unlock the next:

1. Estimate-to-budget spine (2.3) and the unified budget cockpit (1.2). One cost identity is the precondition for everything financial.
2. Payment applications (1.1) on top of that spine. Highest revenue-relevant table-stakes gap, and the models mostly exist.
3. Auto-derived EVM (2.2) once budget and pay-app actuals flow.
4. Submittal and RFI through approval routes (1.4) and drawing compare (1.3) in parallel. These activate dormant infrastructure (approval_routes, file_versions) for high visible value.
5. True 5D cockpit (2.1) as the flagship differentiator demo.
6. Offline field PWA (1.5) to stop losing field-led evaluations.
7. Cross-module controls dashboard (2.5) as the payoff once the data is connected.

The theme throughout: we already own the parts. The differentiated work is connecting them, not adding more modules.
