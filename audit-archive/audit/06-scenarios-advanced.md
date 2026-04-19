# 06 — 50 Advanced Scenarios (51–100)

> Deeper-than-happy-path flows: multi-step business, error recovery, edge
> inputs, keyboard-only, sort/pagination, bulk, status transitions, deep
> links, session edges, import/export, dark-mode a11y.
>
> Harness: `frontend/e2e/audit-phase9-advanced.spec.ts`
> Report: `audit/screenshots/phase9/_advanced-report.json`

## O. Multi-step business (51–60)

- **#51** — Full invoice pipeline: create draft → add 2 line items → save → send → mark paid
- **#52** — Create contact → create invoice against that contact → verify cross-link on contact detail
- **#53** — Create project → log 4h time → see project Umsatz updates
- **#54** — Create workflow → activate → trigger instance (if possible) → see in workflow instances
- **#55** — Create task → assign to Maria → reassign to Thomas → complete
- **#56** — Create retention policy → assign to cabinet → upload doc → verify retention date
- **#57** — Add SKR account → post accounting entry → see in EÜR
- **#58** — Create contract → see auto-computed termination deadline → terminate
- **#59** — Create Wiedervorlage → due date passes → see in dashboard "overdue" count
- **#60** — Add asset → compute AfA → verify AfA-Tabelle row

## P. Error recovery (61–65)

- **#61** — Invalid email in contact form → save → see inline validation error
- **#62** — Negative amount in invoice line → should reject or normalise
- **#63** — Very long name (>500 chars) in cabinet create → server rejects with 422 detail
- **#64** — Submit form with backend offline → see toast "Network error" with retry CTA
- **#65** — Trigger 500 via malformed payload → toast surfaces i18n-ed message

## Q. Edge cases (66–70)

- **#66** — Contact with only company_name (no email / phone) → should save
- **#67** — Invoice with 0€ total → should accept (e.g. cover letter)
- **#68** — Document upload with special-char filename (ä ö ü ß é) → preserved
- **#69** — Long customer name in invoice (>200 chars) → row truncates with ellipsis, full on hover
- **#70** — Cabinet with German umlaut in name → no encoding issues

## R. Keyboard-only (71–73)

- **#71** — Tab from top of dashboard → land on first interactive → reach sidebar nav in ≤6 tabs
- **#72** — Open Cmd+K → type query → Arrow-down → Enter → navigate to first hit
- **#73** — Close modal with Escape (Documents upload, Contacts create, Tasks create)

## S. Search & filter (74–77)

- **#74** — Search "Rechnung" in Documents → results filtered
- **#75** — Combine status=active + type=service on Contracts
- **#76** — Date range filter on Invoices (last 30 days)
- **#77** — Global search across entities for a common word

## T. Sort & pagination (78–80)

- **#78** — Sort Invoices by Betrag asc → first row has smallest amount
- **#79** — Change page size to 50 → see 50 rows
- **#80** — Next-page button on Documents → query includes `?page=2`

## U. Bulk operations (81–83)

- **#81** — Select 3 documents → bulk archive
- **#82** — Select multiple invoices → bulk export PDF
- **#83** — Select multiple tasks → bulk close

## V. Status transitions (84–87)

- **#84** — Invoice Entwurf → Gesendet (status badge changes)
- **#85** — Contract Aktiv → Gekündigt (termination date recorded)
- **#86** — Task Offen → In Bearbeitung → Erledigt
- **#87** — Document Entwurf → Klassifiziert → Archiviert (WORM lock)

## W. Deep links (88–90)

- **#88** — Bookmark /invoices/{known-id} → lands directly on detail
- **#89** — Reload mid-task /documents/123 → page rehydrates, token refresh works
- **#90** — External link /reset-password?token=XYZ → reset-password form pre-filled

## X. Session & auth edge (91–93)

- **#91** — Token expired mid-session → auto-refresh keeps user logged in
- **#92** — Refresh-token expired → graceful logout + "Sitzung abgelaufen"
- **#93** — Log in on second tab → first tab picks up new token on refetch

## Y. Import / export (94–96)

- **#94** — Import 10-row CSV of contacts → all 10 imported
- **#95** — Export selected invoices as ZIP (XRechnung + PDF)
- **#96** — Import MT940 → transactions appear in Banking

## Z. Dark mode + a11y (97–100)

- **#97** — Toggle dark mode → sidebar, cards, tables all render correctly
- **#98** — Dark mode + Arabic RTL → no visual glitches
- **#99** — High-contrast mode (forced-colors) → focus ring visible, text readable
- **#100** — Reduced-motion preference → framer-motion animations disabled

---

## Method per scenario

Each is one Playwright step (or sequence) that records:
- **reached** — did the expected state appear?
- **friction** — free-text note (what tripped up)
- **apiFailures** — captured 4xx/5xx during the flow
- **screenshot** — PNG saved to `audit/screenshots/phase9/<category>/##.png`

Scenarios that require real external resources (real FinTS creds, real SMTP, real CSV upload files) are marked `MANUAL` — the automation only checks the entry point is discoverable.
