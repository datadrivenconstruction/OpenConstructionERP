/**
 * Diagnostic: navigate every top-level route as a freshly-registered user
 * (role=viewer after v2.0.0 BUG-327/386 security hardening) and log every
 * failed API call + console error. No assertions — just data collection.
 */

import { test, type Page } from '@playwright/test';

async function injectAuth(page: Page): Promise<void> {
  const login = await page.request.post(
    'http://localhost:8000/api/v1/users/auth/login/',
    { data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' } },
  );
  const b = login.ok()
    ? await login.json()
    : (await page.request
        .post('http://localhost:8000/api/v1/users/auth/register/', {
          data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!', full_name: 'E2E' },
        })
        .then(() =>
          page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
            data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' },
          }),
        )
        .then((r) => r.json()));
  await page.addInitScript((t: { a: string; r: string }) => {
    localStorage.setItem('oe_access_token', t.a);
    localStorage.setItem('oe_refresh_token', t.r);
    localStorage.setItem('oe_remember', '1');
    localStorage.setItem('oe_user_email', 'test@openestimate.com');
    localStorage.setItem('oe_onboarding_completed', 'true');
    localStorage.setItem('oe_welcome_dismissed', 'true');
    localStorage.setItem('oe_tour_completed', 'true');
    sessionStorage.setItem('oe_access_token', t.a);
  }, { a: b.access_token, r: b.refresh_token ?? b.access_token });
}

const routes = [
  '/',
  '/projects',
  '/boq',
  '/costs',
  '/assemblies',
  '/validation',
  '/takeoff?tab=measurements',
  '/dwg-takeoff',
  '/bim',
  '/data-explorer',
  '/modules',
  '/settings',
  '/ai-estimate',
  '/chat',
  '/reports',
  '/analytics',
];

test('viewer role: collect all errors across top-level routes', async ({ page }) => {
  test.setTimeout(300_000);
  await injectAuth(page);

  const errorsByRoute: Record<string, { http: Array<{ url: string; status: number }>; console: string[] }> = {};
  let current = '';

  page.on('response', (resp) => {
    if (!current) return;
    const status = resp.status();
    if (status >= 400 && resp.url().includes('/api/')) {
      (errorsByRoute[current] ??= { http: [], console: [] }).http.push({
        url: resp.url().replace(/^https?:\/\/localhost:\d+/, ''),
        status,
      });
    }
  });

  page.on('console', (msg) => {
    if (!current || msg.type() !== 'error') return;
    const txt = msg.text();
    // Skip noisy 3rd-party / auth-expected lines
    if (txt.includes('Failed to load resource')) return;
    if (txt.length > 200) return;
    (errorsByRoute[current] ??= { http: [], console: [] }).console.push(txt);
  });

  for (const r of routes) {
    current = r;
    errorsByRoute[r] = { http: [], console: [] };
    try {
      await page.goto(r, { waitUntil: 'networkidle', timeout: 20_000 });
    } catch {
      // Continue even if navigation times out
    }
    await page.waitForTimeout(1500);
  }

  console.log('\n═══ ERROR AUDIT ═══');
  for (const [route, errs] of Object.entries(errorsByRoute)) {
    if (errs.http.length === 0 && errs.console.length === 0) continue;
    console.log(`\n──── ${route} ────`);
    for (const h of errs.http) console.log(`  HTTP ${h.status} ${h.url}`);
    for (const c of errs.console) console.log(`  JS    ${c}`);
  }
  console.log('\n═══ END ═══');
});
