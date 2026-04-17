/**
 * Shared helpers for v1.9 roadmap E2E specs.
 *
 * Auth strategy: obtain a real JWT against the running backend (register if
 * needed), then inject tokens into localStorage + sessionStorage via
 * addInitScript so the React app boots authenticated without a login form.
 * Mirrors the pattern used in ../bim-advanced.spec.ts.
 */
import { type Page, expect } from '@playwright/test';

export const V19_USER = {
  email: process.env.V19_E2E_EMAIL ?? 'v19-e2e@openestimate.com',
  password: process.env.V19_E2E_PASSWORD ?? 'OpenEstimate2024!',
  full_name: 'v1.9 E2E User',
};

// Last access token obtained by loginV19 — used by the helper REST calls
// below so they can authenticate against the backend. Playwright's
// page.request does NOT share storage with the browser's localStorage.
let lastAccessToken: string | undefined;

function authHeaders(): Record<string, string> {
  return lastAccessToken ? { Authorization: `Bearer ${lastAccessToken}` } : {};
}

export async function loginV19(page: Page): Promise<void> {
  let accessToken: string | undefined;
  let refreshToken: string | undefined;

  const tryLogin = async (): Promise<boolean> => {
    const res = await page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
      data: { email: V19_USER.email, password: V19_USER.password },
      failOnStatusCode: false,
    });
    if (!res.ok()) return false;
    const body = await res.json();
    accessToken = body.access_token;
    refreshToken = body.refresh_token ?? body.access_token;
    return true;
  };

  if (!(await tryLogin())) {
    await page.request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: V19_USER,
      failOnStatusCode: false,
    });
    const ok = await tryLogin();
    if (!ok) throw new Error('v1.9 E2E: could not log in or register test user');
  }

  await page.addInitScript(
    (tokens: { access: string; refresh: string; email: string }) => {
      localStorage.setItem('oe_access_token', tokens.access);
      localStorage.setItem('oe_refresh_token', tokens.refresh);
      localStorage.setItem('oe_remember', '1');
      localStorage.setItem('oe_user_email', tokens.email);
      localStorage.setItem('oe_onboarding_completed', 'true');
      localStorage.setItem('oe_welcome_dismissed', 'true');
      localStorage.setItem('oe_tour_completed', 'true');
      sessionStorage.setItem('oe_access_token', tokens.access);
      sessionStorage.setItem('oe_refresh_token', tokens.refresh);
    },
    { access: accessToken!, refresh: refreshToken!, email: V19_USER.email },
  );

  lastAccessToken = accessToken;

  // Hydrate the init script by hitting a cheap page that doesn't redirect.
  await page.goto('/about');
  await page.waitForLoadState('load');
}

/** Fetch the first project id for the logged-in user — skip the test if none exist. */
export async function firstProjectId(page: Page): Promise<string | null> {
  const res = await page.request.get('http://localhost:8000/api/v1/projects/', {
    headers: authHeaders(),
  });
  if (!res.ok()) return null;
  const projects = (await res.json()) as Array<{ id: string }>;
  return projects[0]?.id ?? null;
}

/** Create a throw-away project so the test has a known target. */
export async function ensureProject(page: Page, name = 'v1.9 E2E Project'): Promise<string> {
  const existing = await firstProjectId(page);
  if (existing) return existing;
  const res = await page.request.post('http://localhost:8000/api/v1/projects/', {
    headers: authHeaders(),
    data: { name, description: 'Auto-created for v1.9 tests', currency: 'EUR' },
  });
  if (!res.ok()) {
    // eslint-disable-next-line no-console
    console.error('[v1.9] ensureProject failed:', res.status(), await res.text());
  }
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return body.id as string;
}

/** Find the first BIM model with elements for the project — returns null if none. */
export async function firstBimModelId(
  page: Page,
  projectId: string,
): Promise<string | null> {
  const res = await page.request.get(
    `http://localhost:8000/api/v1/bim_hub/models/?project_id=${projectId}`,
    { headers: authHeaders() },
  );
  if (!res.ok()) return null;
  const body = await res.json();
  const items = (body.items ?? body) as Array<{ id: string }>;
  return items[0]?.id ?? null;
}
