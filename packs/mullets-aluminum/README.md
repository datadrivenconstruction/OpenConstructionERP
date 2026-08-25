# Mullets Aluminum Products partner pack

This branch-specific, code-free partner pack co-brands OpenConstructionERP for
**Mullets Aluminum Products, Inc.** The OpenConstructionERP product identity,
source links, license, and attribution remain intact.

## Included customization

| Setting | Value |
|---|---|
| Slug | `mullets-aluminum` |
| Company | `Mullets Aluminum Products, Inc.` |
| Primary color | `#0055A6` |
| Locale | `en-US` |
| Currency | `USD` |
| Logo | `logo.png` |
| Attribution | `Powered by OpenConstructionERP · In partnership with Mullets Aluminum Products, Inc.` |

The pack intentionally contains no application code, schema changes, company
records, tax rules, cost data, module visibility rules, favicon, or onboarding
script. Its complete runtime payload is `manifest.json` plus `logo.png`.

## Activate

For a source checkout, open **Modules → Partner Packs**, rescan if needed, find
**Mullets Aluminum Products, Inc.**, and select **Activate**. Alternatively, set
`OE_PARTNER_PACK=mullets-aluminum` before starting the application.

The currently verified published-image fallback mounts this folder read-only at
`/app/.openestimate/packs/mullets-aluminum` and sets the same environment
variable. That path is specific to the verified 15.7.0 image; newer images may
use the standard data-directory path `/data/packs/mullets-aluminum`.

Never commit application-user passwords or copy Mullets operational data into
this pack. User accounts belong in the application's PostgreSQL database and
must be managed through the authenticated Users screen.

## Verified behavior

Rendered UAT on 2026-08-25 verified the exact logo and company name,
`#0055A6` branding, attribution, authenticated dashboard, and navigation to
Projects, BOQ, Costs, Tendering, and Scheduling. Evidence is under
[`output/playwright/uat-2026-08-25/`](../../output/playwright/uat-2026-08-25/).

Known blocker: the sign-in page remains OpenConstructionERP-branded and does
not display the active Mullets logo or company name.
