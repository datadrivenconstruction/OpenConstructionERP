/**
 * E2E: the Markups hub shows markups created in every source module.
 *
 * Scenario:
 *   1. Log in + guarantee a project exists.
 *   2. Upload a small DXF so we have a real ``drawing_id``, then create
 *      a DWG annotation against that drawing via the REST API.
 *   3. Create a Markups-hub record directly against ``/v1/markups/``.
 *   4. Navigate to ``/markups`` → assert the unified feed lists both with
 *      the correct source labels and file names.
 *   5. Capture a screenshot of the populated unified table.
 *
 * This is the contract promised by the unified aggregator: "create a
 * markup in DWG, switch to /markups, see it listed".
 */

import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname_esm = path.dirname(fileURLToPath(import.meta.url));
const DXF_FIXTURE = path.resolve(__dirname_esm, 'fixtures', 'test.dxf');

/* ── Auth & project helpers ──────────────────────────────────────────── */

const E2E_USER = {
  email: process.env.V19_E2E_EMAIL ?? 'v19-e2e@openestimate.com',
  password: process.env.V19_E2E_PASSWORD ?? 'OpenEstimate2024!',
  full_name: 'v1.9 E2E User',
};

async function getAccessToken(request: APIRequestContext): Promise<string> {
  const login = async () =>
    request.post('http://localhost:8000/api/v1/users/auth/login/', {
      data: { email: E2E_USER.email, password: E2E_USER.password },
      failOnStatusCode: false,
    });
  let res = await login();
  if (!res.ok()) {
    await request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: E2E_USER,
      failOnStatusCode: false,
    });
    res = await login();
  }
  expect(res.ok(), `login failed: ${res.status()}`).toBe(true);
  const body = await res.json();
  return body.access_token as string;
}

async function ensureProject(
  request: APIRequestContext,
  token: string,
): Promise<{ id: string; name: string }> {
  const listRes = await request.get('http://localhost:8000/api/v1/projects/', {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (listRes.ok()) {
    const projects = (await listRes.json()) as Array<{ id: string; name: string }>;
    if (projects.length > 0) return { id: projects[0]!.id, name: projects[0]!.name };
  }
  const createRes = await request.post('http://localhost:8000/api/v1/projects/', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: 'Unified Markups E2E',
      description: 'Auto-created for markups-unified spec',
      currency: 'EUR',
    },
  });
  expect(createRes.ok(), `project create failed: ${createRes.status()}`).toBe(true);
  const body = await createRes.json();
  return { id: body.id as string, name: body.name as string };
}

async function injectAuth(page: Page, token: string): Promise<void> {
  await page.addInitScript(
    (t: { access: string; email: string }) => {
      localStorage.setItem('oe_access_token', t.access);
      localStorage.setItem('oe_refresh_token', t.access);
      localStorage.setItem('oe_remember', '1');
      localStorage.setItem('oe_user_email', t.email);
      localStorage.setItem('oe_onboarding_completed', 'true');
      localStorage.setItem('oe_welcome_dismissed', 'true');
      localStorage.setItem('oe_tour_completed', 'true');
      sessionStorage.setItem('oe_access_token', t.access);
      sessionStorage.setItem('oe_refresh_token', t.access);
    },
    { access: token, email: E2E_USER.email },
  );
}

/* ── Test ────────────────────────────────────────────────────────────── */

test.describe.configure({ mode: 'serial' });

test.describe('Markups hub — unified feed', () => {
  test('DWG annotation + hub markup both appear in the unified list', async ({
    page,
    request,
  }) => {
    test.skip(!fs.existsSync(DXF_FIXTURE), 'DXF fixture missing');

    const token = await getAccessToken(request);
    const project = await ensureProject(request, token);

    const authHeaders = { Authorization: `Bearer ${token}` };

    // 1. Upload a DXF so we have a real drawing_id.
    const uploadRes = await request.post(
      `http://localhost:8000/api/v1/dwg_takeoff/drawings/upload/?project_id=${project.id}&name=Unified%20E2E%20Drawing&discipline=architecture`,
      {
        headers: authHeaders,
        multipart: {
          file: {
            name: 'unified-e2e.dxf',
            mimeType: 'application/dxf',
            buffer: fs.readFileSync(DXF_FIXTURE),
          },
        },
      },
    );
    expect(uploadRes.ok(), `DXF upload failed: ${uploadRes.status()}`).toBe(true);
    const drawing = (await uploadRes.json()) as { id: string; name: string };

    // Give the backend a moment to finish the parse so the drawing is listable.
    await new Promise((r) => setTimeout(r, 1500));

    // 2. DWG annotation.
    const dwgAnnRes = await request.post(
      'http://localhost:8000/api/v1/dwg_takeoff/annotations/',
      {
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        data: {
          project_id: project.id,
          drawing_id: drawing.id,
          annotation_type: 'arrow',
          geometry: { points: [{ x: 0, y: 0 }, { x: 100, y: 0 }] },
          text: 'Unified DWG arrow',
          color: '#ef4444',
          line_width: 2,
          thickness: 2,
        },
      },
    );
    expect(dwgAnnRes.ok(), `DWG annotation create failed: ${dwgAnnRes.status()}`).toBe(true);

    // 3. Markups hub record.
    const hubRes = await request.post('http://localhost:8000/api/v1/markups/', {
      headers: { ...authHeaders, 'Content-Type': 'application/json' },
      data: {
        project_id: project.id,
        type: 'cloud',
        label: 'Unified HUB cloud',
        text: 'Hub-side marker',
        color: '#3b82f6',
        geometry: {},
      },
    });
    expect(hubRes.ok(), `Hub markup create failed: ${hubRes.status()}`).toBe(true);

    // 4. Navigate to the Markups page and assert both show up.
    await injectAuth(page, token);
    await page.goto('/markups');
    await page.waitForLoadState('load');

    // Select the right project if the default isn't ours.
    const projectSelect = page.locator('select').first();
    if (await projectSelect.isVisible().catch(() => false)) {
      try {
        await projectSelect.selectOption(project.id);
      } catch {
        /* already selected */
      }
    }

    // Force the unified tab (it's the default but be explicit in case the
    // user has previously toggled to hub-only).
    const unifiedTab = page.locator('[data-testid="markups-tab-unified"]');
    await unifiedTab.click();

    const table = page.locator('[data-testid="unified-markups-table"]');
    await expect(table).toBeVisible({ timeout: 10_000 });

    // DWG row
    await expect(table.locator('tr[data-source="dwg_takeoff"]').first()).toBeVisible({
      timeout: 10_000,
    });
    // Hub row
    await expect(table.locator('tr[data-source="markups_hub"]').first()).toBeVisible({
      timeout: 10_000,
    });

    // Label cells contain the expected text.
    await expect(table).toContainText('Unified DWG arrow');
    await expect(table).toContainText('Unified HUB cloud');
    // Drawing name should show up as the file name for the DWG row.
    await expect(
      table.locator('tr[data-source="dwg_takeoff"]').first(),
    ).toContainText('Unified E2E Drawing');

    // Filter chip: click "DWG takeoff" → only DWG rows remain.
    await page.locator('[data-testid="unified-filter-source-dwg_takeoff"]').click();
    await expect(
      table.locator('tr[data-source="markups_hub"]'),
    ).toHaveCount(0, { timeout: 5_000 });
    await expect(
      table.locator('tr[data-source="dwg_takeoff"]').first(),
    ).toBeVisible();

    // Clear filters so the screenshot shows the unified feed.
    await page.locator('[data-testid="unified-filter-source-dwg_takeoff"]').click();

    await page.screenshot({ path: 'test-results/markups-unified.png', fullPage: true });
  });
});
