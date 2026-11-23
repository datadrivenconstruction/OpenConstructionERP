/**
 * What a person sees on a fresh install, measured in a real browser.
 *
 * Every other lane in this repository starts from a machine that is already
 * warm: a dev server that has been up since the job began, a database that a
 * fixture filled, a session a helper signed in. This one starts from what the
 * installer gets - an empty data directory, the CLI, and a Chromium that has
 * never seen this origin - and asks the questions the installer asks:
 *
 *   1. how long until the server answers at all,
 *   2. how much the sign-in page asks for while it waits,
 *   3. whether the first account they create is the one that owns the install,
 *   4. whether they can sign out and back in,
 *   5. whether the settings page names where this software comes from,
 *   6. whether the sign-up form still asks how they found us.
 *
 * The reports that produced this file were made by a person with DevTools open
 * on Windows: 585 requests and 6.4 MB for one load of the sign-in page, 27
 * console errors, and a toast reading "could not load data" on a page that had
 * not been given a chance to load anything. Nothing in the unit suites could
 * see any of that, because each of those numbers is a property of the whole
 * running product and not of any part of it.
 *
 * WHAT IS COUNTED, AND WHY THE CEILING IS NOT ON EVERY REQUEST
 *
 * The count that carries an assertion is the count of same-origin API requests:
 * anything whose path starts with `/api`. The total is recorded too and is not
 * asserted, and the difference is the point. A production bundle serves one
 * document, some styles, some fonts and as many JavaScript chunks as the route
 * graph needs; that number is a property of how the code is split, it moves
 * when anybody adds a lazy route, and a ceiling on it would fail a commit that
 * changed nothing about the loops this lane exists to catch. The requests the
 * installer reported seeing repeated - `current`, `branding/`, `config/`,
 * `health`, `client-errors/` - are all API calls, and an API call repeated
 * against a server that is still starting is the whole defect.
 *
 * HOW THE NUMBERS GET OUT
 *
 * Each test prints one line beginning `OE-COLD-START-METRICS` followed by a
 * JSON object. `scripts/ci/browser_cold_start_lane.py` reads those lines back
 * out of Playwright's own JSON report and turns them into job annotations, so
 * the counts are visible on the run and not only in a log nobody downloads.
 * The line is printed before the assertions run wherever the test has evidence
 * to lose, which is deliberate: a lane that fails on a count is exactly the
 * lane whose count somebody needs to read. The second test is the exception and
 * can be, because each of its steps asserts as it goes and carries its own
 * message. The driver reads the failures out of the same report - Playwright
 * records the title, the message and the step durations of every test that did
 * not pass - and annotates each one, so a red run of this lane names the test
 * that stopped rather than only the exit code it stopped with.
 */
import { test, expect, type Page } from '@playwright/test';

/**
 * One worker, in order, against one server and one database. The second test
 * creates the first account on this install; if it ran after another test that
 * also registered, it would be creating the second one and asserting admin for
 * an account that is not the bootstrap account.
 */
test.describe.configure({ mode: 'serial' });

/** How long the sign-in page is watched after it paints. */
const RECORD_WINDOW_MS = Number(process.env.OE_COLD_START_RECORD_WINDOW_MS ?? '45000');

/** Ceilings. Each one is a number a person reported exceeding, or a loop bound. */
const MAX_API_REQUESTS = 60;
const MAX_REPEATS_OF_ONE_URL = 5;

/**
 * How long the last test gives each of its waits, and why that test's waits and
 * only that test's.
 *
 * The Windows leg of this lane failed once with the product code byte-identical
 * to the run before it that passed: the whole difference between those two
 * commits was two backend PostgreSQL test files, which this lane never installs
 * and never executes. Both runs ran the same four tests against a cold install.
 * The passing one reported 76.7s of Playwright time against a 90.8s boot and all
 * four tests expected; the failing one reported 143.2s against a 100.9s boot and
 * three expected, one unexpected. The record window in the first test is 45s on
 * both, so the three tests that act on the product took about 32s when the leg
 * passed and about 98s when it failed: one exhausted 60s ceiling plus the
 * reporting around it, in the last test, which is the only test whose metrics
 * line never reached the run.
 *
 * Which of that test's three waits ran out is not known, and widening one of them
 * on a guess about which it was would leave the other two where they are for the
 * next run to find. All three are the same kind of wait against the same cold
 * server, so all three move together. 120s is about four times what this platform
 * was measured doing when it passed, and the step timings printed with the report
 * are what keep that from being a quietly widened door: a slow step is still a
 * slow step in the numbers, and if one of these ceilings runs out again the
 * annotation carries the boot time to read it against.
 *
 * The first three tests keep their own ceilings on purpose. They passed on both
 * platforms in both runs, the first test's wait bounds the first paint after a
 * cold boot which is the thing this lane exists to measure, and a lane that moves
 * every ceiling it has after one failure has stopped measuring anything.
 */
const COLD_STEP_TIMEOUT_MS = 120_000;

/** The first account on this install. Policy-compliant: letters, digits, 8+. */
const OWNER_EMAIL = 'browser-lane-owner@example.com';
const OWNER_PASSWORD = 'Browser-Lane!2026';
const OWNER_NAME = 'Browser Lane Owner';

/**
 * The load-failure toast, in the two languages this lane can meet. The English
 * string is the `defaultValue` in `queryErrorToast.ts`; the Arabic one is what
 * `errors.query_failed_title` carries in `ar.ts`, and is the exact sentence the
 * installer reported seeing before they had typed anything.
 */
const LOAD_FAILURE_TOAST = /could not load data|تعذّر تحميل البيانات|failed to load/i;

interface Census {
  total: number;
  api: number;
  assets: number;
  byEndpoint: Record<string, number>;
  worstRepeat: { url: string; count: number };
  serverErrors: { url: string; status: number }[];
  clientErrors: { url: string; status: number }[];
  consoleErrors: string[];
  pageErrors: string[];
}

/** Print the metrics line the CI driver reads back out of the JSON report. */
function report(name: string, metrics: Record<string, unknown>): void {
  // One line, one JSON object, no pretty printing: the driver parses it with a
  // prefix match and `json.loads`, and a wrapped object is a broken one.
  console.log(`OE-COLD-START-METRICS ${JSON.stringify({ name, ...metrics })}`);
}

/** Everything a page asked for, counted the way the report above describes. */
function watch(page: Page): { census: () => Census; stop: () => void } {
  const urls = new Map<string, number>();
  let total = 0;
  let api = 0;
  let assets = 0;
  const serverErrors: { url: string; status: number }[] = [];
  // Published and not asserted. A 4xx is an answer, and the page has a surface for
  // most of them, but a browser logs every failed resource to the console at error
  // level - so when the console-error ceiling below fails, this is the list that
  // says which request caused it. The first run of this lane failed on exactly that:
  // one console error reading "the server responded with a status of 401", with
  // nothing in the report naming the URL that answered it.
  const clientErrors: { url: string; status: number }[] = [];
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];

  const onRequest = (request: { url(): string; resourceType(): string }): void => {
    total += 1;
    let parsed: URL;
    try {
      parsed = new URL(request.url());
    } catch {
      return;
    }
    const key = `${parsed.pathname}${parsed.search}`;
    urls.set(key, (urls.get(key) ?? 0) + 1);
    if (parsed.pathname.startsWith('/api')) api += 1;
    else assets += 1;
    void request.resourceType();
  };

  const onResponse = (response: { url(): string; status(): number }): void => {
    if (response.status() >= 500) {
      serverErrors.push({ url: response.url(), status: response.status() });
    } else if (response.status() >= 400) {
      clientErrors.push({ url: response.url(), status: response.status() });
    }
  };

  const onConsole = (message: { type(): string; text(): string }): void => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300));
  };

  const onPageError = (error: Error): void => {
    pageErrors.push(String(error.message ?? error).slice(0, 300));
  };

  page.on('request', onRequest);
  page.on('response', onResponse);
  page.on('console', onConsole);
  page.on('pageerror', onPageError);

  return {
    census: () => {
      const byEndpoint: Record<string, number> = {};
      let worstRepeat = { url: '', count: 0 };
      for (const [url, count] of urls) {
        // Grouped without the query string, because a poll that varies a cache
        // buster is still one endpoint asked too many times.
        // `?? url` because the project type checks with noUncheckedIndexedAccess,
        // and because a key with no query string is the whole key anyway.
        const endpoint = url.split('?')[0] ?? url;
        byEndpoint[endpoint] = (byEndpoint[endpoint] ?? 0) + count;
        if (count > worstRepeat.count) worstRepeat = { url, count };
      }
      return { total, api, assets, byEndpoint, worstRepeat, serverErrors, clientErrors, consoleErrors, pageErrors };
    },
    stop: () => {
      page.off('request', onRequest);
      page.off('response', onResponse);
      page.off('console', onConsole);
      page.off('pageerror', onPageError);
    },
  };
}

test('the sign-in page asks for little and says nothing failed', async ({ page }) => {
  const { census, stop } = watch(page);
  await page.goto('/login');
  // Painted and interactive: the form is there, so whatever it does next is the
  // page's own doing rather than the bundle still arriving.
  await expect(page.locator('#login-password')).toBeVisible({ timeout: 60_000 });

  await page.waitForTimeout(RECORD_WINDOW_MS);
  const c = census();
  stop();

  const bodyText = (await page.locator('body').textContent()) ?? '';
  const toastSeen = LOAD_FAILURE_TOAST.test(bodyText);

  report('sign-in page census', {
    record_window_ms: RECORD_WINDOW_MS,
    total_requests: c.total,
    api_requests: c.api,
    asset_requests: c.assets,
    by_endpoint: c.byEndpoint,
    worst_repeat: c.worstRepeat,
    server_errors: c.serverErrors,
    client_errors: c.clientErrors,
    console_errors: c.consoleErrors,
    page_errors: c.pageErrors,
    load_failure_toast: toastSeen,
  });

  expect(
    c.api,
    `${c.api} API requests on the sign-in page; the ceiling is ${MAX_API_REQUESTS}. Per endpoint: ${JSON.stringify(c.byEndpoint)}`,
  ).toBeLessThan(MAX_API_REQUESTS);

  expect(
    c.worstRepeat.count,
    `${c.worstRepeat.url} was asked ${c.worstRepeat.count} times; one URL may be asked at most ${MAX_REPEATS_OF_ONE_URL} times`,
  ).toBeLessThanOrEqual(MAX_REPEATS_OF_ONE_URL);

  expect(c.serverErrors, `server answered 5xx: ${JSON.stringify(c.serverErrors)}`).toHaveLength(0);
  expect(c.pageErrors, `uncaught page errors: ${JSON.stringify(c.pageErrors)}`).toHaveLength(0);
  expect(
    c.consoleErrors,
    `console errors: ${JSON.stringify(c.consoleErrors)}; the API answers behind them: ${JSON.stringify(c.clientErrors)}`,
  ).toHaveLength(0);
  expect(toastSeen, 'the sign-in page showed a load-failure toast before anything was asked of it').toBe(false);
});

test('the first account made through the UI owns the install and can sign in again', async ({ page, context }) => {
  await page.goto('/register');
  await expect(page.locator('#register-password')).toBeVisible({ timeout: 60_000 });

  await page.locator('#register-full-name').fill(OWNER_NAME);
  await page.locator('#register-email').fill(OWNER_EMAIL);
  await page.locator('#register-password').fill(OWNER_PASSWORD);
  await page.locator('#register-confirm-password').fill(OWNER_PASSWORD);
  // The submit button is disabled until the privacy-consent box is ticked -
  // RegisterPage requires the name, both password fields, a match, the policy and
  // the consent before it will send. A lane that skipped this would wait out an
  // action timeout on a button nobody can press and report it as a product that
  // will not register its first account. There is exactly one checkbox on the form.
  await page.locator('input[type="checkbox"]').check();
  await expect(page.locator('button[type="submit"]')).toBeEnabled({ timeout: 10_000 });
  await page.locator('button[type="submit"]').click();

  // Registration either signs the first account straight in or says why it did
  // not. A pending-activation answer here is the dead end this lane exists to
  // catch: the first account on an install with no administrator in it has
  // nobody who could approve it.
  await expect(page, 'still on the sign-up form after submitting it').not.toHaveURL(/\/register/, {
    timeout: 60_000,
  });

  // An administrator can reach user management. Nobody else can, so this is the
  // claim "the first account is the admin" asked of the product rather than of
  // the database.
  await page.goto('/users');
  await expect(page, 'the first account was not let into user management').not.toHaveURL(/\/login/, {
    timeout: 30_000,
  });

  // Sign out through the header when the control is reachable. The menu is a
  // dropdown, so the trigger is clicked first; if this build renders it
  // somewhere the lane cannot find, the session is cleared instead and the
  // metrics say which of the two happened, because the difference matters: a
  // control nobody can find is a defect, and a lane that silently worked around
  // it would be the only place that knew.
  let signedOutViaControl = false;
  try {
    await page.locator('header').getByRole('button').last().click({ timeout: 10_000 });
    await page.getByRole('button', { name: /sign out|log out/i }).first().click({ timeout: 10_000 });
    signedOutViaControl = true;
  } catch {
    await context.clearCookies();
    await page.evaluate(() => {
      window.localStorage.clear();
      window.sessionStorage.clear();
    });
  }

  await page.goto('/login');
  await expect(page.locator('#login-password')).toBeVisible({ timeout: 60_000 });
  await page.locator('input[type="email"]').fill(OWNER_EMAIL);
  await page.locator('#login-password').fill(OWNER_PASSWORD);
  await page.locator('button[type="submit"]').click();

  await expect(page, 'the account that was just created could not sign in').not.toHaveURL(/\/login/, {
    timeout: 60_000,
  });
  // The shell is up: a header and a navigation, which is what "the dashboard
  // renders" means to somebody who has never seen the inside of this app.
  await expect(page.locator('header').first()).toBeVisible({ timeout: 30_000 });

  report('first account', {
    email: OWNER_EMAIL,
    reached_user_management: true,
    signed_out_via_control: signedOutViaControl,
    signed_in_again: true,
    url_after_sign_in: page.url(),
  });
});

test('the sign-up form does not ask how the visitor found us', async ({ page }) => {
  await page.goto('/register');
  await expect(page.locator('#register-password')).toBeVisible({ timeout: 60_000 });

  const referralField = page.locator('#register-how-found');
  const referralLabel = page.getByText(/how did you find us/i);
  const fieldCount = await referralField.count();
  const labelCount = await referralLabel.count();
  const marketingOptionCount = await page.locator('option[value="linkedin"], option[value="reddit"]').count();

  report('sign-up form fields', {
    referral_field_count: fieldCount,
    referral_label_count: labelCount,
    marketing_option_count: marketingOptionCount,
    input_count: await page.locator('input, select, textarea').count(),
  });

  expect(fieldCount, 'the sign-up form still carries the referral-source field').toBe(0);
  expect(labelCount, 'the sign-up form still asks how the visitor found us').toBe(0);
  expect(marketingOptionCount, 'the referral-source options are still in the form').toBe(0);
});

test('settings shows support and legal without naming where this software comes from', async ({ page }) => {
  // Signed in as the account the second test made; a signed-out visit to
  // /settings is a redirect and would measure nothing.
  //
  // This test watches the page and prints before it asserts, as the first and
  // third tests do and the second cannot: the second test's report summarises
  // actions that each carried their own assertion, so a failure there is named
  // by the assertion that failed. This one used to print last, and the run that
  // failed it therefore published nothing about itself at all - no URL, no
  // timings, no console errors - which is the reason the driver now also
  // annotates every failing test out of Playwright's own report.
  const { census, stop } = watch(page);
  const timings: Record<string, number> = {};
  let stepStartedAt = Date.now();
  /** Record how long the step just finished took, and start the next one. */
  const mark = (step: string): void => {
    timings[step] = Date.now() - stepStartedAt;
    stepStartedAt = Date.now();
  };

  await page.goto('/login');
  await expect(page.locator('#login-password')).toBeVisible({ timeout: COLD_STEP_TIMEOUT_MS });
  mark('sign-in page painted');
  await page.locator('input[type="email"]').fill(OWNER_EMAIL);
  await page.locator('#login-password').fill(OWNER_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page, 'still on the sign-in form after signing in through it').not.toHaveURL(/\/login/, {
    timeout: COLD_STEP_TIMEOUT_MS,
  });
  mark('signed in');

  // The card lives on the Company & documents tab. SettingsPage reads ?tab= and
  // defaults to 'general', so a plain /settings renders a page that does not
  // contain this card at all and the case would fail on a navigation nobody took
  // rather than on anything the card says. This is the route a person clicks
  // through to, spelled as the URL the page itself publishes.
  await page.goto('/settings?tab=company');
  mark('settings navigated');

  // The card by the handle the product's own tests use -
  // CompanyDocumentsSettings.tsx puts data-testid="support-and-legal" on the
  // Card and CompanyDocumentsSettings.test.tsx asks for exactly that - rather
  // than by its heading text. Two reasons, and the second is a defect this test
  // had.
  //
  // The heading is `settings.support.title`, a translation key that happens to
  // carry the same English sentence in all forty-three bundles today. A handle
  // does not depend on that staying true.
  //
  // The text locator this test filtered on resolved to the *innermost* element
  // holding the heading, because `.last()` over a document-order list of nested
  // matches is the deepest of them. So `cardText` was the heading and its
  // subtitle, the assertion below read two sentences of a card that renders ten,
  // and the comment that called it "the card, and not the page" described an
  // intention the locator never carried out: whatever the card said underneath
  // its own title, this test agreed with it.
  const card = page.locator('[data-testid="support-and-legal"]');
  let cardError = '';
  try {
    await expect(card, 'the Support and legal card did not render').toBeVisible({
      timeout: COLD_STEP_TIMEOUT_MS,
    });
  } catch (error) {
    // Caught so the report still prints. A card that never rendered is the one
    // outcome where the evidence matters most, and an exception thrown here
    // would take the evidence with it. The first few lines rather than the first
    // one, because a wait that runs out puts its subject in the call log below
    // the sentence: "waiting for locator('[data-testid="support-and-legal"]')"
    // is the part that says what was looked for.
    cardError = String((error as { message?: string } | undefined)?.message ?? error)
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line !== '')
      .slice(0, 4)
      .join(' | ');
  }
  mark('card waited for');
  const cardRendered = cardError === '';

  // The door from this card to the source offer, which is what makes the card
  // allowed to be quiet about where the software comes from: it is not quiet
  // about the licence. The link renders whether or not the footers show it.
  const legalLinkCount = await card.locator('a[href="/legal"]').count();
  // Published and not asserted. This notice is the one thing in the card that
  // names a licence, so it is the one thing the origin assertion below can trip
  // on, and it renders only when an administrator has hidden the Legal link -
  // which a fresh install has not done, which is also why the runs that passed
  // measured no origin anywhere on the page.
  const agplNoticeCount = await page.locator('[data-testid="legal-agpl-notice"]').count();

  const cardText = cardRendered ? ((await card.textContent()) ?? '') : '';
  const pageText = (await page.locator('body').textContent()) ?? '';
  const c = census();
  stop();
  mark('evidence gathered');

  const origins = /open source|AGPL|GitHub/i;

  report('settings support and legal', {
    card_rendered: cardRendered,
    card_error: cardError.slice(0, 300),
    url: page.url(),
    step_timeout_ms: COLD_STEP_TIMEOUT_MS,
    timings_ms: timings,
    legal_link_count: legalLinkCount,
    agpl_notice_count: agplNoticeCount,
    card_names_an_origin: origins.test(cardText),
    card_matches: (cardText.match(new RegExp(origins.source, 'gi')) ?? []).slice(0, 10),
    page_names_an_origin: origins.test(pageText),
    page_matches: (pageText.match(new RegExp(origins.source, 'gi')) ?? []).slice(0, 10),
    api_requests: c.api,
    server_errors: c.serverErrors,
    console_errors: c.consoleErrors,
    page_errors: c.pageErrors,
  });

  expect(
    cardRendered,
    `the Support and legal card did not render within ${COLD_STEP_TIMEOUT_MS}ms; url=${page.url()} ` +
      `timings=${JSON.stringify(timings)} card_error="${cardError.slice(0, 200)}" ` +
      `console_errors=${JSON.stringify(c.consoleErrors)} page_errors=${JSON.stringify(c.pageErrors)} ` +
      `server_errors=${JSON.stringify(c.serverErrors)}`,
  ).toBe(true);

  expect(
    legalLinkCount,
    'the card no longer links to /legal, where the source offer this card exists to keep lives',
  ).toBeGreaterThan(0);

  expect(
    origins.test(cardText),
    'the Support and legal card names where this software comes from: ' +
      `${JSON.stringify(cardText.match(new RegExp(origins.source, 'gi')))}. ` +
      'If the match is "AGPL", the cause is the notice at data-testid="legal-agpl-notice", which this card shows ' +
      "when an administrator hides the Legal link: that notice is the licence's own requirement and must not be " +
      'removed to make this pass. A fresh install shows the link and hides the notice, so on a cold start this ' +
      'sentence means the card grew a vendor, a repository or a claim about its origins.',
  ).toBe(false);
});
