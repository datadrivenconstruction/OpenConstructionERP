# OpenConstructionERP / Mullets Aluminum Products, Inc. — Codex Session Handoff

## Handoff date

2026-08-25

## Current repository state

- Working directory: `C:\Users\cadco\source\repos\OpenConstructionERP`
- Upstream: `https://github.com/datadrivenconstruction/OpenConstructionERP.git`
- Upstream default branch: `main`
- Exact checked-out upstream commit: `d5b1225afb608348cc3da1dbac60edb9ef2caca3`
- Upstream commit subject: `chore: release 15.8.0`
- Current working branch: `001`
- Publication remote: `https://github.com/CADcoLabs/OpenConstructionERP.git`
- Checkout is intentionally shallow (`--depth=1`).
- The root already contained this handoff, so a literal `git clone ... .` could not run. The equivalent in-place sequence was used: `git init`, add `origin`, fetch only `main`, and create the tracked checkout. The handoff never moved.
- Branch `001` contains the Mullets partner pack, repository instructions, and this handoff and is published to the CADcoLabs fork. No PR, merge to `main`, or deployment has been performed. Browser UAT was attempted in the current slice but could not run because the in-app browser runtime rejected its required sandbox metadata.

## Verified toolchain

- Git `2.52.0.windows.1`
- Python `3.13.11`
- Node `26.5.0`
- npm `11.6.4`
- Docker Engine `29.7.2`
- Docker Compose `v5.4.0`
- GNU Make is not installed.

## Baseline startup smoke

Branding work did not begin until the startup gate below passed.

### Exact-source attempt

- Command path: `docker compose -f docker-compose.quickstart.yml up -d --build`
- Bound: 15 minutes.
- Result: timed out after 904 seconds before producing an application image or runnable app container.
- This is not recorded as a pass for source commit `d5b1225...`.

### Packaged fallback

- Used the handoff-approved published-image override:
  `docker-compose.quickstart.yml` plus `docker-compose.quickstart.image.yml`.
- Host port `8080` was already allocated, so the isolated smoke used `127.0.0.1:18080`.
- The first source attempt had created disposable compose volumes with an earlier ephemeral password. Both volumes were verified as session-created at `2026-08-25T10:33:15Z`, removed, and recreated; they contained no prior project data and are not recoverable.
- Final container status: PostgreSQL healthy; application healthy.
- `GET http://127.0.0.1:18080/api/health` returned HTTP `200`.
- Response evidence: status `healthy`, version `15.7.0`, database `ok`, Alembic head matched, schema healing did not fail, frontend dist present, 188 modules loaded.
- The packaged fallback stack was restarted in the current slice and is now running with the Mullets pack active. Its existing application and PostgreSQL volumes were preserved.

## Implemented slice: Mullets drop-in partner pack

The smallest existing white-label architecture was used: a declarative data-directory/drop-in pack, not a core fork or pip-package scaffold.

Files:

- `packs/mullets-aluminum/manifest.json`
- `packs/mullets-aluminum/logo.png`

Manifest choices:

- Slug: `mullets-aluminum`
- Exact partner name: `Mullets Aluminum Products, Inc.`
- Pack type: `partner`
- Version: `0.1.0`
- Locale/currency: `en-US` / `USD`
- Primary color: `#0055A6`, measured as the dominant blue in the supplied logo.
- Logo: copied from `C:\Users\cadco\source\repos\v2_MAPI-M1-Ops\docs\IMAGES\MulletsLogoSM.png`; the source file was not moved or modified.
- The core-generated attribution remains active: `Powered by OpenConstructionERP · In partnership with Mullets Aluminum Products, Inc.`

Deliberately omitted because no approved values or content were supplied:

- Partner URL and support/contact metadata
- Favicon
- Accent color
- Promotional claims, tagline, or onboarding copy
- Tax template and estimating methodology
- Validation rules, regional cost data, demo templates, and module visibility changes
- Frontend, backend, PDF, metadata, or PWA changes

## Verification

- Strict manifest validation through `PartnerPackManifest`: passed.
- Real drop-in discovery with the repository root used as the data dir: passed.
- `OE_PARTNER_PACK=mullets-aluminum` activation: passed.
- Logo resolution through `read_pack_file`: passed.
- Source and copied logo SHA-256 match:
  `cae91afec83ca1e7c0e2949bf71a143966f4bc251b1348afc94c1f5799573067`.
- Company name, pack type, primary color, empty behavioral presets, omitted URL/favicon/onboarding, and exact OpenConstructionERP attribution were asserted: passed.
- Focused upstream pytest command was attempted for partner-pack core, drop-in, and demo-project coverage. It stopped in `backend/tests/conftest.py` before collection because `pixeltable_pgserver` is not installed and no external PostgreSQL test URL was configured.
- `LICENSE`, `NOTICE`, and existing OpenConstructionERP attribution files are unchanged.

## Continued verification slice: active Mullets runtime

Live state verified on 2026-08-25:

- Git remains on `feat/mullets-partner-pack` at exact commit `d5b1225afb608348cc3da1dbac60edb9ef2caca3` (`chore: release 15.8.0`).
- Only `packs/mullets-aluminum/` and this handoff are untracked; there are no tracked-file diffs.
- PostgreSQL, OpenConstructionERP, and the separate company SQL Server container are running. The OpenConstructionERP containers are healthy.
- `GET http://127.0.0.1:18080/api/health` returns HTTP `200`, application version `15.7.0`, database `ok`, and matching Alembic head.
- The existing `openconstructionerp_app_data`, `openconstructionerp_pg_data`, and `mssql-data` volumes were neither reset nor replaced.

Runtime activation uses no in-app apply operation and writes no partner state or demo data:

- `OE_PARTNER_PACK=mullets-aluminum` is set on the running application container.
- The host pack folder is bind-mounted read-only at the published image's actual discovery path: `/app/.openestimate/packs/mullets-aluminum`.
- The first attempted read-only target, `/data/packs/mullets-aluminum`, was confirmed not to be scanned by published image `15.7.0`; it was replaced without activating the pack or changing data.
- `GET /api/v1/partner-pack/current` reports the pack active with the exact Mullets name, primary color `#0055A6`, logo present, favicon absent, and attribution `Powered by OpenConstructionERP · In partnership with Mullets Aluminum Products, Inc.`
- `GET /api/v1/partner-pack/logo/mullets-aluminum` returns the 15,116-byte PNG, and its SHA-256 matches the checked-in pack logo.
- A focused Python assertion check covering strict manifest parsing, drop-in discovery, environment activation, color, omitted favicon, logo bytes, and exact attribution passed.

Visual/browser status:

- The running application exposes the approved logo, color, and attribution correctly through the same runtime API and asset routes consumed by `PartnerLogoBadge`.
- Rendered login/header/dashboard verification is still incomplete. The mandatory in-app browser connection failed before navigation with a runtime sandbox-metadata error.
- The existing `PartnerLogoBadge` source renders the runtime partner name/logo in the nav and the runtime logo, primary-color tint, and OpenConstructionERP attribution on the dashboard. Its focused test could not be run because `frontend/node_modules` is absent; dependencies were not installed for this bounded verification slice.
- The three focused backend pytest files remain blocked before collection because `pixeltable_pgserver` is absent and no disposable external PostgreSQL test URL is configured. The live OpenConstructionERP database was not used as a test database.

Company Reporting connection:

- A direct read-only `mapi_reader` connection to Docker SQL Server database `M1_MA_Reporting` succeeded after activation.
- The application-style query returned 16,307 sales orders with maximum order date `2026-08-05`.
- No DDL, DML, restore, reset, or volume operation was run against the company Reporting database.

## Resumed UAT slice: browser connection remains blocked

Live state was reverified on 2026-08-25 before attempting UAT:

- Git is still on `feat/mullets-partner-pack` at `d5b1225afb608348cc3da1dbac60edb9ef2caca3` (`chore: release 15.8.0`). Only `packs/mullets-aluminum/` and this handoff are untracked; there are no tracked-file diffs.
- `openconstructionerp-app-1` and `openconstructionerp-postgres-1` are healthy; `sqlserver` is running.
- The existing `openconstructionerp_app_data`, `openconstructionerp_pg_data`, and `mssql-data` volumes remain mounted. No database or volume was modified, reset, or replaced.
- `GET http://127.0.0.1:18080/api/health` returned HTTP `200`, status `healthy`, version `15.7.0`, database `ok`, matching Alembic head, frontend dist present, and 188 loaded modules.
- The application still has `OE_PARTNER_PACK=mullets-aluminum`, and the pack bind mount remains read-only at `/app/.openestimate/packs/mullets-aluminum`.
- `GET /api/v1/partner-pack/current` returned the active Mullets pack with exact name `Mullets Aluminum Products, Inc.`, primary color `#0055A6`, logo present, favicon absent, and attribution `Powered by OpenConstructionERP · In partnership with Mullets Aluminum Products, Inc.`
- `GET /api/v1/partner-pack/logo/mullets-aluminum` returned 15,116 bytes with SHA-256 `cae91afec83ca1e7c0e2949bf71a143966f4bc251b1348afc94c1f5799573067`.
- A direct `mapi_reader` connection returned `M1_MA_Reporting`, 16,307 sales orders, and maximum order date `2026-08-05`. Permission checks returned `SELECT=1`, `INSERT=0`, `UPDATE=0`, `DELETE=0`, and `CREATE TABLE=0`.

The mandatory in-app browser connection failed before navigation with `codex/sandbox-state-meta: missing field sandboxPolicy`. The browser setup was retried, including a metadata check, but the tool rejected both calls before a tab could be acquired. Therefore:

- Rendered login/header/dashboard UAT did not run and has not passed.
- No visual pass is claimed; browser connectivity is the current release blocker.
- Per the UAT gate, no disposable PostgreSQL test environment was created and no focused backend tests were run.
- `frontend/node_modules` remains absent, so the focused `PartnerLogoBadge` test was not run and project files were not changed to install dependencies.

## Next bounded slice

1. Restore the in-app browser tool's missing sandbox-policy metadata, then perform rendered login/header/dashboard UAT for the Mullets logo, `#0055A6` tint, exact company name, and OpenConstructionERP attribution. Treat any visual defect as a blocker.
2. Only after visual UAT passes, configure a disposable PostgreSQL test URL and run the focused partner-pack backend tests without using the live OpenConstructionERP database.
3. Run the focused `PartnerLogoBadge` test only if frontend dependencies are already available or can be installed without project-file changes.

## Resume prompt

> Resume in `C:\Users\cadco\source\repos\OpenConstructionERP`. Read `sessionhandoffCODEX.md` first. The current blocker is the in-app browser tool error `codex/sandbox-state-meta: missing field sandboxPolicy`; restore that connection and complete rendered login/header/dashboard UAT before running tests. Preserve the read-only Mullets drop-in activation, existing database data/volumes, minimal branding, and OpenConstructionERP attribution. Only after visual UAT passes, configure a disposable PostgreSQL test database and run the focused partner-pack tests. Do not use the live OpenConstructionERP database for tests, add promotional claims, broaden branding, commit, or push without approval.
