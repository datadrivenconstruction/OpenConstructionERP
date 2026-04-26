/**
 * Dashboards T01 — Snapshot Registry E2E.
 *
 * Coverage (multi-format, per CLAUDE-DASHBOARDS.md Part I §1.3):
 *   1. Empty-state render when a project has no snapshots
 *   2. IFC upload — happy path → snapshot appears in list
 *   3. DWG upload — unsupported format → toast surfaces backend i18n message
 *   4. Manifest endpoint reachable for the created snapshot
 *   5. Deletion round-trip
 *
 * Screenshots land in docs/screenshots/dashboards/task-01/<step>.png.
 */

import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const BACKEND = 'http://localhost:8000';
const SCREENSHOT_DIR = path.resolve(
  __dirname,
  '../../docs/screenshots/dashboards/task-01',
);

const IFC_FIXTURE = path.resolve(__dirname, 'fixtures/dashboards/sample-project.ifc');
const DWG_FIXTURE = path.resolve(__dirname, 'fixtures/dashboards/fake-drawing.dwg');

test.describe.configure({ mode: 'serial' });

async function ensureScreenshotDir(): Promise<void> {
  await fs.promises.mkdir(SCREENSHOT_DIR, { recursive: true });
}

async function shot(page: Page, name: string): Promise<void> {
  await ensureScreenshotDir();
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: true,
  });
}

async function injectAuth(page: Page): Promise<string> {
  const credentials = { email: 'test@openestimate.com', password: 'OpenEstimate2024!' };

  let loginRes = await page.request.post(`${BACKEND}/api/v1/users/auth/login/`, {
    data: credentials,
  });
  if (!loginRes.ok()) {
    await page.request.post(`${BACKEND}/api/v1/users/auth/register/`, {
      data: { ...credentials, full_name: 'T01 E2E' },
    });
    loginRes = await page.request.post(`${BACKEND}/api/v1/users/auth/login/`, {
      data: credentials,
    });
  }
  const body = await loginRes.json();
  const accessToken = body.access_token as string;
  const refreshToken = (body.refresh_token || body.access_token) as string;

  await page.addInitScript((tokens: { access: string; refresh: string }) => {
    localStorage.setItem('oe_access_token', tokens.access);
    localStorage.setItem('oe_refresh_token', tokens.refresh);
    localStorage.setItem('oe_remember', '1');
    localStorage.setItem('oe_user_email', 'test@openestimate.com');
    localStorage.setItem('oe_onboarding_completed', 'true');
    localStorage.setItem('oe_welcome_dismissed', 'true');
    localStorage.setItem('oe_tour_completed', 'true');
    sessionStorage.setItem('oe_access_token', tokens.access);
    sessionStorage.setItem('oe_refresh_token', tokens.refresh);
  }, { access: accessToken, refresh: refreshToken });

  return accessToken;
}

async function ensureProject(token: string, context: Page): Promise<string> {
  const res = await context.request.get(`${BACKEND}/api/v1/projects/`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.ok()) {
    const projects = await res.json();
    if (Array.isArray(projects) && projects.length > 0) {
      return projects[0].id;
    }
  }
  const created = await context.request.post(`${BACKEND}/api/v1/projects/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: 'Dashboards T01 Fixture',
      description: 'E2E project for snapshot registry tests',
      classification_standard: 'din276',
    },
  });
  const body = await created.json();
  return body.id;
}

async function pinProject(page: Page, projectId: string, projectName: string): Promise<void> {
  await page.addInitScript(
    ({ id, name }: { id: string; name: string }) => {
      localStorage.setItem(
        'oe_active_project',
        JSON.stringify({ id, name, boqId: null }),
      );
    },
    { id: projectId, name: projectName },
  );
}

let authToken = '';
let projectId = '';

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  authToken = await injectAuth(page);
  projectId = await ensureProject(authToken, page);
  // Clean any existing snapshots left over from a prior run so the empty
  // state assertion is deterministic.
  const list = await page.request.get(
    `${BACKEND}/api/v1/dashboards/projects/${projectId}/snapshots`,
    { headers: { Authorization: `Bearer ${authToken}` } },
  );
  if (list.ok()) {
    const body = await list.json();
    for (const item of body.items ?? []) {
      await page.request.delete(
        `${BACKEND}/api/v1/dashboards/snapshots/${item.id}`,
        { headers: { Authorization: `Bearer ${authToken}` } },
      );
    }
  }
  await ctx.close();
});

test('01 — empty state renders when no snapshots exist', async ({ page }) => {
  await injectAuth(page);
  await pinProject(page, projectId, 'Dashboards T01 Fixture');

  await page.goto(`/projects/${projectId}/dashboards`);
  await page.waitForLoadState('domcontentloaded');

  await expect(page.getByTestId('dashboards-snapshots-page')).toBeVisible();
  await expect(
    page.getByTestId('dashboards-empty-new-snapshot-btn'),
  ).toBeVisible({ timeout: 10_000 });

  await shot(page, '01-empty-state');
});

test('02 — IFC upload creates a snapshot visible in the list', async ({ page }) => {
  test.setTimeout(180_000); // IFC parse + Parquet write can take >60s on first run
  await injectAuth(page);
  await pinProject(page, projectId, 'Dashboards T01 Fixture');

  await page.goto(`/projects/${projectId}/dashboards`);
  await page.getByTestId('dashboards-empty-new-snapshot-btn').click();
  await expect(page.getByTestId('snapshot-create-modal')).toBeVisible();

  await page.getByTestId('snapshot-label-input').fill('IFC sample — E2E');
  await page.getByTestId('snapshot-file-input').setInputFiles(IFC_FIXTURE);

  await shot(page, '02a-modal-with-ifc');

  await page.getByTestId('snapshot-submit').click();

  await expect(page.getByTestId('snapshot-create-modal')).toBeHidden({
    timeout: 120_000,
  });
  await expect(page.getByText('IFC sample — E2E').first()).toBeVisible({
    timeout: 15_000,
  });

  await shot(page, '02b-ifc-snapshot-in-list');
});

test('03 — DWG upload rejected with unsupported-format toast', async ({ page }) => {
  await injectAuth(page);
  await pinProject(page, projectId, 'Dashboards T01 Fixture');

  await page.goto(`/projects/${projectId}/dashboards`);
  await page.getByTestId('dashboards-new-snapshot-btn').click();
  await page.getByTestId('snapshot-label-input').fill('DWG reject — E2E');
  await page.getByTestId('snapshot-file-input').setInputFiles(DWG_FIXTURE);
  await page.getByTestId('snapshot-submit').click();

  // Backend returns 422 with message_key=snapshot.format.unsupported —
  // the modal stays open and a toast flashes the translated message.
  await expect(
    page.locator('text=/unsupported|format/i').first(),
  ).toBeVisible({ timeout: 15_000 });

  await shot(page, '03-dwg-rejected');
});

test('04 — manifest endpoint returns data for the IFC snapshot', async ({ page }) => {
  const listRes = await page.request.get(
    `${BACKEND}/api/v1/dashboards/projects/${projectId}/snapshots`,
    { headers: { Authorization: `Bearer ${authToken}` } },
  );
  expect(listRes.ok()).toBeTruthy();
  const { items } = await listRes.json();
  const target = items.find((i: { label: string }) => i.label === 'IFC sample — E2E');
  expect(target).toBeTruthy();

  const manifestRes = await page.request.get(
    `${BACKEND}/api/v1/dashboards/snapshots/${target.id}/manifest`,
    { headers: { Authorization: `Bearer ${authToken}` } },
  );
  expect(manifestRes.ok()).toBeTruthy();
  const manifest = await manifestRes.json();
  expect(manifest.label).toBe('IFC sample — E2E');
  expect(typeof manifest.total_entities).toBe('number');
  expect(Array.isArray(manifest.source_files)).toBeTruthy();
});

test('05 — delete removes the snapshot from the list', async ({ page }) => {
  await injectAuth(page);
  await pinProject(page, projectId, 'Dashboards T01 Fixture');

  await page.goto(`/projects/${projectId}/dashboards`);

  const card = page.locator('[data-testid^="snapshot-card-"]').first();
  await expect(card).toBeVisible();
  await shot(page, '05a-before-delete');

  const deleteBtn = card.locator('[data-testid^="snapshot-delete-"]');
  await deleteBtn.click();

  // Card should disappear
  await expect(card).toBeHidden({ timeout: 10_000 });
  await shot(page, '05b-after-delete');
});
