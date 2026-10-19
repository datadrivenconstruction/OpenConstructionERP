# Schedule from estimate (4D/5D from the BOQ)

Status: P0 in progress on `wip/schedule-from-estimate-p0-20261019`. P1 and P2 are planned, not built.

The generator turns a priced bill of quantities into a CPM schedule: one summary per bill
section, one task per priced position, durations from labour norms, crews fitted to a window,
regional calendars. A person always previews the plan and confirms it. Nothing in this design
changes that: the generator proposes, with a confidence per activity, and the human decides.

## 1. Measurements (what the data actually carries)

Measured 2026-10-19 on `integration/18.7.0` (`92240c08f`). The numbers decide what we promise.

**Demo projects.** The seeding code was run without a database over all 84 demo templates
(5 core plus 79 pack demos), 8,109 priced positions.

| Field on the position | Positions | Share of cost |
|---|---|---|
| `metadata.labor_hours` > 0 | 0 | 0 % |
| `metadata.workers_per_unit` > 0 | 0 | 0 % |
| hourly labour rows in `metadata.resources` (`type=labor`, `unit=hr`) | 8,109 | 100 % |
| hourly machine rows (`type=equipment`, `unit=hr`) | 8,103 | about 100 % (one template 80.8 %) |

Every demo duration therefore comes from the `resource_sum` path. These hours are synthetic:
`_make_resources` (`core/demo_projects.py`) derives them from the price share and a euro hourly
rate and tags each row `demo_provenance.productivity_verified = false`. The generator now reads
that tag and lowers the confidence of a duration built on it (section 4.3). A demo plan reads
"medium" for that reason, and it should until the demo bills carry real norms (P2, item 14).

**CWICR cost database** (parquet files, counted per rate code):

| Base | Items | Labour hours > 0 | People per unit > 0 | Machine rows |
|---|---|---|---|---|
| USA, UK, AU, VI (each) | 55,719 | 55,558 (99.7 %) | 55,558 | about 47,100 (94 % of cost) |
| CA, RO (each) | 55,719 | 55,558 | 55,558 | about 47,150 |
| TR | 22,704 | 11,866 (52 %) | 11,866 | 4,113 (78 % of cost) |
| IT (Tuscany) | 5,836 | 5,231 (90 %) | 0 | 3,366 (47 % of cost) |
| ZH | 11,312 | 11,284 | 0 | 5,840, counted in machine shifts, not hours |

Three facts from that measurement shape P0:

1. Labour hours are per **rate unit** ("100 CY", "1000 CY"), and the BOQ position takes over
   that unit when an item is applied, so `quantity x labor_hours` holds while the quantity stays
   in rate units.
2. `count_total_people_per_unit` (written to the position as `workers_per_unit`) is **not a crew
   size**. Its ratio to labour hours has a median of 1.01, and about 23,000 USA items have a
   value above 50. Read as a crew, it makes every CWICR duration about `quantity / 8` days. P0
   only accepts it as a crew when it lies in the range a person may type (1 to 20); a larger
   value is ignored and the generator assumes a crew as it does for a bill without one. Whether
   the field should be read at all is an open question for the cost-data owner (section 7).
3. Machine hours exist on 85 % of the big bases, but only as resource rows: there is no summary
   column, and the importer copies no machine-hours key onto the position. In the USA base every
   plant row is followed by an operator row and often an electricity row with the same hours,
   all typed `equipment`. A sum would count one machine hour up to three times. P0 therefore takes
   the **largest** machine row per unit, not the sum (section 4.2).

## 2. The pipeline

```
estimate (BOQ + norms) ──┐
BIM (elements, storeys) ─┼─> WBS / LBS -> activities -> durations -> logic -> calendar
                         │     -> resource + cost loading -> preview (confidence, validation)
                         └─> human confirms -> baseline -> PV / cash flow -> EV / forecast
```

| Step | Today (after P0) | Later |
|---|---|---|
| WBS | bill sections become summaries | grouping by classification or trade (P1) |
| Locations | none | storeys from the model, typed storeys, or none (P1) |
| Activities | one per priced position | (position or trade group) x location (P1) |
| Durations | labour norm, labour rows, unit table, cost share; **machine hours** (P0) | shift settings, productivity factors (P1) |
| Logic | bill order, crews FS, top sections SS 50 % | logic templates by classification (P1) |
| Calendar | regional weeks with holidays | trade calendars from the template (P1) |
| Resources | **labour and machine resources written per task** (P0) | levelling by trade pool in the preview (P1) |
| Cost loading | **`cost_planned` from the position totals** (P0) | markups spread pro rata, cash curve with payment lag (P2) |
| Preview | counts, window fit, notes; **confidence, validation findings, cost line** (P0) | wizard with live LOB preview (P1) |
| Baseline | baselines exist | "save as baseline 0" on confirm (P1) |
| Change propagation | none | stale flag from `boq.position.*` events, accept panel (P1) |

## 3. P0 scope

P0 delivers items 1, 2, 3 and 5 of the analysis plus the measurement above. The stale flag
(analysis item 4 of P0) moves to P1 with the review panel it needs.

### 3.1 Cost loading

- Every generated **task** gets `cost_planned` = the position's `total`, as an exact decimal
  (never through a float). A lump sum that spans the works carries its total too; the S-curve
  spreads it linearly over its span.
- Summaries and milestones keep `cost_planned = None`. BAC is the plain sum over activities
  (`evm_math`, `service_4d`), so a rolled-up summary would count its children twice.
- Markups (overheads, profit, VAT) are not loaded in P0. The schedule's BAC equals the sum of
  the position totals, the direct cost. The preview says so.
- Rule `schedule_5d.cost_reconciliation` (ERROR): the sum of task `cost_planned` differs from
  the sum of priced position totals by more than one cent. It fires only when positions are
  left out of the plan, and `boq_coverage` then names them.

### 3.2 Durations, resources and machine hours

Per task the generator now works out an **effort**: labour hours in total, the crew, machine
hours in total and the machine sets.

- Labour: unchanged paths (`labor_hours` x quantity, else hourly labour rows), with the crew
  rule of 1.2 above for `workers_per_unit`.
- Machine: the largest hourly machine row per unit (rows of type `equipment`, `machine`,
  `machinery` or `plant` in an hour unit, including `machine hours`, `h-maş.`, `giờ máy`, `sa`),
  times the quantity. Machine shifts (机班) are not hours and are not read.
- Machine-driven duration = machine hours / (machine sets x hours per day), with the same
  mobilisation factor (1.1) and week conversion as labour. A position given parallel gangs gets
  one machine set per gang.
- **Duration = max(labour-driven, machine-driven).** When the machine wins, the source is
  `machine_hours` and the preview says so ("set by machine hours, longer than the labour").
  A position with machine rows and no labour data takes the machine duration instead of the
  unit table.
- `Activity.resources` gets up to two rows, in the shape resource levelling already reads
  (`name`, `count`):
  `{"name": "Labour", "type": "labor", "count": crew, "hours": total, "unit": "h", "source": "boq_generation"}`
  and `{"name": "Machines", "type": "equipment", "count": sets, "hours": total, ...}`. The names
  come from the generation catalogue in the request language, so the levelling tab can limit
  "Labour" to, say, 40 people across the plan.
- Task metadata keeps `labor_hours_total`, `machine_hours_total` and `norm_days`, the working
  days the norms imply at the crew the plan uses, before any shortening.

### 3.3 Validation in the preview

The preview runs two rule sets over the plan it would write, through the validation engine,
and returns the failed results with their counts. The same summary is stored on the schedule
under `metadata.boq_generation.validation` when the plan is confirmed.

- `schedule_quality` (existing DCMA-style rules: open ends, negative and excessive lag, hard
  constraints, negative and high float, missing duration).
- `schedule_5d` (new):
  - `schedule_5d.boq_coverage` (WARNING): a priced position (total not zero) that no task
    carries in `boq_position_ids`. One finding per position, with its ordinal and text.
  - `schedule_5d.cost_reconciliation` (ERROR): see 3.1.
  - `schedule_5d.duration_vs_norm` (WARNING): a task whose duration is more than twice or less
    than half of `metadata.norm_days`, and more than two working days away from it. On a fresh
    plan this catches unit-table guesses held down by the price and heavy shortening; on a plan
    edited by hand it catches durations that drifted from the estimate.

Findings never block confirming. They are shown before the confirm button, and the person
decides. Messages are translated (`core/validation/messages/*.json`).

### 3.4 Confidence

A number from 0 to 1 per task and per plan. It is not a probability; it says how much of the
plan is backed by data rather than by a rule of thumb.

`score = 0.5 x duration + 0.3 x logic + 0.2 x breakdown`

| Factor | Source | Value |
|---|---|---|
| duration | `labor_hours` (bill norm) | 0.9 |
| | `machine_hours` (machine norm bound it) | 0.85 |
| | `resource_sum` (hourly labour rows) | 0.8 |
| | `spans_works` (lump sum over the works) | 0.6 |
| | `estimated_fallback` (unit table) | 0.4, or 0.3 when held down by the price |
| | `cost_proportional` | 0.2 |
| | `default_minimum` | 0.1 |
| | norm rows tagged `productivity_verified = false` | at most 0.5 |
| | durations shortened to fit (`compressed_pct`) | x (0.5 + 0.5 x pct / 100) |
| logic | bill order (the only source in P0) | 0.4 |
| | lump sum spanning the works by rule | 0.7 |
| | logic template (P1) | 0.8 |
| breakdown | whole position, one activity | 0.7 |
| | lump sum (no quantity to split) | 0.5 |
| | split by model storeys (P1) | 0.9 |
| | split evenly over typed storeys (P1) | 0.5 |

Bands: **high** at 0.7 and above, **medium** from 0.5, **low** below 0.5. The plan score is the
mean of the task scores weighted by the position total (a plain mean when nothing is priced).

So a position with a real CWICR norm scores 0.71 (high), one on labour rows 0.66, a demo
position on synthetic rows 0.51, a unit-table guess 0.46 (low), a lump sum by cost share 0.32.
The ceiling is low on purpose: bill-order logic is the weakest part of today's plan, and P1
logic templates are what lift it.

Where it shows: the activity's `metadata.confidence` (`score`, `band`, the three factors and
reason codes), a coloured badge on the Gantt row with the reasons in its tooltip (low ones in
the warning colour), and in the preview the plan score, the band counts and a list of the
low-confidence positions to review first, cheapest fix first (the most expensive position
first). Confirming stays a separate, explicit step.

### 3.5 Test plan

Unit (pure, no database):
- effort: labour from `labor_hours`; from hourly labour rows; `workers_per_unit` above 20
  ignored as a crew; largest machine row taken, operator and electricity rows not added;
  machine-bound duration wins over a shorter labour one; parallel gangs divide machine time;
  machine shifts are not read; a position with only machine rows takes the machine duration.
- confidence: each factor value, synthetic rows capped at 0.5, compression factor, bands at
  0.5 and 0.7, cost-weighted plan score, plain mean without prices.
- rules: `boq_coverage` lists exactly the unscheduled priced positions; `cost_reconciliation`
  passes on equality, passes within a cent, fails above; `duration_vs_norm` fires above 2x and
  below 0.5x, not at two days of difference or less, not without `norm_days`, not on summaries.
- rules registered in `schedule_5d` and reachable through the engine with that set name.

Integration (PostgreSQL, `tests/integration`):
- generating writes `cost_planned` on every task equal to its position total, `None` on
  summaries and milestones, and the sum equals the bill's position total exactly.
- tasks carry `resources` with a `Labour` row whose `count` is the crew, and a `Machines` row
  when the position has machine rows; the levelling network built from them has demand.
- a position whose machine hours outlast its labour gets the machine duration and the
  `machine_hours` source.
- the preview carries `confidence`, `cost` and `validation`; a priced zero-quantity position
  shows up as a `boq_coverage` finding and a `cost_reconciliation` error.
- end to end: after generating, the S-curve has a non-zero final planned value equal to the
  BOQ total and EVM reports BAC equal to it.

Frontend (vitest): the preview panel renders the plan confidence, cost line, findings and the
review list; the Gantt badge helpers map scores to bands and reasons to text.

## 4. P1 (about 4 to 6 weeks)

| # | Item | Effort |
|---|---|---|
| 6 | Location split from the model: `BOQElementLink` -> element storey -> quantity per storey -> one activity per position (or group) and storey, with `bim_element_ids` filled, so 4D needs no manual linking | 1.5-2 weeks |
| 7 | Logic templates by classification and trade (DIN 276, MasterFormat, NRM first) as editable data, plus the location direction rule; every inferred link carries its reason | 1.5 weeks |
| 8 | Aggregation by trade and location to keep large plans readable | 4-5 days |
| 9 | Wizard: source, structure, productivity, logic, window, review, with a live preview and a line-of-balance view | 1.5 weeks |
| 10 | Stale flag and review panel: a `boq.position.*` listener marks linked activities with the quantity and cost deltas and a proposed duration; the person accepts per activity | 1-1.5 weeks |
| - | "Save as baseline 0" on confirm; levelling by trade pool in the preview | 3 days |

## 5. P2 (about 6 to 10 weeks)

| # | Item | Effort |
|---|---|---|
| 11 | Takt bridge: a takt plan from the locations and trades, takt time sized from hours per zone, kept in step with the CPM activities | 2 weeks |
| 12 | Cash flow from the cost-loaded schedule with payment terms and retention; cost model cash flow by the activity dates of a budget line | 1-1.5 weeks |
| 13 | XER export and IFC 4D export through the conversion pipeline | 1.5-2 weeks |
| 14 | Cost data enrichment: a machine-hours column, trade codes in 9 languages, crew compositions, real norms on the demo bills | 2-3 weeks of data work |
| 15 | Suggestions with confidence for positions no template places and for fallback positions (norm match from the cost database); always confirmed by a person | 2 weeks |

## 6. Rules added later

`schedule_5d.unloaded_activity`, `schedule_quality.logic_density`, `schedule_quality.out_of_sequence`,
`schedule_5d.location_sequence` (P1, with locations) and `schedule_5d.stale_from_estimate`
(P1, with the stale flag).

## 7. Open questions

- Should `count_total_people_per_unit` be read as a crew at all? P0 ignores values above 20.
  The alternative is to stop copying it into `workers_per_unit`, which changes the cost import.
- The cost importer types operator and electricity rows as `equipment` outside the English
  base. P0 works around it by taking the largest machine row; fixing the mapping is P2 item 14.
- Demo bills carry synthetic norms, so their plans read "medium". Deriving the demo hours from
  the cost database would make the demo honest and high at once.
