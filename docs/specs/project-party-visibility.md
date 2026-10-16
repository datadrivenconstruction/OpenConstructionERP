# Project parties and party visibility in shared registers

Status: implemented in the `teams` module (first version).

## Why

Everyone who is added to a project sees every record in it. On a multi-company
project that is not acceptable: subcontractor A must not read the RFIs and
letters of subcontractor B, and the client must not read the contractor's
work-in-progress correspondence. ISO 19650 describes the same rule for a common
data environment: information is visible to its author until it is shared, and
once shared it is visible to the parties it was shared with.

This version introduces the notion of a **project party** (a company in a role
on one project) and applies the rule "a party sees its own records and the
records shared with it" to the six shared registers. Every other module keeps
its current behaviour.

## Model

All tables live in the `teams` module, next to the existing team visibility
tables, because they answer the same question ("who on this project may open
this record") and are read by the same helpers.

`oe_teams_project_party` (`ProjectParty`)

| Column | Type | Notes |
|---|---|---|
| `project_id` | GUID, FK project, cascade | The project the party belongs to. A party never spans projects. |
| `name` | str(255) | Company name as it appears on this project. Unique per project (case-insensitive, checked in the service). |
| `role` | str(32) | `owner`, `contractor`, `subcontractor`, `consultant`, `supplier`. `owner` is the client or employer, not the platform user who owns the project record. |
| `legal_entity_id` | GUID, nullable | Optional link to `legal_entities`. No FK, the module is optional. |
| `contact_id` | GUID, nullable | Optional link to a contacts record (the company). No FK, same reason. |
| `notes` | text | Free text. |
| `is_active` | bool | An inactive party keeps its records and bindings but cannot receive new shares. |

`oe_teams_party_member` (`ProjectPartyMember`): binds one platform user to one
party on one project. `project_id` is denormalised from the party so that the
unique constraint `uq_teams_party_member_project_user (project_id, user_id)`
can enforce "a member has at most one party per project" in the database, not
only in the service.

`oe_teams_party_record` (`PartyRecordAccess`): one row per (record, party).

| Column | Notes |
|---|---|
| `project_id` | The record's project. Must equal the party's project (validated on write). |
| `entity_type` | One of the six register keys below. |
| `entity_id` | GUID of the record. |
| `party_id` | FK party, cascade. |
| `access` | `originator` (the party that created the record) or `shared`. At most one `originator` row per record (partial unique index). |
| `permission` | `contribute` or `view`. Originator rows are always `contribute`. |
| `shared_by` | User who wrote the row (null for the originator stamp of a system call). |

### Why not reuse `EntityVisibility` rows directly

`EntityVisibility` is subtractive and keyed by team: a row on a record restricts
it to the named teams and hides it from every other member. A party share has
the opposite reading for internal members (they must keep seeing everything).
Writing party shares into `EntityVisibility` would make every shared RFI
restricted under team semantics the moment the team consumer is enforced for
that kind. The party rows therefore live in their own table, while the
resolver follows the same contract as `teams.access` (subtractive, fail closed,
404 not 403, applied after `verify_project_access`) and the same record-kind
catalogue (`rfi` and `correspondence` are already catalogue keys).

## Who is restricted

Party filtering applies to a caller only when ALL of the following hold:

1. the caller is not a system admin,
2. the caller is not the project owner (`Project.owner_id`),
3. the caller is bound to a party on that project, and
4. that party is not the **host party**, the party the project owner is bound
   to (the company running the project on the platform).

Everyone else is an internal member and sees every record, exactly as today.
Consequences:

* A project with no parties, or with parties but no bound members, behaves
  exactly as before. This is the backward-compatibility guarantee and it is
  pinned by tests.
* A user who is a project member but not bound to any party is internal. Binding
  is what makes someone external.
* System calls (`user_id is None`, background jobs) are not filtered, matching
  `teams.access.hidden_entity_ids`.

A restricted caller sees a record when their party holds a row for it in
`oe_teams_party_record` (as originator or through a share). A record with no
rows at all (legacy data, or created by an internal member) is NOT visible to
external parties until someone shares it. This is the restrictive reading of
"a party sees its own records plus those shared with it" and matches the ISO
19650 work-in-progress state.

## Registers covered

The board card lists "requests, interfaces, RFI, correspondence, transmittals,
submittals". Requests of other types (technical query, site query and so on)
are RFI rows with a request type (board card AM-01 extends the RFI register
rather than adding a new one), so they are covered by `rfi`. The two transmittal
modules are both covered, which gives six entity keys:

| Key | Module | Model | Children that inherit visibility |
|---|---|---|---|
| `rfi` | `rfi` | `RFI` | reply attachments, activity, approval instance |
| `interface` | `interface_management` | `InterfaceRecord` | `InterfaceAction` |
| `correspondence` | `correspondence` | `Correspondence` | attachments |
| `transmittal` | `transmittals` | `Transmittal` | recipients, items |
| `submittal` | `submittals` | `Submittal` | attachments, approval instance |
| `file_transmittal` | `file_transmittals` | `FileTransmittal` | items, recipients, cover sheet |

## Permission matrix

Rights: R = read (list, detail, export, search, AI), W = write (update, respond,
review, issue, attach, delete subject to the existing RBAC permission), S =
share or unshare with another party, O = change the originator.

| Caller | Record has a row for caller's party | R | W | S | O |
|---|---|---|---|---|---|
| System admin, project owner | any | yes | RBAC | yes | yes |
| Internal member (unbound, or host party) | any | yes | RBAC | yes | no |
| External party, originator | `originator` | yes | RBAC | yes | no |
| External party, shared `contribute` | `shared/contribute` | yes | RBAC | no | no |
| External party, shared `view` | `shared/view` | yes | no (403) | no | no |
| External party, no row | none | no (404) | no (404) | no (404) | no (404) |

The matrix is identical for all six registers. "RBAC" means the existing
`RequirePermission(...)` and role checks still apply unchanged: party
visibility only narrows. 403 on a view-only share is acceptable because the
caller can already see the record, so nothing about its existence leaks.

Decisions taken on the restrictive side (security-relevant ambiguity):

* An external party can share only records it originated. A party that
  received a share cannot pass it on.
* Creating a record as an external member stamps the caller's party as
  originator in the same transaction as the insert. If the stamp fails, the
  insert is rolled back rather than leaving a record nobody external can see.
* Records with no rows are hidden from external parties (see above).
* Party CRUD and member binding are owner or system admin only, the same bar as
  team changes, because binding a user changes what they can read.
* Revoking a share and every other write to the party tables writes an audit
  row (`ActivityLog`, `entity_type="project_party"` or `"party_record"`).

## Read paths per register

Every path applies the filter after `verify_project_access`. Lists add a SQL
clause (`party_read_clause`), detail and child routes call
`verify_party_record_access`, which answers 404 for a hidden record.

| Path | rfi | interface | correspondence | transmittal | submittal | file_transmittal |
|---|---|---|---|---|---|---|
| List | yes | yes (`/interfaces`, `/register`, `/actions`) | yes | yes | yes | yes |
| Get by id | yes | yes | yes | yes | yes | yes |
| Stats / summary | yes (`/stats`) | yes (`/work-package-health` counts) | n/a | n/a | yes (`/summary`) | n/a |
| Register export (xlsx/csv) | yes (`/export`, `/export/register`) | n/a | yes | yes | yes | n/a |
| Record PDF | yes | n/a | yes | yes | yes | cover sheet |
| Attachments | yes | n/a | yes | n/a | yes | n/a |
| Activity / approval | yes | n/a | n/a | n/a | yes | n/a |
| Mutations by id | yes | yes | yes | yes | yes | yes |
| Batch status / delete | yes (hidden ids skipped as not found) | n/a | n/a | n/a | n/a | n/a |
| Global search (`core/global_search.py`) | yes | n/a | n/a | n/a | n/a | n/a |
| Semantic search (`search` module, vector collections) | yes | n/a | yes | n/a | yes | n/a |
| AI chat tools (`erp_chat/tools.py` search tools) | yes | n/a | yes | n/a | yes | n/a |

AI agents (`ai_agents/agents/*`) do not read these tables directly (checked by
grep at the time of writing); their trigger on `rfi_created` reads only ids.

Events and webhooks: the `rfi.*`, `submittal.*`, `transmittal.*` and
`correspondence.*` events carry ids and short subjects. They are consumed by
notifications (delivered to the assignee, reviewer or recipient named on the
record) and by outbound webhooks configured by project admins. Both audiences
are named on the record or internal, so payloads are not filtered in this
version.

## Not covered in this version

These read the six tables outside the register modules. They return counts or
cross-module summaries and are listed so the next card can close them; an
external party can reach them only through the corresponding module page:

* project dashboards and KPIs: `dashboard/service.py`, `bi_dashboards/kpis.py`,
  `reporting/service.py`, `core/sidebar_badges_router.py`, `projects/router.py`
  overview counts, `projects/service.py`,
* `deadlines/service.py`, `change_intelligence/*`, `reconciliation/service.py`,
  `retrieval/service.py`,
* `collaboration` comments and `collaboration_locks` on rfi, submittal and
  transmittal ids,
* `enterprise_workflows`, `quality_concept/links.py`, `plant_register`.

All other modules (BOQ, costs, schedule and so on) are unchanged: an external
party bound to a party still sees them as any project member does today. The
card that extends the filter to them should start from this list.

## API

Mounted under `/api/v1/teams`:

| Method and path | Who |
|---|---|
| `GET /project/{pid}/parties` | any project member |
| `POST /project/{pid}/parties` | owner, admin |
| `PATCH /project/{pid}/parties/{party_id}` | owner, admin |
| `DELETE /project/{pid}/parties/{party_id}` | owner, admin |
| `GET /project/{pid}/parties/members` | any project member |
| `PUT /project/{pid}/parties/members/{user_id}` (body `party_id`) | owner, admin |
| `DELETE /project/{pid}/parties/members/{user_id}` | owner, admin |
| `GET /project/{pid}/parties/me` | any project member (own scope) |
| `GET /project/{pid}/records/{entity_type}/{entity_id}/parties` | anyone who can read the record |
| `POST /project/{pid}/records/{entity_type}/{entity_id}/shares` | see S column |
| `DELETE /project/{pid}/records/{entity_type}/{entity_id}/shares/{party_id}` | see S column, audited |
| `PUT /project/{pid}/records/{entity_type}/{entity_id}/originator` | owner, admin |

## Validation rules

Write-time (service, 422 or 409):

* a user has at most one party per project (DB unique constraint plus a 409 with
  a clear message),
* the bound user must be able to reach the project (owner or team member),
* a share target must be an active party of the record's project,
* the record must exist in the project named in the path,
* revoking a share writes an audit row in the same transaction.

Rule set `teams` (configuration report, `GET /teams/project/{pid}/validate`):

* `teams.party_member_has_access` (ERROR): a party binding for a user who can no
  longer reach the project.
* `teams.party_record_scope` (ERROR): a share row whose party belongs to another
  project.
* `teams.party_host_defined` (WARNING): parties with bound members exist but
  the project owner is bound to none of them, so every bound member is external.

## Test plan

Distinguishing cases (each must fail before the filter and pass after):

1. Two subcontractor parties A and B, user a in A, user b in B. b creates an
   RFI. a does not see it in the list, gets 404 on `GET /rfi/{id}`, 404 on its
   PDF, does not find it in the export workbook, global search or chat search.
2. b shares it with A as `view`: a sees it in the list and detail, `PATCH`
   answers 403. Revoke: a gets 404 again and an audit row with action
   `party_share_revoked` exists.
3. Internal member (unbound) and a member of the host party see both records.
   Project owner and system admin see both.
4. Backward compatibility: a project with members but no parties returns the
   same list as before for every member.
5. A record with no rows (created by an internal member) is hidden from a and b
   and visible to internal members.
6. Binding a user to a second party on the same project answers 409. Sharing
   with a party of another project answers 404 (the party is not found in this
   project). Sharing a record a party only received answers 403.
7. The same list and by-id cases for interface, correspondence, transmittal,
   submittal and file transmittal (one case each, list plus direct id).

Core tests live in `backend/tests/unit/teams/test_party_visibility.py`
(PostgreSQL unit database, the gated suite). Register wiring tests live in
`backend/tests/unit/teams/test_party_registers.py`.
