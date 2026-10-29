# ADR — Partner-Pack Architecture Decisions

**Status:** accepted
**Date:** 2026-05-28
**Related:** v5.6.0 release (`v5_6_0_release.md`), `docs/partner-packs/README.md`,
`docs/partner-packs/MANIFEST_REFERENCE.md`
**Implementation:** `backend/app/core/partner_pack/`, reference packs under `packs/`

## Context

Three requests during v5.5.x (a Canadian regional pack, a Hessen BIM pack,
and a Saudi consultancy pack) all asked the same question with different
wording: *"How do we ship a regional/brand-specific version of OCERP
without forking the repo?"*

Three shapes were considered:

**Shape A — Declarative preset bundles** (a pack is one manifest + static
assets). The pack flips switches on features the core already ships:
default locale, default currency, validation-rule slugs to enable,
sidebar layout, brand colours, logo, onboarding script.

**Shape B — Plugin runtime** (a pack ships its own Python modules with
new tables, routes, and rule classes that the loader discovers via
entry-points). This is what WordPress/PostHog/Sentry do.

**Shape C — Hosted multi-tenant config layer** (per-tenant manifest
stored in the database, switchable at request time without restart).

A second cross-cutting question was the **distribution mechanism**:

- **REST plugin registry** — packs hit a `/api/v1/admin/packs` endpoint
  with their manifest, the core persists them, applies them at request
  time.
- **Python entry-points** — packs are pip wheels; the core enumerates
  the `openconstructionerp.partner_packs` entry-point group at boot.

## Decision

For v5.6.x we adopt:

1. **Shape A — declarative preset bundles** for partner packs.
2. **Single-tenant** activation: exactly one pack is active per install,
   selected by `OE_PARTNER_PACK` env var or first-alphabetical fallback.
3. **Python entry-points** for distribution, not a REST registry.

Shape B (plugin modules) is the existing path under
`backend/app/modules/<name>/` — but those are *modules*, not packs.
The two systems remain separate and are documented separately
(see `docs/module-development/quickstart.md` for modules).

Shape C (multi-tenant) is deferred to a future major release. The
current architecture does not preclude it; the Pydantic manifest could
be persisted per-tenant later. We chose not to ship it now because
zero of the three partner conversations needed it — every partner runs
their own VPS.

### Why Shape A and not Shape B

- **Lower partner cost-of-entry.** A pack ships in an afternoon: one
  Pydantic model, an SVG, an optional YAML. Shape B requires the
  partner to learn SQLAlchemy, Alembic, FastAPI, the module loader,
  permissions, and the events system before they ship anything.
- **Lower core maintenance.** Shape A packs cannot break the database
  schema, cannot leak data across tenants, cannot collide with core
  routes, cannot conflict with each other (only one active at a time).
- **Forward-compatible with Shape B.** The `validation_rule_packs` list
  on the manifest already accepts opaque slugs. When v7.0 introduces
  runtime-loaded rule packs, the same field becomes the discovery
  point — no manifest schema change.
- **Reuses what already works.** Every preset the manifest exposes
  (locale, currency, rule slugs, sidebar layout) is a setting the
  core already reads from `ProjectConfig` / `TenantConfig`. The pack
  is just a deterministic seed.

### Why entry-points and not a REST registry

- **No new database tables.** The discovery mechanism is `importlib.metadata.entry_points(group=...)`. Zero migrations, zero ORM models, zero admin UI for pack registration.
- **Atomic with the wheel.** `pip install openconstructionerp-batimatech-ca`
  installs the assets, the manifest, and the entry-point in one
  operation. `pip uninstall` reverses it cleanly. No half-applied state.
- **Trivial to test.** Unit tests can `monkeypatch` the entry-points
  iterator and the discovery cache. There is no HTTP layer, no auth, no
  rate limiting to worry about.
- **Already supported by PyPI.** Partners can publish their packs as
  ordinary PyPI distributions with no platform-specific tooling.
- **Versioning is free.** Each pack carries `pack_version` independently
  of the core. `pip install --upgrade` works as expected.
- **Read-only and cacheable.** `discover_packs()` is `lru_cache`'d for
  the process lifetime — zero per-request cost. A REST registry would
  hit the DB or cache on every page load.

The trade-off: packs cannot be installed/removed without restarting the
backend. We judge this acceptable because:

- Partners run dedicated installs (no live pack-switching needed).
- Restart cost is ~3 seconds (Uvicorn factory mode).
- The alternative — runtime install — would require sandboxing arbitrary
  partner Python code, which is a security project we are not signing
  up for.

### Why single-tenant

- Matches every partner conversation to date — each runs their own VPS.
- Avoids the per-request manifest resolution layer (which would require
  caching, tenant inference middleware, and a tenant-pack join table).
- The env-var precedence (`OE_PARTNER_PACK`) makes the active pack a
  deployment artifact, not a runtime decision — easier to reason about,
  easier to debug.
- Frees us to bake pack-derived values (locale default, primary colour)
  into the global app state at boot instead of resolving them per
  request.

Multi-tenant pack selection remains feasible: the same `PartnerPackManifest`
schema could be persisted per-tenant, with a tenant-aware override of
`get_active_pack()`. The frontend hook (`usePartnerPack`) already calls
an HTTP endpoint, so it would automatically pick up per-tenant manifests
without code changes. We will revisit this when a hosted multi-tenant
deployment is on the roadmap.

## Consequences

**Positive**

- Partners can ship a branded edition in one afternoon.
- Core schema and routes are unchanged — packs cannot break upgrades.
- The 10 reference packs under `packs/` double as integration tests for
  the manifest schema.
- AGPL co-brand obligation is centralised in
  `PartnerPackManifest.effective_powered_by` — partners cannot
  accidentally strip the attribution.
- No new infrastructure: no admin UI, no DB tables, no background jobs.

**Negative / accepted**

- Packs cannot add new modules, routes, tables, or rule classes. Partners
  who need any of those write a module instead. We accept the friction
  because it keeps packs trivial and modules powerful.
- Only one pack active per install. Multi-tenant deployments must wait
  for Shape C. Acceptable because zero current partners need it.
- Pack changes require a backend restart. Acceptable given the use case
  (production-pinned deployments, not hot-reloaded experiments).
- Reference rule-pack JSON files under `packs/<slug>/rule_packs/` are
  currently documentation-only — the core does not execute them as
  rules. This is forward-compatible: when v7.0 introduces declarative
  rule packs, the same files become runtime-loadable without a
  manifest-schema change.

**Rollback path**

If Shape A proves insufficient and we need Shape B (runtime module
plugins from packs), the entry-point group becomes a second discovery
mechanism alongside the file-system scan in `module_loader.py`. The
existing `PartnerPackManifest` schema remains valid — Shape B would add
a sibling entry-point group (`openconstructionerp.modules`), not modify
the existing one. No migration of installed packs is required.

If single-tenant proves insufficient, the migration to Shape C is
additive: `get_active_pack()` gains a `tenant_id` parameter and reads
from a new `oe_tenant_partner_pack` join table when present, falling
back to the env-var / first-installed precedence when absent.

## Verification

- 13/13 unit tests in `backend/tests/test_partner_pack_core.py` pass —
  schema validation, entry-point discovery, env-var precedence,
  broken-pack tolerance, all five router endpoints.
- Fresh-venv smoke test on Python 3.14:
  `pip install openconstructionerp openconstructionerp-batimatech-ca` →
  alembic v3148 head, backend boots with `"Partner pack active:
  batimatech-ca"` log line, 5/5 API endpoints pass, 5/5 browser
  screenshots pass. The screenshots were captured and retained with the
  maintainers' internal verification records, not in this repository.
- 10 reference packs under `packs/` exercise the full manifest surface
  (locales, favicon, multiple rule-pack slugs, optional fields).

## Open questions (out of scope)

- **Pack signing / supply-chain.** PyPI trusted publishing handles
  integrity; we have not designed pack-level signing. Revisit if a
  malicious-pack incident occurs.
- **Pack marketplace UI.** Currently partners distribute their pack URL
  manually. A discovery UI (`/admin/marketplace`) is on the roadmap but
  not part of this ADR.
- **Pack-shipped frontend assets** (e.g., a partner-specific dashboard
  widget). Would require either Vite SSR or a runtime React component
  loader. Out of scope for v5.6.x.

## Links

- Onboarding guide: `docs/partner-packs/README.md`
- Manifest field reference: `docs/partner-packs/MANIFEST_REFERENCE.md`
- Source: `backend/app/core/partner_pack/{manifest,discovery,router}.py`
- Reference packs: `packs/{aus-nzs,batimatech-ca,bimhessen-de,brazil-sinapi,doker-formwork,india-cpwd,renewables-epc,saudi-vision2030,uk-jct,us-costdata}/`
- Memory: `v5_6_0_release.md`
