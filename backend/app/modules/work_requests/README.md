# Work Requests (`oe_work_requests`)

One intake spine for every department. A PM raises a request for
engineering, drafting, the workshop, automation or hazardous-area review;
the department runs it across its own board; hours land against the quote;
work is handed to the next department as a child the parent waits on; the
planner shows people per board per day; the right person's bell rings.

This replaces three intake spreadsheets (Engineering + Drafting,
Manufacturing, Automation) and two department trackers (Drafting drawing
status, Switchboards build status + daily headcount) with one record.

## Departments are data

Seeded on first start when none exist, then fully editable
(`PATCH /departments/{key}`): name, colour, lead + members, hourly rate,
the **stages** (`{key, name, colour, order, closes}` - a stage with
`closes` completes the request) and the **request types**
(`{key, label, disciplines, fields, active, position}` - each type's extra
raise-form questions, typed `text|area|date|number|bool|select|url`).

| key | prefix | colour | stages | types |
|---|---|---|---|---|
| `engineering` | `ENG` | blue | received → design → review → issued ✓ | eng_only, eng_and_drafting, load_study, cable_schedule, arc_flash_study, protection_settings, site_survey, design_review |
| `drafting` | `DRF` | violet | ready_to_draft → underway → for_review → ifc → factory_as_built → site_as_built ✓ | drafting_only, update_as_built, ifc_issue, schematics, panel_layout, redlines_to_as_built, cable_schedule_drafting |
| `workshop` | `WKS` | orange | requested → drawings_received → materials_ordered → build → wiring → testing → ready_for_fat → delivered ✓ | switchboard, control_panel, fab_plinth_other, modification_retrofit, gear_tray, terminal_box, repair, testing_only |
| `automation` | `AUT` | teal | scoped → fds → programming → scada → fat → commissioning → complete ✓ | plc_programming, scada, fds, commissioning, hmi_screens, network_config, safety_plc, software_fat, other |
| `hazardous_area` | `HAZ` | red | scope → classification → design_review → inspection → dossier → certified ✓ | area_classification, design_review, inspection_dossier, ex_inspection, equipment_selection, verification_dossier, other |

A custom department mints from the first three letters of its key
(`site_services` → `WR-SIT-000001`); pass `prefix` to choose, and a prefix
already in use is refused rather than shared.

### The owner adds the next type

`work_requests.manage` owns a department's catalogue without waiting on a
release: `POST /departments/{key}/request-types` (the key is slugged from
the label when it is left out, unique per department),
`PATCH .../{type_key}` (label, disciplines, fields, `active`, `position` -
the key is fixed for life), `DELETE .../{type_key}` and
`PUT .../request-types/order` `{keys: [...]}` (anything left out keeps its
relative order at the end, so a stale list never drops a type).

**Retiring is `active: false`, not a delete.** A type any request has ever
been raised against refuses deletion with a `409` naming the count;
retired, it stops being offered on a raise form and stays fully readable -
label and fields - on every request that already carries it.
`GET /departments` returns types in `position` order and live ones only;
the manage screen asks for `?include_inactive=true`.

### One request, several types

An item can need SCADA *and* PLC programming *and* FDS, so a request
carries `request_types: [str]` (1-8). `POST /requests` takes that list or
the legacy `request_type: str`; `PATCH /requests/{id}` takes either and
re-derives. **`request_type` is always the first of the list**, written on
every create and update, so a row seeded before this and any reader still
asking for the singular keep working; a row whose list is empty (the boot
column-heal adds the column empty) reads back as `[request_type]`.

The response carries `request_types`, `request_type_labels` (resolved, in
order) and `field_specs` - the **union** of the chosen types' fields,
de-duplicated by `key`, first definition wins, in type order. That union
is exactly what the raise form should render and exactly what the server
validates, required fields included.

`GET /requests?request_type=scada` matches **membership**, not equality -
a request that asks for SCADA among three types belongs in that column.
`?request_types=a,b` means any of them.

### Topping a live install up

The seed only fires on a database with **no** department, so an install
that started before a release would never see a newly seeded type or the
hazardous-area colour. `reconcile_seeded_departments` runs on every
startup and is deliberately timid: it appends seeded types whose key is
missing, never modifies or reorders a type the owner has edited, never
reactivates a retired one, never touches a custom department, and repaints
`hazardous_area` only while it still carries the colour the old seed gave
it. One log line says what it added.

## The reference

`WR-<PREFIX>-000001`, six digits, one series per department across the
whole business. Minted under a row lock on `oe_work_requests_counter`
with the first-mint race handled in a savepoint (the loser retries onto
the winner's row), and a unique index on `reference` as the backstop.
Never re-issued: the counter seeds from the highest reference already on
the table, so a restore cannot hand a number on a drawing to new work.
`GET /requests/{id}` accepts a reference as well as an id.

## The rails (all server-side, all tested)

- **Status machine** `draft → submitted → accepted → in_progress → (on_hold ⇄)
  → review → complete → closed`, `cancelled` from any open state. An
  illegal move is a `409 {detail: {error, allowed: [...]}}`.
- **A closing stage completes**; a first stage move after acceptance
  starts the work (`in_progress`).
- **Only the requester or a manager closes.** The department says
  `complete`; the person who asked says `closed`.
- **Who may change it**: the requester, the department (lead, members,
  assignees, the responsible person) or a manager. A department with no
  roster configured yet is open to everyone with `update`, so a fresh
  install never locks its boards.
- **Ball in court**: `needs-info` hands it to the requester with the
  question on the record; `answer` hands it back. `my-queue` lists what
  needs *my* answer.
- **Hand-off** creates a child in another department; the parent gains it
  in `depends_on`, so the board shows the switchboard waiting on its
  drawings.
- **A required checklist item stops a close.** A request type may declare
  `checklist: [{key, label, required}]`; a stage that `closes` - and an
  explicit move to `complete` - is a `409` naming every required item
  still unticked. Ticking is department-side, like a stage move.
- **A template is never a live request.** `is_template: true` keeps a row
  out of the register, the board, the planner, the summary, `my-queue`
  and the deadline sweep; `GET /requests?is_template=true` lists them.
- **Bulk is never all-or-nothing.** `POST /requests/bulk` applies the same
  patch through the same rails, one savepoint per request, and returns
  `{updated: [...], refused: [{id, reason}]}`.
- **A programme link stays on its own job.** `schedule_activity_id` and
  `boq_position_ids` are validated against the request's project - `404`
  for an id that does not exist, `400` for one on another job.
- **Every mutation writes its own activity line** (`GET /requests/{id}/activity`),
  server-side, by name.

## Hours and cost

`hours_logged` is the sum of the log; `hours_at_completion = logged +
hours_to_complete` (the department's own estimate of what is left);
`deviation_hours = at_completion − quoted_hours` (null without a quote);
`cost_at_completion = at_completion × department.hourly_rate` as money
text (null without a rate).

## Checklists, templates and duplicates

A request type carries a `checklist`; the request carries only the ticks
(`checklist_state`), so a department editing its list never rewrites what
somebody already signed off. The payload joins the two into
`checklist: [{key, label, required, source, done, by, at}]` with
`checklist_done` / `checklist_total`. Two types on one request UNION
their lists and `required` in either one wins.

### One job's checklist is not every job's

A one-off needs "Client witness test", or an item that simply does not
apply. `checklist_overrides` on the request holds the **difference** from
the type's list - never a copy of it - so an item nobody has touched here
still reads its label and its `required` straight off the type:

    {"added": [{key, label, required, after_key}],
     "hidden": [key, ...], "edits": {key: {label?, required?}},
     "order": [key, ...]}

Each derived entry carries `source`: `"type"` (inherited) or `"request"`
(added here). The payload also exposes `checklist_overrides` and
`checklist_is_overridden`.

| route | body | does |
|---|---|---|
| `POST /requests/{id}/checklist/items` | `{label, required?, after_key?}` | adds one here; key slugged from the label, `409` on a clash |
| `PATCH /requests/{id}/checklist/items/{key}` | `{label?, required?}` | overrides an inherited item / edits an added one; the key is fixed |
| `DELETE /requests/{id}/checklist/items/{key}` | - | removes an added item; **hides** an inherited one |
| `PUT /requests/{id}/checklist/order` | `{keys: [...]}` | reorder; keys left out keep their relative order at the end |
| `POST /requests/{id}/checklist/reset` | - | drop every override; ticks on surviving items are kept |

All five return the full updated request. **`work_requests.manage` or the
department LEAD** - narrower than ticking on purpose, and a department
with no lead configured is manager-only. Anyone else is a `403`:
*"Only the Workshop lead or a manager can change this checklist."*
Deleting a **ticked** item is a `409` (untick it first); a `closed` or
`cancelled` request refuses every edit; the derived list is capped at 60.
The completion gate runs on the DERIVED list, so an added required item
blocks a close and a hidden one no longer does. Hiding is never a delete:
the type still declares the item, so a later change of request type
brings it back.

`POST /requests/{id}/duplicate {title?, project_id?}` copies the types,
the typed fields, the quoted hours, who is on it, the links and the
checklist (all unticked) into a NEW `draft`. It does not copy the hours
logged, the conversation, the attachments, the stage history or the
dependencies - those belong to the request that was worked.

## Turnaround targets

A department may carry `target_days` (WORKING days, weekends skipped).
`accepted_at` is written once, the first time the department takes a
request on - by accepting it or simply moving it off the intake stage.
From those two the payload derives `target_date`, `days_late` and
`is_late`, `GET /summary` gains `late` per department, and the deadline
sweep rings `late` as its own reason alongside `overdue`.

## Export

`GET /requests/export?format=csv|xlsx&...` takes exactly the filters
`GET /requests` does and streams
`work-requests-<dept-or-all>-<YYYY-MM-DD>.csv|xlsx` with the columns the
sheet has. Hours and money are plain decimal text, dates are ISO, and a
cell that would look like a formula is prefixed so a spreadsheet renders
it instead of running it. `xlsx` uses `openpyxl` (already a project
dependency); without it the response is the CSV and `X-Export-Note` says
why.

## Planner

`GET /planner?department=&from=&to=` - every open request in the
department against every day (default five weeks, max 120), with
`capacity[day] = {available, allocated}`. `available` defaults to the
roster size and is overridable per day (`PUT /planner/capacity`, manage).

## Notifications

Written through the platform's notification service in the same
transaction as the action: raised → department; stage/status/complete →
requester; needs-info → requester; answer → department; mention → the
mentioned; hand-off → target department; assigned → the assignees.
`POST /deadline-sweep` rings due-tomorrow / overdue at most once per
request per day (the memory lives in a server-owned column). Domain
events also go onto the bus (`work_requests.request.*`) for webhooks and
the timeline.

## Tests

`backend/tests/modules/work_requests/` - seeds, minting (per department,
first-mint race, real concurrent sessions), the status machine, closing
stages, needs-info/answer, hand-off, hours → cost, planner, summary and
my-queue, permissions (viewer read/create OK, manage refused, the
registration guard), and the router wiring including reference lookup,
409 shape and attachments. Plus `test_multi_type.py` (the list, the
derived singular, the field union, the backfill on read, the membership
filter) and `test_type_catalogue.py` (add/edit/retire/delete/order, the
in-use refusal, the seeded colours being mutually distinct, and the
startup reconcile against an install with a hand-edited catalogue).
Plus `test_checklists.py`, `test_templates.py`, `test_bulk.py`,
`test_export.py`, `test_programme_links.py` and `test_targets.py`.
