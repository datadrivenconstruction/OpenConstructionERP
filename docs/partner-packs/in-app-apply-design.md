# In-App Partner Pack Install / Apply / Update — Design

Status: DESIGN ONLY (no production code in this document). Author: DataDrivenConstruction.
Date: 2026-05-29. Targets core version after v5.8.0 (latest migration on disk is
`v3150_file_favorites`).

> This document specifies how the operator installs, applies, and updates a Partner
> Pack from inside the app at `/modules` → Partner Packs tab, instead of the
> env-only `OE_PARTNER_PACK` mechanism that exists today. It does **not** introduce
> code that ships modules/routes/tables — packs remain declarative presets
> (Shape A, per `docs/adr/2026-05-28-partner-pack-architecture.md`).

---

## 0. Ground truth — what exists today (verified)

| Concern | Where | Behaviour today |
|---|---|---|
| Pack discovery | `backend/app/core/partner_pack/discovery.py:158-182` (`discover_packs`) | `@lru_cache(maxsize=1)`. Scans pip entry-points (`openconstructionerp.partner_packs`) + repo `packs/` dir. Process-lifetime cache; `reset_cache()` clears it (`discovery.py:244-247`). |
| Active pack selection | `discovery.py:193-215` (`get_active_pack`) | `@lru_cache(maxsize=1)`. Reads `os.environ["OE_PARTNER_PACK"]` only. No DB, no per-tenant, no per-project. Changing it needs a restart. |
| HTTP surface | `backend/app/core/partner_pack/router.py:23-154` | 7 GET endpoints, all READ-ONLY: `current`, `installed`, `logo`, `favicon`, `onboarding-script`, `locale/{code}`, `by-slug/{slug}`. **No apply/activate endpoint.** |
| Boot wiring | `backend/app/main.py:1079-1092` | Mounts the router, calls `get_active_pack()`, logs the active pack. The backend does **nothing else** with the manifest. |
| Manifest schema | `backend/app/core/partner_pack/manifest.py:38-189` | Pydantic `extra="forbid"`. Fields enumerated in §2. `to_public_dict()` at `:159-189`. |
| Module enable/disable (runtime) | `backend/app/core/module_loader.py:299-409` (`enable_module` / `disable_module`) | Loads/unloads router + persists. Core modules cannot be disabled. Refuses to disable a module that enabled-modules depend on (`:369-376`). |
| Module state persistence | `backend/app/core/module_state.py:88-153` (`save_module_states` / `set_module_enabled`) | JSON file `module_states.json` beside the SQLite DB (resolver `:34-54`). Consumed on boot in `module_loader.load_all` (`module_loader.py:143-155`). |
| Module mgmt API | `backend/app/core/module_router.py:40-81` | `POST /api/v1/modules/{name}/enable|disable`, gated by `RequirePermission("admin")`. |
| Currency model | `backend/app/modules/reporting/currency_resolver.py:57-90` | Currency is **per-Project** (`Project.currency`). There is **no** global/tenant `default_currency` setting — the resolver comment at `:11-12` says "the tenant model has no `default_currency` yet". |
| Default locale | `backend/app/core/i18n.py` | No DB-backed global default locale; locale is frontend (per-user localStorage). |
| Validation rule packs | `packs/<slug>/rule_packs/*.json` + engine registry `backend/app/core/validation/engine.py:300-335` | Pack JSON files are **documentation only**. The engine only knows `ValidationRule` classes registered in-process via `registry.register(...)`; there is no loader that reads pack JSON into the registry. |
| Tax templates | manifest field only | `default_tax_template` is a declarative slug; **no backend resolver** consumes it. |
| CWICR regions | `backend/app/modules/costs/parquet_lookup.py:29-96` | A region = a parquet file on disk under the CWICR root. "Preload" means ensuring that parquet is present; there is no runtime downloader keyed off the manifest. |
| Audit | `backend/app/core/audit.py:44-112` (`audit_log`) | Writes `oe_core_audit_log` and mirrors into `oe_activity_log`. Session-scoped, flushes (caller commits). |
| Frontend tab | `frontend/src/features/modules/ModulesPage.tsx:120-128` tabs; `:587-825` `PartnerPacksTab` + `PartnerPackCard` | READ-ONLY card grid from `GET /v1/partner-pack/installed`. No apply/update button. |
| Frontend module toggle (reuse target) | `ModulesPage.tsx:1512-1544` `handleBackendToggle` → `apiPost('/v1/modules/{name}/{action}')` | The exact backend path the apply flow should reuse for module enable/disable. |

**Headline finding:** today a pack does almost nothing on the backend. The frontend
(`frontend/src/shared/hooks/usePartnerPack.ts`, `PartnerLogoBadge.tsx`) applies
branding colours, the co-brand badge, and extra locales. `default_currency`,
`default_locale`, `validation_rule_packs`, `default_modules`, `hidden_modules`,
`default_tax_template`, `cwicr_regions` are **not applied to anything**. "Apply a
pack" therefore has to be **built**, not merely "exposed".

---

## 1. Persistence — where the applied-pack state lives

### 1.1 New table `oe_partner_pack_state`

Single-row "applied pack" record (single global active pack — see Decision Fork A).
Stores the slug, the **full manifest snapshot at apply time** (so Update can diff),
and a record of side effects we performed (so Un-apply / switch can reverse them).

Migration `v3151_partner_pack_state` (down-revision `v3150_file_favorites`),
following the idempotent guarded pattern of `v3150_file_favorites.py:49-127`.

```text
oe_partner_pack_state
  id                 String(36)  PK
  slug               String(64)  NOT NULL            -- currently-applied pack slug
  applied_version    String(32)  NOT NULL            -- pack_version at apply time
  applied_manifest   JSON        NOT NULL            -- full to_public_dict() snapshot
  applied_effects    JSON        NOT NULL DEFAULT {} -- what we changed (see §2.9)
  applied_by         String(36)  FK oe_users_user.id NULL
  applied_at         DateTime(tz) NOT NULL server_default=now()
  updated_at         DateTime(tz) NOT NULL server_default=now()
```

Only one row is ever present (the active applied pack). Un-apply deletes it.
Switching packs overwrites it (after reversing the previous pack's reversible
effects — §2.10). `applied_effects` is the audit of mutations, e.g.:

```json
{
  "modules_enabled":  ["oe_takeoff"],          // we turned these ON
  "modules_disabled": ["oe_tendering"],        // we turned these OFF (and they were ON before)
  "currency_default_set": "USD",               // see §2.2 — soft setting only
  "locale_default_set": "en-US",
  "branding_selected": true
}
```

### 1.2 Making `get_active_pack()` DB-aware (the lru_cache problem)

`get_active_pack()` is `@lru_cache(maxsize=1)` (`discovery.py:193`). We must **not**
make a cached function read the DB on every call. Resolution:

1. Keep `get_active_pack()` exactly as-is. It stays the **env fallback / default**
   for single-tenant deployments that set `OE_PARTNER_PACK` (per spec requirement).
2. Add a new **DB-backed resolver** in a new service module
   `backend/app/core/partner_pack/state.py`:
   - `async def get_applied_pack(session) -> PartnerPackManifest | None` — reads
     `oe_partner_pack_state`, then resolves the live manifest via
     `get_pack_by_slug(slug)` (`discovery.py:185-190`). Returns `None` if no row.
   - New **precedence** for "what pack is effectively active":
     1. `oe_partner_pack_state` row (in-app applied) — DB, authoritative.
     2. `OE_PARTNER_PACK` env (legacy single-tenant default) — only if no DB row.
     3. `None`.
3. The READ endpoints (`/current`, `/installed`) switch to the new precedence:
   `current_pack` becomes `async`, takes `SessionDep`, calls
   `get_applied_pack(session) or get_active_pack()`. The branding/logo/locale
   streaming endpoints (`router.py:64-143`) resolve the same way (they currently
   key off `get_active_pack()` + `get_active_pack_module_name()`; both must accept
   the DB-applied slug, see §1.3).

No lru_cache invalidation dance is needed because the DB row is read fresh per
request (cheap single-row PK lookup) and the env path stays cached.

### 1.3 Resource streaming after a DB apply

`get_active_pack_module_name()` (`discovery.py:218-241`) maps the active slug to a
pip module name **only for entry-point packs** (filesystem packs return `None`).
For DB-applied packs we resolve the module name from the **applied slug** rather
than the env slug: extract a `resolve_pack_module_name(slug)` helper and call it
with the effective slug. Filesystem-only packs still cannot stream resources (their
package is not on the import path) — this is an existing limitation, surfaced in the
UI as "logo/onboarding available only for pip-installed packs".

---

## 2. Apply semantics — field-by-field side effects on existing data

The apply operation is a **service method**
`apply_pack(session, slug, *, dry_run, actor_id) -> ApplyResult`. It is
**idempotent** (re-applying the same version is a no-op that returns an empty diff)
and supports **dry-run** (compute the plan, touch nothing). Each field below maps to
exactly one planned action; the plan is what the dry-run preview returns.

### 2.1 `default_modules` / `hidden_modules` → module enable/disable

- `default_modules` (manifest `:118-125`): non-empty list = the set the pack wants
  visible. Action: for every module in the list that is currently **disabled**, call
  `module_loader.enable_module(name, app)` (`module_loader.py:299`), which also
  persists via `set_module_enabled(name, True)` (`module_state.py:118`). Empty list
  = "show all" → **no enable action** (we never force-enable everything).
- `hidden_modules` (manifest `:126-132`): for every module currently **enabled**,
  the pack wants it OFF. Action: `module_loader.disable_module(name, app)`.
- **Slug mapping caveat:** manifest module slugs are partner-authored and may not
  match `module_loader` names (which are `oe_*`, e.g. `oe_takeoff`). The service must
  normalise: try the slug as-is, then `oe_{slug}`, then the kebab/underscore variants
  the loader already mirrors (`module_loader.py:206-207`). Unresolvable slugs are
  reported in the preview as **warnings** ("pack references unknown module 'foo'"),
  never silently dropped.
- **Disabling a currently-enabled module the pack wants hidden — auto vs. warn?**
  This is destructive to the operator's current sidebar/config. Recommendation:
  **WARN-then-confirm**. The dry-run preview lists every module that would be turned
  OFF and every module that would be turned ON; the operator confirms before commit.
  Never silently disable. (Decision Fork B.)
- **Dependency safety:** `disable_module` already refuses if enabled modules depend
  on the target (`module_loader.py:369-376`). The service catches that `ValueError`
  and reports it as a **blocking** preview item ("cannot hide 'X' — required by 'Y'");
  apply proceeds for the rest, or the operator resolves first.
- Core modules can never be disabled (`module_loader.py:366`); if a pack lists a core
  module under `hidden_modules`, it is reported as an ignorable warning.

### 2.2 `default_currency` → DO NOT re-denominate money

This is the dangerous one. `default_currency` (manifest `:97-101`) is an ISO-4217
default. There is **no global currency setting** to write today (currency is
per-Project, `currency_resolver.py:11-12`). Safe behaviour:

- Apply writes the pack's currency into a **new-projects default** only — a soft
  setting consumed by the project-create form / `resolve_template_currency`'s future
  `tenant_currency` slot (currently always `None`, `currency_resolver.py:11-12`).
  Concretely: store it in `oe_partner_pack_state.applied_effects.currency_default_set`
  and expose it via the existing currency-resolution chain as the lowest-priority
  default (below `override` and `Project.currency`).
- **Existing projects / BOQs keep their currency untouched.** We never UPDATE
  `Project.currency` and never re-price any `Position.unit_rate`. Re-denomination is a
  separate, explicit, FX-aware operation that is **out of scope** for pack apply.
- The preview states plainly: "New projects will default to USD. Existing projects
  and their priced BOQs are not changed."

### 2.3 `default_locale` / `additional_locales` → app default locale

- There is no DB-backed global default locale today. Apply writes
  `default_locale` into `applied_effects.locale_default_set`; the
  `GET /v1/partner-pack/current` response already carries `default_locale`, and the
  frontend boot (`usePartnerPack`) can adopt it as the **default** locale for users
  who have not explicitly chosen one (respect an existing per-user choice — never
  override a user's saved locale).
- `additional_locales` are already streamable (`router.py:128-143`); apply does not
  need to move files. The preview lists "adds locales: en-US".

### 2.4 `default_tax_template` → needs a resolver first

`default_tax_template` (manifest `:102-105`) is a declarative slug with **no backend
consumer** today. Apply behaviour: store it in `applied_effects` and surface it in
`/current`, but mark it in the preview as **"informational — no automatic effect
yet"** until a tax-template resolver exists (parallel to `currency_resolver`). Do not
pretend it changes tax behaviour. Building the resolver is tracked as future work,
not part of this apply feature.

**Decision, 2026-10-19:** no resolver. Tax is not a pack setting: VAT, public
holidays, e-invoicing and statutory payment terms come from the core registries
by the project's country, pack or no pack. The preview now carries
`built_in_for_country` with those values, every shipped pack leaves
`default_tax_template` unset, the onboarding scripts no longer carry
`set_tax_template`, and `test_pack_conformance` refuses a pack that names a
template id nothing resolves.

### 2.5 `validation_rule_packs` → no-op-with-warning (recommended) vs. block

> **Outcome note, 2026-08-26.** Fork C shipped as (a), and (a) turned out to be
> the whole of the defect rather than an honest degradation: `validation_rule_packs`
> had no runtime consumer at all, so an entry that *did* resolve enabled exactly as
> much as one that did not, which is nothing. The field is now documents-only, and a
> second field `validation_rule_sets` carries the engine identifiers and is refused at
> apply time when the registry does not know one. See `MANIFEST_REFERENCE.md`. The
> fork text below is left as written, because it is the record of what was decided.

`validation_rule_packs` (manifest `:108-115`) name rule-set slugs. The engine
registry only enables rule sets composed of in-process-registered `ValidationRule`
classes (`engine.py:300-335`); the `packs/<slug>/rule_packs/*.json` files are not
loaded by anything. Per prior research, ~3 of ~800 referenced rule_ids match real
rule classes. Two options (Decision Fork C):

- (a) **Apply enables only the rule sets that already exist in the registry**, and
  logs a warning listing the unknown ones. Net effect today: enable the handful that
  resolve, warn on the rest. The preview shows "enables 2 validation rule sets;
  5 referenced sets are not yet available in this build."
- (b) Block apply on any unknown rule set until the declarative rule-loader (v7)
  exists.

**Recommendation: (a)** — partial, transparent, non-blocking. It lets packs ship
today and degrades honestly. When the rule-loader lands, the same field starts
resolving more sets with no manifest changes.

### 2.6 `cwicr_regions` → preload (best-effort)

`cwicr_regions` (manifest `:93-96`) name CWICR parquet regions. A region exists iff
its parquet is on disk under the CWICR root (`parquet_lookup.py:29-96`). Apply does
**not** download anything (no runtime downloader exists, and large parquet pulls are
not appropriate inside a synchronous apply). Behaviour: for each region, check
presence; report "present" / "not installed" in the preview. Present regions are
recorded as "preferred" so the cost-DB browser surfaces them first. Missing regions
are a **warning with guidance** ("region cwicr-usa-usd not found on this server — see
data-package install"), not a failure.

### 2.7 `branding` → persist the selection only

Branding (manifest `:134-135`) is already frontend-applied via `usePartnerPack` once
`/current` reports the pack. Apply just makes `/current` report this pack (via the DB
row), so branding follows automatically. Record `branding_selected: true` in
`applied_effects`. No extra action.

### 2.8 `onboarding_script_path` → already served

No apply action; once the pack is the active/applied pack, the existing
`/onboarding-script` endpoint streams it (`router.py:108-125`).

### 2.9 What the apply records

After a real (non-dry-run) apply, write the `oe_partner_pack_state` row with the full
manifest snapshot (`applied_manifest`) and the `applied_effects` ledger (§1.1), then
`audit_log(session, action="apply", entity_type="partner_pack", entity_id=slug,
user_id=actor_id, details={diff, effects})` (`audit.py:44`).

### 2.10 Reversibility — un-apply and switch

- **Un-apply** (`POST /unapply`): reverse the **reversible** effects recorded in
  `applied_effects`:
  - Modules **we enabled** (`modules_enabled`) → offer to disable them again
    (respecting dependency guards). Modules **we disabled** (`modules_disabled`) →
    offer to re-enable. This is itself a mutation, so un-apply also has a dry-run
    preview and a confirm. Default proposal: revert exactly the modules we touched,
    leave anything the operator changed manually since apply alone.
  - Currency/locale soft defaults → cleared (existing projects already untouched, so
    nothing to undo there).
  - Branding → `/current` reverts to env pack or vanilla.
  - Delete the `oe_partner_pack_state` row. Audit `action="unapply"`.
- **Switch** (apply pack B while pack A is applied): run un-apply's reversal of A's
  reversible effects, then apply B. Presented as a single combined preview ("turning
  OFF X (from CA pack), turning ON Y (for CB pack)").
- **Modules enabled by a pack that is later un-applied:** reverted to their
  pre-apply state per the `applied_effects` ledger. If the operator manually toggled a
  module after apply, the ledger lets us detect the conflict and leave the operator's
  later choice in place (warn in the preview).

---

## 3. Update semantics — re-apply a new pack version

When an installed pack's `pack_version` (manifest `:67-70`) differs from
`oe_partner_pack_state.applied_version`, the UI shows an **"Update available"** badge.

- The **previously-applied manifest snapshot** lives in
  `oe_partner_pack_state.applied_manifest` (§1.1) — this is precisely what makes a
  diff possible.
- `GET /v1/partner-pack/apply-preview/{slug}` computes a **field-level diff** of
  `applied_manifest` (old) vs the freshly-discovered manifest (new):
  - modules added to / removed from `default_modules` / `hidden_modules`
  - currency / locale / tax-template changes
  - rule-set additions / removals
  - cwicr region additions / removals
  - branding changes (colour / logo / powered-by)
- **Update applies only the delta**, then refreshes the snapshot + version. Example:
  if v0.2.0 adds `oe_takeoff` to `default_modules` and drops `oe_x` from
  `hidden_modules`, the update enables `oe_takeoff` and re-enables `oe_x`, and nothing
  else. The same dry-run preview + confirm gate applies. Audit `action="update"`
  with `details.from_version` / `details.to_version`.
- A brand-new pack wheel that brings a new `pack_version` still requires the wheel to
  be installed and the process restarted **before** the new version is discoverable
  (§4); only then does the diff show the new content.

---

## 4. Install — be honest about the restart boundary

`discover_packs()` is `@lru_cache` (`discovery.py:158`) and enumerates pip
entry-points + the `packs/` dir at first call. True "drop a wheel in at runtime and
load it" is **out of scope for Shape A**: a pack can ship resources but the platform
treats discovery as boot-time. So:

- The UI's "Install" really means **"Apply an already-discovered pack."** It lists
  packs that are discovered-but-not-applied (already present via pip or in `packs/`)
  and lets the operator apply one.
- Adding a **brand-new** pack (a wheel not yet installed) requires
  `pip install <wheel>` (or dropping it in `packs/`) **plus a process restart**. The
  UI states this in the empty/help state and on a "Don't see your pack?" affordance:
  *"New packs are installed by your administrator (pip install + restart). Once
  installed they appear here to apply."*
- Optional convenience (not required): an admin-only `POST /v1/partner-pack/rescan`
  that calls `reset_cache()` (`discovery.py:244`) to re-enumerate the `packs/` dir
  **without** a restart — useful for source-checkout / on-disk packs. It cannot pick
  up newly-`pip install`ed entry-points in a running interpreter reliably, so the UI
  still messages "restart may be required for pip-installed packs." (Decision Fork D.)

---

## 5. API surface

All write endpoints gated by `RequirePermission("admin")` (same as
`module_router.py:42,64`). All take `SessionDep` + `CurrentUserId`
(`dependencies.py:516,518`) and audit on commit.

| Method | Path | Body / Params | Returns |
|---|---|---|---|
| GET | `/api/v1/partner-pack/applied` | — | `{ applied: bool, slug?, applied_version?, current_version?, update_available: bool, applied_at?, applied_by? }` |
| GET | `/api/v1/partner-pack/apply-preview/{slug}` | — | `ApplyPlan` (see below). Pure compute, no mutation. For an already-applied slug it returns the **update delta**; otherwise the **fresh-apply plan**. |
| POST | `/api/v1/partner-pack/apply` | `{ slug, dry_run, confirm_disables }` | `dry_run=true` → `ApplyPlan`; `dry_run=false` → `ApplyResult` (effects performed + audit id). Requires `confirm_disables=true` if the plan disables any currently-enabled module. |
| POST | `/api/v1/partner-pack/unapply` | `{ dry_run, revert_modules }` | `dry_run=true` → reversal plan; else `ApplyResult`. |
| POST | `/api/v1/partner-pack/rescan` *(optional, Fork D)* | — | `{ discovered: [slug...] }`. Calls `reset_cache()`. |

`ApplyPlan` schema:

```json
{
  "slug": "us-costdata",
  "mode": "apply",                       // "apply" | "update"
  "from_version": "0.1.0",               // null on first apply
  "to_version": "0.2.0",
  "modules_to_enable":  [{"slug":"oe_takeoff","display":"Takeoff"}],
  "modules_to_disable": [{"slug":"oe_tendering","display":"Tendering","was_enabled":true}],
  "currency_default":   {"from": "EUR", "to": "USD", "note": "new projects only; existing untouched"},
  "locale_default":     {"from": "en", "to": "en-US"},
  "tax_template":       {"slug":"us_state_sales_tax","effect":"informational_no_resolver"},
  "validation_rule_sets": {"enabled":["masterformat_2020"], "unavailable":["aia_a201_2017","osha_1926"]},
  "cwicr_regions":      {"present":["cwicr-usa-usd"], "missing":[]},
  "branding":           {"changes": true},
  "warnings":  ["pack references unknown module 'foo'"],
  "blocking":  []                        // e.g. ["cannot hide 'costs' — required by 'boq'"]
}
```

`ApplyResult` = `{ ok, audit_id, effects: {...}, plan: ApplyPlan }`.

**RBAC:** admin only (apply/unapply/rescan + the apply preview). The read endpoints
(`/applied`, `current`, `installed`) stay open to any authenticated user (the
frontend needs branding on boot). **Audit:** every apply/update/unapply writes an
`oe_core_audit_log` + `oe_activity_log` entry via `audit_log` (`audit.py:44`).

---

## 6. Frontend UX — redesigned Partner Packs tab

Reuse design-system primitives from `frontend/src/shared/ui/`: `Card`, `Badge`,
`Button`, `ConfirmDialog`, `WideModal`/`WideModalSection`/`WideModalField`, `Toast`,
`InfoHint`, `EmptyState`. Feature data layer mirrors the file-manager template:
`partner-packs/api.ts` + `partner-packs/hooks.ts` (React Query, optimistic where
safe, invalidate `['partner-packs']`, `['partner-pack','applied']`,
`['system-modules']` after apply — the last one because module state changed).

### 6.1 Card states

Each `PartnerPackCard` (extend the existing `:696-825`) gains a footer action area:
- **Not applied:** `Apply` button (primary).
- **Applied, up to date:** `Active` badge (exists, `:741-746`) + `Un-apply` (ghost) +
  `Re-apply` (secondary).
- **Applied, newer version discovered:** amber `Update available v0.1.0 → v0.2.0`
  badge + `Update` button (primary).

### 6.2 Apply / Update wizard (dry-run preview)

Clicking `Apply`/`Update` opens a `WideModal` whose body is the **dry-run preview**
(`GET /apply-preview/{slug}`), grouped into `WideModalSection`s:
Modules (to enable / to disable, with the disable list visually flagged amber),
Regional defaults (currency note "new projects only", locale), Validation
(enabled vs. unavailable rule sets), Cost data (present/missing CWICR), Branding.
Blocking items render red and disable the confirm button until resolved. A
`ConfirmDialog`-style checkbox **"I understand modules will be turned off"** is
required when `modules_to_disable` is non-empty (maps to `confirm_disables`). On
confirm, call `POST /apply {dry_run:false}`, toast success, invalidate queries.

### 6.3 Help / empty state

`InfoHint` at the top of the tab: *"Partner Packs preconfigure currency, locale,
validation standards, branding and which modules are visible. Applying a pack changes
your module setup and defaults but never re-prices existing projects."* Empty state
keeps the existing copy (`:654-666`) plus the install-requires-restart caveat (§4).

### 6.4 ASCII wireframe — tab

```
┌ Modules ─ [Company Profiles] [Partner Packs] [Data Packages] [System] ───────┐
│ Partner Packs                                                                  │
│ Preconfigure currency, locale, standards, branding & visible modules.         │
│ ⓘ Applying a pack changes module setup & defaults — it never re-prices         │
│   existing projects. New packs need admin install + restart.   [Rescan]       │
│                                                                                │
│ ┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐   │
│ │▌US Construction Pack  │ │▌Batimatech (CA)       │ │▌BIM Hessen (DE)       │  │
│ │ us-costdata · v0.2.0  │ │ batimatech-ca · v0.2.0│ │ bimhessen-de · v0.2.0 │  │
│ │ [USD] [us_state_tax]  │ │ [CAD] [ca_gst_pst]    │ │ [EUR] [de_ust_19]     │  │
│ │ Standards: MF2020 +6  │ │ Standards: NBC +4     │ │ Standards: VOB +3     │  │
│ │ ── ✓ Active ────────  │ │ ───────────────────   │ │ ⬆ Update v0.1→v0.2    │  │
│ │ [Un-apply] [Re-apply] │ │ [Apply]               │ │ [Update]              │  │
│ └──────────────────────┘ └──────────────────────┘ └──────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.5 ASCII wireframe — apply-preview modal

```
┌ Apply "US Construction Pack" (us-costdata v0.2.0) ──────────────────── [✕] ┐
│ Review what will change. Nothing is applied until you confirm.              │
│                                                                            │
│ Modules                                                                    │
│   Enable:  ＋ Takeoff                                                       │
│   Disable: − Tendering   ⚠ currently in use                                │
│                                                                            │
│ Regional defaults                                                          │
│   Currency  EUR → USD   (new projects only — existing projects unchanged)  │
│   Locale    en  → en-US (new/un-set users only)                            │
│   Tax       us_state_sales_tax   ⓘ informational — no automatic effect yet │
│                                                                            │
│ Validation standards                                                       │
│   Enable: MasterFormat 2020      Unavailable in this build: AIA A201, OSHA │
│                                                                            │
│ Cost data (CWICR)                                                          │
│   Present: cwicr-usa-usd                                                   │
│                                                                            │
│ Branding   Colours + logo will switch to the partner theme.               │
│                                                                            │
│ ⚠ This will turn OFF 1 module.  [☐ I understand modules will be disabled]  │
│                                              [Cancel]   [Apply pack ▸]      │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Implementation plan (ordered; effort + mutation flags)

Legend: 🟢 non-destructive · 🔴 mutates existing data / config (needs explicit
confirm-before-build).

**Backend**
1. 🟢 Migration `v3151_partner_pack_state` (table per §1.1, idempotent guards per
   `v3150` pattern). ~0.5d.
2. 🟢 Model `PartnerPackStateRow` + import for `create_all` (fresh-SQLite boot). ~0.25d.
3. 🟢 `state.py`: `get_applied_pack`, snapshot read/write helpers; new precedence
   (DB → env → None). ~0.5d.
4. 🟢 `diff.py`: pure manifest-diff producing `ApplyPlan` (used by both preview and
   update). Fully unit-testable, no I/O. ~0.75d.
5. 🔴 `service.apply_pack` / `unapply_pack`: executes the plan — calls
   `module_loader.enable_module/disable_module`, writes state row + effects ledger,
   audits. **Mutates module config.** ~1.5d.
6. 🟢 Endpoints (`applied`, `apply-preview`, `apply`, `unapply`, optional `rescan`)
   with admin RBAC. ~0.5d.
7. 🟢 Make read endpoints DB-aware (`current`, `installed`, logo/favicon/locale/
   onboarding resolve via effective slug). ~0.5d.
8. 🟢 Tests: diff unit tests (apply + update + idempotent + unknown-module + blocking),
   apply integration test against the loader, RBAC 403 test, audit assertion. ~1.25d.

**Frontend**
9. 🟢 `partner-packs/api.ts` + `hooks.ts` (preview/apply/unapply/applied; invalidate
   `system-modules`). ~0.5d.
10. 🟢 Card footer actions + Active/Update badges. ~0.5d.
11. 🔴 Apply/Update `WideModal` preview + confirm-disables checkbox. (UI for a
    mutating action.) ~1d.
12. 🟢 Help/empty-state copy + i18n keys in `en.ts`/`ru.ts` (`modules.pack_apply_*`,
    `modules.pack_update_*`, `modules.pack_unapply_*`, preview section labels). ~0.5d.

**Total ≈ 9.75d.** Steps 5 and 11 are the only ones that change existing operator
config; they are the "confirm-before-build" gate.

---

## 8. Decision forks (for the product owner)

**Fork A — scope of "active pack": single global vs. per-project/tenant.**
Single global applied pack matches today's env model and the single-row table;
simple, ships fast. Per-project/tenant would let one server brand+configure several
clients, but currency/locale/modules are largely global today (module loader and
locale are process-wide), so per-tenant pack would be a much larger build (scoped
module visibility, tenant settings tables). *Recommendation:* **single global applied
pack now**; revisit per-tenant if/when multi-tenant module visibility lands.

**Fork B — disabling currently-enabled modules on apply: auto vs. warn-then-confirm.**
Auto = the pack's `hidden_modules` silently turn off whatever is on; cleanest result,
but surprises operators and can hide work-in-progress. Warn-then-confirm shows the
exact list in the dry-run and requires an explicit checkbox. *Recommendation:*
**warn-then-confirm** (never silently disable). Apply still auto-*enables*
`default_modules` (additive, non-destructive).

**Fork C — `validation_rule_packs` on apply: no-op-with-warning vs. block.**
(a) Enable only the rule sets that already exist in the registry and warn on the rest,
so packs ship today and degrade honestly. (b) Block apply until the declarative
rule-loader (v7) exists, so a pack never claims standards it can't enforce.
*Recommendation:* **(a) no-op-with-warning** — partial + transparent beats blocked.

**Fork D — runtime rescan endpoint: ship it or not.**
A `POST /rescan` (`reset_cache()`) lets on-disk `packs/` packs appear without a
restart, but cannot reliably pick up newly `pip install`ed entry-points in a live
interpreter, so the "restart for pip packs" caveat remains either way.
*Recommendation:* **ship rescan** (cheap, helps source-checkout / partner pilots),
and keep the restart messaging for pip-installed wheels.
