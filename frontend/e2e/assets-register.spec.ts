/**
 * Smoke E2E for the Asset Register page (v2.3.0).
 *
 * Deliberately lean — only verifies the happy-path load of /assets against
 * a stubbed backend. Detailed interactions (filter, edit modal, PATCH
 * payload shape) are covered by ``AssetsPage.test.tsx`` in Vitest, which
 * runs deterministically against the same component without the race
 * conditions that come with a real browser + dev server.
 *
 * Uses a real project id fetched from the demo backend so the Header's
 * "does this project still exist" guard (see
 * ``app/layout/Header.tsx:592``) does not purge our active-project
 * selection.
 */
import { test, expect, type Page } from '@playwright/test';

const DEMO = { email: 'demo@openestimator.io', password: 'DemoPass1234!' };
const API = 'http://localhost:8000/api/v1';

let REAL_PROJECT_ID = '00000000-0000-0000-0000-000000000000';
let REAL_PROJECT_NAME = 'Demo';

function buildAssets(projectId: string) {
  return {
    siemens: {
      id: '22222222-2222-2222-2222-222222222222',
      stable_id: 'AHU-01',
      element_type: 'AirHandlingUnit',
      name: 'Rooftop AHU-01',
      model_id: '33333333-3333-3333-3333-333333333333',
      model_name: 'Mechanical.rvt',
      project_id: projectId,
      asset_info: {
        manufacturer: 'Siemens',
        model: 'SV-100',
        serial_number: 'SN-123',
        operational_status: 'operational',
        warranty_until: '2028-01-01',
      },
    },
    grundfos: {
      id: '44444444-4444-4444-4444-444444444444',
      stable_id: 'PUMP-12',
      element_type: 'Pump',
      name: 'Chilled-water pump 12',
      model_id: '33333333-3333-3333-3333-333333333333',
      model_name: 'Mechanical.rvt',
      project_id: projectId,
      asset_info: {
        manufacturer: 'Grundfos',
        model: 'CR-5',
        operational_status: 'under_maintenance',
      },
    },
  };
}

async function injectAuth(page: Page): Promise<void> {
  const loginRes = await page.request.post(`${API}/users/auth/login/`, { data: DEMO });
  const body = await loginRes.json();
  const access = body.access_token;
  const refresh = body.refresh_token || access;

  await page.addInitScript(
    (args: { access: string; refresh: string; projectId: string; projectName: string }) => {
      try {
        localStorage.setItem('oe_access_token', args.access);
        localStorage.setItem('oe_refresh_token', args.refresh);
        localStorage.setItem('oe_remember', '1');
        localStorage.setItem('oe_user_email', 'demo@openestimator.io');
        localStorage.setItem('oe_onboarding_completed', 'true');
        localStorage.setItem('oe_welcome_dismissed', 'true');
        localStorage.setItem('oe_tour_completed', 'true');
        sessionStorage.setItem('oe_access_token', args.access);
        sessionStorage.setItem('oe_refresh_token', args.refresh);
        localStorage.setItem(
          'oe_active_project',
          JSON.stringify({ id: args.projectId, name: args.projectName, boqId: null }),
        );
      } catch {
        // localStorage unavailable before first navigation establishes
        // origin — later addInitScript firings will succeed.
      }
    },
    { access, refresh, projectId: REAL_PROJECT_ID, projectName: REAL_PROJECT_NAME },
  );
}

test.describe('Asset Register', () => {
  test.beforeAll(async ({ request }) => {
    const loginRes = await request.post(`${API}/users/auth/login/`, { data: DEMO });
    const { access_token } = await loginRes.json();
    const projectsRes = await request.get(`${API}/projects/`, {
      headers: { Authorization: `Bearer ${access_token}` },
    });
    const body = await projectsRes.json();
    const items: { id: string; name: string }[] = Array.isArray(body) ? body : body.items;
    if (!items?.length) throw new Error('No demo projects to use as E2E fixture');
    REAL_PROJECT_ID = items[0].id;
    REAL_PROJECT_NAME = items[0].name;
  });

  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    const assets = buildAssets(REAL_PROJECT_ID);
    await page.route('**/v1/bim_hub/assets/**', async (route) => {
      const url = route.request().url();
      const wantsMaintenance = url.includes('operational_status=under_maintenance');
      const items = wantsMaintenance ? [assets.grundfos] : [assets.siemens, assets.grundfos];
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items, total: items.length }),
      });
    });
  });

  test('lists tracked assets for the active project', async ({ page }) => {
    const assets = buildAssets(REAL_PROJECT_ID);

    // Warm-up: hit /projects first so Header's projects query resolves
    // and its "clear stale project" effect runs before we land on /assets.
    await page.goto('/projects');
    await page.waitForLoadState('networkidle');
    await page.goto('/assets');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('asset-table')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId(`asset-row-${assets.siemens.id}`)).toBeVisible();
    await expect(page.getByTestId(`asset-row-${assets.grundfos.id}`)).toBeVisible();
    await expect(page.getByText('Siemens')).toBeVisible();
    await expect(page.getByText('Grundfos')).toBeVisible();

    // Confirm the COBie-download link is wired up for the row's model.
    const cobieLink = page.getByRole('link', { name: /COBie/i }).first();
    await expect(cobieLink).toHaveAttribute('href', /export\/cobie\.xlsx/);
  });
});
