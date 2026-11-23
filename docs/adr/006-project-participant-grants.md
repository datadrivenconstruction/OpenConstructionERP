# ADR 006: Project participant grants

Status: **accepted, and stages 1-4 of section 10 are implemented.** Date proposed 2026-10-30;
date accepted 2026-11-22, when the owner's eight answers in section 11 were recorded and the
grant table, its service, the second GUC, the two-arm database predicate and the retirement of the
`project_frameworks` union had all shipped.

**Sections 1 to 11 are left as they were written, and they are the proposal, not a description of
the shipped code.** Where the shipped design differs - the scope vocabulary, the shape of the
policy, the census, the performance numbers, and the parts of the plan that were deliberately not
built - section 13 says so and names the file and the test that carries each difference. Read
section 13 before acting on any number below. Where a claim in sections 1 to 12 is still not
measured it stays marked **unverified**.

Supersedes nothing. Extends [ADR 005, organization is the tenant](./005-organization-is-the-tenant.md),
which made a company the tenant and left one question deliberately unanswered: what happens when
work on a project belongs to more than one company.

Owner decision recorded for this ADR: **projects may span multiple organizations.** A project
belongs to one organization; other organizations participate through explicit project
participant grants. The target row-level security shape is:

> a row is visible when the caller's organization owns it, **or** the caller's organization holds
> a grant on the project the row belongs to.

This is a design because Phase 02b does not have the evidence to build it, and because building
it before the tenancy backfill is provably complete would put an authorization decision on top of
data whose owner is still ambiguous.

## 1. What the code stores today

Verified against the tree at the commit this ADR was written on, not assumed.

| Question | Answer in the code today | Evidence |
|---|---|---|
| What does a project store about ownership? | Two different keys. `owner_id`, a **person**, `NOT NULL` in practice; and `organization_id`, a **nullable** company reference with `ON DELETE SET NULL` | `app/modules/projects/models.py:102` and `:126` |
| Which of the two does product code read? | Overwhelmingly the person. **75** read sites of `Project.owner_id` across `app/`. `Project.organization_id` had **one** reader in product code, added by the Phase 02b repair work, plus the repair's own docstring | `grep -rn "Project.owner_id" app --include=*.py \| wc -l` = 75 |
| Who may reach a project's routes? | `verify_project_access`: the owner, an admin, or a team member. Both "missing" and "denied" answer 404 so a UUID cannot be probed | `app/dependencies.py:920`, `app/modules/teams/access.py::is_project_member` |
| What is team membership? | Person to team to project: `Team(project_id=...)`, `TeamMembership(team_id=..., user_id=...)`. There is **no** organization-level membership of a project anywhere in the schema | `tests/pg/governance_fixtures.py::add_project` builds exactly this; no model in `app/modules` names an organization as a project participant |
| How many rows are tenant-owned, and how many are project-scoped? | **30** `tenant_id` columns across **16** model files, against **419** `project_id` columns across **147** model files. **11** files carry both | `grep -rn "tenant_id: Mapped" app/modules --include=models.py \| wc -l` = 30; the same for `project_id: Mapped` = 419 |
| What is the RLS surface? | `tenant_tables()` returns the tables that carry a `tenant_id` column, minus an explicit never-policied set. So the policied surface today is the 30-column set, not the 419 project-scoped columns | `app/core/rls_setup.py:202` |
| What does the strict predicate say? | `(tenant_id)::text = current_setting('app.current_tenant', true)`, one GUC, one value, equality | measured on PostgreSQL 16.11 in Phase 02b; `app/core/rls_setup.py` |

Two consequences follow directly, and they are the reason this ADR exists.

**The tenant boundary and the project boundary are not the same shape.** Tenancy is a single
scalar per row and a single scalar per request, compared for equality. Project participation is a
many-to-many relation between companies and projects. Equality cannot express it, so a grant has
to become part of the predicate rather than part of the data.

**419 project-scoped columns against 30 tenant-owned ones means most of the schema cannot be
policed by `tenant_id` at all.** A delivery note, a diary entry, a BIM issue and a certificate are
project-scoped rows. Today they are protected by `verify_project_access` in the route, which is an
application-level gate, not a database-level one. Grants change what that gate must answer, and
eventually what the database must answer for those tables too.

### 1.1 The seam this ADR was written next to

`ProcurementConceptService.project_frameworks` is the one place in product code that already
implements cross-company visibility on a project, and it is worth reading as the prototype of both
the feature and its hazard:

```python
tenants = [t for t in dict.fromkeys((await self.project_tenant(project_id), tenant_id)) if t]
```

A project member sees the frameworks of the project's company **and** of their own. Before the
fix that accompanies this ADR, `project_tenant` read `Project.owner_id`, so it returned a person
where every tenant-scoped row now carries a company, the first half of that union matched
nothing, and a project member from another company saw an empty list. Two PostgreSQL tests failed
on exactly that, and both pass now that it reads `organization_id`.

Note what that union is: **any team member of a project can read another company's frameworks,
with no grant, no expiry and no audit row.** That is today's behaviour, it is intentional in the
product sense, and under the decision recorded above it is precisely what a grant is meant to
make explicit. This ADR treats that call site as the first thing the grant predicate replaces,
and as the standing example of why "team membership implies cross-company read" needs an owner's
decision rather than an accident of a column read.

**That replacement has now happened**, in stage 5 of section 10, and the union above is no longer
in the tree. `project_frameworks` asks whether the caller's company participates before it
returns anybody's agreements, and the write half of the same rule - calling a framework off, which
commits a company's money against an agreement - asks the same question, because a read that hides
an agreement and a write that still accepts its id are not one rule. See section 13.5.

## 2. The grant entity

One row per participating company per project. Deliberately not per user: a company participates,
and its members inherit that participation through their membership of the company, which is the
composition ADR 005 already established.

Table `oe_projects_participant_grant`:

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `project_id` | `UUID` FK to `oe_projects_project`, `ON DELETE CASCADE` | a grant on a deleted project is meaningless |
| `grantee_organization_id` | `UUID` FK to `oe_users_organization`, `ON DELETE CASCADE` | the participating company. Never a user id: that is the ADR 005 mistake, and a grant that named a person would reintroduce it |
| `granted_by_user_id` | `UUID` FK to `oe_users_user`, `ON DELETE SET NULL` | the human who decided. Kept after they leave, so the decision survives the person |
| `granted_on_behalf_of_organization_id` | `UUID` FK, `ON DELETE CASCADE` | the owning company at grant time. Recorded because ownership can move and the authority to grant moves with it |
| `scope` | `VARCHAR(32)`, `NOT NULL` | what the grantee may do. Initial vocabulary: `read`, `contribute`, `steer`. Not a free string; a check constraint or an enum in the model. **Shipped as `view`, `contribute`, `manage`** - section 13.2 |
| `status` | `VARCHAR(16)`, `NOT NULL`, default `active` | `active`, `suspended`, `revoked`. Mirrors `Membership.status`, so the two authorization layers read the same way |
| `valid_from` / `valid_until` | `TIMESTAMPTZ`, both nullable | open-ended when null. A tender period or a site handover is the normal reason to set them |
| `revoked_at`, `revoked_by_user_id`, `revocation_reason` | nullable | revocation is an event with an author and a reason, not a deletion |
| `created_at`, `updated_at` | `TIMESTAMPTZ`, `NOT NULL` | |
| `metadata_` | `JSON` | consistent with the rest of the schema |

Constraints that carry the design:

* **`UNIQUE (project_id, grantee_organization_id)`** where `status <> 'revoked'`, expressed as a
  partial unique index. One live grant per company per project. Re-granting after a revocation
  inserts a new row, so the history survives; the index keeps the live set unambiguous, which is
  what the predicate reads.
* **The owning company cannot hold a grant on its own project.** Enforced in the service, not the
  database, because it compares two columns across tables; a test asserts it.
* **`valid_until > valid_from`** when both are set.
* A grant does **not** create team memberships and does not create users. It authorizes a company;
  the people are already the grantee company's members.

## 3. How it composes

```
Organization --< Membership >-- User            (ADR 005: who the caller acts as)
     |
     +-- Project.organization_id                (the owning company, exactly one)
     |
     +--< ParticipantGrant >-- Project          (participating companies, zero or more)

Project --< Team --< TeamMembership >-- User    (today's route-level gate, person-scoped)
```

The two layers answer different questions and both stay:

* **Company layer (new).** Is the caller's organization the owner of this project, or a live
  grantee on it? This is the tenant question, and it is the one that belongs in the database.
* **Person layer (existing).** Is this specific person on the project's team, and what role do
  they hold? `verify_project_access` keeps answering it. A grant does not put anybody on a team.

A caller is authorized on a project when **both** layers answer yes: their company participates,
and they personally are on the team (or are an admin). A company-level grant with no team
membership must not open a project, because that would let a company's entire staff read a
project nobody assigned them to. Team membership with no company participation must not open it
either, which is the case that exists today and is the hole this ADR closes.

That is a tightening, and it needs an owner's decision (open question 1) because it will refuse
access that currently succeeds.

## 4. The RLS predicate

### 4.1 Shape

Two GUCs, both set by the same `bound_tenant` call that sets today's one, so there is still a
single place where a request's identity enters the database:

* `app.current_tenant` - the caller's organization id, as today.
* `app.granted_projects` - the comma-separated project ids the caller's organization participates
  in, computed **once per request** from the grant table. Empty string when there are none.

```sql
USING (
  (tenant_id)::text = current_setting('app.current_tenant', true)
  OR (project_id)::text = ANY (
       string_to_array(current_setting('app.granted_projects', true), ',')
     )
)
```

Computing the visible-project list per request rather than per row is the whole performance
argument. A correlated `EXISTS` against the grant table inside `USING` re-plans per row and is
the shape that turns a scan into a nested loop over a million rows.

**Shipped differently, and the difference is the point.** This section proposes one policy whose
`USING` clause ORs two arms, which means rewriting the installed `oe_tenant_isolation` policy on
every policied table - and a policy that governs writes as well as reads, because `USING` applies
to both. What shipped is **two permissive `FOR SELECT` policies**, the existing tenant policy left
byte-identical and a second one carrying only the project arm. PostgreSQL ORs the `USING`
expressions of permissive policies, so reads see exactly the union this section specifies, while
writes remain governed by the tenant policy alone and a grantee's rows still carry the grantee's
own `tenant_id`. That is section 7's first load-bearing rule enforced by the shape of the policy
rather than by a comment in the service. Section 13.3 records it with the file names.

Fail-closed behaviour is inherited and must not change: when `app.current_tenant` is unset or
empty, the first arm matches nothing; when `app.granted_projects` is empty, `string_to_array`
yields `{""}` and the second arm matches nothing either, because no project id is the empty
string. A test asserts both arms refuse separately.

### 4.2 Performance on a 1M-row table - **measured; see section 13.4 for the numbers**

The measurement now exists: `oe_pipeline`, one million rows, twenty tenants, two thousand
projects, two permissive policies installed, three query shapes, median of five after a discarded
warm-up, three rounds, foreign keys left in place. The worst ratio was **1.0046** against the
owner's bar of **1.25**. The harness is
`tests/pg/test_the_two_arm_predicate_stays_within_a_quarter_of_the_single_condition_one.py`, and it
prints an `OE-GRANT-PERF` line with both medians, all three ratios, the row count and the verdict
on every run. Section 13.4 carries the table.

What was known before it was run, and is still worth keeping because it is the reasoning the
measurement was designed to test:

* The repository already has a million-row PostgreSQL harness,
  `tests/pg/test_a_million_rows_are_rewritten_fast_enough_to_boot_on.py`, which builds 4 x 250,000
  rows and asserts a floor of 20,000 rows per second. It measured 23,141 to 26,857 rows/s for the
  tenancy repair on this sandbox's embedded PostgreSQL 16.11. The same harness is the vehicle for
  the grant predicate.
* The predicate above is an `OR` of two equality tests, one against a column and one against a
  small in-memory array. PostgreSQL can serve it with a bitmap OR of two index scans **only if
  both sides are indexable**. `tenant_id` is indexed on the policied tables; `project_id` is
  indexed on some of the 419 and not on others, and that census is part of stage 1 below.
* The risk is not the array test, it is the `OR`: an `OR` across two different columns defeats a
  single index scan and can degrade to a sequential scan on a wide table. If measurement shows
  that, the fallback is a **denormalized visibility column** - stamp the owning organization on
  project-scoped rows at write time, so the predicate becomes one equality again. That is a
  bigger migration and is why it is the fallback and not the plan.

Acceptance bar, as the owner answered question 6: a filtered read of a 1M-row project-scoped table
under the grant predicate must not be slower than the same read under today's single-GUC predicate
by more than a factor of **1.25**. That bar is asserted in the harness above
(`OE_GRANT_PERF_MAX_RATIO`, default `1.25`), together with the row count it is stated at
(`OE_GRANT_PERF_ROWS`, and a third test refuses to run the bar on fewer than a million rows), so
it survives this document.

The 20,000 rows/s floor named in the proposal is **not** asserted by that harness and this ADR does
not claim it is: the floor belongs to
`tests/pg/test_a_million_rows_are_rewritten_fast_enough_to_boot_on.py`, which measures how fast the
tenancy repair rewrites rows at boot - a different operation on different tables. The grant
predicate changed nothing in it, and its numbers are quoted below only as the baseline the
proposal wanted a new predicate to be compared against.

### 4.3 Grant lookup cost

`app.granted_projects` is one indexed query per request against a table whose size is bounded by
projects x participating companies, not by rows. It belongs in the same request-scoped binding
path as `bound_tenant`, and it must be cached per request, not per row and not per statement.
Background paths that bind no tenant today (the Phase 02c list) would bind no grants either, so
they must not silently gain the empty-list arm as a way to see everything: empty means nothing,
in both GUCs.

## 5. Project-scoped versus tenant-owned

The measured split, and what each side needs:

| Class | Count | Examples | What polices it today | What polices it under grants |
|---|---|---|---|---|
| Tenant-owned | **30** columns, **16** model files | `oe_procurement_framework_agreement`, `oe_contacts_contact`, `oe_activity_log`, `oe_compliance_dsl_rule`, `oe_eac_block_graph` | `tenant_id` equality, RLS strict where enabled | unchanged, plus the project arm only where the table also carries `project_id` |
| Both | **11** model files carry `tenant_id` and `project_id` by source grep; **10** tables by the shipped metadata census | the dashboards, the EAC rules and rulesets, the pipelines and their runs, the formwork assignments, the cost-match runs, the point-cloud datasets | both columns exist; only `tenant_id` is policied | **the seam.** These get the two-arm predicate first, because both sides of the `OR` are already columns on the row. **Done: all 10.** Section 13.6 |
| Project-scoped only | **419** columns, **147** model files | deliveries, diary entries, BIM issues, certificates, teams, routes, governance areas, gates, documents | `verify_project_access` in the route; no database policy | a project-level policy, or a denormalized owner column. Stage 4, and the largest single body of work in this ADR |

The order matters: the tables that carry both columns are where a grant can be enforced in the
database with no schema change at all. Ten of them exist, and all ten are policied; the count in
the table above is eleven because it was produced by a grep over model *sources*, and a grep is not
the authority for what a policy can be installed on - five of those eleven files declare
`tenant_id` on one table and `project_id` on a different one. Section 13.6 lists the ten by name
and reconciles the eleven.

**The procurement concept tables are not in the "Both" row, and this ADR named them there by
mistake.** Measured on the shipped metadata: `oe_procurement_concept_framework` carries `tenant_id`
and no `project_id`, and `oe_procurement_concept_award_package` carries `project_id` and no
`tenant_id`. The module sits on both sides of the split at once, one table each, which is exactly
why the call-off rule in section 1.1 cannot be expressed as a policy on either table and had to be
closed in the service. Section 13.5. The 147 project-only files cannot be policied by
`tenant_id` because they do not have one, and adding one to all of them is the "mechanically add
`tenant_id` to every model" move that Phase 02 explicitly rejected.

## 6. Who may create and revoke a grant

* **Create:** a caller whose organization owns the project, holding a manage-level permission on
  it, acting through the ordinary authorization path. Not the grantee: a company cannot invite
  itself.
* **Revoke:** the same authority, plus a platform admin. Revocation is immediate and is an event,
  not a delete (see section 8).
* **Accept:** answered no - question 2. A grant is live when the owning company writes it, and
  `status` carries `active`, `suspended` and `revoked`. No `offered` value shipped, so there is no
  state in which a row exists and means nothing; a company that does not want to participate is
  revoked, and the revocation is an event with an author and a reason. The predicate only ever
  reads `active` rows inside their window, as proposed.
* **Agents:** any grant write reached through an AI agent path must pass the same central
  authorization gate as every other sensitive operation
  (`app/modules/ai_agents/tool_authorization.py`), must be tenant-bound, and must produce an audit
  row. No agent path may write this table directly, and no agent may execute SQL against it.
  **Not built.** No agent tool exposes grants, so today nothing reaches the table except the four
  HTTP routes and the ownership-change suspension; the requirement stands and is listed as open
  work in section 13.7 rather than claimed as done.

## 7. What a grantee organization can read and write

Per `scope`, and stated as refusals so the tests have something to assert:

| Scope | Reads | Writes |
|---|---|---|
| `read` | project-scoped rows of the project, and the owning company's rows that the project's routes deliberately expose - today that is the `project_frameworks` union | nothing. Every write route refuses |
| `contribute` | as `read` | creates and edits **its own** rows on the project: diary entries, deliveries, documents it uploads. Cannot edit the owner's rows, cannot approve, cannot change the plan |
| `steer` | as `contribute` | the project's decision routes: approvals, gate decisions, plan changes, within the caller's own RBAC role |

Two rules that are load-bearing:

**A grantee writes only rows it owns.** A row created under a grant carries the **grantee's**
`tenant_id`, not the project owner's. Ownership follows the author's company, because that is
what makes the row's own tenant scope honest and what keeps a revoked grant from orphaning data.
Consequence: after revocation, the grantee's rows stay the grantee's, and the owner can no longer
read them through the project arm. Whether that is acceptable is open question 3, and the
alternatives are a handover step at revocation or an owner-side copy.

**Revocation is not retroactive.** It stops the predicate from matching from the moment it is
written. It does not delete, re-stamp or hide anything, and it must not be implemented as a data
rewrite: an unbounded `UPDATE` on revocation is exactly the destructive-migration shape Phase 02
rejected.

## 8. Audit trail

Every create, scope change, suspension and revocation writes an `oe_activity_log` row (which is
already tenant-owned and already backfilled) naming the project, the grantee organization, the
acting user, the previous and new state, and the reason where one was given. The grant table keeps
its own history too: revoked rows are retained, so the sequence of grants on a project is
reconstructible from the table alone even if the activity log is pruned.

A grant is an authorization decision, and the standard for those in this repository is that the
conclusion is traceable to evidence. Both records exist so that "who could see this project on
that date" is answerable after the fact.

## 9. Migration impact on the tenant columns

* **Zero changes to the 30 existing `tenant_id` columns.** The grant adds a table and a second
  GUC; it does not re-stamp a single row. That is deliberate: a migration whose main action is an
  unbounded rewrite of 30 columns across a populated install is the thing Phase 02b spent its
  effort making unnecessary.
* **One new table**, created under the migration guards this repository already enforces:
  single head, DDL guarded for existence, no data rewrite in the migration body. If any backfill
  is ever needed it goes in a `DataRepair` with a ledger, an advisory lock and an idempotent
  re-run, not in the revision.
* **The both-column tables** needed an index check on `project_id` before their policy changed.
  Done: all **10** already carry a `project_id` index (`oe_pipeline` carries two,
  `ix_oe_pipeline_project` and `ix_oe_pipeline_project_id`), so the second policy was installed with
  no new index and no schema change anywhere.
* **The 147 project-only files** are untouched until stage 4, and stage 4 is a decision per
  table, not a sweep.
* **Interaction with strict mode.** Enabling `OE_RLS_STRICT` installs the single-arm equality
  predicate. Turning it on before grants existed would have refused every cross-company project
  read that worked, including the `project_frameworks` union. So grants are a **precondition for
  strict mode**, not a follow-up to it, and that ordering is recorded in the Phase 02c list.
  **The precondition is now met only for the ten both-column tables.** Strict mode still refuses
  cross-company reads on the project-scoped-only tables, which have no `tenant_id` for either arm
  to match and are still gated in the route; turning it on is still blocked by that half of stage 4,
  and nothing shipped here changed it.

## 10. Staged plan

Each stage is separately shippable and separately testable, and no stage weakens an existing test.

**Status as accepted.** Stage 1 done, and it produced the census in section 13.6 rather than a
number in section 4.2. Stage 2 done. Stage 3 done. Stage 4 done for the ten both-column tables and
**not started** for the project-scoped-only ones. Stage 5 done, which is why this ADR is accepted
rather than proposed. The build order followed the plan's numbering except that the census and the
table shipped together and the union was retired last, as written. Sections 13.1 and 13.8 name the
commit and the tests for each stage.

1. **Census, no behaviour change.** For the 11 both-column model files, record whether
   `project_id` is indexed and how many rows each table carries on a representative install.
   Deliverable: a table in this ADR replacing the word **unverified** in section 4.2 with numbers.
2. **The table and its service.** `oe_projects_participant_grant`, the model, the migration, a
   service with create/change-scope/suspend/revoke, and the two rules from section 6. No
   predicate change, so nothing that works today stops working. Tests: the unique-live-grant
   constraint, the owner-cannot-grant-itself refusal, revocation retaining the row, and the audit
   row for each transition.
3. **The second GUC.** `bound_tenant` also sets `app.granted_projects`, computed once per request
   and cached. Still no policy change. Tests: the GUC is empty for a caller with no grants, is
   correct for a caller with several, and is empty - not unset - for every background path on the
   Phase 02c list.
4. **The predicate, on the 11 both-column tables first,** behind the existing strict-mode switch,
   measured against the million-row harness with the acceptance bar in section 4.2. Only then the
   project-only tables, one decision at a time.
5. **Retire the accidental union.** `project_frameworks` stops deriving cross-company visibility
   from team membership and reads the grant instead. This is the stage that can refuse access that
   works today, so it needs the owner's answer to open question 1 first, and it needs a rollout
   note in the same shape as the token rollout Phase 02b shipped.

## 11. Questions for the owner, and the eight answers

All eight were answered before this ADR was accepted, and each answer below names the code that
carries it, so an answer is not a sentence in a document but something a test can fail. The
questions are left as written because the reasoning in them is still the reasoning.

1. **Does a grant tighten access that works today?** Team membership currently implies
   cross-company read on the `project_frameworks` path and, at route level, on every project
   route. Making company participation a precondition will refuse some callers who succeed today.
   Is that intended, and is there a migration window in which both answers are accepted?

   **Answer: yes it tightens, and no migration window.** A caller on a project's team whose company
   was never invited in reads an empty framework list and cannot call one off. There is no flag
   that accepts both answers: `OE_PROJECT_GRANTS` gates the *database* arm only, because
   installing a policy is an install-time act an operator has to opt into, while the
   application-layer closure is unconditional - a leak is not a feature to migrate off. The two
   characterization tests that pinned the old behaviour were replaced rather than deleted, and each
   replacement says in its docstring that it used to assert the opposite and why
   (`tests/pg/test_procurement_concept_http.py`,
   `tests/pg/test_procurement_concept_service_on_pg.py`). At route level nothing tightened: which
   projects a caller may open is still `verify_project_access`, unchanged.
2. **Must the grantee accept?** `status` can carry `offered` before `active`. Two-sided grants are
   the norm in joint ventures; one-sided is simpler and is what the schema assumes by default.

   **Answer: no.** One-sided, and `GRANT_STATUSES` is `active`, `suspended`, `revoked` with no
   `offered`. A row that exists means a company participates or has been withdrawn; there is no
   third state in which a row means nothing yet.
3. **What happens to a grantee's own rows when the grant is revoked?** They stay the grantee's
   (section 7). Is a handover or an owner-side copy required for any document class -
   certificates and signed deliverables are the likely candidates?

   **Answer: they stay the grantee's, with no handover and no copy.** Revocation writes the grant
   row and the audit row and nothing else: `revoke_grant` issues no `UPDATE` against any other
   table, and `tests/pg/test_a_withdrawn_grant_closes_the_call_off_again` asserts that a package
   called off while the grant was live keeps its framework agreement afterwards. The consequence
   section 7 named is real and accepted: the owner can no longer read those rows through the
   project arm. That is what makes the grantee's own `tenant_id` honest, and it is enforced by the
   policy shape in section 13.3 rather than by every write path remembering the rule.
4. **Does a grant survive a change of project ownership?** `granted_on_behalf_of_organization_id`
   records who granted it. If the project is sold or transferred, are existing grants honoured,
   suspended pending review, or revoked?

   **Answer: suspended pending review, never silently honoured and never revoked.**
   `suspend_grants_on_ownership_change` moves `active` grants to `suspended`, one audit row each,
   leaves grants already made to the incoming owner alone, and does not touch `revoked_at` or
   `revoked_by_user_id` - suspension is not revocation, and the new owner can re-activate. Because
   the predicate reads only `active` rows, a suspended grant closes immediately, and because the row
   survives, the decision that was made is still readable. Every writer of a project's owning
   company calls it; `tests/unit/test_every_writer_of_a_projects_owning_company_suspends_its_grants.py`
   is a source census that fails if a new writer appears without the call.
5. **Can a grantee sub-grant?** This ADR assumes no: only the owner grants. Confirm, because a
   consortium structure may need a `steer`-scope grantee to bring in its own subcontractors.

   **Answer: no, and there is no bypass either.** `resolve_grant_authority` answers 404 when the
   caller's organization is not the project's owner - 404, not 403, so the existence of the project
   is not disclosed by the refusal - and unlike the *reading* paths it has no platform-admin bypass.
   That asymmetry is deliberate and is stated where it is implemented: reading another company's
   project keeps the bypass the guard has always had, while deciding that another company
   participates has none, because a platform admin is not a party to the commercial relationship
   the grant creates. A consortium brings its subcontractors in through the owner, or the owner
   grants the subcontractor directly.
6. **What slowdown is acceptable** for a filtered read of a 1M-row project-scoped table under the
   two-arm predicate, against the single-arm baseline? A factor, or an absolute budget in
   milliseconds, so stage 4 has a pass mark.

   **Answer: a factor of 1.25, at a million rows.** Asserted, not documented:
   `OE_GRANT_PERF_MAX_RATIO` defaults to `1.25` and the harness fails on the first query shape that
   exceeds it. Measured worst case **1.0046** (section 13.4). No absolute millisecond budget,
   because a median in milliseconds on one sandbox is not a number anybody else can hold the code
   to, while a ratio against the same table in the same run is.
7. **Is `scope` a three-value vocabulary or a permission set?** `read` / `contribute` / `steer` is
   the proposal. If grants must map onto existing RBAC permissions instead, the column becomes a
   reference to a permission set and section 7's table is derived rather than written.

   **Answer: a three-value vocabulary, renamed to `view` / `contribute` / `manage`** to match the
   words the rest of the product uses for the same three levels, with `GRANT_SCOPE_RANK` ordering
   them and a check constraint refusing anything else. It is *not* a reference to an RBAC permission
   set, and section 7's table stays written rather than derived.
   **What is not enforced yet: the distinction between the three values.** Every shipped reader
   asks whether a grant is *live*, not which scope it has, so `view` currently answers the same
   questions `manage` does. The rank is recorded and a scope change is audited with the rank before
   and after, so the data to enforce the difference exists; enforcing it is open work, listed in
   section 13.7. Writing this down matters more than shipping it: an operator who sets `view` today
   gets `manage`'s reads.
8. **Do individuals ever participate without their company?** A freelance engineer seconded to a
   project has no company to grant. Today team membership covers them. If that must keep working,
   the person layer stays authoritative for those callers and the predicate needs a third arm -
   which is a materially more expensive design and should be decided before stage 2.

   **Answer: no, and there is no third arm.** A caller naming no organization participates in
   nothing: `holds_live_grant` answers False for `organization_id=None` rather than raising, the
   application-layer company check answers False, and the grant arm of the policy matches no row,
   because a grant names a company and there is no company to name. Two policies stay two policies.
   The freelance engineer is covered the way ADR 005 already covers them - by being a member of
   whichever company the work is contracted through - and a seconded individual with no company at
   all is a membership question, not a grant question.

## 12. Evidence and verification log

Measured on this tree, in this sandbox, CPython 3.12.8 against a real embedded PostgreSQL 16.11.

| Claim | Command or source | Result |
|---|---|---|
| `tenant_id` columns | `grep -rn "tenant_id: Mapped" app/modules --include=models.py \| wc -l` | **30**, across **16** files |
| `project_id` columns | `grep -rn "project_id: Mapped" app/modules --include=models.py \| wc -l` | **419**, across **147** files |
| files carrying both | `comm -12` over the two file lists | **11** |
| `Project.owner_id` read sites | `grep -rn "Project.owner_id" app --include=*.py \| wc -l` | **75** |
| `Project.organization_id` product readers | `grep -rn "Project.organization_id" app` | **1**, `procurement_concept/service.py:2089`, plus the repair docstring |
| RLS surface definition | `app/core/rls_setup.py:202` `tenant_tables()` | tables carrying `tenant_id`, minus `_NEVER_POLICY` |
| route-level project gate | `app/dependencies.py:920` | owner, admin or team member; 404 for missing and denied alike |
| million-row harness exists | `tests/pg/test_a_million_rows_are_rewritten_fast_enough_to_boot_on.py` | 4 x 250,000 rows, floor 20,000 rows/s |
| grant predicate performance | `tests/pg/test_the_two_arm_predicate_stays_within_a_quarter_of_the_single_condition_one.py` | **measured**: worst ratio **1.0046** against a 1.25 bar; full table in section 13.4 |
| index census on `project_id` | `both_column_tables(Base)` walked against the live catalog | **done**: all 10 both-column tables already carry a `project_id` index |

The rows above marked **unverified** when this ADR was proposed have now been run, and the numbers
in section 13 replace them.

### 12.1 The 30-versus-31 tenant-column discrepancy, reconciled

The proposal recorded **30** `tenant_id` columns from
`grep -rn "tenant_id: Mapped" app/modules --include=models.py | wc -l` and noted that an earlier
status record said 31, without reconciling the two. Reconciled on the accepted tree, both numbers
are right and neither is the number a policy is installed from:

| Step | Count | Why |
|---|---|---|
| the proposal's grep | **30** hits in **16** files | one hit is `previous_tenant_id` on `TenantBackfillEntry` (`app/modules/users/models.py:317`), a ledger column recording a value that used to be there. It is a substring match, not a tenancy column |
| real `tenant_id` columns in `app/modules` | **29** | the grep minus that one |
| tenant-owned tables declared outside `app/modules` | **+2** | `oe_activity_log` in `app/core/audit_log.py` and `oe_job_run` in `app/core/job_run.py`. The grep's path never covered them |
| `tenant_tables(Base)`, the policied surface | **31** | 29 + 2, and none of the 31 is in `_NEVER_POLICY`, so nothing is subtracted |

The consequence is not cosmetic. A census taken by grepping `app/modules` for the column name would
have installed a grant policy on 30 tables and missed the activity log - which is the table
section 8 says every grant decision is written to. `tenant_tables(Base)` reads the metadata the
policy is actually installed against, so it is the number this ADR uses from here on, and section
13.6 lists the tables it returns.

`project_id` was re-measured at the same time: **420** columns across **147** files by the same
grep (the proposal said 419), and `Project.owner_id` has **76** read sites (the proposal said 75).
Both drifted by one as the tree moved; neither number drives a decision any more, since stage 4's
remaining work is a decision per table and not a sweep.

## 13. What shipped, and where it differs from the proposal

Sections 1 to 12 are the proposal as it was written. This section is the record of what the tree
actually contains, and it is the section to read before acting on anything above. Every count here
was taken from `Base.metadata` inside a PostgreSQL test session or from the harness named beside
it; every file name was read from the tree. Where the shipped design differs from the proposal, the
difference is stated as a difference and the reason for it is given, because a document that quietly
rewrites its own proposal is how a decision loses its history.

### 13.1 Stages, commits and files

| Plan stage (section 10) | Commit | Files |
|---|---|---|
| 2. The table, its revision, and the test that the two builds agree | `b543b9ff` | `app/modules/projects/models.py` (`ProjectParticipantGrant`, `GRANT_SCOPES`, `GRANT_SCOPE_RANK`, `GRANT_STATUSES`), `alembic/versions/v3326_project_participant_grant.py`, `tests/pg/test_the_participant_grant_table_is_the_same_however_it_was_built.py` |
| 2. The service, the permission and the four routes | `8a31d546` | `app/modules/projects/{grants,permissions,schemas,router,service}.py`, `tests/pg/test_only_the_owning_organization_decides_who_participates_in_a_project.py`, `tests/unit/test_every_writer_of_a_projects_owning_company_suspends_its_grants.py` |
| 3. The second GUC, bound once per request | `e3ff3e09` | `app/core/rls.py` (`GRANTED_GUC_NAME`, `grants_enabled`, `set_request_granted_projects`), `app/dependencies.py` (`granted_projects_context`), `app/main.py`, `app/config.py` (`OE_PROJECT_GRANTS`) |
| 4, first half. The two-arm predicate on the both-column tables, measured | `e3ff3e09` | `app/core/rls_setup.py` (`grant_read_predicate`, `_grant_policy_statements`, `_apply_grant_policies`), `app/dependencies.py` (`_company_layer_allows`, `accessible_project_ids`), `tests/pg/rls_fixtures.py`, `tests/pg/test_a_grant_opens_exactly_the_project_it_names.py`, `tests/pg/test_a_grant_is_one_of_two_layers_and_both_have_to_answer_yes.py`, `tests/pg/test_the_two_arm_predicate_stays_within_a_quarter_of_the_single_condition_one.py` |
| 4, second half. The project-scoped-only tables | **not started** | 147 model files, a decision per table - section 13.7 |
| 5. Retire the accidental union | this commit | `app/modules/projects/grants.py` (`holds_live_grant`), `app/modules/procurement_concept/service.py` (`project_frameworks`, `_link_framework`), `tests/pg/procurement_concept_fixtures.py` (`add_participation_grant`), and the three test files section 13.5 names |
| 1. Census | measured during the predicate work, published here | section 13.6 |

The four routes are `POST /api/v1/projects/{project_id}/participant-grants`, `GET` on the same
path, `PATCH .../participant-grants/{grant_id}/scope` and `POST .../participant-grants/{grant_id}/revoke`.
There is no suspend route: suspension is what a change of project ownership does, not something a
caller asks for (question 4).

**Adding those four routes tripped a security ratchet, and how it was cleared is part of this
decision.** `scripts/check_security_class_ratchets.py` exists because three published advisories
(GHSA-cvgq, GHSA-vwvr, GHSA-pvpj) were all the same class: a route takes a project or object id and
checks the caller's role but never calls `verify_project_access`, which - row level security being a
deliberate no-op on those paths - is the only boundary between projects. Every route whose path
names an id and which reaches none of `ACCESS_PRIMITIVES` is a new site and fails the run. The four
grant routes name `{project_id}` and call `resolve_grant_authority` instead, so all four were
reported as new sites.

They were cleared by adding `resolve_grant_authority` to `ACCESS_PRIMITIVES`, not by adding four
entries to `scripts/security_class_baseline.json`, and the difference is not cosmetic. A baseline
entry excuses a route forever: deleting the authority call from one of them afterwards would pass
the guard, which is precisely the regression the ratchet exists to catch. An unrecognized primitive
keeps failing until somebody reads the body. And the body does check the boundary - it loads the
project and raises before any row is touched, 404 unless the caller's organization owns it, 409 when
no organization does, with no platform-admin bypass - so it is *stricter* than `verify_project_access`,
which admits team members and admins. Calling `verify_project_access` as well, purely to satisfy the
ratchet by name, was rejected for the same reason the guard's own docstring gives: helpers are
resolved to their bodies and never trusted by name, and a call added to quiet a static check is a
line that says something untrue about the route. The reasoning is recorded in the guard's docstring
beside the list it justifies, so the next person to read either half finds the other.

### 13.2 The scope vocabulary

`read` / `contribute` / `steer` shipped as **`view` / `contribute` / `manage`**, with
`GRANT_SCOPE_RANK` ordering them and a check constraint refusing anything else. Section 7's table
still describes the intended meaning of the three levels; only the words changed, to the words the
rest of the product already uses for them.

**The levels are recorded and audited but not yet differentiated.** Every shipped reader asks
whether a grant is *live*, not which scope it carries, so a `view` grant answers the same questions
a `manage` grant does today. A scope change is audited with the rank before and after, so the data
needed to enforce the difference exists. This is the single largest gap between the proposal and the
tree, it is listed as open work in section 13.7, and it is written down here because an operator who
sets `view` expecting `view` gets `manage`'s reads until that work lands.

### 13.3 One predicate, shipped as two policies

Section 4.1 proposed a single `USING` clause ORing both arms. What shipped is **two permissive
`FOR SELECT` policies on the same table**, and PostgreSQL ORs the `USING` expressions of permissive
policies, so a read sees exactly the union the proposal specified:

* `oe_tenant_isolation` - unchanged in name, predicate and command. It keeps its `IS NULL` arm, so
  `policy_is_strict` still reads a mode off a deparsed `qual` without learning a third shape, and an
  install that never sets `OE_PROJECT_GRANTS` provisions byte-identical SQL.
* `oe_project_grant_read` - `FOR SELECT`, and only:
  `(project_id)::text = ANY (string_to_array(current_setting('app.granted_projects', true), ','))`.

`FOR SELECT` is the load-bearing part. `WITH CHECK` expressions are OR'd across permissive policies
too, so a grant arm that governed writes would let a grantee insert a row carrying the *owner's*
`tenant_id` into a project it was invited to read. Keeping the grant arm on reads alone is section
7's rule that a grantee writes only rows it owns, enforced by the database rather than by every call
site remembering it. Four tests in
`tests/pg/test_a_grant_opens_exactly_the_project_it_names.py` pin it: one asserts the grant arm's
`cmd` is `SELECT` and that the tenant arm is untouched beside it; one asserts a grantee writes rows
it owns into the project it was invited to; one asserts a grantee cannot write a row carrying the
owner's `tenant_id` into that project; one asserts a grantee cannot rewrite the owner's row. Turning
the flag off is a fifth: the arm is dropped and the tenant arm stays, because `CREATE POLICY` is
guarded on `pg_policies` and never replaces an installed policy, so "off" cannot be a no-op that
leaves a widened read installed. The million-row harness re-asserts the command and the policy count
on the table it measures, so the shape cannot drift between the probe and the thing being timed.

Every database observation in those tests also records `current_user`, `session_user` and
`rolsuper`, and asserts `rolsuper is False`: a superuser bypasses every policy silently, so a
measurement taken as one would measure nothing.

### 13.4 The measurement

`oe_pipeline`, one million rows, twenty tenants, two thousand projects, the caller's company owning
50,000 rows and the granted project holding 500. Three rounds, each timing the median of five runs
after one discarded warm-up, foreign keys left in place - a table whose constraints were disabled
for a measurement is not the table the product serves. Baseline is the same table with only the
tenant policy installed; the two-arm column has both.

| query shape | single condition | two arms | ratio |
|---|---|---|---|
| `count_all_visible` - every row the caller can reach | 0.06533 s | 0.06564 s | **1.0046** |
| `listing_page` - the newest 50, what a screen does | 0.06754 s | 0.06751 s | 0.9996 |
| `read_granted_project` - the read the feature exists for | 0.00200 s | 0.00077 s | 0.3866 |

Worst ratio **1.0046** against the owner's bar of **1.25**. The two-arm reads return 50,475 rows
against the baseline's 50,000, so the comparison is not a smaller answer measured as a faster one.
The third shape is faster under two arms because the grant arm gives the planner a `project_id`
index to use where the single arm had only a tenant filter to work with.

The proposal's fallback - a denormalized owner column stamped on project-scoped rows - was not
needed and is not built.

### 13.5 The union retired, and why it could not be a policy

`project_frameworks` no longer derives cross-company visibility from team membership. It resolves
the project's company, then answers in three cases: no company resolved or no company named, an
empty list; the caller's company *is* the project's, that company's agreements; the caller's company
holds a live grant, the project's agreements **and** the caller's own - which is what being invited
in means, since a partner brings the agreements it already has to a project it was invited to.

The write half was closed in the same commit, and closing it is the more important half.
`_link_framework` - calling a framework off, which commits a company's money against an agreement -
used to accept a framework of the caller's company *or* of the project's behind nothing but the
route's access check, so a team member from a third company could call off the project owner's
agreement on the owner's package. It now asks the same participation question and answers the same
404 it answers for an agreement that does not exist, so the refusal does not become a way to ask
which companies were invited in. A read that hides an agreement while the write still accepts its id
is not one rule.

**Neither half could have been a database policy, and the reason is a column census.**
`oe_procurement_concept_framework` carries `tenant_id` and no `project_id`;
`oe_procurement_concept_award_package` carries `project_id` and no `tenant_id`. The call-off
relation crosses the two classes in section 5's table, one table each way, so there is no single row
on which both arms of a predicate could be evaluated. This is why the closure lives in the service:
not because the application layer is the convenient place, but because the database has no row here
that can answer the question. It is also why section 5 named the procurement concept tables in the
"Both" row wrongly - measured, none of them carries both columns.

The characterization test that pinned the old behaviour was replaced, not deleted, and its
replacement keeps the three facts the original was written to establish: the reader is on the
project's team, the reader belongs to a different company, and the framework is not in the reader's
own company's list - so whatever they see comes from the project arm and from nothing else. What
changed is that the project arm now asks whether their company was invited in. The route still
answers `200` with an empty list rather than `403` or `404`, because the caller *can* see the
project: refusing the request would tell them something false about the project, and an empty
framework list is the same answer a project with no frameworks gives. Which projects a caller may
open is still `verify_project_access`, unchanged, and tested where it always was.

### 13.6 The census, as the metadata gives it

`tenant_tables(Base)` returns **31** tables and `both_column_tables(Base)` returns **10**. All ten
carry a `project_id` index already, so the second policy was installed with no schema change
anywhere. Section 12.1 reconciles the 31 against the proposal's 30; the eleven-versus-ten
reconciliation is that five of the eleven model files declaring both column names declare them on
*different tables*, and no policy can be installed on a file:

| Table | `project_id` index |
|---|---|
| `oe_cost_match_run` | yes |
| `oe_dashboards_preset` | yes |
| `oe_dashboards_snapshot` | yes |
| `oe_eac_block_graph` | yes |
| `oe_eac_rule` | yes |
| `oe_eac_ruleset` | yes |
| `oe_formwork_assignment` | yes |
| `oe_pipeline` | yes, twice: `ix_oe_pipeline_project` and `ix_oe_pipeline_project_id` |
| `oe_pipeline_run` | yes |
| `oe_pointcloud_scan_dataset` | yes |

`oe_pipeline.project_id` and `oe_pipeline.tenant_id` are both nullable `VARCHAR(36)`, and a NULL
`project_id` matches no grant arm - the fail-closed direction, and the reason the harness seeds a
million rows with both columns populated on the rows it counts.

### 13.7 Deliberately not built

* **The project-scoped-only tables.** 147 model files, 420 `project_id` columns, no `tenant_id` for
  either arm to match. Still gated in the route by `verify_project_access`. This is the largest body
  of work in this ADR and it is a decision per table, not a sweep. Consequence carried forward:
  `OE_RLS_STRICT` remains blocked by this half, not by grants.
* **Scope differentiation.** Section 13.2. Live-versus-not-live is enforced; `view` versus `manage`
  is not.
* **The agent-path gate.** Section 6's requirement stands. No agent tool exposes grants, so nothing
  reaches the table except the four routes and the ownership-change suspension - which is a
  statement about today's tree, not a guard that keeps it true.
* **Acceptance by the grantee.** Question 2 answered no, so no `offered` status exists and none is
  planned.
* **A third predicate arm for individuals.** Question 8 answered no.

### 13.8 The tests that carry these claims

| Claim | Test |
|---|---|
| the table built by `create_all` and by the revision are the same table | `tests/pg/test_the_participant_grant_table_is_the_same_however_it_was_built.py` |
| only the owning organization decides, and every decision leaves an audit row | `tests/pg/test_only_the_owning_organization_decides_who_participates_in_a_project.py` |
| every writer of a project's owning company suspends its grants | `tests/unit/test_every_writer_of_a_projects_owning_company_suspends_its_grants.py` |
| a grant opens exactly the project it names, and the arm is `FOR SELECT` | `tests/pg/test_a_grant_opens_exactly_the_project_it_names.py` |
| the company layer and the person layer are an AND, and either one alone refuses | `tests/pg/test_a_grant_is_one_of_two_layers_and_both_have_to_answer_yes.py` |
| the two-arm predicate stays inside the owner's budget at a million rows | `tests/pg/test_the_two_arm_predicate_stays_within_a_quarter_of_the_single_condition_one.py` |
| the union is closed on reads and on call-offs, and the owner's own view is unchanged | `tests/pg/test_procurement_concept_service_on_pg.py::test_a_project_member_calls_off_the_projects_framework_once_their_company_participates` |
| revocation is not retroactive, and the next call-off is refused | `tests/pg/test_procurement_concept_service_on_pg.py::test_a_withdrawn_grant_closes_the_call_off_again` |
| the same closure over HTTP, including both withdrawn shapes | `tests/pg/test_procurement_concept_http.py::test_a_project_member_reads_another_companys_frameworks_only_once_a_grant_exists` |
| a legacy project with no `organization_id` still names its owner's company, and a grant to a second company opens the read | `tests/pg/test_a_legacy_project_with_no_organization_names_its_owners_company.py` |
| a caller who cannot see the project at all gets 404 on every route, frameworks included | `tests/pg/test_procurement_concept_idor.py` |

Three of these were changed by stage 5 rather than added, and each change is a deliberate reversal
of an assertion that used to pin the leak: the HTTP characterization named above, the Finding 19
service test, and the legacy-project test's framework read. Question 1's answer is what authorizes
those reversals, and each test says so in its own docstring so the reversal cannot be read as a
regression that somebody quietly accepted.

### 13.9 Two things the first CI run of this ADR taught, which a later revision will need

The PostgreSQL lane failed at `9ef684f9`, the first run that carried the whole of this ADR, and the
run page named six tests. Five of them were not this ADR's tests, and all five carried the same
error; the annotations below are that run's own text, with the five repeated lines of it folded into
one under the names of the tests it stopped:

```
tests.pg.test_tenancy_backfill_on_a_populated_database::test_upgrade_builds_the_tenancy_schema_when_it_is_absent
tests.pg.test_tenancy_backfill_on_a_populated_database::test_upgrade_run_twice_builds_the_same_schema_once
tests.pg.test_tenancy_backfill_on_a_populated_database::test_the_repair_reports_zero_on_a_database_without_the_schema
tests.pg.test_tenancy_backfill_on_a_populated_database::test_downgrade_puts_a_populated_database_back_and_removes_the_schema
tests.pg.test_tenancy_backfill_on_a_populated_database::test_downgrade_on_an_install_that_never_ran_the_repair_changes_no_data
  sqlalchemy.exc.DBAPIError: ... <class 'asyncpg.exceptions.DependentObjectsStillExistError'>:
  cannot drop table oe_users_organization because other objects depend on it
tests.pg.test_the_participant_grant_table_is_the_same_however_it_was_built::test_downgrade_removes_the_grant_table_and_leaves_everything_else_standing
  assert 2 == 1
totals: collected=80 passed=75 failed=5 errored=0 skipped=0
```

Neither cause is a defect in the grant feature. Both are properties of how this ADR's table meets
tests that were written before it, and both will be met again by whatever revision adds the next
table with a foreign key into an existing one.

**A revision is not only tested against the schema it was written on.**
`oe_projects_participant_grant` references `oe_users_organization` twice - as the grantee
(`fk_projects_participant_grant_grantee`) and as the company the grant was made on behalf of
(`fk_projects_participant_grant_on_behalf`). A real `alembic downgrade` reaches `v3325` by running
`v3326`'s downgrade first, so those references would already be gone; but the tenancy test drives
one revision's `downgrade()` by hand, which is the right way to test that revision and the reason it
met a table belonging to a later one. Its teardown dropped the organization table and the database
refused. The fix is `_drop_later_dependents`, which drops the dependents this ADR added
(`_DEPENDENTS_OF_ORGANIZATION`), then asks the catalog whether any others remain
(`contype = 'f' AND confrelid = to_regclass('oe_users_organization')`) and fails as a sentence
naming them if one does. Three details are load-bearing, and each one cost a run to find:

* it is called from **both** places that run that DDL - `_run_revision`, before any hand-driven
  downgrade, and `_drop_tenancy_schema`, after the revision's own statements - because patching only
  the fixture left the same five failures standing;
* the cast has to be `to_regclass(...)`, since a table that has just been dropped has no oid for
  `::regclass` to resolve, and the completeness question therefore has to be asked *before* the drop
  it is checking;
* the catalog's answer is filtered by `_TENANCYS_OWN_REFERENCES` (`oe_projects_project`,
  `oe_users_membership`), the two references that belong to the revision being tested and that its
  own `downgrade()` removes, or the helper names as offenders the very tables it is helping to take
  away.

`DROP TABLE ... CASCADE` was not used, and should not be: in a fixture it turns "something new
depends on this" into a silent widening of what the fixture deletes, which is how a test starts
passing for a reason nobody can state.

**`tests/pg` is one database, so an absolute row count is not a local claim.** The sixth failure was
`assert 2 == 1` in a test that counted projects after a cascade, in this ADR's own file. It passed
when that file ran alone and failed in the lane, because every test in `tests/pg` shares one
database and isolation is rollback-only: a literal `count(*) == 1` is also an assertion about every
test that ran before it. The grant-table tests now assert before-and-after deltas, survival by id,
and cascade counts scoped `WHERE project_id = :id`. Any test written against this ADR's table should
do the same, and a later revision that adds a row to a shared table should expect to meet this one.

One gap this run showed and did not close: `totals` above says `failed=5` while six tests failed,
because `scripts/publish_test_counts.py` is handed eight `--target` files in the lane's own workflow,
`.github/workflows/ci-postgres.yml`, and none of the eight is this ADR's. The sixth failure still
reached the run page - the script annotates every failure in the report, not only its targets' - but
the totals a reader compares against did not cover it, and a file that is not a target can skip
entirely without the lane noticing. Adding this ADR's files as targets is the fix, and it needs a run
to confirm that none of them skips, because the step passes `--fail-on-skip`; that is a change to
make with the evidence in hand rather than blind at the head of a pull request.

The same head's two other red jobs - `Browser cold start (windows-latest)`, and `CLI cold start`,
which is a gate over both cold-start lanes and was red because the browser leg was - were not this
ADR's either. The whole difference between the run that failed them and the run before it, which
passed, is two files under `backend/tests/pg`, which those lanes never install and never execute.
What they taught is recorded where the next reader of those lanes will look for it: in
`scripts/ci/browser_cold_start_lane.py`, in `frontend/e2e/cold-start-first-boot.spec.ts`, in
`scripts/test_browser_cold_start_lane.py`, and in the pull request that carries them.

Two later runs of the same lanes taught two more things, and both are now pinned by a test that
executes the workflow's own text rather than left in a comment beside it. At `68c4f4f7` the gate
failed with `the CLI cold start lane did not pass: abandoned` on a run where everything that ran
had passed: `abandoned` is what the CLI matrix aggregated to when its macOS leg was never acquired
by a hosted runner, and a leg that never ran is not a verdict about the product. At `07d623f7` the
browser lane skipped whole, and the run it skipped on had uploaded the bundle the lane exists to
open - `frontend-dist`, 66,351,876 bytes, unexpired, in that same run's artifacts - because the
lane's `if` read `needs.frontend.result`, an aggregate of three legs, as one verdict about a bundle
only the `ubuntu-latest` leg builds, and the macOS leg beside it had been cancelled for capacity.
Those two are in
`backend/tests/unit/test_the_cold_start_gate_tells_a_leg_that_never_ran_from_a_product_that_failed.py`
and `backend/tests/unit/test_the_browser_lane_is_not_suppressed_by_a_leg_that_built_no_bundle.py`.
Neither is this ADR's subject either, and both are recorded here because this section is where the
pull request's account of what its own CI taught it lives.
