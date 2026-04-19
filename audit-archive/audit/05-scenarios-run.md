# 05 — Scenario Run Report

> Automated walkthrough of all 50 scenarios from `04-scenarios.md` against the
> live VPS (`http://31.97.123.81:7777`) on 2026-04-18.
>
> Harness: `frontend/e2e/audit-phase4-scenarios.spec.ts`
> Raw JSON: `audit/screenshots/phase4/_scenarios-report.json`
> Per-scenario screenshots: `audit/screenshots/phase4/<category>/<id>-ok|fail.png`

## Headline

- **Reached: 50 / 50 (100%)**
- **API 4xx/5xx during flows: 0 unique failures**
- **Runtime JS errors: 0**
- **Typical flow duration: 200–2400ms**

Every flow from the hypothetical-novice-user list reaches the intended entry
point or modal without a 404 / crash / unreachable CTA.

---

## Per-category verdict (logic · quality · design)

### A. Onboarding & Setup (5/5)

| # | Verdict | Notes |
|---|:-------:|-------|
| 1 | ✓ | Language→industry→done path flows in <10s, 3 visible progress dots |
| 2 | ✓ | Language picker covers 10 languages with native labels (Deutsch, English, Türkçe, Русский, العربية, Polski, Română, Hrvatski, Italiano, Français) |
| 3 | ✓ | "Überspringen" reachable top-right on every step |
| 4 | ✓ | Admin → Einladen form reachable; email-based invite + audit log |
| 5 | ✓ | Profile → Passwort ändern with min-length hint |

**Logic:** onboarding persists choice via `dokufluss-onboarding-done` localStorage flag; language via i18next detector.
**Quality:** wizard closes cleanly; picks "Handwerk" profile seeds relevant modules.
**Design:** Apple-HIG — generous whitespace, frosted-glass feel, single primary CTA per step. Progress bar at top. Skip always visible.

### B. Documents (5/5)

| # | Verdict | Notes |
|---|:-------:|-------|
| 6 | ✓ | Upload modal: 3-step wizard (Upload → Analyze → Review) |
| 7 | ✓ | `<input type="file" multiple>` — multi-select works |
| 8 | ✓ | Filter sheet with Typ / Schrank / Status / Datum |
| 9 | ✓ | Search debounce (300ms) + clears on Esc |
| 10 | ✓ | `Cmd+K` opens Spotlight, input auto-focuses |

**Logic:** OCR runs async post-upload; classification prediction rendered as a badge next to file.
**Quality:** full-text search routes to Meilisearch if configured; falls back gracefully in DEV_MODE (after R5 fix).
**Design:** list vs grid toggle, inline type badges, floating FAB for quick upload.

### C. Cabinets (3/3)

| # | Verdict | Notes |
|---|:-------:|-------|
| 11 | ✓ | Create-cabinet button labeled "Schrank erstellen" / "Neu" |
| 12 | ✓ | Seeded cabinets visible: Allgemein, Eingangsrechnungen, Verträge, Angebote |
| 13 | ✓ | Document detail has a "Verschieben" dropdown with all cabinets |

**Logic:** `field_schema` validated as JSON list; each document enforces required fields on upload.
**Design:** cards with icon + usage stats; retention policy visible per-cabinet.

### D. Invoicing (6/6)

| # | Verdict | Notes |
|---|:-------:|-------|
| 14 | ✓ | Creator page renders with Kunde, Positionen, Summen blocks |
| 15 | ✓ | List has primary CTA "Rechnung erstellen" + export row actions |
| 16 | ✓ | `/dunning` page renders Mahnung levels |
| 17 | ✓ | Serienrechnungen tab reachable |
| 18 | ✓ | E-Invoice (XRechnung / Peppol) page renders |
| 19 | ✓ | Overdue filter tab with count badge |

**Logic:** invoice numbering per-org (`RE-YYYY-NNNN`); mahnstufe 0..3 enforces valid transitions.
**Quality:** all list endpoints pass `page_size=200` post-R10 fix.
**Design:** 4 KPI cards (Offene Forderungen / Umsatz diesen Monat / …), 5 status tabs with counts.

### E. Accounting (4/4)

| # | Verdict | Notes |
|---|:-------:|-------|
| 20 | ✓ | EÜR / UStVA / BWA / Offene Posten / Kostenstellen / Kontenzuordnung tabs present |
| 21 | ✓ | `/datev-export` renders period picker |
| 22 | ✓ | UStVA picker: year + quarter |
| 23 | ✓ | Kontenzuordnung tab reachable |

**Logic:** SKR04 by default, accounts seedable; EÜR sum formula `Einnahmen − Ausgaben` verified on screenshot.
**Quality:** year filter (2022–2026) above table.
**Design:** compact table rows, 3 KPI cards, tab chip bar up top.

### F. Banking (3/3, after R19 fix)

| # | Verdict | Notes |
|---|:-------:|-------|
| 24 | ✓ (fixed) | Added "Bank verbinden" primary action on Übersicht header |
| 25 | ✓ (fixed) | Added "Importieren" secondary action |
| 26 | ✓ | "Abgleich" tab shows reconcile suggestions |

**Round 19 fix:** `frontend/src/pages/BankingPage.tsx` — added 2 PageHeader actions pointing to the Transaktionen tab (where the FinTS connect flow + CSV import sit). i18n keys `banking.connectBank` / `banking.importCsv` added in all 10 locales.

### G. Contacts / CRM (4/4)

| # | Verdict | Notes |
|---|:-------:|-------|
| 27 | ✓ | "Neuen Kontakt erstellen" → well-structured form (6 sections) |
| 28 | ✓ | "Visitenkarte scannen" reachable |
| 29 | ✓ | "Importieren" button exists |
| 30 | ✓ | Communication timeline on detail page |

**Logic:** `ContactCreate` now requires ≥1 of company_name / first_name / last_name / email (R8 validator fix).
**Design:** BCR (Business Card Reader) uses OCR extraction; Adress autocomplete.

### H. Contracts (3/3)

| # | Verdict | Notes |
|---|:-------:|-------|
| 31 | ✓ | "+ Neuer Vertrag" form opens |
| 32 | ✓ | "Läuft bald aus" (< 90 days to expiry) tab |
| 33 | ✓ | Status column with Gekündigt state; row action for termination on detail |

**Logic:** termination deadline auto-computed from end_date − notice_days (R8 fix in contracts.py stats).
**Design:** contract cards with status badge; KPIs for Aktiv / Läuft bald aus / Abgelaufen / Gekündigt.

### I. Projects & Construction (3/3)

| # | Verdict | Notes |
|---|:-------:|-------|
| 34 | ✓ | "+ Erstellen" primary action on Projekte page |
| 35 | ✓ | Bautagebuch "+ Neuer Eintrag" button |
| 36 | ✓ | Aufmass page renders measurement section |

**Logic:** project Umsatz = hours × rate; Handwerk-profile defaults preloaded after onboarding.
**Design:** project cards with colored accent strip, budget progress bar.

### J. Tasks & Workflows (4/4)

| # | Verdict | Notes |
|---|:-------:|-------|
| 37 | ✓ | Task modal with Aufgabenname + Fälligkeit + Priorität + Beschreibung |
| 38 | ✓ | Priority + assignee columns in list |
| 39 | ✓ | Wiedervorlage page renders |
| 40 | ✓ | Workflow Designer opens at `/workflows/new/designer` without the R14 red-toast |

**R14 fix recap:** `useSLAConfigs('new')` no longer fires `GET /sla/config/new` → 404 → toast.
**Design:** Designer: canvas with dot grid + toolbar + Knotenkonfiguration side panel.

### K. Time & HR (3/3)

| # | Verdict | Notes |
|---|:-------:|-------|
| 41 | ✓ | Zeiterfassung "Neuer Eintrag" |
| 42 | ✓ | Urlaub "Neuer Antrag" |
| 43 | ✓ | Leave "Beantragt / Pending" filter tab |

**Logic:** working-days helper excludes Bundesland-specific holidays (partial — backend only).

### L. Compliance / GoBD (3/3)

| # | Verdict | Notes |
|---|:-------:|-------|
| 44 | ✓ | "Kette verifizieren" CTA on GoBD-Status tab |
| 45 | ✓ | GDPdU-Export section reachable |
| 46 | ✓ | "Aufbewahrungsfristen-Monitor" section reachable |

**Logic:** audit chain verification is a `POST /audit/verify-chain`; skeleton/error/empty states properly wired (R3 fix).
**Design:** 75 % konform ring on demo, coloured section badges, Letzte Prüfung timestamp.

### M. Search / AI (2/2)

| # | Verdict | Notes |
|---|:-------:|-------|
| 47 | ✓ | AI Assistant button in top-left of sidebar ("KI" chip, `Ctrl+J`) |
| 48 | ✓ | `/search` page with query input |

**Logic:** chat context-aware of current document if opened from detail page; `SearchService` gracefully returns empty when Meilisearch is down (R5 fix).

### N. Cross-cutting (2/2)

| # | Verdict | Notes |
|---|:-------:|-------|
| 49 | ✓ | Erscheinungsbild toggle in Settings (System / Hell / Dunkel) |
| 50 | ✓ | Logout in user popup from bottom-left user block |

---

## Summary scorecard

| Dimension | Grade | Evidence |
|-----------|:-----:|----------|
| Functional reach | A+ | 50/50 scenarios reach target |
| API resilience | A+ | 0 × 4xx/5xx during flows |
| Visual polish | A | Apple-HIG sidebar, consistent FAB, breadcrumbs |
| Discoverability | A− | Banking needed explicit connect CTA (fixed R19); Copilot is hidden under small "KI" chip — could be labeled |
| German-localisation | A | Every scenario renders in de-DE without fallbacks |
| Onboarding | A | Three-step wizard + Schnellstart, skip always visible |
| Error handling | A | Disabled submit on empty forms, 422 for empty contact, graceful Meili fallback |

## Residual items (low-impact UX backlog)

These do not block any scenario but would elevate the product from "works" to "refined":

1. **Banking "Bank verbinden" should land on a dedicated connect modal**, not the Transaktionen tab (current behaviour after R19 fix).
2. **AI Copilot button** — consider labeling the small KI chip with "Assistent" on hover and giving it a dedicated sidebar row (currently a top-corner icon).
3. **Table column overlap on 1440px** — "MINDESTBESTAND" + "EK-PREIS" collide in Inventory table header.
4. **Projects create button** — current label is generic "Erstellen"; consider "+ Projekt" for clarity.
5. **Cmd+K shortcut hint** — show "⌘K" chip inside the sidebar search input to surface the shortcut.

## Deploy trail

Every scenario run was against the **deployed VPS**. The Banking CTA fix (R19) was the final code change before the 50/50 run. Deploy timestamps and artifacts are captured in `99-changes-log.md`.
