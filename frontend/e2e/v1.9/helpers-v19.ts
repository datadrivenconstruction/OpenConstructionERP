/**
 * Shared helpers for v1.9 roadmap E2E specs.
 *
 * Auth strategy: obtain a real JWT against the running backend (register if
 * needed), then inject tokens into localStorage + sessionStorage via
 * addInitScript so the React app boots authenticated without a login form.
 * Mirrors the pattern used in ../bim-advanced.spec.ts.
 */
import { type Page, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// ESM-safe equivalent of __dirname (package.json has "type": "module").
const __dirname_esm = path.dirname(fileURLToPath(import.meta.url));
const TOKEN_PATH = path.resolve(__dirname_esm, '.auth-token.txt');

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

// Module-level token cache shared across loginV19 calls in the same worker.
// Avoids hitting the /login/ endpoint repeatedly when many tests in one
// worker call loginV19 sequentially (the backend rate-limits at ~5/min).
let cachedAccessToken: string | undefined;
let cachedRefreshToken: string | undefined;

async function obtainTokens(page: Page): Promise<{ access: string; refresh: string }> {
  if (cachedAccessToken && cachedRefreshToken) {
    return { access: cachedAccessToken, refresh: cachedRefreshToken };
  }
  // Try reading the token cached by globalSetup before hitting /login/.
  // Shared across all parallel workers through the file system.
  try {
    if (fs.existsSync(TOKEN_PATH)) {
      const cached = fs.readFileSync(TOKEN_PATH, 'utf-8').trim();
      if (cached) {
        cachedAccessToken = cached;
        cachedRefreshToken = cached;
        return { access: cached, refresh: cached };
      }
    }
  } catch {
    /* fall through to network login */
  }
  const tryLogin = async () => {
    const res = await page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
      data: { email: V19_USER.email, password: V19_USER.password },
      failOnStatusCode: false,
    });
    return res;
  };

  let res = await tryLogin();
  if (!res.ok() && res.status() !== 429) {
    // User may not exist yet — register then retry.
    await page.request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: V19_USER,
      failOnStatusCode: false,
    });
    res = await tryLogin();
  }
  if (!res.ok() && res.status() === 429) {
    // Rate-limited — back off once and retry.
    await new Promise((r) => setTimeout(r, 65_000));
    res = await tryLogin();
  }
  if (!res.ok()) {
    throw new Error(`v1.9 E2E: login failed with status ${res.status()}`);
  }
  const body = await res.json();
  cachedAccessToken = body.access_token as string;
  cachedRefreshToken = (body.refresh_token ?? cachedAccessToken) as string;
  return { access: cachedAccessToken!, refresh: cachedRefreshToken! };
}

export async function loginV19(page: Page): Promise<void> {
  const tokens = await obtainTokens(page);

  await page.addInitScript(
    (t: { access: string; refresh: string; email: string }) => {
      localStorage.setItem('oe_access_token', t.access);
      localStorage.setItem('oe_refresh_token', t.refresh);
      localStorage.setItem('oe_remember', '1');
      localStorage.setItem('oe_user_email', t.email);
      localStorage.setItem('oe_onboarding_completed', 'true');
      localStorage.setItem('oe_welcome_dismissed', 'true');
      localStorage.setItem('oe_tour_completed', 'true');
      sessionStorage.setItem('oe_access_token', t.access);
      sessionStorage.setItem('oe_refresh_token', t.refresh);
    },
    { access: tokens.access, refresh: tokens.refresh, email: V19_USER.email },
  );

  lastAccessToken = tokens.access;

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
