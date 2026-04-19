/**
 * Playwright global setup — login once, cache the JWT tokens, write a
 * storage-state file that every test reuses. Avoids hammering the
 * backend /login/ endpoint (which rate-limits after ~5 hits / minute)
 * when a spec fans out across many parallel workers.
 */
import { chromium, type FullConfig } from '@playwright/test';
import { V19_USER } from './helpers-v19';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname_esm = path.dirname(fileURLToPath(import.meta.url));
const STATE_PATH = path.resolve(__dirname_esm, '.auth-state.json');
const TOKEN_PATH = path.resolve(__dirname_esm, '.auth-token.txt');

async function globalSetup(_config: FullConfig) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();

  // Try logging in first. If the user doesn't exist, register and retry.
  const login = async () =>
    page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
      data: { email: V19_USER.email, password: V19_USER.password },
      failOnStatusCode: false,
    });
  let res = await login();
  if (!res.ok() && res.status() !== 429) {
    await page.request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: V19_USER,
      failOnStatusCode: false,
    });
    res = await login();
  }
  if (!res.ok()) {
    // Rate-limited or other issue — wait + retry once.
    await new Promise((r) => setTimeout(r, 65_000));
    res = await login();
  }
  if (!res.ok()) {
    throw new Error(`globalSetup: login failed with status ${res.status()}`);
  }
  const body = await res.json();
  const access = body.access_token as string;
  const refresh = (body.refresh_token ?? access) as string;

  fs.writeFileSync(TOKEN_PATH, access, 'utf-8');

  // Hydrate localStorage for the origin so subsequent contexts start
  // authenticated.
  await page.goto('http://localhost:5173/about');
  await page.evaluate(
    ({ access, refresh, email }) => {
      localStorage.setItem('oe_access_token', access);
      localStorage.setItem('oe_refresh_token', refresh);
      localStorage.setItem('oe_remember', '1');
      localStorage.setItem('oe_user_email', email);
      localStorage.setItem('oe_onboarding_completed', 'true');
      localStorage.setItem('oe_welcome_dismissed', 'true');
      localStorage.setItem('oe_tour_completed', 'true');
      sessionStorage.setItem('oe_access_token', access);
      sessionStorage.setItem('oe_refresh_token', refresh);
    },
    { access, refresh, email: V19_USER.email },
  );

  await ctx.storageState({ path: STATE_PATH });
  await browser.close();
}

export default globalSetup;
