/**
 * v1.9 R3 #9 + #12 — DWG UX polish.
 *
 * Combined spec for two items that both touch ``DwgTakeoffPage.tsx``:
 *   #9  Offline Ready badge on the DWG takeoff page + REST endpoint.
 *   #12 Summary tab redesign (4 KPI cards + layer / type breakdowns).
 *
 * The spec degrades gracefully in offline CI — individual scenarios are
 * skipped when prerequisites (project, seeded drawing) aren't available.
 */
import { test, expect } from '@playwright/test';
import { loginV19, firstProjectId } from './helpers-v19';

test.describe('v1.9 R3 #9 + #12 — DWG polish', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  // ── #9 Offline Ready badge ────────────────────────────────────────────

  test('Offline readiness endpoint returns the expected shape', async ({ page }) => {
    const res = await page.request.get(
      'http://localhost:8000/api/v1/dwg_takeoff/offline-readiness/',
    );
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty('ready');
    expect(body).toHaveProperty('converter_available');
    expect(body).toHaveProperty('version');
    expect(body).toHaveProperty('message');
    expect(typeof body.ready).toBe('boolean');
    expect(typeof body.converter_available).toBe('boolean');
    expect(typeof body.message).toBe('string');
  });

  test('Offline Ready badge is visible on the DWG takeoff page', async ({ page }) => {
    const projectId = await firstProjectId(page);
    test.skip(!projectId, 'no project available');

    await page.goto('/dwg-takeoff');
    await page.waitForLoadState('networkidle');

    // The badge lives either on the empty-state hero (no drawing selected)
    // or floating on the viewer (drawing selected). Either way the
    // data-testid is "dwg-offline-badge".
    const badge = page.getByTestId('dwg-offline-badge').first();
    await expect(badge).toBeVisible({ timeout: 15_000 });

    // It must display one of the two known labels from the OfflineReadyBadge.
    const text = (await badge.textContent()) ?? '';
    const recognised = /Offline Ready|Install converter|Checking/i.test(text);
    expect(recognised).toBeTruthy();
  });

  test('Clicking the Offline Ready badge opens the hint popover', async ({ page }) => {
    const projectId = await firstProjectId(page);
    test.skip(!projectId, 'no project available');

    await page.goto('/dwg-takeoff');
    await page.waitForLoadState('networkidle');

    const badge = page.getByTestId('dwg-offline-badge').first();
    await expect(badge).toBeVisible({ timeout: 15_000 });

    // Wait for the probe to complete so the button is no longer in the
    // loading state (the loading label doesn't render the hint popover).
    await expect(badge).not.toContainText('Checking', { timeout: 10_000 });

    await badge.locator('button').first().click();
    await expect(page.getByTestId('dwg-offline-hint')).toBeVisible();
  });

  // ── #12 Summary tab redesign ──────────────────────────────────────────

  test('Summary tab renders 4 KPI cards and layer breakdown', async ({ page }) => {
    const projectId = await firstProjectId(page);
    test.skip(!projectId, 'no project available');

    const drawingsRes = await page.request.get(
      `http://localhost:8000/api/v1/dwg_takeoff/drawings/?project_id=${projectId}`,
    );
    test.skip(!drawingsRes.ok(), 'drawings endpoint unavailable');

    const drawings = (await drawingsRes.json()) as Array<{ id: string }>;
    test.skip(drawings.length === 0, 'no seeded DWG drawing for summary scenario');

    await page.goto(`/dwg-takeoff?drawingId=${drawings[0]!.id}`);
    await page.waitForLoadState('networkidle');

    // The right panel has a Summary tab. Click it.
    const summaryTab = page.getByRole('button', { name: /Summary/i }).first();
    await expect(summaryTab).toBeVisible({ timeout: 15_000 });
    await summaryTab.click();

    // Body renders
    const body = page.getByTestId('dwg-summary-tab');
    await expect(body).toBeVisible();

    // 4 KPI cards
    const kpis = page.getByTestId('dwg-summary-kpi');
    await expect(kpis).toHaveCount(4);

    // By-layer and by-type sections exist
    await expect(page.getByTestId('dwg-summary-by-layer')).toBeVisible();
    await expect(page.getByTestId('dwg-summary-by-type')).toBeVisible();

    // Export button is present
    await expect(page.getByTestId('dwg-summary-export')).toBeVisible();
  });
});
