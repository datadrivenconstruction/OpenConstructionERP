/**
 * v1.9 #5 + #6 — offline-first query behaviour.
 *
 * Regression targets:
 *  - frontend/src/main.tsx  (global QueryClient: networkMode: 'offlineFirst',
 *                            navigator.onLine retry guard)
 *  - frontend/src/features/projects/ProjectDetailPage.tsx
 *    (ApiError 404 distinction — offline/5xx shows "can't reach server",
 *    true 404 shows "not found" and clears stale recents)
 *
 * We don't need to validate the full IndexedDB persistence path here —
 * offlineStore.ts is covered by its own unit tests. What we verify is:
 *   a) going offline mid-session does NOT produce the old
 *      `AbortError: signal is aborted without reason` user-facing error
 *   b) hitting /projects/<bad-uuid> shows "Project not found" (true 404 path)
 */
import { test, expect } from '@playwright/test';
import { loginV19 } from './helpers-v19';

test.describe('v1.9 #5 — BOQ list does not hang with AbortError when offline', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  test('going offline on /boq does not surface "signal is aborted" to the user', async ({
    page,
    context,
  }) => {
    await page.goto('/boq');
    await page.waitForLoadState('networkidle');

    // Capture all console errors during the offline transition.
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await context.setOffline(true);
    // Give React Query and any pending fetches a chance to settle into
    // the offline branch of shared/lib/api.ts.
    await page.waitForTimeout(2000);

    // The specific symptom the user reported was an "AbortError: signal is
    // aborted without reason" error. With networkMode: 'offlineFirst' and
    // the retry guard, that error should no longer be thrown.
    const aborts = errors.filter((e) => /signal is aborted without reason/i.test(e));
    expect(aborts).toEqual([]);

    await context.setOffline(false);
  });
});

test.describe('v1.9 #6 — project-not-found vs network error distinction', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  test('unknown project id renders the "Project not found" empty state (true 404 path)', async ({
    page,
  }) => {
    // Deliberately invalid UUID — the backend returns 404.
    await page.goto('/projects/00000000-0000-0000-0000-000000000000');
    await page.waitForLoadState('networkidle');

    const notFound = page.locator('text=/project\\s+not\\s+found/i');
    await expect(notFound).toBeVisible({ timeout: 10_000 });
  });

  test('network error on project fetch shows retry UI, not "not found"', async ({
    page,
  }) => {
    // Intercept just the single project-detail fetch and force a network
    // failure — keeps the app shell reachable (Vite dev has no SW yet) while
    // exercising the offline/5xx branch of ProjectDetailPage.tsx.
    const targetId = '11111111-1111-1111-1111-111111111111';
    await page.route(`**/api/v1/projects/${targetId}`, (route) => route.abort('failed'));

    await page.goto(`/projects/${targetId}`);
    await page.waitForTimeout(2500);

    // Must NOT show the "Project not found" copy — that branch clears
    // sidebar recents, which is wrong when the project might still exist.
    const notFoundCount = await page.locator('text=/project\\s+not\\s+found/i').count();
    expect(notFoundCount).toBe(0);

    // Should show a retry button (either offline or server-error UI path).
    const retryBtn = page.locator('button', { hasText: /retry/i });
    await expect(retryBtn).toBeVisible({ timeout: 8_000 });
  });
});
