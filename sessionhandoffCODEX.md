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

## Backend source functionality validation

Completed on 2026-08-25 from branch `001` without using either live database:

- Used Python 3.13 and uv's isolated no-project environment, so no repository virtual environment or lockfile was created.
- The test harness booted its own throwaway embedded PostgreSQL cluster before importing the application.
- Focused partner-pack suites passed: 72 tests covering core manifests, drop-in discovery/API behavior, and demo-project resolution.
- Full API smoke passed: 11 tests covering application lifespan startup, health and system status, registration/login, project CRUD, BOQ estimating, costs, tendering, and scheduling.
- The temporary PostgreSQL server shut down and its `oe-tests-pg-*` data directory was removed. The existing OpenConstructionERP and `M1_MA_Reporting` database containers were not used or changed.
- A post-pytest Colorama logging error occurred after the successful test result while the PostgreSQL cleanup logger wrote to a closed stream. PostgreSQL still reported a successful stop, pytest exited `0`, and the temporary data directory no longer exists.

## Final rendered UAT attempt: browser metadata still blocked

Reverified live on 2026-08-25 without resetting or modifying application or database state:

- Git is on branch `001`, tracking `cadcolabs/001`, at published commit `51e6cbf4eda3d860b5e95f73558d0b2af2f47e66` (`feat(partner-pack): add Mullets branding`). This handoff is the only working-tree modification.
- `openconstructionerp-app-1` and `openconstructionerp-postgres-1` are healthy; the separate `sqlserver` container is running.
- The existing `openconstructionerp_app_data`, `openconstructionerp_pg_data`, and `mssql-data` volumes remain present. The ERP containers still mount the two ERP volumes, and the application still mounts `packs/mullets-aluminum` read-only at `/app/.openestimate/packs/mullets-aluminum`.
- `GET http://127.0.0.1:18080/api/health` returned HTTP `200`, status `healthy`, database `ok`, matching Alembic head, frontend dist present, and 188 loaded modules.
- `OE_PARTNER_PACK=mullets-aluminum` remains active. `GET /api/v1/partner-pack/current` returned the exact company name `Mullets Aluminum Products, Inc.`, primary color `#0055A6`, logo present, favicon absent, and the OpenConstructionERP partnership attribution.
- The logo endpoint returned 15,116 bytes with SHA-256 `cae91afec83ca1e7c0e2949bf71a143966f4bc251b1348afc94c1f5799573067`.

The mandatory in-app browser connection again failed before navigation with `codex/sandbox-state-meta: missing field sandboxPolicy`. Consequently, rendered UAT for the login page, Mullets logo/name, `#0055A6` branding, attribution, authenticated dashboard, and basic navigation did not run and has not passed. No visual pass is claimed; browser connectivity remains the release blocker.

## Next-session authorization and browser readiness

The user explicitly authorized full rendered UAT through the configured standalone Playwright MCP. This work should begin only in the next session, after the user updates Codex and restarts the machine. Repair of the in-app browser is authorized as a separate follow-up after Playwright UAT; it must not delay or replace the Playwright evidence gate.

Pre-restart diagnostic evidence:

- Final git status was `MM sessionhandoffCODEX.md`: the previously staged handoff update and the newer unstaged next-session instructions must both be preserved. No commit or push was made.
- `codex --version` returned `0.147.0`; `codex doctor` reported `0.149.1` available and otherwise reported zero failed checks.
- The installed VS Code Codex extension is `26.818.61809`.
- The configured bundled browser, Chrome, computer-use, and Node browser runtime are `26.611.61049`.
- The exact in-app browser failure remains `codex/sandbox-state-meta: missing field sandboxPolicy`, raised before any browser code or navigation runs.
- The version difference is a likely host/runtime integration issue, not a confirmed root cause. Reverify all versions after the update and restart instead of relying on these pre-restart values.
- Standalone Playwright is configured as `npx --yes @playwright/mcp@latest`, and its navigation, snapshot, screenshot, console, network, form, and interaction tools were exposed in this session. Reverify availability in the new session.

Required Playwright UAT evidence:

1. Reverify git status, Docker health, the current partner-pack API response, logo hash, and the three named volumes without resetting or modifying them.
2. Use the standalone Playwright browser against `http://127.0.0.1:18080`; do not wait for the in-app browser repair.
3. At a desktop viewport, visually verify the login page, exact Mullets logo and company name, `#0055A6` branding, OpenConstructionERP partnership attribution, spacing, clipping, contrast, and obvious broken assets.
4. Authenticate with an existing application UAT account, then verify the dashboard/header branding and basic navigation through the principal project, BOQ/estimating, costs, tendering, and scheduling surfaces available to that account.
5. Capture screenshots plus accessibility snapshots, console errors, and failed network requests sufficient to support every visual/navigation claim. Record artifact paths in this handoff.
6. Treat any visual, authentication, console, network, or navigation defect as a blocker. Do not claim a pass from API/source inspection alone.
7. Do not search for or expose credentials. If no existing application UAT account is available, stop and ask before creating one because registration would modify the live ERP application database.
8. After Playwright UAT concludes, retry the in-app browser on the updated/restarted Codex installation. Record the new versions and outcome; if the same metadata error remains, preserve the exact error and continue using Playwright for UAT.

## Post-update standalone Playwright rendered UAT

Completed on 2026-08-25 at a 1440 x 1000 desktop viewport against `http://127.0.0.1:18080` with the configured standalone Playwright MCP. No registration, project creation, estimate creation, tender creation, schedule creation, test suite, database command, commit, push, PR, Reporting refresh, container reset, or volume reset was performed.

Preflight reverified without resetting state:

- Git is on `001`, tracking `cadcolabs/001`, at published commit `51e6cbf4eda3d860b5e95f73558d0b2af2f47e66`. The handoff remained `MM sessionhandoffCODEX.md`; the staged index version was not changed.
- `openconstructionerp-app-1` and `openconstructionerp-postgres-1` were healthy; `sqlserver` was running.
- `openconstructionerp_app_data`, `openconstructionerp_pg_data`, and `mssql-data` existed with their original creation timestamps. The application pack bind mount remained read-only at `/app/.openestimate/packs/mullets-aluminum`.
- `/api/health` returned HTTP 200, status `healthy`, version `15.7.0`, database `ok`, matching Alembic head, frontend dist present, and 188 modules.
- `/api/v1/partner-pack/current` returned the active Mullets partner pack with exact company name `Mullets Aluminum Products, Inc.`, primary color `#0055A6`, logo present, and OpenConstructionERP partnership attribution.
- The runtime logo returned 15,116 bytes and SHA-256 `cae91afec83ca1e7c0e2949bf71a143966f4bc251b1348afc94c1f5799573067`, matching `packs/mullets-aluminum/logo.png`.

Rendered results:

- Authentication passed using the existing built-in Admin demo account exposed by the login page. No credentials were searched for or exposed, and no account was created.
- Authenticated dashboard passed. It rendered the exact Mullets company name and runtime logo in the header and partner banner. The banner rendered `Powered by OpenConstructionERP · In partnership with Mullets Aluminum Products, Inc.` without clipping.
- The dashboard partner banner applied `rgb(0, 85, 166)` (`#0055A6`) as its left border and gradient tint.
- Projects, Bid Schedule (`/boq`), Cost Database (`/costs`), Tendering (`/tendering`), and 4D Schedule (`/schedule`) navigation all passed after fresh accessibility snapshots; each destination had the expected URL/title and rendered without an obvious layout, clipping, contrast, or broken-asset defect.
- Console evidence reports zero errors and zero warnings. Network evidence contains 169 requests, all successful; there were no failed requests.
- The authenticated application automatically sent `PUT /api/v1/users/me/dashboard-layout/` and received HTTP 200 while loading the dashboard. No explicit create/update action was taken in the UI; this automatic preference persistence is recorded because it is a live ERP application write inherent in the authorized UAT session.
- **UAT blocker:** the rendered login page shows only the upstream OpenConstructionERP logo/name. It does not render the active Mullets logo or exact company name. Because login branding was an explicit visual gate, overall rendered UAT is **blocked**, not passed.

Evidence directory: `output/playwright/uat-2026-08-25/`

- Login: `login-page.png`, `login-accessibility.md`, `login-console-errors.txt`, `login-network.txt`
- Dashboard: `dashboard.png`, `dashboard-accessibility.md`, `dashboard-partner-rendering.json`, `dashboard-partner-images.json`, `dashboard-branding-styles.json`
- Navigation: `projects.png`, `projects-accessibility.md`, `boq.png`, `boq-accessibility.md`, `costs.png`, `costs-accessibility.md`, `tendering.png`, `tendering-accessibility.md`, `scheduling.png`, `scheduling-accessibility.md`
- Whole session: `session-console-errors.txt`, `session-network.txt`
- Runtime preflight/postflight/logo/volumes: `runtime-preflight.json`, `runtime-postflight.json`, `mullets-logo-runtime.png`, `volumes.txt`
- Evidence totals: `evidence-summary.json`

## Post-update in-app browser retry

- Codex CLI: `0.149.1`
- VS Code: `1.134.0` (`x64`)
- VS Code Codex extension: `openai.chatgpt@26.818.61809`
- Bundled Browser plugin/runtime: `26.611.61049`
- Bundled Chrome plugin/runtime: `26.611.61049`
- Bundled Computer Use plugin/runtime: `26.611.61049`
- Node: `26.5.0`

The independent in-app browser bootstrap failed before browser acquisition or navigation with the unchanged exact error `codex/sandbox-state-meta: missing field sandboxPolicy`. The Codex CLI update from `0.147.0` to `0.149.1` therefore did **not** resolve the browser metadata blocker; the bundled browser runtime and VS Code extension versions did not change from the pre-restart values.

## Next bounded slice

Fix the login surface to consume the active partner pack using the existing partner-branding component/pattern, then rerun the same standalone Playwright login and authenticated smoke. Keep the in-app browser metadata issue independent; do not let it block standalone UAT. Do not publish or modify either database without a new explicit approval.

## Resume prompt

> Resume in `C:\Users\cadco\source\repos\OpenConstructionERP`. Read `AGENTS.md` and `sessionhandoffCODEX.md` completely, then verify live git and Docker state without resetting anything. Preserve `MM sessionhandoffCODEX.md`; branch `001` tracks `cadcolabs/001` at `51e6cbf4e`. Standalone Playwright UAT evidence is under `output/playwright/uat-2026-08-25/`. Authentication, dashboard partner branding, exact `#0055A6`, attribution, projects, BOQ, costs, tendering, scheduling, console, and network checks passed, but overall UAT is blocked because the login page does not render the active Mullets logo/name. Implement only the smallest existing-pattern login branding fix, without creating accounts or using either live database for tests, then rerun the same standalone rendered checks. The in-app browser independently remains blocked by `codex/sandbox-state-meta: missing field sandboxPolicy` on Codex CLI `0.149.1`, extension `26.818.61809`, and bundled browser runtime `26.611.61049`. Do not commit, push, open a PR, refresh Reporting, or modify either database without explicit approval.

## Superseded next bounded slice (pre-UAT)

1. Run the authorized standalone Playwright UAT and capture evidence. Stop for approval only if an application UAT account must be created; treat every defect as a blocker.
2. Update this handoff with the exact UAT result and artifact paths, then independently retry and diagnose the in-app browser after the Codex update/restart.
3. Only after rendered UAT passes, decide whether to keep the published-image runtime for evaluation or complete a source-built unified Docker image.

## Superseded resume prompt (pre-UAT)

> Resume in `C:\Users\cadco\source\repos\OpenConstructionERP` after the Codex update and machine restart. Read `AGENTS.md` and `sessionhandoffCODEX.md` completely before acting, then verify every handoff claim against live git and Docker state without resetting anything. Branch `001` tracks `cadcolabs/001` at published commit `51e6cbf4e`; preserve both the staged and unstaged handoff changes (`MM sessionhandoffCODEX.md`). The user explicitly authorizes standalone Playwright UAT now. Reverify the Playwright tools, application health at `http://127.0.0.1:18080`, Mullets partner-pack API/logo, and the existing volumes, then complete evidence-backed rendered UAT for the login page, exact Mullets logo/name, `#0055A6` branding, OpenConstructionERP attribution, authenticated dashboard, and basic project/BOQ/cost/tendering/scheduling navigation. Capture screenshots, accessibility snapshots, console errors, and failed network requests; treat any defect as a blocker and update the handoff with artifact paths and exact results. Use an existing application UAT account; if none is available, stop and ask before creating one because that changes the live ERP database. After Playwright UAT, independently retry the in-app browser and record post-update versions and whether `codex/sandbox-state-meta: missing field sandboxPolicy` is resolved. Never use the live ERP PostgreSQL database or `M1_MA_Reporting` for tests. Do not commit, push, open a PR, refresh Reporting, or modify either database without explicit approval.
