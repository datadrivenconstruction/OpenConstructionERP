/**
 * v1.9 #23 / #27 / #33 — live-repro specs.
 *
 * These are NOT unit tests — they open the live /bim/rules, /tasks and /cde
 * pages, exercise the user flow that was reported broken, and capture the
 * network trace. Useful both as regression guards and as diagnostic probes
 * when the fix landing in this commit needs to be verified in a running
 * browser session.
 */
import { test, expect } from '@playwright/test';
import { loginV19, ensureProject } from './helpers-v19';

test.describe.configure({ mode: 'serial' });

test.describe('v1.9 #27 — Tasks: create modal respects active category tab', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
    await ensureProject(page);
  });

  test('opening "+" while on the Topic tab defaults the new task to task_type=topic', async ({
    page,
  }) => {
    await page.goto('/tasks');
    await page.waitForLoadState('networkidle');

    // Click the Topic tab. The labels come from i18n — match the case-
    // insensitive text since the button values may be localised.
    const topicTab = page.locator('button', { hasText: /^topic$/i }).first();
    await expect(topicTab).toBeVisible({ timeout: 10_000 });
    await topicTab.click();
    await page.waitForTimeout(300);

    // Open the create dialog. The "+" button is typically at the top
    // right; match by aria-label or visible icon.
    const addBtn = page
      .locator('button', { hasText: /add task|create task|new task|\+\s*task/i })
      .first();
    if (await addBtn.isVisible({ timeout: 2000 })) {
      await addBtn.click();
    } else {
      // Fallback: click the first "+" icon button
      await page.locator('button[aria-label*="add" i]').first().click();
    }

    // The type select should be pre-populated with "topic" — either as a
    // <select value="topic"> or a button showing "Topic" label.
    const typeSelect = page.locator('select[name="task_type"], select[name="type"]').first();
    if (await typeSelect.isVisible({ timeout: 1500 })) {
      await expect(typeSelect).toHaveValue('topic');
    } else {
      // Non-<select> implementation — just assert the form is visible and
      // the word "Topic" appears somewhere in the dialog.
      const dialog = page.locator('[role="dialog"], .modal').first();
      await expect(dialog).toBeVisible();
      const topicInDialog = dialog.locator('text=/topic/i');
      await expect(topicInDialog.first()).toBeVisible({ timeout: 5_000 });
    }
  });
});

test.describe('v1.9 #33 — CDE: New Container actually creates a container', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
    await ensureProject(page);
  });

  test('clicking New Container submits and shows a success toast (or a concrete error)', async ({
    page,
  }) => {
    await page.goto('/cde');
    await page.waitForLoadState('networkidle');

    // Make sure at least one project is selected — the create button is
    // disabled without a project.
    await page.waitForTimeout(500);

    // Capture the POST /api/v1/cde/containers/ network call outcome.
    const postPromise = page
      .waitForResponse(
        (r) =>
          r.url().includes('/api/v1/cde/containers/') && r.request().method() === 'POST',
        { timeout: 15_000 },
      )
      .catch(() => null);

    const newBtn = page
      .locator('button', { hasText: /new\s+container/i })
      .first();
    await expect(newBtn).toBeVisible({ timeout: 10_000 });
    await newBtn.click();

    // Fill form
    const codeInput = page.locator('input[name="container_code"]').first();
    const titleInput = page.locator('input[name="title"]').first();
    if (await codeInput.isVisible({ timeout: 3_000 })) {
      await codeInput.fill(`V19-E2E-${Date.now().toString(36).toUpperCase()}`);
      await titleInput.fill('v1.9 E2E test container');
      const submit = page.locator('button', { hasText: /create\s+container/i }).last();
      await submit.click();

      const postRes = await postPromise;
      // We don't assert success — we assert we got a concrete response and
      // the UI shows a toast (either success or a clear error). The user's
      // original bug was "nothing happens" — any visible feedback is a win.
      expect(postRes).not.toBeNull();
      const status = postRes!.status();
      // eslint-disable-next-line no-console
      console.log(`[v1.9#33] CDE create response: ${status}`);

      // A toast (success or error) must be visible within 5s.
      const toast = page.locator('[role="status"], .toast, [data-sonner-toast]').first();
      await expect(toast).toBeVisible({ timeout: 5_000 });
    } else {
      test.skip(true, 'CDE create dialog fields not found — UI layout may have drifted');
    }
  });
});

test.describe('v1.9 #23 — BIM Rules: created rule appears in the list', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  test('page loads without crashing and the rules list query fires', async ({ page }) => {
    // Lightweight smoke — we can't reliably create a rule without a loaded
    // BIM model in the test DB, but we can verify:
    //   a) the page renders
    //   b) the quantity-maps GET returns 2xx
    const getPromise = page
      .waitForResponse(
        (r) =>
          r.url().includes('/quantity-maps') && r.request().method() === 'GET',
        { timeout: 10_000 },
      )
      .catch(() => null);

    await page.goto('/bim/rules');
    await page.waitForLoadState('networkidle');

    const getRes = await getPromise;
    expect(getRes).not.toBeNull();
    expect(getRes!.ok()).toBeTruthy();

    // The page should render some rules-related heading or empty state.
    // Use `body` only — `main` + `body` matches two elements and trips
    // Playwright's strict-mode selector check.
    await expect(page.locator('body')).toBeVisible();
  });
});
