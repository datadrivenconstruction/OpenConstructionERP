# Module ecosystem overview

OpenConstructionERP is modular. Well over a hundred first-party modules ship in the box, and each one is a self-contained package that the platform discovers and mounts on start. You enable the ones a project needs and ignore the rest. This page groups the modules by area with a one-line description each, so you can see the full breadth and find the piece you are looking for. For the workflows that tie several modules together, read the [user guide](../user-guide/README.md). To build your own module, read the [platform and builder guide](../platform/README.md).

A module can depend on others, so enabling a workflow usually pulls in what it needs. Where a module is a thin analytical layer over data another module owns, that is noted, because it means the module adds a view rather than a new place to enter data.

## Estimating and the bill of quantities

The core estimating stack, from a first rough number to a fully qualified bill.

- Bill of Quantities - the core BOQ editor: hierarchical sections and positions, rates, calculations and export.
- Conceptual Estimate - an order-of-magnitude estimate from areas and unit counts before detail exists.
- Assemblies and Calculations - reusable rate recipes built from labour, material and equipment components.
- Estimating Methodologies - the method behind an estimate, so the approach is recorded, not just the number.
- Basis of Estimate - auto-drafts the inclusions, exclusions and assumptions that qualify a proposal.
- Allowances and Contingency - provisional sums, prime-cost sums and contingencies with a running drawdown.
- Preliminaries - general conditions and site establishment priced as time-related and fixed items.
- Waste Factors - net-to-gross quantity adjustment with waste, lap and coverage factors.
- Labor and Crew Rates - all-in labour rate build-up and composite crew rates.
- Production-Norm Expansion - expands a work item into unpriced labour, machine and material demand from norm coefficients.
- Resource Summary - rolls per-position resource splits into one procurement-ready schedule.
- Estimate Rollup - consolidates estimates into portfolio and program totals.
- Formwork - a formwork system catalogue with reuse-aware unit-cost computation.
- Design Options - generate and compare priced design variants side by side.
- Value Realized - composes figures the platform already computes into a project and portfolio value summary.

## Cost data and catalogs

The rates and resources an estimate draws on, and the tools to search and compare them.

- Cost Database - cost items and rate databases, including CWICR and regional catalogues, with bulk import.
- Product and Resource Catalog - a curated catalog of materials, equipment, labour and operators.
- Cost Explorer - a search-first workspace to find priced work by its resources and compare scope across regional bases.
- Cost Match - matches items to cost positions to price them.
- Price Index Adjustment - moves rates across time and location onto a common footing.
- Supplier Catalogs and Vendor Management - vendor price lists and supplier records.

## BIM, CAD and reality capture

Bring any model or drawing in, coordinate it, and turn it into structured quantities. All formats convert through the DDC canonical pipeline rather than native IFC parsing.

- BIM Hub - model and element management, BOQ linking, quantity maps and model diffs.
- CAD Import - the CAD conversion pipeline for DWG, DGN, RVT and IFC.
- Quantity Takeoff - manual and assisted takeoff from drawings and models.
- DWG Takeoff - a 2D DWG and DXF viewer with measurement, annotation and BOQ linking.
- CAD-BIM Match to Cost - maps model, drawing, PDF and photo elements to cost positions and scales resources into the BOQ.
- Element Match - the underlying element-to-cost matching service.
- Point Cloud and Reality Capture - ingests laser-scan, photogrammetry and LiDAR into confirmed, validation-gated quantities.
- Clash Detection - geometric coordination across federated models.
- Clash AI Triage - ranks new clashes by severity, rework cost and location, with confidence scores.
- Clash Cost Impact - estimates the rework cost of a clash issue from the cost database.
- Coordination Hub - one dashboard fusing clashes, requests, submittals and actions per federation.
- Smart Views - saved filters across a model federation.
- BIM Requirements - IDS and COBie import and export for owner data drops.
- BCF Issues and Viewpoints - round-trip issues and viewpoints through the open BCF standard.
- OpenCDE API - a compliance layer for the OpenCDE Foundation API and BCF API.
- Geo Hub - anchor projects, plots and models on a 3D globe with pin layers; site surveys compare a dated drone orthophoto with the schedule.

## Scheduling, cost and controls

Plan the work in time, track cost against it, and control change.

- 4D Schedule - a Gantt schedule linking BOQ work to a timeline with dependencies and critical path.
- Schedule Advanced (Last Planner) - phase plans, look-ahead, constraints, weekly work plans and percent-plan-complete.
- 5D Cost Model - S-curves, cash-flow projections, earned value and budget tracking over time.
- Full EVM - advanced earned value with forecasting, S-curves and to-complete performance analysis.
- Project Controls - an executive dashboard of cost, schedule, quality, safety, risk and change side by side.
- Progress Tracking - records progress against the plan.
- Project Timeline - a cross-module timeline of project events.
- Tasks - task tracking, including issues linked to model elements.
- Cost-Value Reconciliation and Cashflow - value earned against cost incurred, with cash flow.
- Finance - invoicing, payments, budgets and earned value.
- Risk Register - probability and impact scoring with Monte Carlo contingency analysis.
- Change Intelligence - reads the change family to report what is waiting on whom and for how long.
- Dashboard Rollup and Dashboards - configurable project and portfolio dashboards.
- Management of Change - structured change control across disciplines.
- Cost Recovery - back-charges the project intends to recover, with a per-party recovery ledger.
- Event Reconciliation - stitches one real event back together across the modules that recorded it.

## Commercial and procurement

Buy the work, manage the parties, and run the developer and asset side of a business.

- Tendering - bid packages, distribution, collection and side-by-side comparison.
- Bid Management - invitations, question threads, submissions, levelling and award.
- RFQ and Bidding - request for quotation with submission, evaluation and award.
- Procurement - purchase orders, goods receipts and vendor management.
- Subcontractor Management - subcontractor records, scope and performance.
- Contract Types Engine - the contract forms and terms a project runs under.
- Change Orders - scope changes with cost, schedule and approval workflow.
- Variations and Site Measurements - variations captured and measured on site.
- Claims Evidence - assembles a reproducible, content-addressable evidence pack for a claim.
- CRM Sales Pipeline - accounts, leads, opportunities, activities and win-loss analytics.
- Webhook Leads - captures inbound leads from external forms.
- Client and Partner Portal - a controlled outside view for clients, subcontractors and suppliers.
- Property Development - the developer lifecycle from lead through reservation, contract, handover and warranty.
- Accommodation - worker camps, rentals and visitor lodging in one model.
- Equipment and Fleet Management - plant and fleet on site.
- Resource Planning - people, crews, equipment and subs with skills, availability and conflict detection.
- Asset Operations - operation and management of delivered assets.
- Service and Maintenance - service jobs and maintenance work.
- Payroll - payroll for site and staff labour.
- Off-site, Prefab and DfMA - a register for off-site manufactured units with a quality gate before dispatch.

## Field and site operations

Capture what happens on site and keep the paper trail that protects the project.

- Daily Site Diary - weather-aware daily entries with crew, plant, deliveries, delays and photos.
- Field Diary and Field Reports - additional daily field records for site teams.
- Field Time - hours worked on site.
- Forms and Checklists - permits, briefings and recurring site paperwork.
- Voice Capture - dictated entries from the field.
- Site Logistics and Delivery - gates, laydown zones and a clash-checked delivery booking board.
- Requests for Information - questions, responses and their cost and schedule impact.
- Submittals - shop drawings, product data and samples with review workflows.
- Transmittals - formal document transmittals with acknowledgement.
- Correspondence - letters, emails and notices with direction and cross-references.
- Phone Log - a record of significant calls.
- Meetings - agendas, attendees, minutes and action items.
- Inbound Email and Inbound Capture Gateway - bring outside messages and documents into the project.
- Commissioning (Cx) - prefunctional and functional checklists with system-readiness scoring.
- Handover and Closeout - assembles the completion package from punch list, inspections and documents.

## Quality, safety and sustainability

Keep the work compliant, safe and accountable, and measure its environmental footprint.

- Validation Engine - configurable rule sets that score data quality with a traffic-light report.
- Requirements and Quality Gates - requirements as structured triplets run through sequential quality gates.
- EAC v2 Engine - a single rules engine behind takeoff, validation and clash outputs.
- Quality Inspections - checklists and pass-fail workflows for pours, waterproofing, services and handover.
- Quality Management System - inspections, non-conformances, punch list and audits unified with cost-of-quality analytics.
- Non-Conformance Reports - material, workmanship and design non-conformances with root cause and corrective action.
- Punch List - snags from discovery through resolution, verification and close, with photo evidence.
- Construction Control - a universal quality-control engine with material records, as-built evidence and acceptance gates.
- Safety Management - incident and observation tracking with risk scoring and corrective actions.
- HSE Advanced - job safety analysis, permit to work, toolbox talks, audits and safety performance indicators.
- Carbon and Sustainability - embodied and operational carbon with environmental product data and reporting.
- ESG Site Performance - site-level environmental, social and governance metrics.
- Compliance DSL - compliance rules expressed in a small domain language.
- Compliance AI - assisted checking of documents against compliance requirements.
- Compliance Documents - the register of certificates and compliance paperwork.

## Documents, files and collaboration

Store, control and mark up the project's documents, and work on them together.

- Document Management - upload, categorise and manage project documents with tagging and search.
- Common Data Environment (ISO 19650) - document containers, revisions, state transitions and suitability codes.
- Markups and Annotations - drawing markups, scale calibration and stamp templates.
- Comments and Viewpoints - threaded comments with mentions on any entity.
- Real-time collaboration locks - soft locks so two people do not overwrite each other.
- Document Connectors - links to external document stores.
- Contacts Directory - one directory of clients, subcontractors, suppliers and consultants.
- Team Visibility - team-based access control within a project.
- Notifications - in-app notifications with per-user preferences.
- A family of file tools rounds this out: file search, versioning, approvals, comments, tags, references, transmittals, distribution, favourites, saved views and a recycle bin.

## AI, search and intelligence

Assisted drafting and answers over your own project data. AI suggestions always carry a confidence score and wait for a person to confirm.

- AI Estimation - a BOQ drafted from a text description or a photo.
- AI Estimate Builder - assembles an AI-drafted estimate for review.
- AI Agents - task-focused assistants over project data.
- ERP Chat - a chat that reads and writes project data through typed tools rather than guesswork.
- Project Intelligence - project completion analysis, scoring and guided recommendations.
- Semantic Search - meaning-based search across the cost database and project data.
- Find Records - fast lookup of records across modules.

## Reporting, analytics and integrations

Turn the data into reports and connect it to the outside world.

- Reporting and Dashboards - KPI snapshots, report templates and generated reports.
- BI Dashboards and Reporting - richer business-intelligence dashboards and analytics.
- Integrations - chat connectors, outgoing webhooks, email and calendar feeds.
- Pipeline Builder - configurable data pipelines.
- Enterprise Workflows - configurable approval workflows for invoices, orders, variations and BOQs.
- Approval Routes - the approval chains those workflows follow.
- Background Jobs - status and control for long-running background work.
- Backup and Restore - export and import of your data.

Electronic invoicing is available too, producing standards-based e-invoice formats that can be embedded in a PDF, so the finance side can exchange invoices in the formats regulators expect.

## Regional packs

Region-specific settings, standards and defaults, enabled per project.

- Regional packs cover the DACH countries, the United Kingdom, the United States, India, the Middle East and Gulf, Russia and the CIS, Latin America, Mexico, South Africa and the wider Asia-Pacific.

## Platform, foundation and administration

The core that everything else stands on.

- Projects - projects with regional settings, classification standards and validation configuration.
- Users and Authentication - users, tokens, API keys and role-based access control.
- Internationalization Foundation - multi-currency exchange rates, a country registry, work calendars and tax configuration.
- Direct Uploads and Resumable Uploads - reliable file upload, including large files.
- Admin - gated operator endpoints for maintenance and test fixtures.
- Client Error Sink - collects front-end errors for diagnosis.
- Architecture Map - an interactive visual map of the system for developers.

## Building your own

Every module in this list is a Python package under `backend/app/modules/` with a manifest, and yours can be too. The platform discovers it, mounts its API, registers its data models and wires its validation on the next restart, with no central file to edit. Start with the [platform and builder guide](../platform/README.md) and the [module development quickstart](../module-development/quickstart.md).
