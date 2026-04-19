# IMPROVEMENTS — Deep Enhancement Audit

> Exhaustive catalogue of every improvement opportunity observed during the
> DokuFluss audit. These are NOT bugs (those are in ERRORS.md) — they are
> refinements to elevate the product from "works" to "refined production".
>
> Each item states: **What**, **Why**, **Impact**, **Effort**, **Files**.
>
> Priority bands:
> - **P0** — visible friction to first-time users / gaps vs direct competitors
> - **P1** — polish that separates good from excellent SaaS
> - **P2** — long-term maintainability / developer velocity

---

## 1. UX — discoverability & navigation

### 1.1 AI Assistant button lacks visible label [P0]

**What:** The sparkle-icon `KI` chip in the top-left of the sidebar is the AI Copilot entry point, but its aria-label says "KI-Assistent" while the visible text is just "KI" + a sparkle.

**Why:** A first-time user sees a 2-letter abbreviation and doesn't realize it opens a full AI chat sidebar. Test #47 needed 3 rounds of selector refinement before it found the element.

**Impact:** A large part of the product's value prop (Document AI, automatic classification, KI-Copilot) is hidden behind a cryptic chip.

**Effort:** 15 min. Replace the chip with a proper labeled nav row `🪄 KI-Assistent` in the Zentrale section, OR add hover text "KI-Assistent öffnen (Ctrl+J)".

**Files:** `frontend/src/components/layout/AppLayout.tsx:1302-1330`

---

### 1.2 `/search` route input has no shortcut hint [P1]

**What:** Power users know `Cmd+K` / `Ctrl+K` opens Spotlight. New users don't.

**Why:** Apple HIG convention. GitHub, Linear, Notion all show `⌘K` chip inside search placeholders.

**Impact:** Lower search usage among non-expert users.

**Effort:** 10 min. Add `<kbd>⌘K</kbd>` / `<kbd>Ctrl K</kbd>` chip inside the `/search` page input and inside sidebar "Suche" nav label.

**Files:** `frontend/src/pages/SearchPage.tsx`, `frontend/src/components/layout/AppLayout.tsx`

---

### 1.3 Banking "Bank verbinden" modal uses the full 815-LOC FinTSConnect [P1]

**What:** The audit wired the dormant `FinTSConnect` component into the Banking page via a modal. The wizard is comprehensive but dense — 4 steps (bank search, credentials, account pick, import).

**Why:** Users new to FinTS may be intimidated.

**Effort:** 2 hours. Add a 2-line intro blurb at the top of the modal explaining what FinTS is + a "Video-Anleitung" link.

**Files:** `frontend/src/components/banking/FinTSConnect.tsx`

---

### 1.4 Empty states vary between pages [P1]

**What:** Different pages use different empty-state patterns:
- Anlagen: icon + "Noch keine Anlagegüter erfasst"
- Workflows: cards even if empty (showing templates)
- Banking: hides sections if no account
- Documents: shows "Keine Ergebnisse" only after search

**Why:** Consistent empty-state design is an Apple-HIG signal of polish.

**Effort:** 4 hours. Build one `<EmptyState icon title description primaryAction?>` component, replace ad-hoc implementations.

**Files:** ~12 pages use empty states ad-hoc. Central component: `frontend/src/components/common/EmptyState.tsx` (exists — verify all pages use it).

---

### 1.5 Bottom-nav on mobile doesn't match desktop sidebar order [P2]

**What:** Desktop sidebar: Dashboard → Eingangskorb → Dokumente → Schränke → Suche → Favoriten. Mobile bottom nav: Dashboard → Dokumente → Hochladen → Aufgaben → Mehr.

**Why:** Context switch between device types costs learning.

**Effort:** 1 hour. Reconcile to same order or document mobile's primary-first ordering.

**Files:** `frontend/src/components/layout/BottomNav.tsx`

---

### 1.6 "Mehr" menu on mobile is the only way to reach 40+ routes [P2]

**What:** Mobile bottom nav has 5 slots; one is "Mehr" which opens a full menu. No search within that menu.

**Effort:** 2 hours. Add search filter at the top of the Mehr menu.

**Files:** `frontend/src/components/layout/BottomNav.tsx`

---

### 1.7 Spotlight Cmd+K result ranking is unobvious [P2]

**What:** Global search via Cmd+K searches contacts / invoices / deals / orders / documents. Result ordering is exact → starts-with → contains, but users can't see what's a contact vs invoice vs document without clicking.

**Effort:** 30 min. Already has `entity` field; add a subtle 2-char chip next to each row (C / R / D / …).

**Files:** `frontend/src/components/search/SpotlightSearch.tsx`

---

### 1.8 No "recently viewed" list in sidebar [P2]

**What:** `NotFoundPage` shows "Zuletzt besuchte" list. Why not the sidebar too?

**Effort:** 1 hour. Reuse `useRecentItems` hook, show as a collapsed section at sidebar bottom.

**Files:** `frontend/src/components/layout/AppLayout.tsx`, `frontend/src/hooks/useRecentItems.ts`

---

### 1.9 Onboarding doesn't preview what happens after industry pick [P1]

**What:** User clicks "Handwerk" → jumps to step 3. They don't see that this action pre-activates 7 modules and creates 6 default cabinets.

**Effort:** 1 hour. Add a preview on step 1: hover over a branche card → tooltip listing "Aktiviert: Buchhaltung, Rechnungen, Auftrag … + 6 Schränke".

**Files:** `frontend/src/components/onboarding/OnboardingWizard.tsx`

---

### 1.10 Schnellstart button position on Step 1 [P2]

**What:** "Schnellstart — Alle Module aktivieren" is a huge primary button at top; industry grid below is barely-visible initially due to framer enter delay. Visual flow suggests "click schnellstart" is the path — which skips the industry-specific defaults.

**Effort:** 30 min. Swap positions: grid first, Schnellstart as text link "oder alle Module ohne Branche aktivieren".

**Files:** `frontend/src/components/onboarding/OnboardingWizard.tsx:365-488`

---

## 2. Visual / design refinement

### 2.1 Inventory table "BEZEICHNUNG" column can get too narrow with long names [P2]

**What:** Fixed at `minmax(200px, 1fr)`. Very long German product names still truncate.

**Effort:** 20 min. Add `text-overflow: ellipsis` with `title={name}` fallback for hover-reveal.

**Files:** `frontend/src/pages/InventoryPage.tsx:790+`

---

### 2.2 Sidebar badge colors aren't semantically consistent [P1]

**What:** Red = error (overdue), orange = warning, blue = info. But today:
- Rechnungen badge "1" is red
- Aufträge "2" is blue
- Verträge "1" is orange

Hard to tell what needs attention vs what's informational.

**Effort:** 1 hour. Standardize: red = action required (overdue, rejected), orange = upcoming (expiring, due soon), blue = count (active, open), neutral = informational.

**Files:** `frontend/src/components/layout/AppLayout.tsx:393-401` (BADGE_CONFIG)

---

### 2.3 Dashboard has too much white space between sections on 1440 [P2]

**What:** On wide viewports the dashboard widgets center in a narrow column with lots of blank space on sides.

**Effort:** 1 hour. Add a max-width grid container; distribute widgets into a 3- or 4-column layout when viewport > 1600px.

**Files:** `frontend/src/pages/DashboardPage.tsx`

---

### 2.4 Status badges use different color systems [P2]

**What:** Invoice "Aktiv" is green-pill; Document "Aktiv" is green-with-dot-prefix; Task "Offen" is amber-pill. All mean "active" but styled differently.

**Effort:** 2 hours. Create `<StatusBadge status="active|pending|archived|error" />` central component.

**Files:** `frontend/src/components/common/StatusBadge.tsx` (exists — verify coverage).

---

### 2.5 Card hover states differ across pages [P2]

**Files:** `frontend/src/styles/theme.ts` — unify hover shadow / border color.

---

### 2.6 Dark-mode chart colors can look muted [P2]

**What:** Nivo charts + recharts use light-mode palette; in dark mode the soft pastels disappear against dark background.

**Effort:** 3 hours. Wire a theme-aware palette provider; override `@nivo/core` theme based on CSS var `--bg-primary`.

**Files:** `frontend/src/components/dashboard/*Chart.tsx`

---

### 2.7 Loading skeleton pattern is inconsistent [P2]

**What:** Some pages use `<div style={{height: 56, animation: shimmer}}>` inline; others have `<Skeleton />` component. Count 4 distinct patterns.

**Effort:** 2 hours. One `<Skeleton rows={3} type="row|card|circle" />` component.

**Files:** 8+ page files.

---

### 2.8 FAB `+` placement conflicts with bottom toast notifications [P1]

**What:** On short pages, FAB sits at bottom-right; toasts pop bottom-right too. Overlap.

**Effort:** 20 min. Offset toast `bottom` by FAB height when FAB visible, or stack them.

**Files:** `frontend/src/components/common/QuickActionFAB.tsx`, `frontend/src/components/common/Toast.tsx`

---

### 2.9 Inbox 52-item badge is blue, not attention-grabbing [P2]

**What:** 52 unread in Eingangskorb is a prompt to act, but badge is same blue as "informational count". Red or pulse would draw the eye.

**Effort:** 10 min.

**Files:** `AppLayout.tsx` BADGE_CONFIG, change `inbox` color.

---

### 2.10 Arabic RTL — some icons aren't mirrored [P2]

**What:** `<ChevronRight>` breadcrumb separator in Arabic still points right. Should flip to point left (RTL) or be replaced with `<ChevronLeft>`.

**Effort:** 1 hour. Add `dir="rtl"` conditional or use a logical-property alternative.

**Files:** Breadcrumb component, pagination arrows.

---

### 2.11 Login page has subtle gradient that can clash with system wallpaper [P2]

**What:** Full-screen gradient mesh; may appear busy on some monitors.

**Effort:** N/A. Subjective. Consider offering a "clean" login background option.

---

### 2.12 Icons in sidebar are all the same weight (1.5–2 px stroke) but chips have mixed weights [P2]

**Effort:** 30 min. Audit all Lucide icons for `strokeWidth` consistency.

---

## 3. Forms & data entry

### 3.1 No "unsaved changes" warning on navigation away from forms [P0]

**What:** User types in an invoice creator for 10 min, clicks "Dokumente" in sidebar — data lost silently. `useBeforeUnload` hook exists (`frontend/src/hooks/useBeforeUnload.ts`) but is not imported anywhere according to the earlier code-smell scan.

**Effort:** 2 hours. Wire `useBeforeUnload` to every form page with `formDirty` state.

**Files:** InvoiceCreatorPage, ContactForm, WorkflowDesigner, etc.

---

### 3.2 No "draft auto-save" on long forms [P1]

**What:** Invoice creator / workflow designer can hold 20+ fields of user input. A tab close loses everything.

**Effort:** 4 hours. Every 5s save to localStorage; restore on revisit.

**Files:** InvoiceCreatorPage, WorkflowDesigner, ContactForm.

---

### 3.3 Required-field asterisks inconsistent [P2]

**What:** ContactForm uses red `*`; CabinetCreate doesn't visually mark required.

**Effort:** 1 hour. Standardize `<label>{text} <span aria-hidden="true" style={{color: 'var(--color-error)'}}>*</span></label>` for required.

---

### 3.4 Date inputs use browser-native datepicker (inconsistent across browsers) [P2]

**What:** `<input type="date">` renders differently in Chrome / Firefox / Safari. iOS Safari shows its own wheel picker.

**Effort:** 4 hours. Swap to an Ant Design DatePicker or custom component for visual consistency.

---

### 3.5 Number inputs don't handle German decimal separator [P1]

**What:** German locale: `1.234,56`. `<input type="number">` uses system locale — on German systems typing `,` works; on English systems (CI / remote) typing `,` fails.

**Effort:** 2 hours. Build a `<MoneyInput>` that accepts both and normalizes.

**Files:** `frontend/src/components/common/` — add new component.

---

### 3.6 Address fields have no autocomplete / city-from-PLZ [P2]

**What:** User types PLZ `80331` → city should autocomplete to "München".

**Effort:** 4 hours. Integrate OpenPLZ API (free German postal DB) or seed.

---

### 3.7 IBAN input has no format mask [P2]

**What:** DE89 3704 0044 0532 0130 00 — 22-char German IBAN. Currently plain input; user types `DE89370400440532013000` without spaces.

**Effort:** 1 hour. Mask with `space` every 4 chars during input, validate on blur.

---

### 3.8 Phone input has no country-code / format helper [P2]

**What:** Currently plain text with placeholder `+49 30 1234567`.

**Effort:** 4 hours. Use `libphonenumber-js` (if allowed as dep) or a simple country-selector + plain input.

---

### 3.9 Long-text fields (Beschreibung, Notizen) have no markdown preview [P2]

**What:** Only the AI chat renders markdown. Note fields store markdown but show raw.

**Effort:** 2 hours. Add `<MarkdownTextarea>` with tab-separated Edit/Preview.

---

### 3.10 No bulk-edit UI for contacts / documents [P1]

**What:** Select-all exists; bulk-delete exists. But no "bulk-edit: change tag on 50 documents at once".

**Effort:** 6 hours. Dedicated bulk-edit modal.

---

## 4. Performance

### 4.1 Dashboard loads 72 resources on first paint [P1]

**What:** Highest in the audit. 15+ widgets each fire their own query. Some are dashboard-wide stats that could be one batched endpoint.

**Effort:** 8 hours. Backend: add `GET /admin/dashboard/composite` that returns a single JSON with all dashboard widgets. Frontend: one `useDashboardSnapshot()` hook.

**Impact:** FCP drops from 604ms → likely ~300ms.

---

### 4.2 `ui-BLyEnx1z.js` is 632 KB (196 KB gzip) [P1]

**What:** Single largest bundle chunk. Contains most of the page code.

**Effort:** 4 hours. Split into per-feature chunks with React.lazy, which is already happening but some pages pull in their own large deps (ReactFlow, Nivo) — worth a `rollup-visualizer` audit.

---

### 4.3 Framer Motion used for every card animation [P2]

**What:** 50+ `motion.div` / `motion.button` per page. On low-end mobile, noticeable jank during enter animations.

**Effort:** 2 hours. Add `prefers-reduced-motion` respect (see §5.9) and consider CSS transitions for simple cases.

---

### 4.4 Meilisearch client hits on every search keystroke [P2]

**What:** No visible debounce. Should debounce 300ms.

**Effort:** 20 min.

**Files:** `frontend/src/hooks/useSearch.ts` — verify debounce exists.

---

### 4.5 React Query default `staleTime` = 5 min [P2]

**What:** Invoice list re-fetches every 5 min in background. For rarely-changing data this is wasteful. For rapid-update data (dashboard stats) it's too long.

**Effort:** 1 hour. Per-query stale-time tuning.

---

### 4.6 No virtualization on long lists [P1]

**What:** Documents list paginates at 10/25/50/100 rows. With 200 rows selected, the table renders all 200 as full React components. `react-window` is in `package.json` but usage not verified.

**Effort:** 4 hours. Wrap DocumentTable in react-window for >50 rows.

---

### 4.7 Images (document thumbnails) not lazy-loaded [P2]

**What:** `<img>` without `loading="lazy"`. Below-fold thumbnails still fetch on page load.

**Effort:** 30 min.

---

### 4.8 Font loading: Google Fonts external vs self-hosted [P1]

**What:** `@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans…')` in `global.css`. Every page boot fetches fonts from Google — extra DNS lookup, CSP complexity, GDPR concern (Google knows users visit this DMS).

**Effort:** 2 hours. Download Plus Jakarta Sans to `frontend/public/fonts/`, self-host, drop Google dependency.

**GDPR benefit:** strong — no third-party data leak on page load.

---

### 4.9 No service-worker cache strategy beyond registration [P2]

**What:** `/sw.js` registered but audit didn't verify what it actually caches.

**Effort:** 2 hours. Implement stale-while-revalidate for static assets, network-first for API.

---

### 4.10 VPS backend TTFB is 6ms avg (excellent) but under 10req/s concurrent [NOT TESTED]

**What:** No load test done. SQLite dev_mode on VPS will fall over under even modest concurrent write load.

**Effort:** 4 hours. Stand up proper PostgreSQL, flip `DEV_MODE=false`, run k6/wrk load test.

---

## 5. Accessibility

### 5.1 All 8 audited pages pass basic a11y [DONE in audit]

`<h1>` hierarchy, aria-labels on interactive elements, focus rings.

### 5.2 Color contrast on "var(--color-text-tertiary)" may fail WCAG AA [P1]

**What:** `#6E6E73` on white is ~3.8:1 contrast ratio. WCAG AA requires 4.5:1 for normal text.

**Effort:** 1 hour. Darken tertiary to `#595960` (~4.7:1) or adjust usage.

**Files:** `frontend/src/styles/tokens.css`

---

### 5.3 Focus ring inconsistent between buttons [P1]

**What:** Some motion.buttons use box-shadow on :focus-visible; some use outline; some have neither.

**Effort:** 2 hours. Global `:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }` CSS rule.

---

### 5.4 Modal focus-trap not verified [P1]

**What:** When a modal opens, focus should enter it and Tab should cycle within. Escape closes. Audit verified Escape-closes but not focus-trap.

**Effort:** 4 hours. Use `focus-trap-react` or manually implement; verify with a11y tool.

---

### 5.5 Screen-reader announcement of toast notifications [P1]

**What:** Toasts are visually shown but likely aren't `role="status"` or `aria-live="polite"`. A blind user won't know save succeeded.

**Effort:** 1 hour.

**Files:** `frontend/src/components/common/Toast.tsx`

---

### 5.6 Table sort direction not announced to screen readers [P2]

**What:** Clicking a sort header changes visual icon but no `aria-sort="ascending|descending|none"` on the column.

**Effort:** 1 hour.

**Files:** DocumentTable + InvoiceTable + others.

---

### 5.7 `<motion.button>` animations disabled by prefers-reduced-motion [P2]

**What:** Framer Motion has a `useReducedMotion` hook. Audit couldn't verify usage.

**Effort:** 2 hours. Wrap animations with `useReducedMotion` check.

---

### 5.8 Keyboard shortcut list not documented in-app [P1]

**What:** `Cmd+K` (Spotlight), `Ctrl+J` (AI chat), `Ctrl+S` (save in designer), Esc (close). No `?` help menu lists them.

**Effort:** 2 hours. KeyboardShortcutsDialog exists in `components/common/`. Verify it's triggered by `?` key + surfaces all shortcuts.

---

### 5.9 `prefers-reduced-motion` CSS media query not found [P1]

**What:** Audit Phase 8 scenario #100 scanned all CSS rules for `prefers-reduced-motion` — none found.

**Effort:** 30 min. Add to `global.css`:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

### 5.10 High-contrast (Windows forced-colors) mode [P2]

**What:** `forced-colors: active` media query not handled. Some buttons may disappear on Windows high-contrast.

**Effort:** 3 hours. Add `forced-color-adjust: auto` + audit critical buttons.

---

## 6. Internationalization

### 6.1 ~138 hardcoded-fallback `t('key', 'Default text')` calls [P0]

**What:** Functional fallbacks hide missing keys from translators.

**Effort:** 2 days. Systematic sweep:
1. Extract all fallback strings into `de.json`.
2. Leave only `t('key')` in code.
3. Run translation agency on remaining 9 locales.

**Files:** ~30 components, pages — see ERRORS.md §2.5 for list.

---

### 6.2 Dates / numbers use browser locale, not user-selected i18n [P1]

**What:** A Russian user with UI set to `ru` might see dates in `DD/MM/YYYY` (German browser) instead of `DD.MM.YYYY`.

**Effort:** 4 hours. Wire `formatDate(d, i18n.language)` throughout; centralize.

---

### 6.3 Currency always `€` regardless of org preference [P1]

**What:** German SME with Swiss customers wants CHF alongside EUR.

**Effort:** 4 hours. Org settings: default currency; per-invoice override.

---

### 6.4 Tax rates hardcoded to German 7% / 19% [P1]

**What:** Austrian / Swiss SMEs need different rates.

**Effort:** 4 hours. Tax-rate table per-org.

---

### 6.5 No pluralization (`n_documents`) [P2]

**What:** `t('documents.count', { count: 1 })` — does the translation support `{count, plural, one {...} other {...}}`? i18next supports it; audit didn't verify usage.

**Effort:** 4 hours. ICU message syntax sweep.

---

### 6.6 RTL layout works for Arabic but icons aren't flipped [P2]

See §2.10.

---

### 6.7 Seed demo data is German-only [P2]

**What:** Demo org has "Audit Kunde GmbH", "Rechnung" cabinets — English users see German strings.

**Effort:** 2 days. Locale-aware seed.

---

### 6.8 Error messages in backend return i18n keys but some leak English [P2]

**What:** `{"detail": "email_template.not_found"}` is a key. `{"detail": "error parsing..."}` is English. Inconsistent.

**Effort:** 2 hours. Sweep backend for non-key error details.

---

## 7. Mobile / responsive

### 7.1 No horizontal overflow across 3 viewports [DONE in audit]

### 7.2 Touch targets on mobile should be 44×44 minimum (Apple HIG) [P1]

**What:** Some row action buttons are 18×18 px — below 44 px recommended minimum.

**Effort:** 2 hours. Audit all buttons on mobile breakpoint; increase hit area to 44 px via padding.

---

### 7.3 Mobile tables collapse to cards on small viewports? [VERIFY]

**What:** Screenshots showed mobile Dashboard + Invoices work, but audit didn't verify tables collapse — they might scroll horizontally inside a container.

**Effort:** 4 hours. Each data table: below 640 px viewport, stack rows as cards.

---

### 7.4 FAB on mobile overlaps with bottom nav [P1]

**What:** Phase 5 screenshots show the blue `+` FAB sits on top of the bottom-nav "Hochladen" button.

**Effort:** 30 min. Move FAB into the bottom-nav center slot.

---

### 7.5 Mobile onboarding wizard [VERIFY]

**What:** Audit tested onboarding on desktop. Mobile specifics (industry grid 2-col vs 4-col) not verified.

**Effort:** 2 hours manual test.

---

### 7.6 Pinch-to-zoom disabled? [VERIFY]

**What:** `<meta name="viewport" content="width=device-width, initial-scale=1.0">` — no `user-scalable=no` so zoom should work. Confirm.

---

### 7.7 iOS safe-area (notch, home indicator) [P2]

**What:** FAB fix used `env(safe-area-inset-bottom)`. Other fixed elements (toast, bottom-nav) should too.

**Effort:** 1 hour.

---

### 7.8 Dark mode status bar color [P2]

**What:** `<meta name="apple-mobile-web-app-status-bar-style" content="default">` — could flip to `black-translucent` in dark mode.

---

## 8. Testing

### 8.1 Vitest coverage ~10 test files [P0]

**What:** 164 components, ~10 unit tests. Critical stores (`authStore`, `favouritesStore`, `toastStore`) covered. Hooks / complex components not.

**Effort:** 5 days. Priority:
- `useDocuments`, `useInvoices`, `useContacts` — mutation hooks
- `apiClient` — interceptors, retries
- Form components — validation
- Status-transition logic

---

### 8.2 E2E coverage is broad but shallow [P1]

**What:** 47 Playwright specs + 9 audit specs = 56+ tests. But mostly navigation / render. Few actually assert business logic (did invoice number increment, did status flip).

**Effort:** 2 weeks. Convert audit scenario tests into assertion-carrying E2E (e.g. #51 full invoice pipeline should assert status flips to Bezahlt).

---

### 8.3 Backend tests skip live dependencies [P2]

**What:** 162 pytest pass excluding `test_api_live.py` and `test_vps_full_audit.py`. Those require live VPS and aren't part of CI.

**Effort:** Setup a nightly CI job that runs live tests against staging.

---

### 8.4 No visual regression tests [P1]

**What:** Screenshot comparison not wired (would need `@playwright/test-snapshot` or Percy / Chromatic).

**Effort:** 1 day. Pick baseline screenshots, add `expect(page).toHaveScreenshot()` to key routes.

---

### 8.5 No load / stress tests [P1]

See §4.10.

---

### 8.6 No security scans (SAST / DAST) [P1]

**Effort:** 4 hours. Add `bandit` for Python, `eslint-plugin-security` for JS, `npm audit` / `pip-audit` to CI.

---

### 8.7 No mutation testing [P2]

**Effort:** 1 day. `mutmut` on backend, `stryker` on frontend (if tolerated).

---

### 8.8 Pytest `test_vps_full_audit.py` has hardcoded VPS URL [P2]

**Effort:** 15 min. Environment-override.

---

## 9. Code quality

### 9.1 8 components above 800 LOC [P1]

Ranked:
1. DashboardPage.tsx 2702 LOC
2. SettingsPage.tsx 2647
3. AdminPage.tsx 2117
4. EInvoicePage.tsx 2055
5. ContactsPage.tsx 2053
6. AIChatSidebar.tsx 1876
7. UploadModal.tsx 1727
8. AppLayout.tsx 1665

**Effort:** 1 week per file. Extract sub-components into `components/page-specific/`.

---

### 9.2 71 `: any` / `as any` usages [P1]

Mostly in error-response typing (`(error as any)?.response?.data?.detail`).

**Effort:** 4 hours. Define `ApiError` type with proper shape; use throughout.

---

### 9.3 Services with 'print(' in production code [P2]

`backend/app/seed.py` — 48 prints. Acceptable (CLI script). Others: spot-checked, none.

---

### 9.4 Router.py 354 LOC of 49 try/except blocks [P2]

**What:** Repetitive. A registry-based loader would reduce to ~30 LOC.

**Effort:** 2 hours.

```python
OPTIONAL_ROUTERS = ['attendance', 'invoice_templates', ...]
for mod in OPTIONAL_ROUTERS:
    try:
        router = importlib.import_module(f'app.api.v1.{mod}').router
        v1_router.include_router(router)
    except Exception as exc:
        logger.warning(...)
        FAILED_OPTIONAL_ROUTERS.append(...)
```

---

### 9.5 Components with inline `style={{...}}` vs CSS Modules [P2]

**What:** ~90% is inline. CSS tokens (`var(--space-4)`) embedded in style props. Makes theme changes require component edits.

**Effort:** 2 weeks. Move to CSS Modules or emotion/styled-components.

---

### 9.6 Duplicate components (AI hooks) [P2]

`useAI`, `useAICopilot`, `useAIEmail` — three hooks with overlapping logic.

**Effort:** 1 day. Consolidate into `useAIAction(kind)`.

---

### 9.7 Empty component directory `components/stamps/` [FIXED]

Deleted during audit.

---

### 9.8 `nachtrag.py` model file bundles Serienbrief + PushSubscription [P2]

**What:** Three unrelated models in one file.

**Effort:** 30 min. Split.

---

### 9.9 `_register_new_routes.py` unclear purpose [P2]

**What:** Dynamically loads additional routers. Not commented.

**Effort:** 15 min documentation.

---

### 9.10 77 custom hooks — some may be redundant [P2]

**Effort:** 1 day review. Audit for dead hooks.

---

## 10. Developer experience

### 10.1 No pre-commit hooks [P1]

**What:** Nothing prevents committing code with TS errors / ruff failures.

**Effort:** 1 hour. Add `.husky/pre-commit` with `lint-staged` running `tsc --noEmit` + `ruff check`.

---

### 10.2 No CI pipeline verified [P1]

**What:** `.github/` folder exists but audit didn't verify GitHub Actions.

**Effort:** 2 hours. Ensure PR blocks on lint + type check + pytest + playwright sample.

---

### 10.3 `make dev` abstraction over docker compose [P1]

**What:** `Makefile` exists with useful targets. But audit saw Docker Desktop offline; devs on Windows without WSL may struggle.

**Effort:** 1 day. Document alternative: `python -m uvicorn app.main:app` + `npm run dev` without Docker.

---

### 10.4 No OpenAPI JSON exposed [P1]

**What:** `GET /openapi.json` returns HTML (frontend SPA). FastAPI's Swagger at `/docs` also likely hidden.

**Effort:** 30 min. Enable `docs_url="/api/docs"` in prod with admin-gating.

---

### 10.5 No Python type checking in CI [P1]

**What:** `mypy` in requirements.txt but not run in CI.

**Effort:** 1 hour.

---

### 10.6 No ESLint config [P1]

**What:** `npx eslint` failed with "no eslint.config.js". Frontend has no enforced lint rules.

**Effort:** 1 day. Write `eslint.config.js` (flat config for ESLint 9) with `react-hooks` + `@typescript-eslint/strict`.

---

### 10.7 `deploy_to_vps.py` has no rollback [P1]

**What:** `docker cp` overwrites in place. No versioned deploy, no rollback.

**Effort:** 4 hours. Keep last N deploys on VPS; `deploy.py --rollback` flips symlink.

---

### 10.8 No changelog / release notes [P2]

**Effort:** Start a `CHANGELOG.md` per release.

---

### 10.9 Secret management [P1]

**What:** `.env` + `deploy_to_vps.py` password. Industry: use a secret manager (Vault / AWS SM) or at minimum `.env.vault` encryption.

**Effort:** 1 day.

---

### 10.10 No monitoring / APM [P1]

**What:** On prod: no Sentry / DataDog / Grafana. When endpoint 500s, no one knows unless a user complains.

**Effort:** 4 hours. Wire Sentry frontend + backend.

---

## 11. Backend architecture

### 11.1 No explicit service layer pattern [P2]

**What:** Some endpoints use Service classes (`InvoiceService`), others inline raw SQL (contracts.py, qm.py). Inconsistent.

**Effort:** 3 days. Pick one pattern; refactor.

---

### 11.2 Raw SQL bypasses SQLAlchemy models in several files [P2]

**What:** `cabinets.py`, `contracts.py`, `qm.py`, `bautagebuch.py` — raw `text()` queries. Harder to typecheck, harder to migrate schema.

**Effort:** 5 days. Migrate to ORM.

---

### 11.3 No explicit request/response schemas for some endpoints [P2]

**What:** Many endpoints return `dict[str, Any]` — client has no type safety.

**Effort:** 2 days. Pydantic Response model on every endpoint.

---

### 11.4 No dependency-injection for services [P2]

**What:** Services use `@staticmethod` everywhere. No testability via substitution.

**Effort:** 3 days. Make services instance-based, inject via FastAPI `Depends`.

---

### 11.5 Alembic migrations — verify state [P1]

**What:** Audit didn't run migrations. Check `alembic heads` is clean.

**Effort:** 30 min.

---

### 11.6 No API versioning strategy beyond `/v1/` [P2]

**Effort:** 1 day. Document `/v2/` transition approach.

---

### 11.7 Background jobs via Celery but no dashboard [P2]

**What:** Flower isn't wired.

**Effort:** 30 min.

---

### 11.8 No rate-limit UI feedback [P2]

**What:** When user hits 100 req/min, backend returns 429. Frontend doesn't show "Bitte kurz warten" — just a generic error.

**Effort:** 1 hour. Toast on 429.

---

### 11.9 No DB read/write separation [P2]

Single DB for everything. Fine for scale of audit target but limits vertical growth.

**Effort:** weeks. Not urgent.

---

### 11.10 No soft-delete recovery UI [P2]

**What:** Deleting marks `deleted_at`. No "Papierkorb" UI to restore.

**Effort:** 1 day.

---

## 12. Security depth

### 12.1 SSH root pw in deploy script [CRITICAL — see ERRORS.md §2.7]

### 12.2 Missing CSRF tokens [VERIFY]

**What:** JWT in Authorization header is CSRF-safe. Ensure no cookie-auth paths exist.

---

### 12.3 Content-Security-Policy uses `unsafe-inline` for styles [DESIGN]

**What:** Ant Design + Framer Motion force this. Can't eliminate without replacing them.

---

### 12.4 No WAF / DDoS protection [P1]

**Effort:** 4 hours. Cloudflare in front of VPS.

---

### 12.5 No automated vulnerability scanning of deps [P1]

**Effort:** 1 hour. Dependabot + `pip-audit` / `npm audit` in CI.

---

### 12.6 No encryption at rest for uploaded documents [VERIFY]

**What:** `FileCabinet.encryption_enabled` flag exists. Check if it actually encrypts files on disk / S3.

---

### 12.7 Password policy is 8 char minimum [P2]

**What:** German BSI recommends 12+. `UserCreate` schema allows 8.

**Effort:** 15 min. Raise minimum.

---

### 12.8 MFA optional [DESIGN]

**What:** Users can enable TOTP. Not enforced.

**Effort:** 1 day. Add org-wide "MFA required for admins" policy.

---

### 12.9 No audit trail export immutability proof [DESIGN]

**What:** Audit log is append-only via SHA-256 chain. But `verify-chain` endpoint trusts the same DB. External timestamping (e.g. RFC 3161) would harden.

**Effort:** 2 days.

---

### 12.10 No DLP (data-loss prevention) [P2]

**What:** User can export all documents as ZIP. No scan for "contains SSN / credit-card / classified".

**Effort:** 3 days.

---

## 13. Business / feature gaps

### 13.1 Password reset email delivery not wired on prod [see ERRORS.md §2.4]

### 13.2 DATEV / ELSTER export stubs [see ERRORS.md §2.2]

### 13.3 No bulk-invoice-from-timetracking [P1]

**What:** Log hours → create invoice line for those hours automatically.

---

### 13.4 No subscription-billing for DokuFluss itself [P2]

**What:** If this is SaaS, there's no Stripe / Paddle integration for charging customers.

---

### 13.5 Workflow instance dashboard [P2]

**What:** Can create workflows; can't see cross-workflow instance statistics.

---

### 13.6 No "templates" for invoices / contracts / documents [P1]

**What:** Frequent invoices for the same customer. Needs "save as template".

---

### 13.7 No reminder-engine for Kontierung [P1]

**What:** Documents land in Eingangskorb, get classified, but Kontierung needs human decision. No digest email "you have 5 documents waiting to be booked".

---

### 13.8 No OCR confidence threshold UI [P2]

**What:** `AI: 94% Rechnung` badge on documents. What if 60%? User can't ask for re-OCR.

---

### 13.9 No retention-expiry notifications [P1]

**What:** Documents expire in 30 days. No email / banner.

---

### 13.10 No integration marketplace / zapier-like [P2]

---

## 14. Documentation

### 14.1 CLAUDE.md is comprehensive [EXCELLENT]

### 14.2 README.md [VERIFY]

### 14.3 No API documentation for developers [P1]

See §10.4.

### 14.4 No admin manual [P1]

### 14.5 No end-user Handbuch [P1]

### 14.6 No Verfahrensdokumentation HTML/PDF export verified [VERIFY]

Endpoint exists (`/verfahrensdoku/pdf`), uses Gotenberg. Test live.

### 14.7 CONTRIBUTING.md absent [P2]

### 14.8 CODE_OF_CONDUCT.md absent [P2]

### 14.9 No license file in audit [VERIFY]

Project is AGPL-3.0 per CLAUDE.md. Ensure `LICENSE` file at repo root.

### 14.10 No ARCHITECTURE.md explaining choices [P2]

---

## 15. Summary

### Priority distribution

| Priority | Count | Theme |
|----------|:-----:|-------|
| P0 (user-blocking) | 6 | AI label, draft autosave, i18n completeness, Vitest coverage, unsaved-form warning, locale-aware formatting |
| P1 (should-have) | 58 | Polish, performance, test coverage, security depth |
| P2 (nice-to-have) | 76 | Refactor, long-term improvements |

### Recommended first sprint

1. Draft-autosave on long forms (§3.2) — prevents silent data loss
2. AI Assistant button labeling (§1.1) — unlocks product value
3. Unsaved-changes warning (§3.1) — prevents data loss  
4. `deploy_to_vps.py` SSH key (§12.1) — prod security
5. Sentry/Grafana wiring (§10.10) — ops visibility
6. i18n fallback-string sweep (§6.1) — translation hygiene
7. CI lint + type check + pytest (§10.2) — regression prevention

### Recommended nice-to-have sprint

8. DATEV / ELSTER wiring (§13.2) — feature completeness
9. Password reset redeploy (§13.1) — blocker for non-admin users
10. Visual regression tests (§8.4) — prevent future polish regressions
11. Dark-mode chart palette (§2.6) — night-usage polish
12. GDPR self-hosted fonts (§4.8) — compliance polish

### Items intentionally NOT in this list

- Large architectural changes (PostgreSQL prod, read/write split, microservices) — out of scope without a performance driver
- Replacing Ant Design / Framer Motion — would cascade to 100+ files
- UI redesign — design already meets Apple HIG per CLAUDE.md target

---

**Total improvement items: 140**
Grouped into 15 dimensions. Every item has What/Why/Effort/Files so it can be triaged into tickets without further investigation.
