# Module Connectivity Audit, 2026-06-06

## Executive summary

This audit walks all 15 sidebar groups and asks one question: when two modules clearly belong together in a real construction workflow, can a user actually click from one to the other, or does the relationship die at the screen? The answer, far too often, is that the data model already holds the link (a real foreign key on the wire) but the UI throws it away. We found 80 connectivity defects. The dominant pattern is not missing data; it is missing edges. A clash shows a 4,500 EUR cost impact with the exact BOQ positions on the payload, yet the positions appear only in a plain HTML tooltip with no link. A Last Planner commitment points at a real Task row but forces the foreman to paste a raw UUID. A carbon inventory has a working assign-from-BOQ backend endpoint that the frontend never calls. Across the platform the story repeats: the plumbing is built, the tap is missing.

The defects sort into seven recurring shapes. Data islands (records that display a foreign key as plain text or a raw UUID instead of a link) are the largest class and the cheapest to fix. Missing links (a sibling module that should be one click away is not reachable at all). Takeoff ties (a BOQ or takeoff quantity that should flow into a downstream record but must be re-keyed by hand). Extra clicks (an action succeeds but the success toast offers no way to see the result). Dead ends (a workflow the intro copy promises but no control exists to start it). Duplicate overlaps (two sibling modules doing the same job from disjoint tables, with no cross-write and no signpost). Naming mismatches (a sidebar label that disagrees with the page it opens, or a tool grouped under the wrong heading).

Three structural problems deserve founder-level decisions because they cannot be closed by adding a link. First, the platform runs two parallel quality systems: the standalone Inspections, NCR and Punch List modules and a separate QMS stack with its own qms_* tables, and they never cross-write, so the same site keeps two disjoint registers and the dashboards disagree. Second, three change pipelines (Management of Change, Variations, Change Orders) auto-mirror in the backend but read as three accidental sidebar siblings. Third, Carbon and Sustainability both compute embodied carbon from the BOQ against EPD sources, and the BOQ-driven flow Carbon advertises actually lives only in Sustainability. These three need a chosen source of truth, not a pill.

The good news: most of the value is cheap. The single highest-leverage move is to make foreign keys clickable. Roughly a third of the findings are high impact and small effort, almost all of them either turning an already-fetched UUID into a deep link or adding a sibling cross-link pill. Those land in Tier 1 below and should ship first.

## Connectivity map: the strongest missing edges

These are the relationships the platform clearly intends (the FK or endpoint exists) but cannot be navigated. Ordered by how load-bearing the edge is to a real workflow.

- BOQ position to / from everything. The BOQ is the cost spine, yet the back-references die at display: Clash cost impact to BOQ position, EIR requirement to BOQ position, 4D Schedule activity to BOQ positions, 5D cost line to BOQ position, Markup to BOQ position, Submittal to BOQ items, Finance invoice line to cost line. Almost all are data islands where the id is already on the payload.
- Estimate to programme. BOQ to Schedule is one-directional (Generate from BOQ lives only inside Schedule); Takt and Last Planner cannot pull trades or locations from the BOQ or BIM and force retyping.
- Tender to contract to actual. Bid Management and Tendering both award but hand off differently (one to PO, one nowhere near Contracts); the awarded bid carries everything a contract needs but the user re-enters it; the Contract counterparty FK is shown as a bare type word.
- Federation to clash. A BIM federation exists to be clash-checked but has no Run clash detection action; Clash does not link back to the Coordination Hub or Federations.
- Capacity to leveling to resources. Capacity Planning detects conflicts with zero outbound navigation; Resource Leveling shows fix suggestions with no Apply control; neither links to the other or back to Resources.
- Quality source events. NCR to its originating Inspection, Punch item to its source inspection/NCR/clash, CAPA to its source record, Validation error to a raised NCR: all are FKs or metadata rendered as static text.
- Field evidence to records. A defect Photo cannot become a Punch item, NCR, or diary entry; Daily Diary entries carry source_module / source_ref but never link.
- Person and party. Accommodation occupant, Payroll worker, Service technician/customer, Correspondence parties, Meeting attendees, Resource assignment project/task: all are real contacts/resources shown as plain text.
- Executive rollup to source. Project Controls cost KPIs ignore the BOQ baseline and 4 KPI tiles drill to nothing; BI Dashboards drill has no per-row deep link though Project Controls already solved it.
- AI to the modules it reads. AI Chat and Advisor render projects, BOQ items and cost sources with no deep link out; estimating pages never surface the AI tools.

## Per-group findings

### Model coordination

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Clash cost impact island | Clash Detection | /clash | data_island | high | medium |
| Clash to RFI/NCR | Clash Detection | /clash | missing_link | high | large |
| Clash back to hub | Clash Detection | /clash | missing_link | medium | small |
| Federation run clash | BIM Federations | /bim/federations | missing_link | high | medium |
| BIM Rules naming | BIM Rules | /bim/rules?mode=requirements | naming | medium | small |
| Quantity rules to BOQ | BIM Rules | /bim/rules | extra_clicks | medium | small |
| EIR to BOQ position | EIR Matrix | /requirements/matrix | data_island | medium | medium |
| EIR cell to deliverable | EIR Matrix | /requirements/matrix | missing_link | medium | medium |
| Hub KPI cards clickable | Coordination Hub | /coordination | extra_clicks | medium | small |

### Scheduling

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Commitment task picker | Advanced Schedule (LPS) | /schedule-advanced | data_island | high | medium |
| Takt import from BOQ/BIM | Takt Planning | /takt | takeoff_tie | high | large |
| Gantt row to BOQ | 4D Schedule | /schedule | data_island | medium | medium |
| BOQ to Schedule (in) | 4D Schedule | /boq | missing_link | medium | medium |
| Constraint create dead end | Advanced Schedule (LPS) | /schedule-advanced | dead_end | high | medium |
| Takt cold-start to master | Takt Planning | /takt | naming | medium | small |
| Task committed/constrained badge | Tasks | /tasks | missing_link | medium | large |

### Cost control and risk

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Capacity outbound nav | Capacity Planning | /portfolio/capacity | data_island | high | small |
| Leveling Apply control | Resource Leveling | /portfolio/leveling | dead_end | high | medium |
| Leveling project links | Resource Leveling | /portfolio/leveling | data_island | medium | small |
| Leveling to Capacity | Resource Leveling | /portfolio/leveling | missing_link | medium | small |
| Resources to Capacity/Leveling (in) | Resources & Crew | /resources | missing_link | high | small |
| 5D linked-record UUIDs | 5D Cost Model | /5d | data_island | high | medium |

### Commercial

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Invite from directory | Bid Management | /bid-management | missing_link | high | medium |
| Scope from BOQ | Bid Management | /bid-management | takeoff_tie | high | large |
| Award to contract seed | Bid Management | /bid-management | missing_link | high | large |
| Contract counterparty link | Contracts | /contracts | data_island | medium | medium |
| Contract SoV from BOQ | Contracts | /contracts | takeoff_tie | high | large |
| Tendering to contract | Tendering | /tendering | missing_link | medium | medium |
| Tendering bid from directory | Tendering | /tendering | missing_link | medium | medium |
| Sub agreement to contract | Subcontractors | /subcontractors | data_island | medium | medium |
| Sub ratings to QA/HSE | Subcontractors | /subcontractors | missing_link | medium | medium |
| Bid vs Tendering overlap | Bid Management + Tendering | /bid-management | duplicate_overlap | medium | large |

### Procurement and change

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Variation linked records | Variations | /variations | data_island | high | small |
| Change order related records | Change Orders | /changeorders | data_island | medium | small |
| CO item from BOQ | Change Orders | /changeorders | takeoff_tie | high | medium |
| PO line from BOQ | Procurement | /procurement | takeoff_tie | high | large |
| Supplier catalog dead tabs | Supplier Catalogs | /supplier-catalogs | duplicate_overlap | medium | small |
| Compare price to PO | Supplier Catalogs | /supplier-catalogs | missing_link | medium | medium |
| Three change pipelines | Management of Change | /moc | naming | medium | small |
| PipelineBanner dead code | Variations / Supplier Catalogs | /variations, /supplier-catalogs | dead_end | low | small |

### Field operations

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Diary vs Field Reports overlap | Daily Diary | /daily-diary | duplicate_overlap | high | large |
| Diary entry source link | Daily Diary | /daily-diary | data_island | high | medium |
| Diary to Payroll/Field Reports | Daily Diary | /daily-diary | missing_link | medium | small |
| Service technician/customer link | Service & Maintenance | /service | data_island | high | medium |
| Service vs Equipment assets | Service & Maintenance | /service | duplicate_overlap | medium | large |
| Sub Portal naming | Sub Portal | /portal | naming | medium | small |
| Portal grant access UUIDs | Sub Portal | /portal | data_island | medium | medium |
| Subcontractor to portal invite | Sub Portal | /portal | missing_link | medium | medium |

### Resources and assets

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Equipment rental UI missing | Equipment & Fleet | /equipment | dead_end | high | large |
| Assignment project/task link | Resources & Crew | /resources | data_island | high | medium |
| Payroll worker link | Payroll | /payroll | data_island | medium | medium |
| Asset register overlap | Asset Register | /assets | duplicate_overlap | medium | small |
| Payroll to Resources rate | Payroll | /payroll | missing_link | medium | small |
| Equipment to Resources (in) | Equipment & Fleet | /equipment | missing_link | medium | small |
| Resource request from BOQ | Resources & Crew | /resources | takeoff_tie | low | medium |

### Quality

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Two quality systems | Inspections/NCR/Punch vs QMS | /inspections, /ncr, /punchlist vs /qms | duplicate_overlap | high | large |
| NCR to inspection link | NCR | /ncr | data_island | medium | small |
| Punch source badge links | Punch List | /punchlist | data_island | medium | small |
| Punch pin on drawing | Punch List | /punchlist | takeoff_tie | medium | medium |
| Validation to NCR | Validation | /validation | missing_link | medium | medium |
| Closeout readiness chips | Handover & Closeout | /closeout | missing_link | medium | medium |
| Inspection WBS tie | Inspections | /inspections | takeoff_tie | low | medium |
| Inspection toast deep link | Inspections | /inspections | extra_clicks | low | small |

### Safety and ESG

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Carbon assign-from-BOQ | Carbon & ESG | /carbon | takeoff_tie | high | medium |
| Carbon vs Sustainability | Carbon & ESG / Sustainability | /carbon | duplicate_overlap | high | large |
| Sustainability discoverability | Sustainability | /sustainability | missing_link | high | small |
| HSE incident picker | HSE Management | /hse-advanced | missing_link | high | medium |
| Audit finding to CAPA | HSE Management | /hse-advanced | missing_link | medium | medium |
| CAPA source id picker | HSE Management | /hse-advanced | data_island | medium | medium |
| QMS vs standalone | Quality Management (QMS) | /qms | duplicate_overlap | high | large |
| QMS inspection to NCR | Quality Management (QMS) | /qms | missing_link | medium | small |
| Safety dashboard tiles | Safety | /safety | extra_clicks | medium | small |

### Communication

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Correspondence party links | Correspondence | /correspondence | data_island | medium | small |
| Meeting attendee pickers | Meetings | /meetings | data_island | medium | medium |
| RFI to/from Submittals | RFI | /rfi | missing_link | medium | small |
| Meeting action to RFI | Meetings | /meetings | missing_link | low | medium |
| Contact communication usages | Contacts | /contacts | missing_link | medium | large |

### Documents

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Photo to punch/NCR/safety | Project Photos | /photos | missing_link | high | medium |
| Markup/Submittal BOQ link | Markups | /markups | data_island | medium | small |
| Markup measurement to takeoff | Markups | /markups | takeoff_tie | medium | medium |
| CDE submit for approval | Common Data Environment | /cde | missing_link | medium | small |
| Photo timeline to diary | Project Photos | /photos | takeoff_tie | medium | small |
| Transmittal to submittal | Transmittals | /transmittals | missing_link | low | medium |

### Real estate

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Accommodation occupant link | Accommodation | /accommodation/:id | data_island | medium | small |
| Accommodation charge to Finance | Accommodation | /accommodation/:id | missing_link | medium | medium |
| PropDev block picker | Accommodation | /accommodation/:id | extra_clicks | high | medium |
| PropDev to Accommodation | Property Development | /property-dev | missing_link | medium | small |
| House type to BOQ | House Types | /property-dev/settings/house-types | takeoff_tie | high | large |
| Doc template dev picker | Document Templates | /property-dev/settings/document-templates | extra_clicks | medium | small |
| PropDev related-record scope | Property Development | /property-dev | data_island | medium | medium |
| Contacts to PropDev record (in) | Property Development | /contacts | missing_link | medium | medium |

### Finance

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Snapshots mis-grouped | Snapshots | /dashboards | naming | high | small |
| Snapshot to takeoff/match | Snapshots | /dashboards | takeoff_tie | medium | medium |
| Reporting vs Reports overlap | Reporting Dashboards | /reporting | duplicate_overlap | medium | medium |
| Reporting vs Finance/Analytics | Reporting Dashboards | /reporting | duplicate_overlap | medium | small |
| Invoice to claim/cost line | Finance | /finance | data_island | medium | medium |
| Analytics to Finance | Analytics | /analytics | missing_link | medium | small |
| Reports to source modules | Reports | /reports | missing_link | low | medium |

### Controls and BI

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Controls dead drill tiles | Project Controls | /project-controls | dead_end | medium | medium |
| Controls to BI Dashboards | Project Controls | /project-controls | missing_link | medium | small |
| BI KPI source chips | BI Dashboards | /bi-dashboards | data_island | medium | medium |
| BI to Project Controls | BI Dashboards | /bi-dashboards | missing_link | medium | small |
| Controls cost baseline from BOQ | Project Controls | /project-controls | takeoff_tie | high | medium |
| BI drill deep link | BI Dashboards | /bi-dashboards | duplicate_overlap | low | medium |

### Automation and AI

| ID source | Module | Route | Type | Impact | Effort |
|---|---|---|---|---|---|
| Chat read renderers no link | AI Chat | /chat | data_island | high | medium |
| Advisor source to costs/BOQ | AI Cost Advisor | /advisor | data_island | high | medium |
| AI tools cross-link strip | AI Agents/Advisor/Chat | /ai-agents, /advisor, /chat | missing_link | medium | small |
| Estimating to AI (in) | AI Agents/Advisor | /boq, /costs, /match-elements | missing_link | medium | medium |
| Chat admin hidden | AI Chat | /chat/admin | dead_end | low | small |
| Agent vs chat BOQ target | AI Agents/Chat | /ai-agents, /chat | naming | low | small |
| Chat takeoff tool | AI Chat | /chat | takeoff_tie | medium | large |

## Ranked fix backlog

### Tier 1: high impact, small effort (ship first)

These are the 2-click and missing-link wins. Almost all are "turn an already-fetched id into a deep link" or "add a sibling cross-link pill". No backend rework beyond serializing a field that is already on the model.

CONN-01. Capacity Planning has zero outbound navigation.
- Files: frontend/src/features/portfolio/CapacityPlanningPage.tsx
- Change: Add a DismissibleInfo links array (mirror ResourcesPage) to Resource Leveling /portfolio/leveling, Resources & Crew /resources, 4D Schedule /schedule. Make each resource label a button navigating to /resources?resourceId=<id>; make a conflict cell tooltip link to /portfolio/leveling. Add a header action Open Resource Leveling.
- Outcome: A foreman who spots a red over-allocated cell clicks straight to the leveling tool that resolves it, instead of dead-ending on a heatmap.

CONN-02. Resources & Crew never links to the two portfolio tools built from its own data.
- Files: frontend/src/features/resources/ResourcesPage.tsx
- Change: Add Capacity Planning /portfolio/capacity and Resource Leveling /portfolio/leveling to the DismissibleInfo links array. Add a header action on the Assignments tab Portfolio capacity.
- Outcome: A dispatcher managing one project's bookings reaches the all-projects conflict view in one click.

CONN-03. Variation Orders hide their own linked Change Order and contract.
- Files: frontend/src/features/variations/VariationsPage.tsx; verify serialization in backend/app/modules/variations/schemas.py and frontend api.ts.
- Change: In the DetailDrawer Variation Order branch add a Linked records pill row mirroring MoCPage: reference_change_order_id -> navigate('/changeorders'), affected_contract_id -> navigate('/contracts'). Ensure both fields are exposed on the VariationOrder schema/type.
- Outcome: From an approved order the user jumps to the Change Order that drives the budget and the contract it amended, instead of seeing a dead cost figure.

CONN-04. Change Orders never render linked POs, RFIs, or the originating variation.
- Files: frontend/src/features/changeorders/ChangeOrdersPage.tsx; ensure GET /{id} returns linked_po_ids, linked_rfi_ids.
- Change: In DetailView add a Related card mapping linked_po_ids to /procurement chips, linked_rfi_ids to /rfis chips, plus a From variation chip to /variations.
- Outcome: A reviewer approving a budget-committing change order sees and opens every PO, RFI and source variation it ties to.

CONN-05. Sustainability is the most connected carbon page but the least reachable.
- Files: frontend/src/features/boq/BOQListPage.tsx (and the BOQ editor toolbar); read params in frontend/src/features/sustainability/SustainabilityPage.tsx.
- Change: Add a BOQ toolbar action Carbon footprint -> navigate('/sustainability?project_id=&boq_id=') preselecting the active project and BOQ. Add the reciprocal pill in Carbon.
- Outcome: A user looking for carbon from their BOQ finds it from the BOQ in one click rather than landing on Carbon and giving up.

CONN-06. Snapshots is mis-labelled and mis-grouped under Finance.
- Files: frontend/src/app/layout/Sidebar.tsx; locale label nav for the Snapshots entry.
- Change: Move the /dashboards (Snapshots) sidebar entry out of grp_finance into the Controls & BI or Coordination/CAD-BIM group, next to BIM and Data Explorer. Rename the label from Snapshots to Model Snapshots.
- Outcome: A user opening Finance no longer lands on a CAD/BIM parquet tool; the tool sits where its function belongs.

CONN-07. Clash page does not link back to the Coordination Hub or Federations.
- Files: frontend/src/features/clash/ClashDetectionPage.tsx
- Change: Add link pills to the existing DismissibleInfo (storageKey clash): Coordination Hub -> /coordination, BIM Federations -> /bim/federations.
- Outcome: A user deep-linked into /clash gets one-click back to the rollup and to the federated model set being clashed.

CONN-08. Coordination Hub KPI cards are not clickable.
- Files: frontend/src/features/coordination/CoordinationKPICards.tsx (onClick passed from CoordinationHubPage).
- Change: Make cards actionable: Open Clashes / Open Cost Impact -> /clash?project={id} filtered to open, Rule Packs -> /bim/rules, Federations -> /bim/federations. Add hover/focus affordances.
- Outcome: Clicking the big number drills into the list that explains it, the instinctive action people already try.

CONN-09. BIM Quantity Rules apply toast has no way to see the created BOQ positions.
- Files: frontend/src/features/bim/BIMQuantityRulesPage.tsx
- Change: In applyMutation onSuccess add a View in BOQ action to the success toast navigating to /boq for the active project (to the specific boq_id if returned).
- Outcome: After the headline action of the page, the new positions are one click away instead of a manual hunt in /boq.

CONN-10. NCR to its originating inspection is a static badge plus an unfiltered link.
- Files: frontend/src/features/ncr/NCRPage.tsx; add ?highlight handling to InspectionsPage.tsx.
- Change: Make the INS-001 badge and the View Inspection button deep-link to the specific inspection via /projects/{project_id}/inspections?highlight={linked_inspection_id}; auto-scroll/expand the matching row.
- Outcome: From an NCR the user lands on the exact failed inspection, not the full register.

CONN-11. Punch item source badges (From Inspection / NCR / clash) are static text.
- Files: frontend/src/features/punchlist/PunchListPage.tsx; carry source ids in metadata on auto-creation.
- Change: Turn each badge into a button: inspection -> source inspection, NCR -> /ncr filtered, clash -> /clash or the coordination task for clash_result_id.
- Outcome: The inspect-defect-close trail is navigable both ways.

CONN-12. Safety cross-module summary tiles are not clickable.
- Files: frontend/src/features/safety/SafetyPage.tsx
- Change: Make each QualityDashboardSummary tile a link: Pending Inspections -> /inspections, Open NCRs -> /ncr, Open Defects -> /punchlist, Open Incidents -> Safety incidents tab filtered open.
- Outcome: A PM drills from a count straight into the filtered source list.

CONN-13. Markup and Submittal BOQ links render as dead text.
- Files: frontend/src/features/markups/MarkupsPage.tsx; frontend/src/features/submittals/SubmittalsPage.tsx.
- Change: In MarkupDetail render a button when linked_boq_position_id is set -> navigate('/boq?positionId='+id). In Submittals make the linked-BOQ line a clickable pill list per id.
- Outcome: An estimator clicks from a clouded drawing change to the BOQ line it affects.

CONN-14. CDE has no Submit for approval and no Submittals link.
- Files: frontend/src/features/cde/CDEPage.tsx (ContainerRow); frontend/src/features/submittals/SubmittalsPage.tsx (reciprocal pill).
- Change: In ContainerRow expanded actions add Submit for approval -> navigate('/submittals?create=true&container_id='+id). Add a Submittals link pill to CDE DismissibleInfo and a CDE pill to Submittals.
- Outcome: The CDE -> Submittal -> Transmittal document-control loop is fully connected.

CONN-15. Accommodation occupant FK shown as plain name.
- Files: frontend/src/features/accommodation/AccommodationDetailPage.tsx; ensure occupant_contact_id on the decorated booking payload (accommodation/router.py) and the Booking type in api.ts.
- Change: Render occupant as a Link to /contacts/{occupant_contact_id} when present, with plain-text fallback. Same in BookingChargesPanel header.
- Outcome: From a camp booking the operator opens the housed worker's contact record.

CONN-16. Property Development never surfaces linked Accommodation.
- Files: frontend/src/features/property-dev/PropertyDevPage.tsx
- Change: Add an Accommodation pill to the intro DismissibleInfo and a Worker housing link in the Block/Development detail drawer -> /accommodation?block={blockId}.
- Outcome: A developer reaches worker housing for a block in one click, closing the loop the bootstrap flow already implies.

CONN-17. Payroll has no link to the place that owns worker pay rates.
- Files: frontend/src/features/payroll/PayrollPage.tsx
- Change: Add a Resources & Crew pill to the DismissibleInfo links (copy set worker pay rates) -> navigate('/resources').
- Outcome: When a posted batch looks wrong the user jumps to the rate owner, completing hours -> rate -> cost.

CONN-18. Equipment & Fleet does not link back to the crew that operates a machine.
- Files: frontend/src/features/equipment/EquipmentPage.tsx
- Change: In the DetailDrawer header add View assignments -> /resources; add an inline /resources link in the Utilization blocked banner.
- Outcome: From a machine the user reaches its resource assignments, making the existing one-directional link bidirectional.

CONN-19. Asset Register and Equipment & Fleet are two asset registers with no cross-link.
- Files: frontend/src/app/layout/Sidebar.tsx (rename nav.assets to Building Assets (FM), with i18n sweep); frontend/src/features/bim/AssetsPage.tsx and frontend/src/features/equipment/EquipmentPage.tsx (reciprocal pills).
- Change: Rename the Asset Register sidebar label; add an Equipment & Fleet pill on AssetsPage and a Building Assets pill on EquipmentPage with disambiguating copy.
- Outcome: Users can tell which register to open for plant vs installed equipment and cross over when needed.

CONN-20. RFI and Submittals, the twin design-team workflows, do not cross-link.
- Files: frontend/src/features/rfi/RFIPage.tsx; frontend/src/features/submittals/SubmittalsPage.tsx.
- Change: Add a Submittals pill to RFI intro DismissibleInfo and an RFI pill to Submittals intro DismissibleInfo.
- Outcome: PMs move between the question and approval workflows in one click.

CONN-21. Correspondence parties shown as plain text instead of contact links.
- Files: frontend/src/features/correspondence/CorrespondencePage.tsx
- Change: In CorrespondenceRow render From/To as deep links to /contacts (open contact drawer via state) when the value is a contact id; reuse ContactSearchInput resolution for display names.
- Outcome: A PM reading a notice opens the sender's contact card to check status and prior correspondence.

CONN-22. Project Controls does not link to its sibling BI Dashboards over the same KPI registry.
- Files: frontend/src/features/project-controls/ProjectControlsPage.tsx
- Change: Add a BI Dashboards pill to DismissibleInfo; add a Trend & alerts action in the DrillDrawer header -> /bi-dashboards.
- Outcome: From a red point-in-time tile the executive pivots to the trend and alert rules for the same KPI.

CONN-23. BI Dashboards never points to Project Controls.
- Files: frontend/src/features/bi-dashboards/BIDashboardsPage.tsx
- Change: Add a Project Controls pill to the DismissibleInfo links array.
- Outcome: The two sibling executive surfaces read as one connected loop.

CONN-24. Takt cold-start dead-ends with no way to create a master schedule.
- Files: frontend/src/features/takt/TaktSchedulePage.tsx
- Change: In the no-master EmptyState add Go to Advanced Schedule -> /schedule-advanced (ideally inline createMasterSchedule).
- Outcome: A user can actually reach the line-of-balance from a cold start.

CONN-25. Document Templates per-development default is gated behind pasting a raw UUID.
- Files: frontend/src/features/property-dev/settings/DocumentTemplatesSettingsPage.tsx
- Change: Replace the activeDevId free-text input with a Development select populated from listDevelopments (reuse the DashboardsHub dropdown pattern), storing the id in the same localStorage key.
- Outcome: Per-development default templates become reachable in two clicks instead of never.

CONN-26. Inspection follow-up toasts do not deep-link to the created records.
- Files: frontend/src/features/inspections/InspectionsPage.tsx; add ?highlight to PunchListPage.
- Change: Add an Open punch item action (?highlight=punch_item_id) to createDefectMut onSuccess; change the NCR toast to deep-link to the created NCR via ncr_id.
- Outcome: After raising a punch item or NCR from a failed inspection the user opens it directly.

### Tier 2: medium (worth doing, moderate effort)

CONN-27. Clash cost-impact money cell to BOQ positions (popover with per-position links; gate on confidence high). Files: frontend/src/features/clash/ClashCostImpactColumn.tsx; add boq_id to AffectedPosition in backend/app/modules/clash_cost_impact/schemas.py and service if missing.

CONN-28. Federation Run clash detection action seeding member model ids; extend clash deep-link to accept ?models=id1,id2. Files: frontend/src/features/bim/FederationsPage.tsx; ClashDetectionPage model picker.

CONN-29. EIR matrix row BOQ indicator chip linking to /boq; surface linked_position_id on the row payload. Files: frontend/src/features/requirements/RequirementsMatrixPage.tsx.

CONN-30. EIR cell Open deliverable link by deliverable type (model -> /bim, drawing -> /markups or /files, schedule -> /schedule, etc.). Files: RequirementsMatrixPage.tsx CellEditor.

CONN-31. Last Planner commitment task picker replacing the UUID input (fetchTasks by project); same for constraints. Files: frontend/src/features/schedule-advanced/ScheduleAdvancedPage.tsx.

CONN-32. Constraint create flow with a New constraint modal and task picker; fix the empty-state copy. Files: ScheduleAdvancedPage.tsx ConstraintsTab.

CONN-33. 4D Schedule Gantt row View in BOQ pill when boq_position_ids present; expose the field on GanttData. Files: frontend/src/features/schedule/SchedulePage.tsx.

CONN-34. BOQ -> Build schedule from this BOQ action pre-opening Generate-from-BOQ. Files: frontend/src/features/boq/BOQListPage.tsx.

CONN-35. Resource Leveling Apply control on suggestions (PATCH assignment shift/spread) with confirm and query invalidation. Files: frontend/src/features/portfolio/ResourceLevelingPage.tsx.

CONN-36. Resource Leveling project links in drawer/bookings and a View in 4D Schedule link; surface project_id. Files: ResourceLevelingPage.tsx.

CONN-37. Resource Leveling DismissibleInfo to Capacity/Resources/Schedule; add capacity/leveling keys to PlanningCrossLinks. Files: ResourceLevelingPage.tsx, shared PlanningCrossLinks.

CONN-38. 5D linked-record UUIDs turned into navigable links with human labels. Files: frontend/src/features/costmodel/CostLineRollupDrawer.tsx.

CONN-39. Bid Management invite from Subcontractor Directory with prequal traffic-light. Files: frontend/src/features/bid-management/BidManagementPage.tsx.

CONN-40. Tendering award to Formalise as Contract plus Contracts pill in DismissibleInfo. Files: frontend/src/features/tendering/TenderingPage.tsx.

CONN-41. Tendering AddBidDialog Select from Subcontractors. Files: TenderingPage.tsx.

CONN-42. Contracts counterparty resolved to firm name with deep link. Files: frontend/src/features/contracts/ContractsPage.tsx ContractDetailDrawer.

CONN-43. Subcontractor agreement to Contracts cross-link; deep-link the Related chips with sub pre-selected. Files: frontend/src/features/subcontractors/SubcontractorsPage.tsx.

CONN-44. Subcontractor ratings deep links per dimension to QA-NCR and HSE/Safety filtered by sub. Files: SubcontractorsPage.tsx.

CONN-45. Change Order line items Pick from BOQ pre-filling original_quantity/rate. Files: frontend/src/features/changeorders/ChangeOrdersPage.tsx AddItemDialog.

CONN-46. Supplier Catalogs demote PRs/POs/3-Way Match dead tabs to one banner. Files: frontend/src/features/supplier-catalogs/SupplierCatalogsPage.tsx.

CONN-47. Supplier Catalogs Create PO from PriceComparisonModal vendor card prefilling /procurement. Files: SupplierCatalogsPage.tsx.

CONN-48. Three change pipelines: consistent intros, MoC pill in Variations and Change Orders DismissibleInfo. Files: VariationsPage.tsx, ChangeOrdersPage.tsx.

CONN-49. Daily Diary entry source picker and deep links for incident/inspection summaries (source_module/source_ref). Files: frontend/src/features/daily-diary/DailyDiaryPage.tsx.

CONN-50. Daily Diary to Payroll and Field Reports pills; Open today's field report header action. Files: DailyDiaryPage.tsx.

CONN-51. Service technician/customer pickers and deep links; surface customer in contract drawer. Files: frontend/src/features/service/ServicePage.tsx.

CONN-52. Sub Portal rename to Client & Partner Portal across en.ts and 26 locales; align portal_payments. Files: frontend/src/app/locales/*; Sidebar.

CONN-53. Portal Grant Access ticket/document pickers and deep links in Access Rules and Audit Log. Files: frontend/src/features/portal/PortalPage.tsx.

CONN-54. Subcontractors Invite to portal action navigating to /portal Invite modal prefilled. Files: SubcontractorsPage.tsx; PortalPage.

CONN-55. Resources assignment project/task columns with links; surface project_name. Files: frontend/src/features/resources/ResourcesPage.tsx.

CONN-56. Payroll worker cell to resource drawer; surface resource_id on the payroll response. Files: frontend/src/features/payroll/PayrollPage.tsx.

CONN-57. Punch pin on drawing in AddPunchModal (document_id/page/x/y) and a link to reopen the drawing. Files: frontend/src/features/punchlist/PunchListPage.tsx.

CONN-58. Validation Raise NCR action on error rows pre-filling from the finding. Files: frontend/src/features/validation/* ResultRow.

CONN-59. Closeout readiness chips for punch_closure and final_inspection_cert with deep links and Build warn. Files: frontend/src/features/closeout/CloseoutPage.tsx.

CONN-60. Carbon Add from BOQ button calling assign-boq-position; wire assignBoqPosition in carbon/api.ts. Files: frontend/src/features/carbon/CarbonPage.tsx, carbon/api.ts.

CONN-61. HSE incident picker in Open Investigation modal plus Investigate row action in Safety. Files: frontend/src/features/hse/HSEAdvancedPage.tsx, SafetyPage.tsx.

CONN-62. Audit finding Create CAPA action pre-filling source_type/source_id. Files: HSEAdvancedPage.tsx.

CONN-63. CAPA dependent source_id picker and source deep link; reconcile NCR copy with enum. Files: HSEAdvancedPage.tsx.

CONN-64. QMS inspection fail -> Raise NCR button pre-filling linked_inspection_id. Files: frontend/src/features/qms/QMSPage.tsx.

CONN-65. Meeting attendee/chair pickers (UserSearchInput/ContactSearchInput) with links. Files: frontend/src/features/meetings/MeetingsPage.tsx.

CONN-66. Photo Raise from photo actions to punch/NCR/safety with photo_id prefill; diary/punch pills. Files: frontend/src/features/photos/PhotoGalleryPage.tsx.

CONN-67. Markup measurement Use as quantity deep link to /takeoff. Files: frontend/src/features/markups/MarkupsPage.tsx.

CONN-68. Photo timeline Open day diary link and diary/progress pills. Files: PhotoGalleryPage.tsx.

CONN-69. Accommodation charge Invoice in Finance action and View invoice deep link. Files: AccommodationDetailPage.tsx.

CONN-70. Accommodation PropDev block and BIM model pickers replacing UUID inputs. Files: AccommodationDetailPage.tsx SettingsTab.

CONN-71. PropDev related-record scoped deep links (buyer/plot params honoured by targets). Files: PropertyDevPage.tsx.

CONN-72. Contacts to PropDev specific lead/buyer deep links (tab + id params read on mount). Files: frontend/src/features/contacts/ContactsPage.tsx, PropertyDevPage.tsx.

CONN-73. Snapshots to /match-elements and /takeoff deep links; surface snapshot baseline on those pages. Files: frontend/src/features/dashboards/SnapshotsPage.tsx.

CONN-74. Reporting Finance tab Open in Finance header action and per-card drills. Files: frontend/src/features/reporting/ReportingPage.tsx FinanceDashboardView.

CONN-75. Finance invoice From claim and cost-line deep links. Files: frontend/src/features/finance/FinancePage.tsx InvoicesTab.

CONN-76. Analytics Finance link and per-row deep link to /projects/{id}/finance. Files: frontend/src/features/analytics/AnalyticsPage.tsx.

CONN-77. Project Controls 4 dead drill tiles: register providers or mark non-drillable. Files: backend/app/modules/bi_dashboards/kpis.py, backend/app/modules/project_controls/service.py, frontend ControlsTile.tsx.

CONN-78. Controls cost baseline from BOQ: _evm_snapshot_for_project BOQ fallback and a View BOQ baseline drill link. Files: backend/app/modules/bi_dashboards/kpis.py; ProjectControlsPage DrillDrawer.

CONN-79. BI KPI source chips from source_modules and a View source records drill. Files: frontend/src/features/bi-dashboards/* KpiLibraryCard.

CONN-80. AI Chat read renderers deep links (projects, BOQ, schedule, validation, risk) via a shared deepLink field. Files: frontend/src/features/chat/* renderers, DataRightPanel.tsx.

CONN-81. AI Advisor source code to /costs and Add to BOQ / Use in Quick Estimate. Files: frontend/src/features/advisor/AdvisorPage.tsx.

CONN-82. AI tools cross-link strip across AgentsPage, AdvisorPage, chat empty state. Files: AgentsPage.tsx, AdvisorPage.tsx, DataPanelEmpty.tsx.

CONN-83. Estimating to AI affordances (Draft positions with AI, Ask the Cost Advisor, Benchmark this rate) on BOQ editor and Costs. Files: BOQEditorPage.tsx, costs pages.

### Tier 3: larger reworks (need a source-of-truth decision or substantial build)

CONN-84. Clash promote to RFI/NCR with a back-reference FK on the RFI model. Files: ClashDetectionPage.tsx; RFI model migration.

CONN-85. Takt import from BOQ sections and BIM levels/zones. Files: TaktSchedulePage.tsx import modals.

CONN-86. Tasks committed/constrained badge requiring the tasks endpoint to flag commitment/constraint references. Files: TasksPage.tsx; tasks list endpoint or schedule lookup.

CONN-87. Bid Management scope from BOQ bulk import. Files: BidManagementPage.tsx AddScopeLineForm.

CONN-88. Bid Management award to pre-seeded contract-create flow. Files: BidManagementPage.tsx; CreateContractModal seed.

CONN-89. Contract Schedule of Values source from BOQ or awarded tender. Files: ContractsPage.tsx CreateContractModal.

CONN-90. Bid Management vs Tendering convergence (or at least a documented decision helper). Files: both pages.

CONN-91. Procurement PO line from BOQ via cost_line_id; expose requisition endpoints or wire cost_line_id onto PO items. Files: backend/app/modules/procurement/router.py, ProcurementPage.tsx.

CONN-92. Daily Diary vs Field Reports: pick one canonical daily record (merge or demote); reconcile workforce headcounts. Files: DailyDiaryPage.tsx, FieldReportsPage.tsx; stores.

CONN-93. Service vs Equipment asset register: choose system of record; let Service reference an Equipment asset id. Files: ServicePage.tsx, equipment models.

CONN-94. Equipment rental UI (Deployment tab) backed by new listRentals/createRental/returnRental in equipment api; Project column on the asset list. Files: frontend/src/features/equipment/EquipmentPage.tsx, api.ts.

CONN-95. Two quality systems (Inspections/NCR/Punch vs QMS): pick one source of truth or merge; interim banners. Files: qms and standalone modules backend + frontend.

CONN-96. Carbon vs Sustainability: position as one chain or fold Sustainability into Carbon as an Analyse BOQ tab. Files: CarbonPage.tsx, SustainabilityPage.tsx.

CONN-97. Contacts communication usages (correspondence, RFI ball-in-court) in the contacts bridge. Files: contacts bridge service, ContactDetailPage.

CONN-98. House type to BOQ build-cost tie with a house_type_id filter. Files: HouseTypeSettingsPage, BOQ.

CONN-99. AI Chat takeoff tool (search_takeoff_quantities/get_match_results) with deep-linking renderer. Files: backend/app/modules/erp_chat/tools.py, chat renderers.

### Small cleanups (low impact, small effort, do alongside)

CONN-100. Delete or render the 7 unused PipelineBanner.tsx copies. Files: frontend/src/features/*/PipelineBanner.tsx.

CONN-101. BIM Rules naming: rename sidebar to BIM Requirements (Compliance) or add a second BIM Quantity Rules entry. Files: Sidebar.tsx.

CONN-102. Inspection WBS picker tie to schedule activity. Files: InspectionsPage.tsx CreateInspectionModal.

CONN-103. Reports to source modules Open source links. Files: ReportsPage.tsx.

CONN-104. Reporting vs Reports overlap: make Reports the single home for generated documents; Reporting Reports tab becomes a redirect card. Files: ReportingPage.tsx.

CONN-105. BI drill deep link parity by factoring _deep_link out of project_controls/service.py into a shared helper. Files: backend project_controls and bi_dashboards.

CONN-106. AI Chat admin observability link in ChatTopBar (admin-gated). Files: ChatTopBar.tsx.

CONN-107. Agent vs chat BOQ target: route ApplyActionButton to /boq/{boqId}. Files: ApplyActionButton.tsx.

CONN-108. Move /ai-estimate into the Automation & AI group (or duplicate). Files: Sidebar.tsx.

CONN-109. Transmittal to submittal row-level backlink badge. Files: TransmittalsPage.tsx.

CONN-110. Meeting action item Raise RFI action and RFI pill. Files: MeetingsPage.tsx.

CONN-111. Resource request Size from BOQ pill. Files: ResourcesPage.tsx Requests tab.

## Counts

- Total findings: 80.
- Tier 1 (high impact, small effort): 26 (CONN-01 to CONN-26).
- Tier 2 (medium): 57 items spanning CONN-27 to CONN-111, of which the medium-effort core is CONN-27 to CONN-83.
- Tier 3 (larger reworks): CONN-84 to CONN-99.
- Source-of-truth decisions required (cannot be closed by a link): two quality systems (CONN-95), Carbon vs Sustainability (CONN-96), Daily Diary vs Field Reports (CONN-92), Service vs Equipment assets (CONN-93), Bid vs Tendering (CONN-90), three change pipelines (CONN-48 interim, full convergence longer term).
