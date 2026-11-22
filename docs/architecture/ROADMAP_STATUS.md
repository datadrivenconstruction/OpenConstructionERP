# Roadmap status

Phase status and the disposition of every significant capability: what to keep, adapt,
refactor, replace or build, with the evidence for each decision. The measurements behind
these decisions are in [FOUNDATION_AUDIT.md](./FOUNDATION_AUDIT.md); the architecture they
serve is in [TARGET_ARCHITECTURE.md](./TARGET_ARCHITECTURE.md).

Status is recorded at commit `999f3f80cf033649e92fc738f7273b7202fd695a`, audited
2026-10-28.

This file is the roadmap-status record for the intelligence programme. The repository has
no other: `docs/rfc/25-project-intelligence-audit.md` cites a `ROADMAP_v1.9.md` that does
not exist in the tree, and `git ls-files | grep -i roadmap` returns only permits-domain
code. That dangling reference is left alone here, because a path matching
`docs/ROADMAP_v*.md` is on the internal-artifact denylist in
`scripts/check_repo_hygiene.py` and creating it would fail the repo-hygiene gate.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| **01 — Foundation Audit** | Verify the live state, audit repository, architecture, capabilities and security, classify every capability, write these three documents | **Complete.** Documentation only. No code, dependency, schema, configuration or workflow change |
| **02 — ERP Hardening** | Close the control gaps that must be closed before automated agents touch data | **In progress.** Scope items 1 and 2 — the RLS strict predicate behind a readiness gate, and the central agent authorization gate — are implemented and tested, and item 1's database behaviour is now observed on a real PostgreSQL cluster; items 3 to 11 are not started. See [Phase 02 delivered](#phase-02-delivered) |
| **02b — Tenancy foundation** | Make a tenant a company rather than a person: `Organization` and `Membership`, a `tenant_id` claim on every access token, no fall-through to `sub`, a backfill for existing installs, and a tenant binding for work that has no request | **Delivered, with a listed remainder.** The blocker Phase 02 named, `tenant_is_user`, is cleared by the data model rather than by weakening the check, and the strict gate is observed opening and closing on a populated database. The agent run paths are bound; six other background paths are not, and are listed for 02c. See [Phase 02b delivered](#phase-02b-delivered) |
| **03 — Intelligence Core foundations** | Versioned domain contract, ontology, graph and evidence projections, governed tool platform | Not started |
| **04 — Reasoning** | Cross-domain dependency, impact and quantitative risk engines | Not started |
| **05 — Interaction** | Unified simulation, ranked decision support, proactive detection, multimodal ingestion, voice | Not started |

Phase numbering after 02 is a proposal. It should be re-derived from evidence when Phase 02
closes, not treated as committed.

## Decision summary

| Disposition | Count | Meaning |
|---|---|---|
| **KEEP** | 21 | Working and tested. Build on it; do not duplicate it |
| **ADAPT** | 14 | Right mechanism, insufficient reach or coverage. Extend in place |
| **REFACTOR** | 5 | Right capability, wrong structure. Change the shape, not the behaviour |
| **REPLACE** | 2 | A named implementation is wrong for the requirement, and the replacement is narrow |
| **BUILD** | 11 | Does not exist. No working code would be duplicated by building it |

The KEEP count is the important one. This is a mature platform with 213 modules, 4,627
routes, 788 models and a test estate in the thousands of files. Most of what an
intelligence layer needs is already here, and the cheapest available mistake is building a
second one of something that works.

## KEEP

Kept as-is, with the evidence that justifies keeping rather than rewriting.

| Capability | Evidence | Why it is kept |
|---|---|---|
| Module system and loader | `core/module_loader.py` (918 lines), 213 manifests, dependency-sorted loading, auto-mounted routers and models | The platform's best structural idea. Drop-in extension is real on the backend and is the seam the intelligence layer plugs into |
| RBAC permission engine | `core/permissions.py` (374 lines), 8-role hierarchy with aliases, 171 module `permissions.py` files, 215 dotted action keys, `scripts/check_permission_registration.py` | Complete, guarded, and already used at the router edge via `RequirePermission` |
| Validation engine | `core/validation/` — 16 files, 18,767 lines, rules plus a DSL, severity-weighted reporting | The largest concentration of encoded construction knowledge in the repository, and the base for the ontology |
| Canonical conversion approach | [ADR-002](../adr/002-no-ifcopenshell-ddc-canonical-only.md); DWG, DGN, RVT and IFC as inputs, one canonical JSON internally | A deliberate, recorded decision that removes a heavy native dependency. Reversing it would need an argument nobody has made |
| BOQ and cost domain | 21 cost-related modules, 100 BOQ and 103 cost test files | Deepest area in the platform. Nothing here should be reimplemented |
| Common data environment | `documents`, `cde`, 14 `file_*` modules, `transmittals`, `submittals`, `signing`, `opencde_api`, 40 document and 16 CDE test files | A full document-control surface with versioning and approval |
| Scheduling | `schedule`, `schedule_advanced`, `timeline`, `core/cpm.py`, 74 plus 11 test files | Real CPM logic in core, not a stub |
| Contracts and commercial control | `contracts`, `eac`, `full_evm`, `cvr`, `commitment_release`, `payment_release`, `reconciliation`, 86 contract test files | Earned-value and commitment machinery is expensive to rebuild and already tested |
| BIM and coordination | `bim_hub`, `bim_requirements`, `bcf`, `clash`, `coordination_hub`, `pointcloud`, 63 BIM and 26 clash test files | Substantial, on the canonical format |
| Storage abstraction | `core/storage.py` (1,830 lines), local and S3 backends, presigned URLs, multipart, signed upload tokens | One ABC over two backends, exactly the right shape for evidence storage |
| Audit trail | `core/audit_log.py` (552 lines) with `AuditContext` and `ActivityLog`, plus gates, pruning and a router; five Alembic revisions extending and indexing it | Already records actor, action and bounded state. Agent runs write into the same discipline |
| Trust envelope | `ai_agents/trust.py` (458 lines): calibrated confidence, rationale, sources by real id or path, `what_would_increase_confidence` | This is the evidence-traceability requirement, already implemented in pure standard library |
| Accuracy scoreboard | `accuracy.py`, `accuracy_service.py` (218 lines), `feedback_summary.py`, runs stored with a trust payload and `actual_outcome` | Stores the outcomes needed to calibrate later phases. Rare and valuable |
| Agent runtime | `ai_agents/base.py` (652 lines): tool loop, observation truncation, per-step timeouts, structured token accounting | A real runtime, not a wrapper. Extend it; do not replace it |
| Propose-then-apply | `ai_agents/proposals.py` (339 lines) with cross-currency rejection | The human-approval pattern, already working for BOQ |
| Event bus and hooks | `core/events.py` (513 lines) with detached publish, `core/hooks.py` (171 lines) separating error-propagating filters from swallowed actions | The decoupling mechanism that lets an intelligence layer subscribe without importing modules |
| Authorization test estate | 45 IDOR and cross-tenant integration files plus a dedicated CI job with a documented selection chain | The compensating control for weak database-level isolation, and the regression net for Phase 02 |
| Guard battery | 69 `check_*` scripts, including the architecture-manifest guard that keeps a generated artifact honest | Encodes hard-won lessons. Every phase adds guards rather than removing them |
| Regional pack architecture | 50 packs under `packs/`, 13 regional modules, [ADR 2026-05-28](../adr/2026-05-28-partner-pack-architecture.md) | Extension point for jurisdiction-specific intelligence |
| Localization | 45 locale files, 44 offered languages, RTL and Hijri dependencies, an LLM translation path, 12 locale guards | Arabic and English are already first-class, which the long-term vision requires |
| Supply-chain and release gates | `dependency-review.yml` with a copyleft denylist and `fail-on-severity: high`, `sbom-and-licenses.yml`, `secret-scan.yml`, `check_dependency_licences.py`, `release-signing.yml` | Working security policy. Phase 02 adds analysis, never relaxes these |
| Secret and CORS enforcement | refusal to boot on a weak or short `JWT_SECRET` outside development, with dev-mode rotation and persistence; production CORS wildcard refusal | Correctly fail-closed already |

## ADAPT

The mechanism exists and is sound; its reach, coverage or enforcement is what falls short.

| # | Capability | Evidence | What changes | Dependencies | Risks | Phase |
|---|---|---|---|---|---|---|
| A1 | Row-level security | `rls.py` (142 lines), `rls_setup.py` (443 lines); `rls_enforce` defaults to False; predicate admits NULL `tenant_id`; only 29 `tenant_id` columns across 15 of 169 `models.py` files | Enable on a documented path: connect as the non-superuser `oe_app` role, backfill `tenant_id`, then tighten to a strict predicate. The code already describes this as the intended sequence. **Phase 02: strict predicate and readiness gate delivered; the role change and the backfill are still open.** | A database role change, a backfill per table, and the 45 IDOR tests as the acceptance net | Breaking existing installs if the strict predicate lands before the backfill; mitigated by keeping the permissive policy until coverage is measured per table | **02** |
| A2 | Tool platform governance | `ToolRegistry`, `FunctionTool`, `__agent_context__` injection in `base.py`; `required_permission_for_tool` in `triggers.py`; `agents/_access.py::assert_user_can_access_project` | Move the check from convention into the registry: resolve the required permission, verify caller authorization and project access, then invoke. No tool signature changes. **Phase 02: delivered, in the runner rather than the registry; no tool signature changed.** | A1 for scoped reads; the existing permission registry | Over-blocking legitimate tools; mitigated by failing closed only for tools that declare a permission, and logging every denial | **02** |
| A3 | Inference declarations | `InferenceDeclaration` validated by the loader, guarded by `check_module_inference_declarations.py`, tested by 3 files, adopted by **9 of 213** manifests | Extend adoption to every surface that produces a machine-derived conclusion, then make the guard ratchet so the count cannot fall | None | Large but mechanical; the risk is declaring inaccurately, which is worse than not declaring | **02** |
| A4 | Project intelligence | `project_intelligence` (11 files, 4,899 lines); [RFC 25](../rfc/25-project-intelligence-audit.md) records "13 hardcoded if-then rules", "no ML, no anomaly detection, no forecast", status draft | Implement RFC 25's chosen Option A: keep the shell, retarget the widgets to financial metrics, tighten the cache, reposition the advisor. The RFC already specifies endpoints, frontend shape and a testing plan | The domain contract (B1) for financial metrics; A2 for any agent involvement | Duplicating RFC 25's work by designing a parallel module. The RFC's Option B was explicitly deferred | **03** |
| A5 | Risk engine | `risk` (14 files, 4,763 lines); `accuracy_service.py` stores recorded outcomes | Grow from register to quantitative exposure, calibrated against recorded outcomes that already exist | B1, B4 for evidence links | Producing numbers with no basis; mitigated by the trust envelope's rule that confidence is never fabricated | **04** |
| A6 | Impact analysis | `change_intelligence` (24 files, 10,720 lines), `clash_cost_impact`, `variations`, `eac`, `estimate_rollup` | Connect per-domain impact into cross-domain propagation from one originating event | B3 dependency graph | Double-counting impact across domains; needs one propagation owner | **04** |
| A7 | Semantic match service | `core/match_service/` (24 files, 7,803 lines), `core/vector*.py`, [ADR-003](../adr/003-vector-match-service.md), optional `vector` extra | Reuse as the derived evidence index rather than building a second vector path; add provenance per embedding | B1 contract versioning | Treating a projection as authority, which ground rule 1 forbids | **03** |
| A8 | Proactive triggers | `triggers.py` (135 lines) with `EventTrigger`, `scheduler.py` (182 lines), `core/events.py` | Add the detection layer that decides what is worth raising; the trigger and scheduling machinery stays | A2 governance, since proactive runs act without a person asking | Unsolicited agent runs are the highest-risk surface; they need the strictest permission defaults | **05** |
| A9 | Retrieval | `modules/retrieval` (10 files, 1,826 lines), facet query over documents, correspondence and change orders, project-scoped with bounded reads | Extend to evidence-linked search returning citations, not only records | B4 | Unbounded reads; the module already bounds per source and that discipline must survive the extension | **03** |
| A10 | Rate limiting | `core/rate_limiter.py` (191 lines), in-process, its own docstring says "For production, replace with Redis-based implementation"; 26 usage points | Same interface, Redis-backed implementation when more than one process serves traffic. `celery[redis]` is already available via the `server` extra | A Redis deployment | Changing the interface would touch 26 files; the adaptation is deliberately behind the existing one | **02** |
| A11 | Caller scoping | `core/cost_scope.py` (308 lines) with `bind_caller`, `caller_scope`, `system_scope`, `visible_ids`; `RequestScopeMiddleware` | Reuse as the scope every agent read passes through, so tool reads inherit the same visibility rules as HTTP reads | A2 | Background sessions deliberately bypass scope; that distinction must stay explicit for agent work. **Phase 02: partly — the event bus was missing the binding the other two run paths apply, and now has it; reusing `cost_scope` for every agent read is still open.** | **02** |
| A12 | Backup and recovery | `modules/backup` (7 files) with a derived model registry and sensitive-field redaction; `check_backup_freshness.py` | Extend to cover derived stores and to document a restore path, including the boot-time schema heal it must survive | A1, R3 | A restore that lands on a schema produced by boot-time DDL is not reproducible today | **02** |
| A13 | Architecture documentation | prose counts stale across `README.md`, `OVERVIEW.md` and `llms.txt` while the generated manifest is exact | Apply the remedy the repository already proved: generate the numbers, or guard them, as `check_architecture_manifest.py` and `check_public_language_counts.py` do | None | Low. The risk of not doing it is that the next reader trusts 16.2.0 | **02** |
| A14 | Multimodal ingestion | `match_service` extractors including DWG, `cv`, `pdf_paint_scan.py`, `inbound_capture`, `ai_estimator` (19 files, 11,016 lines) | Unify into one ingestion path that emits evidence-linked observations with citations | B4, A7 | Duplicating four working extractors; the unification is a façade over them, not a rewrite | **05** |

## REFACTOR

Behaviour is correct and tested; structure is what obstructs the next phase.

| # | Target | Evidence | Reason | Dependencies | Risks | Phase |
|---|---|---|---|---|---|---|
| R1 | Composition root | `backend/app/main.py` is **5,520 lines** and owns app construction plus schema healing, Alembic head checks, OpenAPI priming, boot-phase reporting, a heartbeat thread, data-repair publishing, self-upgrade and `/api/health`. Its comments record a 139.7-second startup that starved the health check | A file that constructs the application should not also perform operational surgery on the database. Splitting it makes boot stages individually testable and makes startup latency measurable | R3 shares the boot path, so sequence them | Touching startup is high-risk; mitigated by extracting pure functions first, one commit per stage, with the existing startup tests as the net | **02** |
| R2 | Framework versus domain in `core/` | `core/` holds 175 entries mixing framework code (`module_loader.py`, `events.py`, `storage.py`, `validation/`) with construction-domain code (`cpm.py`, `boq_target.py`, `cde_states.py`, `cde_naming.py`, `classification_registry.py`, `country_coverage.py`, `calendar.py`, `cost_scope.py`), while `docs/architecture/README.md` describes `core/` as "not tied to any one feature" | Ground rule 6 requires the layers to be distinguishable by location. A separate intelligence package cannot depend on a domain contract that lives inside the framework namespace | B1, which is the contract the extracted domain publishes | Very high blast radius: `core/` is imported everywhere. Must be incremental, module by module, with import guards added as each move lands | **03** |
| R3 | Migration reproducibility | `core/postgres_migrator.py` (1,345 lines) stamps rather than runs Alembic, heals indexes and columns at boot under an advisory lock, best-effort per statement with skipped statements logged; `main.py` adds deferred foreign-key healing and `UNVALIDATED_CONSTRAINTS_SQL`; 428 revisions are tracked | The live schema is not reproducible from migration history, and constraints can exist unvalidated. That obstructs audit, point-in-time recovery and any claim about data integrity | R1, A12 | The boot-time heal is what makes self-hosted upgrades easy, so removing it outright would regress a real user benefit. The refactor keeps the convenience and adds a reproducible path alongside it, rather than replacing it silently | **02** |
| R4 | Frontend registration | 318 `<Route path=` entries hand-written in `App.tsx`, 154 sidebar rows hand-maintained in `navCatalog.ts`, 208 feature folders that nothing discovers, 16 plugin manifests that do get their routes automatically | Two registration systems with different guarantees, both hand-maintained, is where screens go missing. The plugin registry already proves the automatic path works | None | Regressions in navigation are user-visible immediately; the 1,196 frontend test files and the route-death checks are the net | **03** |
| R5 | API contract artifact | `api-types.ts` is generated from a running backend by `npm run api:generate` and is **not tracked** (`git ls-files` returns nothing); `docs/architecture/README.md` nonetheless describes a "generated API client" in `shared/`, which holds one file | A frontend cannot type-check against the API without booting the backend, and 21 of 208 features have no backend mapping in the manifest. A published contract is also the natural source for typed agent tools | B12 | Committing a generated file invites drift; the alternative is generating it in CI, which needs the backend bootable there — already true for the PostgreSQL matrix | **02** |

## REPLACE

Only two implementations are wrong for the requirement, and both replacements are narrow.
Nothing here is a wholesale rewrite, and no working functionality is duplicated.

| # | Replaced | Evidence | Reason | Replacement | Dependencies | Risks | Phase |
|---|---|---|---|---|---|---|---|
| P1 | The hardcoded rule scorer inside `project_intelligence` | RFC 25: "scoring is 13 hardcoded if-then rules; an LLM narration sits on top, but no ML, no anomaly detection, no forecast"; `_GAP_RULES` and `_ACHIEVEMENT_RULES` in `scorer.py`; the RFC rates the achievements card "Low — vanity metric" | Rule tables cannot produce the financial readiness signal the page is asked for, and RFC 25 has already decided the remedy | The RFC's Option A: keep the shell, swap the widgets for KPI cards and analytics, drop the vanity metric, tighten the cache. Option B (a parallel new module) was explicitly deferred and stays deferred | A4, B1 | Building a second intelligence module beside this one, which is precisely what Option B warned against | **03** |
| P2 | The in-memory rate limiter implementation | `core/rate_limiter.py` docstring: "Simple in-memory rate limiter (no Redis required) ... For production, replace with Redis-based implementation" | Per-process counting makes the effective limit the configured limit times the process count, and login throttling is weakest under horizontal scale — the condition it exists to protect against | A Redis-backed implementation of the same interface, selected by configuration, keeping the in-process one for single-node and desktop installs where it is correct | A10, the existing `server` extra | Losing the zero-dependency install path. Avoided by making it a backend choice behind the same interface, not a new requirement | **02** |

## BUILD

Does not exist in any form. Each item is checked against the tree before being listed, so
none of these duplicates working code.

| # | Item | Evidence it is absent | Reason it is needed | Dependencies | Risks | Phase |
|---|---|---|---|---|---|---|
| B1 | Versioned canonical construction domain contract | The canonical JSON form covers CAD and BIM inputs ([ADR-002](../adr/002-no-ifcopenshell-ddc-canonical-only.md)) but no single contract spans projects, cost, schedule, procurement, documents and site records; the 788 models are the de facto contract and are not published | A separate intelligence package needs something stable to depend on instead of importing 788 models. This is the precondition for ground rule 5 | R2 | Over-specifying early and freezing a wrong shape; mitigated by versioning the contract and shipping it read-only first | **02** |
| B2 | Construction ontology layer | `core/validation/` encodes rules and registries; nothing exposes typed relations between construction concepts as queryable meaning | Rules can check data but cannot answer what something is or how it relates, which every reasoning capability needs | B1 | Duplicating the validation rule set; the ontology must reference the existing rules, not restate them | **03** |
| B3 | Project Intelligence Graph | No entity graph over project data exists. The only dependency graph in the tree is over modules, in `architecture_manifest.json` | Cross-domain reasoning needs edges between cost items, activities, documents, resources and risks | B1, B2, A7 | A graph that becomes a second source of truth; ground rule 1 forbids it, and the projection must be rebuildable and provenanced | **03** |
| B4 | Evidence Graph | `TrustEnvelope` cites sources per answer; sources are not linked into a traversable structure | "What supports this conclusion" must be answerable by traversal, and every citation must resolve to a record and a version | B3, the CDE, `claims_evidence` | Citations that resolve to stale versions; each edge must carry the document version | **03** |
| B5 | Cross-domain Dependency Engine | `depends` resolves module load order; `core/cpm.py` resolves schedule networks; nothing links a cost line to the drawing and activity it derives from | Impact and simulation both need dependency traversal across domains | B3 | Cycle handling and ambiguous derivation; needs an explicit, cited derivation record rather than inference | **04** |
| B6 | Unified simulation scenarios | BOQ what-if and `schedule_advanced` simulate inside their own domains; there is no scenario object holding a set of assumptions and reporting combined effect | What-if answering requires one assumption set evaluated across cost, schedule and procurement | B5 | Non-reproducible scenarios; every result must record the assumptions and the data version | **05** |
| B7 | Proactive detection layer | `triggers.py` fires on declared events and `scheduler.py` runs on a schedule; nothing decides that an unasked-about condition warrants attention | Proactive intelligence is the difference between a tool that answers and one that warns | A8, B5 | Alert fatigue and unrequested agent action; the strictest permission defaults and a citation requirement per alert | **05** |
| B8 | Agent authorization policy service | Permission is enforced at the HTTP edge by `RequirePermission` and, by convention, inside tools; `required_permission_for_tool` maps names to permissions but the registry does not enforce it | Ground rule 4 and the execution contract need one place where an agent's authority is defined, checked and logged | A2, A3 | Duplicating the RBAC engine; the service must consume it, never reimplement it. **Phase 02: delivered as `ai_agents/tool_authorization.py`, which consumes `PermissionRegistry` and `agents/_access.py` and reimplements neither.** | **02** |
| B9 | Approval records for agent-proposed mutations | `proposals.py` implements the flow for BOQ positions; `approval_routes` exists as a module; there is no general record of "an agent proposed X, person Y approved it at Z" across domains | Human approval must be auditable for every sensitive operation, not only BOQ applies | B8, the audit log | Two approval systems; extend the audit discipline already in place | **02** |
| B10 | Metrics and tracing | Only `/api/health` was found; no `metrics`, `ready` or `live` route in `main.py`; no tracing | Capacity, latency and saturation cannot be answered from the platform, and the recorded 139.7-second startup incident shows the cost of that blindness | R1 | Metric cardinality explosion over 4,627 routes; label discipline must be defined before the first endpoint | **02** |
| B11 | Import-boundary guard for the intelligence package | No such guard exists among the 69 `check_*` scripts, and nothing today prevents a new package from importing `app.core` internals | Ground rule 5 has to be enforced mechanically, or the separation survives only as long as reviewers notice. The repository's own history, recorded in `check_architecture_manifest.py`, is an argument for guards over memory | B1 | A guard that fires on legitimate code gets deleted; scope it to the new package only | **03** |

## Phase 02 scope, as recommended

Phase 02 is ERP hardening: close the control gaps before automated agents are given wider
reach. It contains no new intelligence capability, on purpose.

1. **A1** — the RLS enablement path: non-superuser connection, measured `tenant_id`
   coverage, backfill, then a strict predicate, with the 45 IDOR tests as acceptance.
   **Partly delivered**: the strict predicate, the readiness gate and both directions of
   the mode transition are implemented and tested. The role change, the coverage
   measurement and the backfill are not, and the readiness report still refuses strict on
   a stock install — see [Phase 02 delivered](#phase-02-delivered).
2. **A2 and B8** — enforce tool authorization in the registry, and give agent authority one
   defined home. **Delivered**, with one correction to the wording: the gate is in
   `AgentRunner.run`, not in `ToolRegistry`, because the registry has no execution method
   and the runner holds the only `tool.run(...)` call.
3. **B9** — general approval records for agent-proposed mutations.
4. **A3** — inference declarations beyond the current 9 of 213, with a ratcheting guard.
5. **R3** — a reproducible migration path alongside the boot-time heal.
6. **R1** — split the composition root, stage by stage.
7. **B10** — metrics and tracing, with label discipline agreed first.
8. **A10 and P2** — a Redis-backed rate limiter behind the existing interface.
9. **R5 and B1** — a published, versioned API and domain contract.
10. **A13** — correct or generate the stale documentation counts, including the structural
    claims in `llms.txt` about `services/`, Kubernetes and a root `alembic/` directory.
11. **CSP tightening plan** — `script-src` currently allows `'unsafe-inline'` and
    `'unsafe-eval'`; a nonce or hash migration is a project in itself and Phase 02 should
    produce the plan and the first measured step, not a claim that it is solved.

Explicitly out of Phase 02: the ontology, the graphs, simulation and proactive detection.
They depend on the contract and the authorization gate, and starting them first would build
reasoning on top of an unenforced boundary.

## Phase 02 delivered

Two of the eleven scoped items are implemented and tested; the other nine are untouched.
This section records what changed, what was verified and what is still open, so a later
reader does not have to reconstruct it from a diff.

### What changed

| Item | Change | Files |
|---|---|---|
| **A1** | A strict tenant predicate beside the permissive one, and a readiness gate in front of it. `OE_RLS_STRICT` is refused unless `rls_readiness_report` is clean; the refusal is logged, returned as `strict_refused`, and provisioning continues in permissive mode so asking for strict can never leave a table with no policy. Mode changes apply in both directions, so turning strict off drops the strict policy and recreates the permissive one. The readiness endpoint now also reports `strict_requested`, so a silent downgrade is visible without reading the boot log | `core/rls_setup.py`, `config.py`, `modules/admin/rls_router.py` |
| **A2 / B8** | One mandatory authorization gate for every agent tool call, in the runner immediately before the single `await tool.run(...)`. It resolves the principal from the trusted context, the tool's permission from `TOOL_PERMISSIONS`, the caller's current role from the database, and every project the call names in either the context or the arguments; fails closed on anything missing, unparseable or raising; refuses arguments that try to name a principal; denies before the tool is reached; and logs the denial at `WARNING` without the arguments. All three production execution paths pass an authorizer, and all fifteen registered tools name a permission | `ai_agents/tool_authorization.py` (new), `ai_agents/base.py`, `ai_agents/router.py`, `ai_agents/service.py`, `ai_estimator/service.py`, `ai_agents/triggers.py` |
| **A11** (repair) | The event bus started agent runs without the `cost_scope.caller_scope` binding that the scheduler and the HTTP background task both apply, so the same agent read a wider cost catalogue when an event fired it than when its schedule did | `ai_agents/events.py` |

Nothing else moved: no schema, no migration, no dependency, no workflow and no frontend
file. The contract these changes establish — ownership semantics, database roles, policy
semantics and the tool-registration obligations — is written up in
[TARGET_ARCHITECTURE.md](./TARGET_ARCHITECTURE.md#what-phase-02-added).

### Evidence

Executed locally, for real, on Python 3.11.2 with pytest 8.4.2 and `--noconftest`:

- **50 new tests, all passing.** `test_rls_strict_policy_is_refused_until_the_database_is_ready.py`
  (14) pins the refusal and permissive fallback, the no-NULL-escape strict predicate, that
  `ENABLE` and `FORCE` survive, that strict is inert while enforcement is off, that the
  rollback drops the strict policy and drops it before recreating, that an unrecognised
  policy is never dropped, and that an unreadable catalog does not stop provisioning.
  `test_every_agent_tool_call_passes_one_mandatory_authorization_gate.py` (34) pins the
  authorized path, every denial code, the forged-context and forged-identifier cases, the
  absence of side effects on a denial, what the denial payload and log line may contain,
  the distinction between refusal / unknown tool / tool failure, and both ratchets.
  `test_an_event_triggered_agent_run_reads_costs_as_its_creator.py` (2) pins the scope
  binding on every dispatch path.
- **No regression, measured rather than assumed.** A pristine worktree at the audited
  commit and the working tree were both run over the same 67 test files selected by name
  across `rls`, `ai_agents`, `ai_estimator`, `tenant`, `permission`, `settings` and
  `admin`: **555 passed / 20 failed / 236 errors / 13 skipped** before, **569 passed /
  20 failed / 236 errors / 13 skipped** after. The single difference is the new RLS file.
  Every pre-existing failure and error is unchanged and environment-caused.
- **All 67 `scripts/check_*.py` guards return identical exit codes** before and after:
  53 pass, 9 fail, 5 need arguments — the same 14 pre-existing environment cases in both
  trees.
- **`ruff==0.16.6`**, the version CI pins, reports `check` and `format --check` clean on
  all twelve changed files.
- **The permissive path is byte-identical.** `_policy_statements(table)` with
  `strict=False` emits exactly the SQL the audited version emitted, and the two early-return
  stats dictionaries that `test_a_worker_that_waited_for_the_rls_lock_provisions_after_it`
  pins exactly are untouched.
- **Each new ratchet was mutation-checked**: removing an authorizer from a call site,
  unmapping one tool, and removing the scope binding each fail the test meant to catch
  them, and each file was restored byte-identically afterwards.
- **CI at the commit that carried the code** (`beb2b94`): 8 of 8 workflow runs `success`
  and 46 of 46 check runs `success`, including CI at 20 of 20 jobs and CI (PostgreSQL) at
  16 of 16. The Tenant Isolation / IDOR job passed, which is the acceptance net this phase
  was told to preserve, and the embedded-PostgreSQL matrices passed on Linux, Windows and
  macOS, which is where the RLS and agent-runtime suites actually execute. The intermediate
  commit `dc509d6` failed Repo hygiene on the architecture-manifest step, because a new
  module file is manifest drift; `beb2b94` repairs it, and the two matrix runs on
  `dc509d6` were cancelled by that superseding push, so no signal was lost.

### Observed on a real PostgreSQL cluster

The evidence above was SQL generation and decision logic. This is behaviour, and it
was observed rather than inferred, on the PostgreSQL 16.11 cluster that
`pixeltable-pgserver` 0.5.1 bundles and `app/core/embedded_pg.py` boots - the same
mechanism the *CI (PostgreSQL)* workflow uses, reached locally by installing that
wheel and running the lane with its own gate, `OE_TEST_DB=pg`. Without the gate the
lane reports `PG lane only` and skips; the new tests were confirmed to skip without
it and pass with it, so a green run cannot be a collection that never happened.

| What ran | Result |
|---|---|
| `tests/pg/test_a_strict_rls_policy_is_enforced_by_the_real_database_role.py` (new) | 18 passed |
| `tests/pg/test_rls_strict_mode_is_refused_until_the_database_is_ready_and_rolls_back.py` (new) | 15 passed |
| `tests/pg/test_a_background_session_keeps_the_connecting_role_and_is_not_policied.py` (new) | 5 passed |
| `tests/pg/test_rls_readiness_report_measures_the_real_database.py` (existing) | 3 passed |
| `tests/pg/test_rls_ws_handshake.py` (existing) | 10 passed |
| `tests/integration/test_rls_enforcement.py` (existing, previously unrunnable here) | 11 passed |
| `tests/unit/test_the_rls_tenant_binding_has_one_call_site_so_background_work_is_unpolicied.py` (new) | 3 passed |

*Corrected by Phase 02b:* that file is now
`tests/unit/test_which_paths_bind_a_tenant_and_which_still_do_not.py`. Its name asserted an
invariant - one call site - which was true when it was written and which Phase 02b changed on
purpose, so keeping the name would have kept a false claim in the tree and keeping the
assertion would have failed for exactly the reason it was written to detect. The pin survives,
corrected: which paths bind a tenant, which still do not, and that the ones that still do not
are the 02c list rather than an oversight nobody wrote down. The count in the row above is the
count at the time it ran, and is left as it was.
| the three Phase 02 unit suites | 50 passed |

Fifty-one of those ran in the PostgreSQL lane in a single session, and the eleven in
`test_rls_enforcement.py` had never run in this environment before: they need a
cluster, and they provision the real roles through `apply_rls` and drive raw SQL
through the application's own `async_session_factory`, so the `after_begin` listener
does the role downgrade exactly as it does for a request.

The role under test is `oe_app`, entered with `SET LOCAL ROLE` and with
`app.current_tenant` bound transaction-locally, which is how a real request enters
it. The cluster's session user is the `postgres` superuser, so every isolation
assertion also records `current_user` and that user's `rolsuper` flag: a superuser
bypasses every policy silently, and a test that did not prove which role answered
would pass just as happily with no policy installed.

What PostgreSQL actually did:

| Situation | Observed |
|---|---|
| Strict policy, caller bound to tenant A | reads A's two rows of four; `current_user` is `oe_app`, `rolsuper` false |
| Strict policy, caller bound to tenant B | reads B's one row; never A's, never the unowned one |
| Strict policy, no tenant bound (anonymous request) | GUC set to the empty string, zero rows: fails closed |
| Strict policy, a tenant value that matches nothing | zero rows, including a value shaped like an injection |
| Same query as the connecting superuser | all four rows, so the two above are a policy and not an empty table |
| `UPDATE` / `DELETE` of another tenant's row, committed | `rowcount` 0 and the row unchanged |
| `DELETE FROM t` with no predicate at all, committed | 2 rows, the caller's own; other tenants' rows survive |
| `INSERT` naming another tenant | refused: `new row violates row-level security policy` |
| `INSERT` with a NULL tenant under strict | refused, so a strict install cannot grow the backlog it hides |
| The same NULL insert under the permissive policy | accepted, which is the difference between the two modes |
| Row-level security enabled with no policy at all | zero rows: enabled-and-unpolicied denies |
| `oe_system`, tenant bound | all four rows: `rolbypassrls` true, `rolsuper` false |
| `pg_policies.qual`, both modes | deparsed with and without the `IS NULL` arm, and `policy_is_strict` reads both correctly |
| `relrowsecurity` / `relforcerowsecurity` | both true, so the owner is bound as well |
| `oe_app` in `pg_roles` | `rolsuper`, `rolbypassrls`, `rolcanlogin`, `rolinherit` all false, with `SELECT`/`INSERT`/`UPDATE`/`DELETE` on the table: privileges and isolation are separate facts, and a denial here is the policy rather than a missing grant |
| `verify_rls_role` after `ALTER ROLE oe_app SUPERUSER` | raises `RLSConfigurationError`; passes again once the attribute is removed. Same for `BYPASSRLS` |
| The six `_NEVER_POLICY` reference tables | row-level security not even enabled, no policy row, and readable by `oe_app`: a global record is excluded by name, not admitted by a NULL escape |
| Strict refused, then the rows backfilled, then the same call | refused with `strict_refused`, permissive installed; after the backfill `ready_for_strict` is true and the same call installs strict, reporting `policies_replaced: 2` |
| Strict switched back off | `policies_replaced: 2`, the permissive predicate installed, and the row strict had been hiding readable again |
| Three enable/disable cycles | each ends in the mode asked for, and tenant B never reads tenant A's row in either mode |
| A policy this code does not recognise | left in place, `policies_replaced: 0`: an administrator's own policy survives a boot |

`CREATE ROLE` inside the guarded `DO` block was separately confirmed to succeed
inside an explicit transaction, which is what lets provisioning create the roles in
the same transaction that takes the advisory lock.

### The CI run that carries this evidence

Recorded because "the tests pass" is not checkable without naming where they
passed, and because part of this is inference rather than observation and has to
be labelled as such.

At commit `4adcfd2`, which is the commit that carries these tests:

| Workflow run | Result |
|---|---|
| CI (PostgreSQL) `40764424145` | `success`, 16 of 16 jobs, including `backend-postgres` and `Object ownership and cross-tenant access` |
| Repo hygiene (both events) | `success` |
| Authors Guard, Dependency Review, Secret scan (both events) | `success` |
| CI `40764424102` | `failure`: 16 of 20 jobs `success`, 4 `cancelled` |
| Check runs at that commit | 46 total, 42 `success`, 4 `cancelled` |

The four cancelled jobs are all `macos-latest`: the three embedded-PostgreSQL
Backend CI shards and Frontend CI. They never ran anything. Each has an empty
runner name, **zero steps**, 21 minutes in the queue, and the annotation "The job
was not acquired by Runner of type hosted even after multiple attempts" beside
three notices that "jobs targeting macOS arm64 runners may experience longer
queue times". Every Linux and Windows sibling in the same matrices succeeded, and
the same pattern occurred earlier on this branch and resolved on its own, so this
is runner capacity and not a result about the code. Both re-run endpoints refuse
this token (`403 Resource not accessible by integration`), so it could not be
retried from here; re-running those four jobs is an owner action.

Which jobs executed the new tests, and why that is known rather than hoped:

* `backend-postgres` runs `pytest tests/pg` with `OE_TEST_DB: pg` set at job
  level. The lane skips only when that variable is absent, so the three new files
  there ran rather than skipped.
* `backend` runs `pytest tests/unit --splits 6` on Linux and `backend-cross-os`
  runs the same directory `--splits 3` on Windows and macOS, so the new unit file
  was collected on Linux and on Windows. The macOS shards are the cancelled ones.
* All five files are in the tree at that commit, and a collection error makes
  pytest exit non-zero, so a green step means they were collected and passed.

What is inference: Actions job logs cannot be downloaded from this environment
(the results blob host is outside its egress allowlist), so the per-test CI
listing was never read. The claim above rests on the gate being set at job level,
the files being present, and the steps concluding `success` - not on a log line
naming each test. The behaviour itself was observed directly and locally, which
is the stronger of the two: the cluster, the roles, the policies and the row
counts in the table above were read from a running PostgreSQL 16.11, and the same
files were separately confirmed to skip without `OE_TEST_DB=pg` and pass with it,
so a green run cannot be a lane that never started.

### Tenant identity: what the investigation found

`tenant_is_user` is not a defect in one login flow. It is the documented shape of
the platform, and the evidence is a chain rather than a single reading:

* **No tenant claim is issued, anywhere.** `create_access_token` builds
  `iss`, `sub`, `email`, `role`, `iat`, `exp`, `type`, `jti` and an optional `sid`,
  and nothing else. It has exactly one caller, `_issue_token_pair`, which all six
  token-minting flows reach: `login`, `demo_login`, `desktop_bootstrap`,
  `oidc_login`, `refresh_tokens` and `change_password`. The `extra_claims`
  parameter exists and no caller in the application passes it.
* **So the resolver always falls through.** `resolve_tenant_id` prefers a
  `tenant_id` claim and falls back to `sub`; with no claim ever issued, every
  authenticated request resolves its tenant to the user's own id.
* **That is the intended semantics, not an accident.** `core/tenant_scope.py`
  states there is no separate Tenant or Org entity and no `tenant_id` claim, and
  that the tenant is the owning user's id. Migration `v231_contact_tenant_id` says
  the same in its own docstring - "For single-tenant installs (the only shape
  shipped today)", backfilling `tenant_id = created_by`, with rows whose
  `created_by` is NULL left NULL and admin-only - and anticipates linking
  `tenant_id` to "a real Tenants table" later.
* **The write sites agree.** `subcontractors` and `tendering` store
  `tenant_id=str(user_id)`; `design_management` and `stakeholders` store
  `resolve_tenant_id(payload)`, which is the same value. Nothing stores an
  organisation id, because there is none to store.
* **There is no organisation to derive one from.** `User` carries `email`,
  `hashed_password`, `full_name`, `role`, `locale`, `is_active`, timestamps,
  `oidc_sub`, `oidc_issuer`, `metadata_`, `timezone` and `measurement_system`, and
  no organisation or tenant reference. `LegalEntity` is a financial entity, "a
  company of the group, with the country and currency its books follow", and
  nothing links a user to it as an ownership scope. Team membership is per
  project (`oe_teams_membership(team_id, user_id)` to a team with a `project_id`),
  so project ownership is a real and enforced boundary - it is what
  `assert_user_can_access_project` and `cost_scope` use - but it is not what the
  29 `tenant_id` columns store, and substituting it would be a data-model change
  rather than a fix.

Enforcing a strict policy over that data would scope each user to their own rows,
which is correct for a single-user install and would hide a colleague's rows from
everybody else on a shared one. That is precisely what the `tenant_is_user` blocker
detects, so the refusal is the right behaviour and not an obstacle to route around.

**No tenant claim was invented and `sub` was not equated with a tenant.** The
prerequisite, stated exactly:

1. a tenancy entity - an organisation or tenant table - with a membership relation
   from `User` to it, since none exists today;
2. `create_access_token` issuing a `tenant_id` claim from that membership. The
   resolver already prefers the claim over `sub`, so this needs no call-site
   change, which is what `core/tenant_scope.py` was written to allow;
3. a backfill re-pointing existing `tenant_id` values from user ids to the
   organisation id, per table, with the NULL rows `v231` deliberately left NULL
   given an owner or an explicit global designation;
4. only then `OE_RLS_STRICT`, which the readiness report will stop reporting
   `tenant_is_user` for.

Until step 1 exists, strict mode stays safely refused, and the refusal is logged,
returned in the provisioning stats and visible in the readiness response.

### What was not verified

- **The application itself cannot boot in this environment.** `app/core/stats.py` line 25
  declares `def percentile[Number: (float, Decimal)]`, which is Python 3.12 syntax, so on
  3.11.2 anything that imports `app.main` or a module router dies at import with
  `SyntaxError: expected '('`. That is the whole reason the HTTP-level suites were not
  executed here: `tests/integration/test_tenant_isolation.py` fails during startup and
  `tests/unit/test_idor_router_guards.py` reports 1192 failures against 715 passes, both
  from that one file. Neither is a product result, and neither can be a regression from
  this phase: `git diff --name-only HEAD` was empty while those runs were made, so the
  selection ran against unmodified application code. **CI's `access-control` and
  `backend-postgres` jobs on Python 3.12 are the authority for them**, and the 62-file
  selection they run is spelled out in `.github/workflows/ci-postgres.yml`.
- **Fourteen further runtime dependencies were not installed here** (pandas, pyarrow,
  duckdb, opencv-python-headless, ezdxf, trimesh, pycollada, laspy, lazrs, boto3, celery,
  pdfplumber, pypdf, pypdfium2), so suites importing them cannot collect locally either.
  The RLS lane needs none of them, which is why it does run.
- **No migration was executed and no backfill was measured against a populated database.**
  The backfill observed above is a three-row probe table. Nothing here claims a migration
  was tested against a production database, and Phase 02 added no migration.
- **Strict mode is observed enforcing, refusing and rolling back, but only over probe
  rows.** No claim is made that it is safe to enable on a real install: on a stock install
  the readiness report refuses it for `tenant_is_user`, and clearing that is the
  data-model change described above.
- **The cluster observed is the embedded one, whose connecting role is the `postgres`
  superuser.** A deployment that connects as a non-superuser application role exercises the
  `GRANT "oe_app", "oe_system" TO CURRENT_USER` path in `_role_setup_statements`, which was
  not observed here and is wrapped in an exception handler that swallows failure.

### Deployment prerequisites and rollback

1. The default path is unchanged: with `OE_RLS_ENFORCE` off, none of this executes.
2. To enforce, set `OE_RLS_ENFORCE=1` and boot, then read
   `GET /api/v1/admin/rls/readiness` (admin only). It reports the blocker codes and now
   also `strict_requested`.
3. To tighten, resolve the blockers the report names — in practice `tenant_is_user` and
   `null_tenant_rows`, which means an ownership backfill per table — then set
   `OE_RLS_STRICT=1` and boot again. A refusal is safe: the install keeps the permissive
   policy it already had.
4. To roll back, unset `OE_RLS_STRICT` and boot. Provisioning drops the strict policy and
   recreates the permissive one, and `policies_replaced` in the returned stats counts how
   many. Unsetting `OE_RLS_ENFORCE` stops transactions from entering `oe_app` but leaves
   the policies installed.
5. The agent gate needs no configuration and has no kill switch. It is not a mode; it is
   the execution path.

### Remaining gaps

1. **`tenant_is_user` blocked strict mode. Closed by Phase 02b**, and the investigation above
   is left standing because it is what established why the blocker could not simply be switched
   off: no tenant claim was issued by any of the six token-minting flows, `resolve_tenant_id`
   therefore always returned the user id, the `tenant_id` columns stored user ids by migration
   and by write site, and no organisation entity existed to derive anything else from.
   Enforcing strict over that data would have scoped each user to their own rows and hidden
   colleagues from each other. The four-step prerequisite listed under "Tenant identity" is
   what Phase 02b built, in that order: the tenancy entity and its membership relation, the
   claim issued from it, the backfill re-pointing the existing values, and then the check
   itself - unchanged. `rls_readiness_report` still refuses strict mode for the same reasons it
   always did; what changed is the data. Measured on a populated database in
   `tests/pg/test_tenancy_backfill_on_a_populated_database.py`: the blocker is raised before
   the repair, gone after it, and the gate still stays shut while a row nobody can account for
   remains `NULL`, then opens when that row is attributed explicitly and closes again when
   another such row appears.
2. **A session that never resolved a tenant keeps the connecting role** — the cluster
   superuser in a default install — and is therefore not policied at all. This is now
   observed rather than read: on the real cluster a bound session ran as `oe_app` and read
   two rows of four, and the next session, with the same `current_request_tenant()` answer
   of `None`, ran as a superuser and read all four. *Narrowed by Phase 02b, not closed.* There
   are now two binders: the global request dependency, and `app.core.rls.bound_tenant` for work
   with no request to inherit from. The three agent run paths use the second one, resolving the
   organization of whoever started the run through the same membership rows the mint uses and
   passing it explicitly, so a run and the login that would have started it agree. A run whose
   initiator belongs to no organization binds `None` rather than binding nothing: `None` stamps
   an empty `app.current_tenant`, which a fail-closed policy matches no row against, so such a
   run sees no tenant rows instead of every company's. What is still unpolicied by construction
   is everything else that starts work outside a request, and it is listed with its call sites
   under [Phase 02c](#phase-02c-the-background-paths-that-still-bind-nothing). The listener
   names its own remedy — run trusted system work under the `BYPASSRLS` role — and `oe_system`
   was observed reading every row with a tenant bound.
3. **Coverage is still 29 `tenant_id` columns across 15 of 169 `models.py` files.** Phase 02
   added none, deliberately: a column nothing populates is a policy that hides rows from
   their owners.
4. **The gate verifies the projects a call names.** Resolving a resource identifier to the
   project that owns it — a `boq_id` to its project — stays the tool's job, and a tool
   that does not do it is not caught by the gate. Enforcement is therefore not universal in
   the strongest sense: it is universal over tool *invocation*, and the resource-level
   check remains a documented obligation on each tool.
5. **A tool absent from `TOOL_PERMISSIONS` falls to `ai_agents.run`** and, with no
   authorizer supplied, would run. Every registered tool is mapped today and a test fails
   if one is not, but the default itself is still permissive.
6. **Denials are logged, not written to the audit trail.** `core/audit_log.py` is the
   platform's audit facility and the gate does not use it; the refusal is persisted on the
   run's own step record, which is queryable per run but is not an audit row. Whether a
   denied tool call belongs in `ActivityLog` is a decision for whoever owns that schema.

## Phase 02b delivered

Phase 02b is the tenancy foundation Phase 02's readiness gate was refusing to proceed without.
It answers one question - what is a tenant - and then makes every credential, every write site
and every background run agree with the answer. A reading order for reviewers, with the commits
grouped by theme and the riskiest files named, is in
[PHASE_02B_REVIEW_GUIDE.md](./PHASE_02B_REVIEW_GUIDE.md).

### The decision

[ADR 005](../adr/005-organization-is-the-tenant.md), accepted. A tenant is an `Organization`; a
person is a `Membership` of one; the active organization is chosen when the token is minted, by
flagged default first, then oldest, then smallest id, so a caller cannot change tenant between
two requests a second apart. `oe_projects_project` gains an `organization_id` that is `SET NULL`
on delete, because a project outlives the company record that named it and orphaning it is
recoverable while deleting it is not. The tenant stays a `varchar(36)` holding a UUID text,
which is what every existing `tenant_id` column already is, so no column type anywhere had to
change.

### What changed

| Area | Change |
|---|---|
| Schema | `oe_users_organization`, `oe_users_membership`, `oe_users_tenant_backfill` (the ledger), `oe_projects_project.organization_id`. Alembic revision `v3325_organization_tenancy`, inspector-guarded and reversible: the downgrade replays the ledger before dropping anything |
| Existing installs | A boot-time data repair, `users_tenant_organization_backfill`, because this product does not run `alembic upgrade`: it creates the schema and stamps the head. It adopts or creates one default organization, gives every user an active membership, re-points every user-id tenant, records each overwrite in the ledger before writing it, links projects, and is idempotent |
| Tokens | `_issue_token_pair` resolves the organization once and passes `tenant_id` through the existing `extra_claims` path, so all six flows - login, demo login, desktop bootstrap, OIDC login, refresh, password change - behave identically because they share one code path. The refresh token carries no claim: it is not a credential for data |
| The door | `reject_token_without_a_tenant` refuses an access token with no claim, 401 plus `WWW-Authenticate: Bearer`, telling the caller to refresh or sign in again. `resolve_tenant_id` returns the claim or `None`, with no fall-through to `sub`, and `tenant_scope_owner` given `None` filters to nothing rather than to everything |
| Readiness | `tenant_is_user` clears because the data changed, not because the check did. `rls_readiness_report` is untouched |
| Write and read sites | Seven places wrote a person's id into a tenant column or compared a tenant column to one. Five are corrected - contacts, subcontractors, tendering, finance open-items import, and the contacts scope filter. Two are seeds, listed below |
| Background work | `app.core.rls.bound_tenant`, and the three agent run paths use it, resolving the initiator's organization through the same membership rows the mint uses |

### Where the evidence contradicted the plan

The plan assumed a migration would carry the backfill, and this product does not run
migrations: it creates the schema and stamps the head, so a backfill inside the revision would
never have executed on any real install. It became a boot repair instead, and the revision
stays DDL-only. The plan also did not mention write sites, and there were seven; did not mention
that `_is_admin` looked a tenant id up as a user id; did not mention that `finance`'s open-items
import filtered contacts by `tenant_id == owner OR (tenant_id IS NULL AND created_by == owner)`,
which matches zero contacts after a backfill and was hidden by admin callers; assumed all six
token flows worked, when `oidc_login`'s auto-creation-disabled refusal was attached to the role
sync rather than to the missing account, so every returning SSO user was refused on an install
with no `OIDC_GROUP_ROLE_MAP`; and assumed a populated install could reach `ready_for_strict`
after a backfill, which it cannot while a row nobody can account for stays `NULL`. ADR 005's
consequences section carries the full list, including the fixtures that had been relying on a
person being a tenant and therefore never actually built two of them.

### Phase 02c: the background paths that still bind nothing

Named here rather than implemented, because each one needs a decision this phase does not have
the evidence to make: whose tenant is a scheduled run, and is a startup seed writing to one
company or to the install. One row below is struck through because it was closed after the list
was first written, and a second was closed afterwards; both stay on the list, since a closed gap
that disappears from the record looks like a gap nobody ever found. `tests/unit/test_which_paths_bind_a_tenant_and_which_still_do_not.py`
asserts that these paths still bind nothing, so closing one has to be a deliberate change that
moves it to the bound list.

| File | Call site | Required binding or role | Risk while it is open |
|---|---|---|---|
| ~~`app/modules/dashboards/router.py`~~ **closed** | `_tenant_id_from_payload`, used by **twenty-six** routes, not the eight an earlier truncated census reported; and its exact twin in `app/modules/compliance/router.py`, four more | Both private resolvers deleted and every call site moved to `app.core.tenant_scope.resolve_tenant_id` | Was the highest risk of the list: a second tenant resolver with its own fall-through to `sub`, so thirty routes across two modules bypassed both the door's refusal and the no-fallback rule, and its docstring still read "for the single-tenant shape we ship today, `tenant_id` equals the user id". Closed by `cf8e4c4`; `tests/unit/test_no_route_resolves_a_tenant_from_the_token_subject.py` fails if either comes back |
| `app/modules/pointcloud/seed.py` | :346, `tenant_id = owner_id` | Write the owner's organization id, or seed under an explicit install-level tenant | Seeds rows no token can name. On a demo install the seeded point clouds become invisible to the very users the seed ran for, once the claim is required |
| `app/modules/value/seed.py` | :272, `tenant_id=owner_id` | The same | The same, for the value-engineering time factors |
| `app/modules/ai_agents/scheduler.py` | :116, inside `with cost_scope.caller_scope(agent_user_id)` | Bind the schedule owner's active organization with `bound_tenant`, or run install-wide work under `oe_system` | A scheduled run keeps the connecting superuser and is not policied at all, so it can read every company's rows |
| `app/modules/ai_agents/events.py` | :140, inside `with cost_scope.caller_scope(agent_user_id)` | Bind the originating user's organization | The same, for event-triggered runs |
| `app/core/job_runner.py` | `_default_session_factory` at :86, which is where a job's session comes from | Bind per job from the job's owner, or run under `oe_system` for platform work | The same, for every queued job |
| `app/modules/property_dev/service.py` | :3562, `resolved_tenant = tenant_id if tenant_id is not None else str(data.tenant_id)` | Confirm the tenant in use is the caller's and never one supplied in the request body | A tenant taken from a payload body would be caller-chosen, which is the one shape of this bug that is an authorization hole rather than a visibility one |
| ~~`app/modules/procurement_concept/service.py`~~ **closed** | `project_frameworks`, the union over `[project_tenant(project_id), caller_tenant]`, and its write-side twin `_link_framework` | **Security.** Replaced by an explicit project participant grant check, per [ADR 006](../adr/006-project-participant-grants.md) stage 5 | Was: any team member of a project read another company's framework agreements with no grant, no scope, no expiry and no audit row, and could call one off on the owner's package, because the only gate in front of both was `verify_project_access`, which answers the person question and not the company one. Both halves now ask whether the caller's company holds a live grant, and both were pinned by characterization tests that fail if the behaviour changes in either direction - so closing them was the deliberate act those tests demanded, and each replacement says in its docstring that it used to assert the opposite. Neither half could be a policy: `oe_procurement_concept_framework` carries `tenant_id` and no `project_id`, and `oe_procurement_concept_award_package` the reverse, so no row exists on which both arms could be evaluated. ADR 006 section 13.5 |

**Ordered work, and what must come first.** The rows above are background paths that bind no
tenant. One further item belongs on this list and ahead of them in consequence, because it gates a
switch rather than a code path.

1. **Project participant grants** - [ADR 006](../adr/006-project-participant-grants.md),
   **accepted, and the part of it that gates strict mode is implemented.** A project belongs to one
   organization and other organizations participate through explicit grants. On the tree: the
   `oe_projects_participant_grant` table and revision `v3326_project_participant_grant`; a service
   in `app/modules/projects/grants.py` with create, change-scope, list and revoke, plus the
   suspension that a change of project ownership triggers; four routes under
   `/api/v1/projects/{project_id}/participant-grants`; a second GUC `app.granted_projects` bound
   once per request behind `OE_PROJECT_GRANTS`; and a second permissive `FOR SELECT` policy
   `oe_project_grant_read` installed beside the untouched `oe_tenant_isolation` policy on all
   **10** tables that carry both a `tenant_id` and a `project_id` column. Permissive policies are
   OR'd, so the two together are the target predicate - "the caller's organization owns the row,
   **or** it holds a live grant on the project the row belongs to" - while writes stay governed by
   the tenant policy alone, which is how a grantee's rows carry the grantee's own `tenant_id`.
   Measured on one million `oe_pipeline` rows, the worst of three query shapes cost **1.0046x** the
   single-condition baseline against an owner's bar of **1.25**.

   **What is still open, and what it still gates.** The **147** project-scoped-only model files
   (**420** `project_id` columns, no `tenant_id` for either arm to match) remain gated in the route
   by `verify_project_access` and have no database policy. Strict mode installs the single-arm
   equality predicate
   `(tenant_id)::text = current_setting('app.current_tenant', true)`, which cannot express
   participation, so **`OE_RLS_STRICT` is still blocked - by that half of the work, no longer by
   grants.** Two further gaps are recorded in ADR 006 section 13.7 rather than left implicit:
   `scope` is stored, ranked and audited but not yet differentiated, so a `view` grant answers what
   a `manage` grant does today; and no agent tool exposes grants, which is a statement about the
   current tree and not a guard that keeps it true. Size of the job as originally measured: **30**
   `tenant_id` columns across **16** model files by source grep, reconciled in ADR 006 section 12.1
   to **31** policied tables - the grep matched a `previous_tenant_id` ledger column and never
   covered `oe_activity_log` or `oe_job_run`, which are declared outside `app/modules`.
2. **The six background paths in the table above**, in the order listed, each closed by a
   deliberate change that moves it out of the unbound list asserted by
   `tests/unit/test_which_paths_bind_a_tenant_and_which_still_do_not.py`.
3. **Only then strict mode.** ADR 006 stage 4's million-row measurements are in hand and inside the
   budget (worst ratio 1.0046 against 1.25), so the remaining gate on strict mode is the
   project-scoped-only half of item 1, not the measurement.

### Operating the tenancy repair on first boot

The tenancy backfill is a `DataRepair` and runs inside application startup, before the module
loader and therefore before the server socket opens. Operators need three numbers and one rule.

**What a first boot costs.** Measured on a real embedded PostgreSQL 16.11 in this sandbox, on
1,000,000 rows spread over four tenant-carrying tables at 250,000 each, with the set-based
batching the repair now uses (`_BATCH = 100_000`):

| Table | Rows per second |
|---|---|
| `oe_contacts_contact` | 26,857 |
| `oe_compliance_dsl_rule` | 25,691 |
| `oe_activity_log` | 24,557 |
| `oe_eac_block_graph` | 23,141 |

Preparation cost 0.011 s. At the slowest measured table a million rows is about 43 s, and summing
the four tables as measured gives about 40 s; **the figure to plan with is ~47 s per million
rows**, which is the slowest observed rate plus headroom for a busier install. Before the batching
change the same volume ran at 2,645 to 2,994 rows/s, so a million rows held a boot for roughly six
minutes. **The second and every later pass costs 0.674 s and changes 0 rows** - that is what a
normal boot pays, and it is the number that matters for steady state rather than for the first
start after an upgrade.

**What a health check must tolerate.** Starlette runs every startup handler to completion before
the socket opens, so during the repair the process answers nothing: not HTTP, not a readiness
endpoint. A liveness probe that expects an HTTP answer inside the repair window kills a healthy
boot and restarts it, and because the repair is idempotent and ledgered the restart begins again
from a scan, so an aggressive probe turns a 47-second boot into a crash loop.

* Use a **startup probe**, or an `initialDelaySeconds` sized to the install: `failureThreshold x
  periodSeconds` must exceed the expected repair time. For an install with a million
  tenant-carrying rows budget at least 120 s, about 2.5x the measured 47 s.
* A **TCP** liveness check is worse than useless here. The port is not open yet, so it reports
  exactly the same failure as a dead process.
* Do not shorten the repair by disabling it. A skipped repair leaves rows this release expects to
  have been corrected, and `init-db` logs that as a failure rather than hiding it.

**Multiple workers do not multiply the wait.** The repair takes a non-blocking,
transaction-scoped advisory lock, `pg_try_advisory_xact_lock(573910446)`. A second worker that
finds the lock held returns in **8 ms** and boots without running the repair; the worker holding it
does the work once. Scaling out is therefore safe. That lock is distinct from the migration heal
lock, `826340271`, so the two never confuse each other.

**When to run it as an explicit admin command instead.** Above roughly **a million tenant-carrying
rows** - that is, above about **47 s** of first-boot wait - run the repair before boot rather than
inside it:

    openconstructionerp init-db --data-dir DIR

`init-db` runs the same repair registry as startup, through `app/core/data_repairs.py`, and every
entry is idempotent and ledgered, so the boot that follows performs a scan that finds nothing and
costs under a second. Below that threshold the in-boot path is the right default: it needs no
operator, no extra deployment step, and no change to how the install is started.

The threshold is a planning figure derived from the measurements above, not a limit enforced in
code. Nothing in the application refuses to boot on a large install. It just takes longer, and the
probe has to know that.

### Evidence, executed locally

Run in this sandbox on CPython 3.12.8, which had to be built from source here because the
image ships 3.11 and `app/core/stats.py` uses syntax 3.11 cannot parse. The PostgreSQL lane ran
against a real embedded PostgreSQL 16 cluster, not a mock, and the counts below were read back
out of JUnit reports by `scripts/publish_test_counts.py` - the same script the workflow now
runs, so this table is its output and not a transcription of a log.

| What ran | Result |
|---|---|
| the whole access-control job, replayed locally from the workflow's own step list (66 files, 10 steps) | **2583 passed, 1 failed, 1 xfailed, 0 skipped**, 27 min |
| `tests/unit/test_idor_router_guards.py` | 1907 passed |
| the 30-file module and unit ownership-guard step | 307 passed |
| `tests/pg/test_quality_concept_idor.py` (fixture corrected) | 11 passed |
| `tests/integration/test_tenant_isolation.py` (fixture corrected) | 33 passed, 1 failed |
| `tests/unit/test_tenant_scope.py` | 19 passed |
| `tests/unit/test_every_token_flow_names_an_organization.py` | 19 passed |
| `tests/unit/test_contact_tenancy.py` | 11 passed |
| `tests/unit/test_which_paths_bind_a_tenant_and_which_still_do_not.py` (renamed and corrected) | 16 passed |
| `tests/pg/test_tenancy_backfill_on_a_populated_database.py` (one test added) | 21 passed |
| `tests/pg/test_two_organizations_are_isolated_under_the_application_role.py` (new) | 11 passed |
| the four existing row-level-security PostgreSQL files | 41 passed |

Nothing was skipped in any of it, which matters more than it looks: the PostgreSQL lane skips
silently unless `OE_TEST_DB=pg` is set, and a skipped target is indistinguishable from a passing
one in a job conclusion. That is why the publisher fails a step on a skipped target rather than
merely reporting it.

Before this phase's fixture corrections the same replay gave 2516 passed and 3 failed over 62
files. Two of those three failures were fixtures that asserted cross-tenant isolation while
building one tenant, and one was a payload override that minted a caller the product no longer
accepts. The remaining failure is the environment described below, and the four added files are
the 65 tests in the last four rows.

### What was not verified locally, and why

This sandbox had to build its own CPython 3.12 from source, because the image ships 3.11 and
`app/core/stats.py` uses PEP 695 syntax that 3.11 cannot parse. That interpreter has no
`_ctypes`: the image has `libffi.so.8` but no `ffi.h`, and generating one needs autotools the
image does not have. The consequence is specific and worth recording rather than papering over.
The module loader skips `oe_dashboards` when its import chain fails, so no dashboards route is
mounted, and `tests/integration/test_tenant_isolation.py::test_tenant_b_cannot_delete_tenant_a_snapshot`
fails locally on the assertion that tenant A can still read its own snapshot: the GET returns
FastAPI's bare `{"detail": "Not Found"}`, which is a missing route and not a missing row. Every
other dashboards assertion in that file accepts 403 or 404 and so passes without proving
anything. A route census on `create_app()` reports zero dashboards routes, which is the
evidence for the diagnosis. On a runner with a normal CPython the module mounts and the test
exercises the real refusal.

## Blockers and limitations

Recorded so that no later reader mistakes them for passing results.

- **The backend test suite could not be executed in the audit environment.**
  `backend/pyproject.toml` requires Python 3.12 or newer; the environment provides 3.11.2;
  25 of 3,199 files under `backend/app` do not parse on 3.11; a 3.12 interpreter could not
  be obtained; and `backend/tests/conftest.py` raises when it cannot boot embedded
  PostgreSQL. **CI is the authority on test results.** At the audited commit its recorded
  state is 46 of 46 check runs `success`, with CI at 20 of 20 jobs and the PostgreSQL
  matrix at 16 of 16.
- **No runtime was started.** Every behavioural statement comes from code, tests and
  recorded CI results, not from an observed response.
- **Phase 02 did execute tests locally, and they are still partial.** The bullet above
  describes the audit. During Phase 02 a dependency set was installed and 50 new tests plus
  a 67-file before/after comparison were run for real with `--noconftest` on Python 3.11.2.
  Those runs exercise pure logic and faked connections; anything needing embedded
  PostgreSQL or Python 3.12 still did not run, and no database was ever started. The
  distinction is recorded in [Phase 02 delivered](#phase-02-delivered) under "What was not
  verified".
- **Fork platform settings are not changeable from here.** The actions-permissions, rerun
  and dispatch endpoints refused the available token, so the five `disabled_fork`
  workflows — including CodeQL and OpenSSF Scorecard — are reported rather than enabled.
  Enabling them is an owner action on the fork.
- **Workflow job logs could not be downloaded**; job conclusions, step timings and check
  annotations were used instead.
- **Test-file counts are a proxy.** They are name-matched counts of files, reproducible
  with `find`, and they say what tests are about rather than what they assert.
- **Capability statuses are static readings.** A module classified Partial here may be
  further along at runtime than its code suggests, or less; where the repository has
  already assessed itself, as RFC 25 does for project intelligence, that assessment is
  cited rather than second-guessed.

## Where to go next

- [FOUNDATION_AUDIT.md](./FOUNDATION_AUDIT.md) — the measurements these decisions rest on.
- [TARGET_ARCHITECTURE.md](./TARGET_ARCHITECTURE.md) — the architecture and its ground
  rules.
- [Architecture overview](./README.md) — how the codebase fits together today.
- [ADR index](../adr/README.md) and [RFC index](../rfc/README.md).
