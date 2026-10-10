/**
 * Background services center: header button, panel toggle and restart, the
 * first-run wizard, the module banner, and no horizontal scroll at phone width.
 *
 * The processes API is answered by an in-memory registry in the page by
 * default, so the spec runs whether or not the backend ships it yet. Set
 * E2E_PROCESSES_REAL=1 to talk to the real endpoints instead (the wizard and
 * banner cases then skip, since they depend on a specific server state).
 *
 * Set PROCESSES_SHOTS=<dir> to also save desktop and 390px screenshots in
 * light and dark.
 */

import { test, expect, type Page, type Route } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';

const DEMO_EMAIL = 'demo@openconstructionerp.com';
const REAL = process.env.E2E_PROCESSES_REAL === '1';
const SHOTS = process.env.PROCESSES_SHOTS;

type Proc = Record<string, unknown> & { id: string; enabled: boolean; status: string; modules: string[] };

function proc(id: string, over: Partial<Proc>): Proc {
  return {
    id,
    name_key: `processes.${id}.name`,
    purpose_key: `processes.${id}.purpose`,
    off_impact_key: `processes.${id}.off_impact`,
    category: 'scheduler',
    modules: [],
    start_mode: 'boot',
    default_enabled: true,
    enabled: true,
    required: false,
    stoppable: true,
    env_locked: false,
    status: 'running',
    ram_mb_estimate: 5,
    ram_mb_actual: null,
    last_error: null,
    restart_count: 0,
    next_retry_at: null,
    started_at: null,
    log_tail: [],
    ...over,
  };
}

function seedRegistry(firstRunDone: boolean) {
  return {
    first_run_done: firstRunDone,
    processes: [
      proc('embedding_model', { category: 'ai_model', modules: ['search', 'costs', 'ai'], start_mode: 'lazy', enabled: false, status: 'disabled', ram_mb_estimate: 450 }),
      proc('bge_reranker', { category: 'ai_model', modules: ['costs'], start_mode: 'lazy', status: 'error', ram_mb_estimate: 350, last_error: { message: 'model weights not found', at: null }, log_tail: ['loading reranker', 'model weights not found'] }),
      proc('vector_db', { category: 'vector_index', modules: ['search', 'costs'], start_mode: 'lazy', enabled: false, status: 'disabled', ram_mb_estimate: 200 }),
      proc('kpi_scheduler', { modules: ['reporting'] }),
      proc('ai_agent_scheduler', { modules: ['ai_agents'], enabled: false, status: 'disabled' }),
      proc('cost_cache_prewarm', { category: 'cache_warmup', modules: ['costs'], enabled: false, status: 'disabled', ram_mb_estimate: 60 }),
      proc('notification_worker', { category: 'sync', modules: ['notifications'] }),
      proc('file_trash_purge', { category: 'maintenance', modules: ['file_trash'] }),
      proc('event_bus', { category: 'sync', required: true, stoppable: false, ram_mb_estimate: 2 }),
    ],
  };
}

async function mockProcesses(page: Page, firstRunDone = true) {
  const reg = seedRegistry(firstRunDone);
  const calls: string[] = [];
  const snapshot = () => ({
    processes: reg.processes,
    total_ram_mb_estimate: reg.processes.filter((p) => p.enabled).reduce((s, p) => s + (p.ram_mb_estimate as number), 0),
    process_rss_mb: null,
    first_run_done: reg.first_run_done,
  });
  await page.route('**/api/v1/processes/**', async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const parts = url.pathname.replace(/\/$/, '').split('/');
    calls.push(`${req.method()} ${url.pathname}`);
    if (req.method() === 'GET') return route.fulfill({ json: snapshot() });
    const last = parts[parts.length - 1];
    if (last === 'first-run') {
      const body = req.postDataJSON() as { module_ids: string[]; start_now: boolean };
      reg.first_run_done = true;
      if (body.start_now) {
        for (const p of reg.processes) {
          if (p.modules.some((m) => body.module_ids.includes(m))) Object.assign(p, { enabled: true, status: 'running' });
        }
      }
      return route.fulfill({ json: snapshot() });
    }
    if (last === 'preset') {
      for (const p of reg.processes) if (!p.required) Object.assign(p, { enabled: false, status: 'disabled' });
      return route.fulfill({ json: snapshot() });
    }
    const p = reg.processes.find((x) => x.id === parts[parts.length - 2]);
    if (!p) return route.fulfill({ status: 404, json: { detail: 'unknown process' } });
    if (last === 'enable') Object.assign(p, { enabled: true, status: 'running' });
    if (last === 'disable') Object.assign(p, { enabled: false, status: 'disabled' });
    if (last === 'restart') Object.assign(p, { status: 'running', last_error: null, restart_count: (p.restart_count as number) + 1 });
    return route.fulfill({ json: p });
  });
  // The list endpoint has no trailing segment after the slash on some clients.
  await page.route('**/api/v1/processes', (route) => route.fulfill({ json: snapshot() }));
  return calls;
}

async function demoLogin(page: Page): Promise<void> {
  const response = await page.request.post('/api/v1/users/auth/demo-login/', { data: { email: DEMO_EMAIL } });
  if (!response.ok()) test.skip(true, `demo-login unavailable: ${response.status()}`);
  const body = (await response.json()) as { access_token: string; refresh_token: string };
  await page.goto('/');
  await page.evaluate(
    ({ access, refresh }) => {
      sessionStorage.setItem('oe_access_token', access);
      sessionStorage.setItem('oe_refresh_token', refresh);
      localStorage.setItem('oe_onboarding_completed', 'true');
    },
    { access: body.access_token, refresh: body.refresh_token },
  );
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

test.describe('Background services center', () => {
  test('opens the panel, toggles and restarts a service', async ({ page }) => {
    const calls = REAL ? [] : await mockProcesses(page);
    await demoLogin(page);
    await page.goto('/');

    const button = page.getByTestId('header-processes');
    await expect(button).toBeVisible({ timeout: 30_000 });
    if (!REAL) await expect(button).toHaveAttribute('data-health', 'error');
    await button.click();

    const panel = page.getByTestId('processes-panel');
    await expect(panel).toBeVisible();
    await expect(page.getByTestId('processes-summary')).toBeVisible();
    if (REAL) return;

    await shot(page, 'panel-desktop-light');

    const vector = page.getByTestId('process-row-vector_db');
    await vector.getByTestId('process-toggle').click();
    await expect(vector.getByTestId('process-status')).toHaveAttribute('data-status', 'running');
    expect(calls).toContain('POST /api/v1/processes/vector_db/enable');

    const reranker = page.getByTestId('process-row-bge_reranker');
    await reranker.getByTestId('process-expand').click();
    await expect(reranker.getByText('model weights not found').first()).toBeVisible();
    await shot(page, 'panel-desktop-light-details');
    await reranker.getByTestId('process-restart').click();
    await expect(reranker.getByTestId('process-status')).toHaveAttribute('data-status', 'running');
    expect(calls).toContain('POST /api/v1/processes/bge_reranker/restart');

    // A service the platform needs has no live switch.
    await expect(page.getByTestId('process-row-event_bus').getByTestId('process-toggle')).toBeDisabled();

    await page.keyboard.press('Escape');
    await expect(panel).toBeHidden();
  });

  test('first-run wizard starts the services of the picked modules', async ({ page }) => {
    test.skip(REAL, 'depends on a server that never ran the first-run choice');
    const calls = await mockProcesses(page, false);
    await demoLogin(page);
    await page.goto('/');

    const wizard = page.getByTestId('processes-wizard');
    await expect(wizard).toBeVisible({ timeout: 30_000 });
    await shot(page, 'wizard-desktop-light');
    await wizard.getByTestId('wizard-module-reporting').click();
    await wizard.getByTestId('wizard-module-ai_agents').click();
    await wizard.getByTestId('wizard-start').click();
    await expect(wizard).toBeHidden();
    expect(calls).toContain('POST /api/v1/processes/first-run');

    // Reopenable from the panel.
    await page.getByTestId('header-processes').click();
    await page.getByTestId('processes-open-wizard').click();
    await expect(page.getByTestId('processes-wizard')).toBeVisible();
    await page.getByTestId('wizard-later').click();
    await expect(page.getByTestId('processes-wizard')).toBeHidden();
  });

  test('module page offers to turn on what it needs', async ({ page }) => {
    test.skip(REAL, 'depends on a specific server state');
    const calls = await mockProcesses(page);
    await demoLogin(page);
    await page.goto('/costs');
    const notice = page.getByTestId('module-processes-notice-costs');
    await expect(notice).toBeVisible({ timeout: 30_000 });
    await shot(page, 'notice-costs-desktop-light');
    await notice.getByTestId('module-processes-turn-on').click();
    await expect.poll(() => calls.filter((c) => c.endsWith('/enable')).length).toBeGreaterThan(0);
  });

  for (const scheme of ['light', 'dark'] as const) {
    test(`fits a 390px phone without horizontal scroll (${scheme})`, async ({ page }) => {
      test.skip(REAL, 'layout check runs on the mocked registry');
      await page.setViewportSize({ width: 390, height: 844 });
      await page.emulateMedia({ colorScheme: scheme });
      await mockProcesses(page);
      await demoLogin(page);
      await page.evaluate((s) => localStorage.setItem('oe_theme', s), scheme);
      await page.goto('/');
      await expect(page.getByTestId('header-processes')).toBeVisible({ timeout: 30_000 });
      await noHorizontalScroll(page);
      await shot(page, `header-390-${scheme}`);
      await page.getByTestId('header-processes').click();
      await expect(page.getByTestId('processes-panel')).toBeVisible();
      await noHorizontalScroll(page);
      await page.getByTestId('process-row-bge_reranker').getByTestId('process-expand').click();
      await noHorizontalScroll(page);
      await shot(page, `panel-390-${scheme}`);
      if (scheme === 'dark') {
        await page.setViewportSize({ width: 1440, height: 900 });
        await shot(page, 'panel-desktop-dark');
      }
    });
  }
});
