# One-Click Country Pack — Full Workspace Install

Status: DESIGN (2026-05-31). Owner: core. Supersedes the disconnected
`frontend/src/features/onboarding/countryPacks.ts` hardcoded picker.

## 1. Goal (founder intent)

> Let the user pick a country pack as an option right at the start, and then
> have everything install for them in one go: the language, all the databases,
> the simple ones and the vector ones alike, and two example projects from that
> country with all of their data.
>
> I do not see the packs we built together with partner companies. Why are they
> not showing up?
>
> Author a bespoke template for each one.
>
> These demos need to be worked all the way through every module, so the user
> sees straight away how to work with the platform.

So: pick a country/partner pack in onboarding → **one click installs everything**:
1. **Language** (locale) switched + activated.
2. **Both databases**: the *simple/relational* cost DB (CWICR) **and** the *vector* DB (embeddings for semantic search).
3. **2 example projects from that country**, each **fully worked through every module** so a new user immediately sees how to operate the whole platform.

And the **partner packs we actually built** (17 in `packs/` as of 2026-08) must be the thing shown in onboarding — not a separate hardcoded list.

## 2. Current state and the three gaps

**Gap A — onboarding ignores real packs.** `OnboardingWizard.tsx` renders a
hardcoded `COUNTRY_PACKS` list (21 generic presets) and never calls the
partner-pack API. The 12 real packs (`GET /api/v1/partner-pack/installed`) are
invisible. *This is why the founder doesn't see the partner packs.*

**Gap B — pack demos are thin.** `install_demo_project` builds the core
(BOQ ×2, schedule, budget/cash-flow/EVM, tendering, risk, change-orders,
documents) for every demo. But the rich per-module data lives in
`_seed_module_data`, whose 14 blocks are **dict-keyed by `demo_id` with an
empty-list fallback** (`_CONTACTS.get(demo_id, [])`). Only the 5 built-ins
(berlin/london/medical-us/dubai/paris) have entries. **All 12 pack demos get
zero** contacts / tasks / RFIs / meetings / safety / inspections / invoices /
finance-budgets / punchlist / field-reports / submittals / NCRs / correspondence.

**Gap C — whole modules are never seeded for anyone.** The dashboard landing
page alone shows three cards that are *always empty* even on built-ins:
**Daily diary**, **Variations**, **Compliance summary**. Several more content
modules have no demo data at all (see §4 matrix).

**Gap D — install is multi-step + manual.** Today a user must apply the pack,
then separately load CWICR, then separately vectorize, then install demos. No
single action; no "both databases"; no "2 projects".

## 3. Architecture decision — bespoke template + derived module data

Hand-authoring 14+ module blocks × ~20 demos by hand is ~10k LOC and
unmaintainable. Fully-generic data would feel canned. **We do a hybrid:**

- **The bespoke part is the `DemoTemplate` itself** — real local BOQ sections,
  local classification (DIN276 / NRM / MasterFormat / NBR / CPWD / SBC…),
  local currency, locale, address, and real local company names in
  `tender_companies`. This is authored per country and is where the national
  character lives. (This is the bespoke part the founder asked for.)
- **A generic, template-DERIVED module seeder** turns *any* template into full
  module coverage by generating realistic rows for every content module **from
  the template's own sections / companies / locale / currency**. Because it
  references the template's real trades and firms, the output reads as
  project-specific, not canned. An RFI cites a real section title; an NCR is
  raised against a real trade; a submittal names a real subcontractor; an
  invoice is issued by a real tender company.

**Authority rule:** the 5 built-ins keep their hand-authored dicts (they win on
`demo_id` match); every other demo (the 12 packs + the new bespoke 2nds) gets
the derived data. Implementation: each block becomes
`rows = _HAND[demo_id] or generated["<key>"]`.

This single change makes **all 12 existing pack demos full-module instantly**,
and every future bespoke demo is full-module for free.

## 4. Module-coverage matrix

Content modules a flagship project should visibly populate. "covered" = already
seeded; "ADD" = new block in the derived seeder (and, where a built-in should
also show it, a hand block); "infra" = not demo content.

| Module (dir)              | Today        | Plan |
|---------------------------|--------------|------|
| projects                  | covered      | — |
| boq (+ 2nd budget BOQ)    | covered      | — |
| markups                   | covered      | — |
| schedule / schedule_advanced | covered   | — |
| finance / full_evm / eac (cashflow, EVM, budget) | covered | — |
| tendering / bid_management | covered     | — |
| risk                      | covered      | — |
| changeorders              | covered      | — |
| documents / cde           | covered (stubs) | — |
| contacts / crm / subcontractors | hand-only | derive for packs |
| tasks                     | hand-only    | derive for packs |
| rfi                       | hand-only    | derive for packs |
| meetings                  | hand-only    | derive for packs |
| safety / hse_advanced     | hand-only    | derive for packs |
| inspections / qms         | hand-only    | derive for packs |
| punchlist                 | hand-only    | derive for packs |
| fieldreports              | hand-only    | derive for packs |
| submittals                | hand-only    | derive for packs |
| ncr                       | hand-only    | derive for packs |
| correspondence            | hand-only    | derive for packs |
| **variations**            | **none**     | **ADD** (dashboard card empty) |
| **daily_diary**           | **none**     | **ADD** (dashboard card empty) |
| **compliance / compliance_docs** | **none** | **ADD** (dashboard card empty) |
| **procurement**           | **none**     | **ADD** |
| **contracts**             | **none**     | **ADD** |
| **transmittals / file_transmittals** | **none** | **ADD** |
| **resources / equipment** | none (in BOQ meta only) | **ADD** (lightweight) |
| **requirements / bim_requirements** | none | ADD (lightweight) |
| **progress**              | none         | ADD (lightweight, derives from schedule) |
| takeoff / dwg_takeoff     | none         | best-effort: link a demo drawing doc |
| bim_hub / cad / clash     | stub         | keep stub (geometry bundle is separate) |
| carbon                    | none         | optional, defer |
| admin/users/teams/notifications/integrations/backup/search/file_*/ai/portal/pipelines/*_pack | infra | none |

Priority order for ADD: the 3 dashboard-visible gaps first
(**variations, daily_diary, compliance**), then contracts/procurement/
transmittals, then the lightweight rest.

## 5. Orchestration endpoint

`POST /api/v1/partner-pack/full-install` — RBAC `admin`. Synchronous, runs
under the client's `LONG_RUNNING_TIMEOUT_MS` (300 s). Returns a per-step result
so the UI can render a checklist that fills in.

Request:
```jsonc
{
  "slug": "batimatech-ca",     // partner-pack slug (required)
  "set_locale": true,           // switch active locale to pack default_locale
  "install_cost_db": true,      // load-cwicr for resolved region(s)
  "vectorize": true,            // build vector DB for the loaded region(s)
  "demo_count": 2               // install up to N country demos (default 2)
}
```

Steps (each fail-soft; a failed step is reported, never aborts the rest):
1. **apply_pack(slug)** — existing `apply_pack`, but call with
   `install_demo=False` (we install demos explicitly in step 5 so we control
   the count). Enables modules, sets currency/classification/branding, persists
   active pack.
2. **locale** — record `default_locale` as the workspace locale (front-end
   activates it; back-end just confirms availability).
3. **cost_db** — resolve `manifest.cwicr_regions` slugs → load-cwicr `db_id`s
   via the **city-suffix map** (§5.1) and call the existing CWICR loader for
   each resolvable region. Skip+report unresolved/empty regions.
4. **vector_db** — for each loaded region, run the existing
   `vector/vectorize` path (LanceDB embedded / Qdrant server). Fail-soft if the
   embedding model is unavailable (feature degrades, not a hard error).
5. **demos** — pick up to `demo_count` demo ids for the pack's country from
   `DEMO_CATALOG` (filter by `country`; the pack flagship from
   `PACK_DEMO_PROJECT` is always included first), then call
   `install_demo_project` for each (idempotent).

Response:
```jsonc
{
  "slug": "batimatech-ca",
  "ok": true,
  "steps": [
    {"step": "apply_pack",  "status": "ok",      "detail": {"modules_enabled": 7}},
    {"step": "locale",      "status": "ok",      "detail": {"locale": "fr-CA"}},
    {"step": "cost_db",     "status": "ok",      "detail": {"regions": ["CA_TORONTO"], "items": 54213}},
    {"step": "vector_db",   "status": "ok",      "detail": {"regions": ["CA_TORONTO"], "vectors": 54213}},
    {"step": "demos",       "status": "ok",      "detail": {"installed": ["office-montreal", "condo-toronto"]}}
  ]
}
```

### 5.1 CWICR slug → db_id map (city suffix)

Pack slugs are `cwicr-{lang}-{city}`; load-cwicr ids are `{COUNTRY}_{CITY}`.
Resolve by the **city** token (the lang token is unreliable: `eng`/`fra` both
mean Canada). Build a `{city: db_id}` index from `_REGION_CURRENCY` keys and
match the slug's last segment. Known live ids include `DE_BERLIN`, `FR_PARIS`,
`GB_LONDON`, `CA_TORONTO`, `BR_SAOPAULO`, `AE_DUBAI`, `SA_RIYADH`, `AU_SYDNEY`,
`NZ_AUCKLAND`, `IN_MUMBAI`, `US`/`USA_USD`. Unresolved slugs (e.g.
`cwicr-fra-montreal`, which has no CWICR data yet) are skipped and reported in
`detail.skipped`.

## 6. Bespoke 2nd demos to author

Each onboarding country needs **2** demos. Inventory by country:

| Country | demo #1 (exists)                     | demo #2 |
|---------|--------------------------------------|---------|
| DE      | residential-berlin (built-in)        | office-frankfurt (bimhessen-de pack) ✓ |
| GB      | office-london (built-in)             | commercial-london (uk-jct pack) ✓ |
| US      | medical-us (built-in)                | commercial-denver (us-costdata pack) ✓ |
| FR      | school-paris (built-in)              | **AUTHOR** |
| AE      | warehouse-dubai (built-in)           | **AUTHOR** |
| CA      | office-montreal (batimatech pack)    | **AUTHOR** |
| AU      | mixed-use-sydney (aus pack)          | **AUTHOR** |
| NZ      | commercial-auckland (nzs pack)       | **AUTHOR** |
| BR      | residential-saopaulo (brazil pack)   | **AUTHOR** |
| IN      | govt-building-delhi (india pack)     | **AUTHOR** |
| SA      | mixed-use-riyadh (saudi pack)        | **AUTHOR** |

→ **8 new bespoke templates** (FR, AE, CA, AU, NZ, BR, IN, SA), each a distinct
archetype from its sibling. Each is a new `backend/app/core/demo_packs/<id>.py`
exporting a `TEMPLATE = DemoTemplate(...)`; the loader auto-registers it and
`_catalog_entry_from_template` auto-adds a `DEMO_CATALOG` row with `country`
derived from the address. (Theme packs formwork/modular/renewables: keep 1 each
for now; not country onboarding targets.)

Authoring brief per template (mimic `demo_packs/office-montreal.py`):
- Distinct building archetype + real city in that country (not the sibling's).
- 8–13 sections, ~60–120 priced positions, **real local classification codes**.
- Correct `currency`, `locale`, `validation_rule_sets`, structured `address`
  with real lat/lng, 4–6 real local `tender_companies`.
- Realistic local description with standards (NBC/CSA, RE2020, NCC, NBR, NBC-IN,
  SBC, etc.). The derived seeder handles all module data — authors do **not**
  hand-write RFIs/NCRs/etc.

## 7. Onboarding rewire (frontend)

- Fetch `GET /api/v1/partner-pack/installed`; render those as the primary
  "Set up by country" cards (logo, partner name, country, currency, locale).
- Keep the generic `countryPacks.ts` presets as a secondary "Other countries"
  group for countries without a partner pack (locale + classification only,
  no demos) so the existing breadth is preserved.
- On select → `POST /partner-pack/full-install` with a **progress checklist**
  UI (the 5 steps from §5, each ✓/spinner/✗). On completion, activate locale
  client-side and route to the first installed demo project.
- Remove the old per-button `handlePackDb`/`handlePackDemo`/`handlePackLocale`
  fan-out in favour of the single orchestrated call.

## 8. Build lanes (parallel, disjoint files)

- **Lane E (engine)** — `backend/app/core/demo_projects.py`: add the derived
  module seeder + wire `_HAND[demo_id] or generated[...]` into all 14 blocks +
  add the §4 ADD modules. Solo on this file.
- **Lane O (orchestrator)** — `backend/app/core/partner_pack/` (+ a thin route):
  the `full-install` endpoint, slug→db_id resolver, step runner. Solo here.
- **Lanes D1–D8 (demos)** — one new `demo_packs/<id>.py` each. Fully disjoint.
- **Lane F (frontend)** — `OnboardingWizard.tsx` + `countryPacks.ts` rewire,
  built against the §5 contract.

## 9. Verification

Per pack on :8000: run full-install; assert response steps all ok; open the
first demo's `/projects/{id}` and confirm the previously-empty cards (Daily
diary, Variations, Compliance) now render rows; spot-check RFIs/NCRs/meetings/
submittals/invoices pages show the demo's data; confirm locale switched and the
cost DB browser shows the region's items.
