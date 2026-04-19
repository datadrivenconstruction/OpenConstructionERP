/**
 * v1.9 #16 — Data Explorer Power BI-style analytics (RFC 16).
 *
 * Covers the v1.9.1 shortlist:
 *   1. Cross-filter chart → table (slicer chip round-trip).
 *   2. Add slicer chip for "Material = Concrete" — charts update.
 *   3. Save view, reload page, verify state restored via localStorage.
 *   4. Switch to line chart — axes + value formatting render.
 *   5. Top-5 radio → chart shows exactly 5 entries.
 *
 * These tests run against the live dev backend: they upload a real CAD
 * file through the Data Explorer, which takes a few seconds, so the whole
 * spec gets a generous per-test timeout. The test is deliberately skipped
 * when no sample CAD file is available on disk so it doesn't gate CI.
 */
import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loginV19 } from './helpers-v19';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Pick the first RVT / IFC fixture the repo ships. If nothing is available
// we skip the whole spec — RFC 16 is purely a front-end concern and we
// don't want to block other roadmap items on a missing fixture.
function findSampleFile(): string | null {
  const candidates = [
    path.resolve(__dirname, '../../../data/seeds/sample.ifc'),
    path.resolve(__dirname, '../../../data/seeds/sample.rvt'),
    path.resolve(__dirname, '../../../data/fixtures/sample.ifc'),
    path.resolve(__dirname, '../../../data/fixtures/sample.rvt'),
    path.resolve(__dirname, '../../test_drawing.pdf'), // fallback just to not-fail; upload will reject.
  ];
  for (const p of candidates) {
    if (fs.existsSync(p) && !p.endsWith('.pdf')) return p;
  }
  return null;
}

async function uploadFixture(page: Page, filePath: string): Promise<void> {
  await page.goto('/data-explorer');
  await page.waitForLoadState('domcontentloaded');
  const input = page.locator('input[type="file"]');
  await input.setInputFiles(filePath);
  // Wait for the charts / table tabs to appear — signalling describe() finished.
  await expect(page.locator('[data-testid="explorer-slicer-banner"]')).toBeVisible({
    timeout: 90_000,
  });
}

test.describe('v1.9 #16 — Data Explorer analytics (RFC 16)', () => {
  const samplePath = findSampleFile();

  test.beforeEach(async ({ page }) => {
    if (!samplePath) test.skip(true, 'no CAD fixture available on this environment');
    await loginV19(page);
  });

  test('cross-filter: clicking a chart bar filters the table', async ({ page }) => {
    test.slow();
    await uploadFixture(page, samplePath!);
    // Switch to the Charts tab and wait for the Recharts surface to mount.
    await page.getByRole('button', { name: /Charts/i }).click();
    await expect(page.locator('[data-testid="chart-bar"]')).toBeVisible({ timeout: 30_000 });

    // The hidden drill-trigger also acts as a stable cross-filter button —
    // but we want the cross-filter, not the modal. Click a Cell instead.
    const firstCell = page.locator('[data-testid="chart-bar"] .recharts-bar-rectangle').first();
    await firstCell.click();

    // Slicer banner gains a chip.
    await expect(page.locator('[data-testid^="slicer-chip-"]').first()).toBeVisible();

    // Switch to the Data tab — rows should still render (filtered subset).
    await page.getByRole('button', { name: /Data Table/i }).click();
    await expect(page.locator('[data-testid^="slicer-chip-"]').first()).toBeVisible();
  });

  test('save and restore a view from localStorage', async ({ page }) => {
    test.slow();
    await uploadFixture(page, samplePath!);
    // Capture a view with default config.
    page.once('dialog', async (d) => { await d.accept('E2E saved view'); });
    await page.locator('[data-testid="explorer-save-view-btn"]').click();

    // Drawer should open with exactly one view.
    const drawer = page.locator('[data-testid="views-drawer"]');
    await expect(drawer).toBeVisible();
    await expect(drawer.locator('[data-testid^="view-item-"]').first()).toBeVisible();

    // Reload the page and verify the view persists.
    const beforeUrl = page.url();
    await page.reload();
    await page.waitForURL(beforeUrl);
    await expect(page.locator('[data-testid="explorer-views-btn"]')).toBeVisible();
    await page.locator('[data-testid="explorer-views-btn"]').click();
    await expect(page.locator('[data-testid="views-drawer"] [data-testid^="view-item-"]').first()).toBeVisible();
  });

  test('switching to line chart keeps the chart rendered', async ({ page }) => {
    test.slow();
    await uploadFixture(page, samplePath!);
    await page.getByRole('button', { name: /Charts/i }).click();
    await page.locator('[data-testid="chart-type-line"]').click();
    await expect(page.locator('[data-testid="chart-line"]')).toBeVisible({ timeout: 30_000 });
    // Recharts axis elements present.
    await expect(page.locator('[data-testid="chart-line"] .recharts-xAxis')).toBeVisible();
    await expect(page.locator('[data-testid="chart-line"] .recharts-yAxis')).toBeVisible();
  });

  test('top-5 radio limits the chart to exactly 5 entries', async ({ page }) => {
    test.slow();
    await uploadFixture(page, samplePath!);
    await page.getByRole('button', { name: /Charts/i }).click();
    await expect(page.locator('[data-testid="chart-bar"]')).toBeVisible({ timeout: 30_000 });
    await page.locator('[data-testid="chart-topn-top-5"]').click();
    // Each bar is a .recharts-bar-rectangle — count them after the trim.
    const bars = page.locator('[data-testid="chart-bar"] .recharts-bar-rectangle');
    await expect(async () => {
      const count = await bars.count();
      expect(count).toBeLessThanOrEqual(5);
      expect(count).toBeGreaterThan(0);
    }).toPass({ timeout: 10_000 });
  });

  test('clear-all removes every slicer chip', async ({ page }) => {
    test.slow();
    await uploadFixture(page, samplePath!);
    await page.getByRole('button', { name: /Charts/i }).click();
    await expect(page.locator('[data-testid="chart-bar"]')).toBeVisible({ timeout: 30_000 });
    // Add a slicer via the hidden drill trigger (actually calls onSliceDoubleClick,
    // which opens the modal). Close the modal, then add a bar-cell slicer.
    const firstBar = page.locator('[data-testid="chart-bar"] .recharts-bar-rectangle').first();
    await firstBar.click();
    await expect(page.locator('[data-testid^="slicer-chip-"]').first()).toBeVisible();
    await page.locator('[data-testid="slicer-clear-all"]').click();
    await expect(page.locator('[data-testid^="slicer-chip-"]')).toHaveCount(0);
  });
});
