# 4D-5D Implementation Plan — OpenEstimate

Based on: "ERP Excel logic for building a 4D-5D Workflow" (data:driven construction.io)

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    PROJECT ESTIMATE (BOQ)                        │
│  Position | Amount | Unit | Unit Price | Total | Schedule Link  │
│  ────────────────────────────────────────────────────────────── │
│  Uses assemblies OR direct cost items                           │
│  Quantities from: manual entry / QTO (3D) / AI takeoff          │
│  → Output: 5D cost model                                        │
└──────────────┬──────────────────────────────────┬───────────────┘
               │                                  │
               ▼                                  ▼
┌──────────────────────────┐    ┌──────────────────────────────────┐
│  CALCULATION / ASSEMBLY  │    │         4D SCHEDULING            │
│  (Sborny Rascenka)       │    │                                  │
│                          │    │  Gantt chart                     │
│  Code | Desc | Factor    │    │  Activity → BOQ position links   │
│  Qty  | Unit | Cost      │    │  Resource allocation             │
│  Total | Work Order      │    │  Critical path                   │
│                          │    │  Progress tracking               │
│  Combines DB items       │    │                                  │
│  with multipliers        │    │  → Output: construction schedule │
└──────────┬───────────────┘    └──────────────────┬───────────────┘
           │                                       │
           ▼                                       ▼
┌──────────────────────────┐    ┌──────────────────────────────────┐
│       DATABASE           │    │         5D COST MODEL            │
│                          │    │                                  │
│  Code | Desc | Unit      │    │  S-curve (planned vs actual)     │
│  Unit Cost | Source      │    │  Cash flow projection            │
│                          │    │  Cost forecast                   │
│  CWICR, RSMeans, BKI     │    │  Earned value analysis           │
│  55,000+ items           │    │  Budget tracking                 │
└──────────────────────────┘    └──────────────────────────────────┘
```

---

## Phase A: Assemblies / Calculations (CRITICAL — the missing middle layer)

### What it is
An Assembly (Calculation) is a "recipe" — a composite cost item built from
multiple Database items, each with a factor/multiplier.

Example: **"Reinforced Concrete Wall C30/37, d=25cm"**
```
Code: ASM-332-001
Components:
  C-332-001  Concrete C30/37 supply + place    × 0.25 m3/m2  = €87.50/m2
  C-333-002  Reinforcement BSt 500 S           × 25 kg/m2    = €46.25/m2
  C-345-001  Formwork both sides               × 2.0 m2/m2   = €37.00/m2
  LABOR-001  Concrete worker (Betonbauer)      × 1.5 h/m2    = €67.50/m2
  ─────────────────────────────────────────────────────────
  Assembly rate per m2:                                       = €238.25/m2
```

### Data model
```
Assembly:
  - id: UUID
  - code: str (ASM-XXX-NNN)
  - name: str
  - description: str
  - unit: str (m2, m3, pcs...)
  - category: str (concrete, masonry, steel, MEP...)
  - classification: JSON {din276: "332", nrm: "2.6.1"}
  - components: → AssemblyComponent[]
  - total_rate: Decimal (computed from components)
  - regional_factors: JSON {Berlin: 1.05, München: 1.12}
  - bid_factor: Decimal (default 1.0 — markup/discount)
  - is_template: bool (reusable across projects)
  - project_id: UUID | null (null = global template)

AssemblyComponent:
  - id: UUID
  - assembly_id: FK
  - cost_item_id: FK → CostItem (from Database)
  - description_override: str | null
  - factor: Decimal (multiplier — e.g., 0.25 m3 per m2)
  - quantity: Decimal
  - unit: str
  - unit_cost: Decimal (from CostItem, or override)
  - total: Decimal (computed: factor × quantity × unit_cost)
  - sort_order: int
```

### Frontend
- Assembly editor: table of components, add from cost database
- Factor calculator: input factor per component
- Live total recalculation
- "Apply to BOQ" — creates position with assembly rate
- Assembly library browser (templates)

### Endpoints
- POST /assemblies/ — create assembly
- GET /assemblies/ — list/search assemblies
- GET /assemblies/{id} — get with components
- POST /assemblies/{id}/components — add component
- PATCH /assemblies/{id}/components/{cid} — update factor
- POST /assemblies/{id}/apply-to-boq — create BOQ position from assembly

---

## Phase B: 4D Scheduling (Time Dimension)

### What it is
Link BOQ positions to a construction schedule. Each position gets:
- Start date, end date, duration
- Predecessor/successor relationships
- Resource assignments
- Progress tracking (% complete)

### Data model
```
Schedule:
  - id: UUID
  - project_id: FK
  - name: str (e.g., "Bauzeitenplan")
  - start_date: date
  - end_date: date
  - status: str (draft, active, completed)

Activity:
  - id: UUID
  - schedule_id: FK
  - parent_id: FK | null (for WBS hierarchy)
  - name: str
  - description: str
  - wbs_code: str (e.g., "1.2.3")
  - start_date: date
  - end_date: date
  - duration_days: int
  - progress_pct: Decimal (0-100)
  - status: str (not_started, in_progress, completed, delayed)
  - dependencies: JSON [{activity_id, type: "FS"|"SS"|"FF"|"SF", lag_days}]
  - resources: JSON [{resource_id, allocation_pct}]
  - boq_position_ids: list[UUID] (links to BOQ positions)
  - color: str (for Gantt display)
  - sort_order: int

WorkOrder:
  - id: UUID
  - activity_id: FK
  - assembly_id: FK | null
  - boq_position_id: FK | null
  - assigned_to: str (subcontractor, crew)
  - planned_start: date
  - planned_end: date
  - actual_start: date | null
  - actual_end: date | null
  - planned_cost: Decimal
  - actual_cost: Decimal
  - status: str (planned, issued, in_progress, completed)

Resource:
  - id: UUID
  - project_id: FK
  - name: str (e.g., "Crane 1", "Concrete Crew A")
  - type: str (labor, equipment, material, subcontractor)
  - unit: str (h, day, week)
  - rate: Decimal (cost per unit)
  - availability: JSON (calendar/capacity)
```

### Frontend
- **Gantt Chart** — interactive timeline (drag to reschedule)
  - Library: @dhx/gantt or custom with D3.js
  - Zoom levels: day/week/month
  - Critical path highlighting
  - Dependency arrows
  - Progress bars
- **Activity ↔ BOQ linking** — drag position onto timeline
- **Resource view** — who works when, capacity planning
- **Work order management** — issue, track, close

### Endpoints
- CRUD /schedules/, /activities/, /work-orders/, /resources/
- POST /activities/{id}/link-position — link BOQ position to activity
- GET /schedules/{id}/gantt — structured data for Gantt rendering
- GET /schedules/{id}/critical-path — compute critical path
- PATCH /activities/{id}/progress — update % complete

---

## Phase C: 5D Cost Model (Cost + Time Integration)

### What it is
Combine 3D (geometry/quantities) + 4D (schedule) + 5D (cost) into
a unified model for:
- Cash flow projection (when money is spent)
- S-curves (planned vs earned vs actual value)
- Earned Value Analysis (EVM)
- Budget tracking & forecasting
- Cost reporting by time period

### Data model
```
CostSnapshot:
  - id: UUID
  - project_id: FK
  - period: date (monthly snapshot)
  - planned_cost: Decimal (BCWS — Budgeted Cost of Work Scheduled)
  - earned_value: Decimal (BCWP — Budgeted Cost of Work Performed)
  - actual_cost: Decimal (ACWP — Actual Cost of Work Performed)
  - forecast_at_completion: Decimal (EAC)
  - variance: Decimal (planned - actual)
  - spi: Decimal (Schedule Performance Index)
  - cpi: Decimal (Cost Performance Index)

BudgetLine:
  - id: UUID
  - project_id: FK
  - boq_position_id: FK | null
  - activity_id: FK | null
  - category: str (material, labor, equipment, subcontractor, overhead)
  - planned_amount: Decimal
  - committed_amount: Decimal (contracts signed)
  - actual_amount: Decimal (invoices paid)
  - forecast_amount: Decimal
  - period_start: date
  - period_end: date
```

### Frontend
- **Dashboard 5D** — main cost management view
  - S-curve chart (Planned/Earned/Actual over time)
  - Cash flow bar chart (monthly spend)
  - KPIs: SPI, CPI, EAC, VAC
  - Budget vs Actual summary table
- **Cost breakdown** — by KG/NRM/Division, by time period
- **Forecast** — "what if" scenario modeling
  - Adjust schedule → see cost impact
  - Adjust rates → see budget impact
- **Reports** — PDF export of 5D status

### Endpoints
- GET /projects/{id}/5d/dashboard — aggregated 5D metrics
- GET /projects/{id}/5d/s-curve — time series for S-curve
- GET /projects/{id}/5d/cash-flow — monthly cash flow
- GET /projects/{id}/5d/budget-tracking — budget vs actual by category
- POST /projects/{id}/5d/snapshot — create monthly snapshot
- GET /projects/{id}/5d/forecast — EAC, ETC, VAC calculations

---

## Phase D: QTO from 3D Model

### What it is
Quantity Takeoff from BIM/3D model — extract quantities automatically
and link to BOQ positions.

### Data model
```
QTOSession:
  - id: UUID
  - project_id: FK
  - boq_id: FK
  - source_file: str (IFC/RVT/DWG filename)
  - status: str (processing, ready, linked)
  - elements_count: int
  - linked_count: int

QTOElement:
  - id: UUID
  - session_id: FK
  - element_id: str (from CAD canonical format)
  - category: str (wall, floor, column...)
  - description: str (auto-generated from properties)
  - quantities: JSON {area: 37.5, volume: 9.0, length: 12.5}
  - classification: JSON {din276: "330"}
  - boq_position_id: FK | null (linked position)
  - status: str (unlinked, linked, excluded)
```

### Frontend
- 3D viewer (Three.js) with element selection
- Split view: 3D left, BOQ right
- Drag element → create/link position
- Auto-classify elements → suggest cost codes
- Quantity comparison: model vs BOQ

---

## Implementation Priority

### Immediate (next sprint):
1. **Assemblies module** — the "Calculation" layer is the core missing piece
2. **Assembly editor UI** — build calculations from cost database

### Short-term (2-3 weeks):
3. **4D Schedule** — basic Gantt chart with activity-BOQ linking
4. **Work Orders** — link assemblies to schedule activities
5. **Resource management** — basic resource types and rates

### Medium-term (4-6 weeks):
6. **5D Dashboard** — S-curves, cash flow, EVM
7. **Budget tracking** — planned vs actual vs forecast
8. **Monthly snapshots** — automated cost reporting

### Later (Phase 2-3):
9. **QTO from 3D** — CAD import + auto-quantity extraction
10. **AI classification** — auto-assign cost codes from model elements
11. **Real-time collaboration** — multiplayer editing (Yjs)
