# Part 4 - Agent A - Deep UI Audit

Target: OpenConstructionERP V4 (http://127.0.0.1:8080), bundled React SPA + FastAPI.
Test file: `qa_output/generated_tests/test_p4_agent_a_ui_deep.py`
Run log: `qa_output/logs/p4_agent_a_run.log`
Browser: Chromium headless, 1440x900, single authenticated context.
Run time: ~2m 16s.

## Summary

- **Tests:** 28 total
- **Passed:** 26
- **Failed:** 2 (`test_projects_click_first`, `test_i18n_switch[ar]`)

The raw `.goto()` + `pageerror` + `console.error` sweep passes on every route, but every single screenshot (`qa_output/screenshots/p4_*.png`) shows the **landing/login page**, not the authenticated module. Investigation after the run surfaced the root cause: the UI login flow never completes for the seeded `demo@openestimator.io` admin. The backend hangs the login request instead of responding (rate-limiting mis-behaviour, see BUG-1), so the Playwright context never acquires a JWT, the `jwt_token` / `access_token` localStorage fallback is written but ignored by the SPA, and every protected route silently renders the public marketing page. As a result the "26 passing" route checks only prove that the landing page is clean - the audit of the actual in-app content could not take place because login itself is broken.

The two hard failures are consequences of the same problem (`/projects` never shows cards; `html dir` never flips to `rtl`). The report below lists the real, user-observable issues uncovered while tracing this.

---

## BUG-1 - Login endpoint hangs for demo admin after a few bad attempts (BLOCKER)

**Severity:** BLOCKER (blocks all UI auth, blocks automated E2E testing)

**Route / endpoint:** `POST /api/v1/users/auth/login/`

**Repro:**
1. Submit 5-10 login attempts with `demo@openestimator.io` from one client.
2. Submit another correct login request for the same user (e.g. `curl -X POST -d '{"email":"demo@openestimator.io","password":"DemoPass1234!"}' .../auth/login/`).
3. The request times out after 30s+ with no response at all (status code 000 at the curl level).
4. Other users (`estimator@...`) correctly return `429 Too many login attempts` within a few ms; `demo@...` in the same moment just hangs.

**Evidence:**
- `curl -m 15 -X POST .../auth/login/ -d '{"email":"demo@openestimator.io",...}'` -> `[000 15.007s]` (connection timeout).
- Same moment, `curl -X POST -d '{"email":"estimator@openestimator.io",...}'` -> `429 Too many login attempts. Please wait a minute and try again.` in 4ms.
- `curl -X POST -d '{"email":"x@y.z","password":"bad"}'` -> `401` in 227ms.

**Impact:**
- Blocks the primary seeded admin, the account used in every demo/onboarding flow.
- Makes automation frameworks (Playwright, Cypress, Selenium) unable to run against the same demo credentials the docs recommend.
- Leaks request slots - the Uvicorn worker sits holding an open request until client timeout; under real rate-limit pressure this can become a DoS vector.
- Users see an infinitely-spinning "Anmelden" button with no error surfaced.

**Expected:** Per-user rate limit should return `429` (as it does for other users) or `503` immediately - never hang.

**Screenshot:** n/a (server-side; repro via curl).

---

## BUG-2 - SPA routes silently render public landing page when unauthenticated (CRITICAL)

**Severity:** CRITICAL (security + usability)

**Routes:** `/dashboard`, `/projects`, `/boq`, `/costs`, `/catalog`, `/takeoff`, `/schedule`, `/tendering`, `/reports`, `/documents`, `/validation`, `/requirements`, `/risk`, `/changeorders`, `/assemblies`, `/settings`, `/audit`, `/markups`, `/punchlist`, `/fieldreports`, `/tasks`, `/contacts` - **all of them**.

**Repro:**
1. Open a fresh Chromium session with no cookies/localStorage.
2. Navigate directly to `http://127.0.0.1:8080/dashboard` (or any route above).
3. URL stays at `/dashboard` but the page renders the marketing landing + login panel. No redirect to `/login`, no "please sign in" toast.
4. Same happens for every protected route we visited - see `qa_output/screenshots/p4_dashboard.png`, `p4_boq.png`, `p4_projects.png`, `p4_settings.png`, etc. All identical.

**Impact:**
- User who bookmarks `/boq` and later opens it when the session expired sees a marketing page and has to figure out they need to log in - confusing.
- Deep-link bookmarks are lost; after successful login the user is not returned to the intended route.
- Automated tooling cannot rely on a redirect signal to know auth state - tests accidentally "pass" on the marketing page (this is what happened here).
- SEO/crawler exposure: every internal route returns 200 with identical marketing HTML shell.

**Expected:** Unauthenticated navigation to a protected route should either redirect to `/login?next=/dashboard` or render an auth-gate component - not the public homepage.

**Screenshot:** `qa_output/screenshots/p4_dashboard.png`, `qa_output/screenshots/p4_projects.png`, `qa_output/screenshots/p4_boq.png` (all visually identical to `p4_i18n_de.png`).

---

## BUG-3 - Unhandled React render crash on 422 login response (CRITICAL)

**Severity:** CRITICAL

**Route:** `/login`

**Repro:**
1. Open `/login`.
2. Using React-compatible input events (native setter + `dispatchEvent`), set email to empty string and submit - or any path that causes the backend to return 422 with a Pydantic `detail` array.
3. Backend correctly returns `422 {"detail":[{"type":"value_error","loc":[...],"msg":"value is not a valid email address...","input":"","ctx":{...}}]}`.
4. The app crashes with **Minified React error #31**: "object with keys {type, loc, msg, input, ctx}".

**Console:**
```
[error] Failed to load resource: the server responded with a status of 422 (Unprocessable Content)
[error] Error: Minified React error #31; visit https://reactjs.org/docs/error-decoder.html?invariant=31&args[]=object%20with%20keys%20%7Btype%2C%20loc%2C%20msg%2C%20input%2C%20ctx%7D ...
    at vendor-react-D5GrJ9NQ.js:38:6312
```

**Impact:**
- Any validation error on the login form (or any other form that bubbles a 422 into a render path) breaks the UI - user has to reload.
- React-error-#31 means somewhere in the stack `{detail: [...]}` is passed into JSX as a child instead of being mapped to readable messages.

**Expected:** Validation errors rendered as friendly text ("Please enter a valid email"), no uncaught render error.

**Screenshot:** n/a (console-level; log captured in `qa_output/logs/p4_agent_a_run.log` around the ad-hoc repro step).

---

## BUG-4 - Login form submit button is a no-op when React state is not synthetically primed (MAJOR)

**Severity:** MAJOR (blocks automated testing; likely edge-case for real users with autofill)

**Route:** `/login`

**Repro:**
1. Open `/login`.
2. Set `input#login-email` and `input#login-password` values via `element.value = "..."` (what Playwright `fill()` does; what some password managers also do).
3. Click the `Anmelden` submit button.
4. Expected: `POST /api/v1/users/auth/login/` fires with the values. Actual: no network request is made; form silently does nothing.
5. Repeat with `page.keyboard.type(...)` (real key events) - same result: no request.
6. Only flows that use `dispatchEvent(new Event('input', {bubbles:true}))` or the demo-user buttons ever fire the POST.

**Impact:**
- Browser autofill from password managers may silently fail - user clicks Log-in, nothing happens, no error.
- Any E2E automation (Playwright, Selenium, Cypress) cannot log in via the UI without React-state-aware input hacks.
- Explains why `test_p4_agent_a_ui_deep.py` passed route checks despite never being authenticated.

**Expected:** Either use uncontrolled inputs / `defaultValue`, or read `element.value` at submit time as fallback, or debounce the controlled state. The form must be robust to browser autofill.

**Screenshot:** `qa_output/screenshots/p4_projects_click.png` (shows the post-"login" state is still /login).

---

## BUG-5 - i18n Arabic locale does not apply `dir="rtl"` (MAJOR)

**Severity:** MAJOR (accessibility/RTL support)

**Route:** `/dashboard` (reproducible on any route)

**Repro:**
1. Open `/dashboard`.
2. Set locale to Arabic by `localStorage.setItem('i18nextLng', 'ar')` (and `'locale'`, `'lang'`, `'language'` as fallbacks).
3. Reload.
4. Page reloads, but `document.documentElement.getAttribute('dir')` returns `"ltr"`. `<body>` has no `dir` either.

**Impact:**
- Arabic / Hebrew users see LTR layout - broken reading order, broken mirroring of icons/arrows.
- Violates WCAG 1.3.2 (Meaningful Sequence) and is a blocker for MENA rollout (Dubai demo project in the seed set is direct evidence this is an intended market).

**Expected:** When locale is RTL-script, `<html dir="rtl" lang="ar">` is set and RTL Tailwind classes (`rtl:` variants) activate.

**Screenshot:** `qa_output/screenshots/p4_i18n_ar.png` (note: the landing page is LTR; German marketing text still visible because auth failed, but the absence of `dir="rtl"` was verified programmatically in `test_i18n_switch[ar]`).

---

## BUG-6 - Language switcher is not discoverable / not selector-stable (MINOR)

**Severity:** MINOR (usability; affects automation)

**Route:** `/` , `/dashboard`, `/login`

**Repro:**
1. Probed common selectors: `[data-testid="language-switcher"]`, `[aria-label*="language"]`, `select[name*="lang"]`, `button:has-text("EN"|"DE")`, `[class*="lang"]`.
2. None resolve to a usable, uniquely identifiable control on the app shell. A `Deutsch` button is visible in the login header but its behavior is not obviously "switch language" (it is typed `submit`, see BUG-7).

**Impact:**
- Users looking for a language picker may not find one.
- Automated tests cannot reliably flip language; had to fall back to writing `localStorage.i18nextLng` directly.

**Expected:** A single, labelled language picker (`<button aria-label="Change language">` or `data-testid="language-switcher"`) visible on every page, not only the login.

**Screenshot:** `qa_output/screenshots/p4_dashboard.png` (no switcher visible post-"login").

---

## BUG-7 - Non-submit controls on login page declared `type="submit"` (MINOR)

**Severity:** MINOR (accessibility, form semantics)

**Route:** `/login`

**Repro:**
1. Open `/login`.
2. `document.querySelectorAll('button[type="submit"]')` returns 3 buttons:
   - "Deutsch" (header language switcher) - not in the login form, but type=submit.
   - "Anmelden" (real submit, inside the form).
   - "Mehr über die Plattform erfahren" ("Learn more about the platform", a marketing link) - not in any form, type=submit.

**Impact:**
- Pressing Enter while focus is outside the login form can trigger the wrong "submit".
- Generic Playwright selector `button[type="submit"]` picks the first match (the language button), breaking deterministic login automation.
- Accessibility testing tools flag orphan `type=submit` buttons.

**Expected:** Only real form-submitting controls should be `type="submit"`; decorative buttons should be `type="button"`.

**Screenshot:** console inspection only.

---

## BUG-8 - `/projects` does not expose first-project as a clickable element (MAJOR)

**Severity:** MAJOR - but caveat: **this may be a symptom of BUG-2 (page not authenticated), not a standalone bug**. The test is retained because it documents an end-user impact: a user who arrives via bookmark cannot open any of the 5 seed projects.

**Route:** `/projects`

**Repro:**
1. Open `/projects` (either freshly, or after the UI login flow that hangs on the demo user).
2. No elements matching `a[href*="/projects/"]`, `[data-testid^="project-card"]`, `.project-card`, `tr[role=row] a[href*="/projects/"]` exist.
3. The page is visually the marketing landing.

**Impact:** The 5 seeded demo projects (Berlin, London, NY, Paris, Dubai) are unreachable via the `/projects` URL for any unauthenticated visitor, and - because BUG-1 prevents the admin login - for the Playwright-driven demo harness too.

**Screenshot:** `qa_output/screenshots/p4_projects_click.png`.

---

## INFO-1 - `oe_error_log` in localStorage grows unbounded and contains PII-ish data

**Severity:** INFO

After the 422 repro above, `localStorage.oe_error_log` contained `[{"id":"err_001","timestamp":"..."}]`. There is no visible retention policy. If the app keeps appending, this storage key may grow indefinitely, and if it includes email/input values from failed validations, it also leaks PII to any script running on the page (XSS, browser-extension).

**Expected:** Cap the log size (ring buffer) and scrub `email`, `password`, user-content before persisting.

---

## Route sweep result (for completeness)

All 23 protected routes returned HTTP 200 with no `pageerror` and no non-noise `console.error`. BUT: because of BUG-2, every one of them rendered the landing page. The list is useful only to assert that none of the route paths 500 or crash the SPA bootloader - **not** that the corresponding feature works. Screenshots:

```
p4_dashboard.png   p4_projects.png    p4_projects_new.png
p4_boq.png         p4_costs.png       p4_catalog.png
p4_takeoff.png     p4_schedule.png    p4_tendering.png
p4_reports.png     p4_documents.png   p4_validation.png
p4_requirements.png p4_risk.png       p4_changeorders.png
p4_assemblies.png  p4_settings.png    p4_audit.png
p4_markups.png     p4_punchlist.png   p4_fieldreports.png
p4_tasks.png       p4_contacts.png
p4_i18n_de.png     p4_i18n_ar.png     p4_i18n_zh.png
p4_boq_after_add.png  p4_projects_click.png
```

All under `C:/Users/Artem/OpenConstructionERP/qa_output/screenshots/`.

## Next steps suggested

1. Fix BUG-1 (make the `demo@...` user login endpoint actually respond - probably a stuck bcrypt worker or a deadlock in the per-user rate-limit path).
2. Fix BUG-2 + BUG-4 so that automation can actually reach the authenticated views.
3. Re-run `pytest qa_output/generated_tests/test_p4_agent_a_ui_deep.py -v` and the screenshots will then reflect the real module UIs - at which point a second audit pass will be able to surface module-level issues (AG Grid editing, validation dashboard, i18n strings, RTL layout, etc.).
