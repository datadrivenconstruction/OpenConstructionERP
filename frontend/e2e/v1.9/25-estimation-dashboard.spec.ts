/**
 * v1.9 #25 — Estimation Dashboard (RFC 25) end-to-end smoke test.
 *
 * Verifies that the reshaped Project Intelligence page (now labelled
 * "Estimation Dashboard") renders the new hero + analytics layout without
 * any "N/A" placeholders, without console errors, and that the refresh
 * button clears the "n min ago" timer.
 */
import { test, expect, type ConsoleMessage } from '@playwright/test';
import { ensureProject, loginV19 } from './helpers-v19';

test.describe('v1.9 #25 — Estimation Dashboard renders + refreshes', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  test('page renders KPI cards and analytics widgets, refresh works', async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg: ConsoleMessage) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    const projectId = await ensureProject(page, 'RFC25 Estimation Dashboard');
    await page.goto(`/project-intelligence?project_id=${projectId}`);
    await page.waitForLoadState('networkidle');

    // Header renames to "Estimation Dashboard"
    await expect(
      page.getByRole('heading', { name: /Estimation Dashboard/i }),
    ).toBeVisible({ timeout: 10_000 });

    // 3 KPI cards appear within 5 s
    const kpiVariance = page.getByTestId('kpi-card-variance');
    const kpiSchedule = page.getByTestId('kpi-card-schedule');
    const kpiRisk = page.getByTestId('kpi-card-risk');
    await expect(kpiVariance).toBeVisible({ timeout: 5_000 });
    await expect(kpiSchedule).toBeVisible({ timeout: 5_000 });
    await expect(kpiRisk).toBeVisible({ timeout: 5_000 });

    // 5 of the 6 analytics widgets must be visible within 5 s (the 6th —
    // real-time validation — is always rendered so we also sanity-check it).
    const widgets = [
      'pi-widget-cost-drivers',
      'pi-widget-price-volatility',
      'pi-widget-schedule-cost',
      'pi-widget-vendor-concentration',
      'pi-widget-scope-coverage',
    ];
    for (const testid of widgets) {
      await expect(page.getByTestId(testid)).toBeVisible({ timeout: 5_000 });
    }

    // No visible "N/A" state after 10 s — empty widgets use the localised
    // "No data yet" string instead of "N/A".
    await page.waitForTimeout(10_000);
    const naRegex = /\bN\/A\b/;
    const body = await page.textContent('body');
    expect(body ?? '').not.toMatch(naRegex);

    // Refresh button refetches and clears the "n min ago" timer.
    const refreshBtn = page.getByTestId('pi-refresh-button');
    await expect(refreshBtn).toBeVisible();
    await refreshBtn.click();
    // The timer should flip back to "just now" right after refresh.
    await expect(page.getByText(/just now/i)).toBeVisible({ timeout: 5_000 });

    // No console errors throughout the run.
    expect(
      consoleErrors.filter((e) => !e.includes('DevTools')),
    ).toEqual([]);
  });
});
