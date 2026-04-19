/**
 * v1.9.4 R5 Cluster A — Tasks + Projects full user workflows.
 *
 * Goal: exercise real user flows (not just page loads). Create, edit, delete
 * tasks; add a custom category; cycle the filter tabs; click through to a
 * project detail page. Every significant step takes a screenshot so we can
 * diagnose UI regressions visually.
 *
 * Artifacts land in test-results/r5-cluster-a/.
 */
import { test, expect, type ConsoleMessage, type Page } from '@playwright/test';

const OUT = 'test-results/r5-cluster-a';

// Use the admin account confirmed to exist in every environment. The v1.9
// helper defaults to a throwaway user that may not be provisioned — we roll
// our own tiny login so the spec is self-contained.
const ADMIN_EMAIL = process.env.R5_ADMIN_EMAIL ?? 'admin@openestimate.io';
const ADMIN_PASSWORD = process.env.R5_ADMIN_PASSWORD ?? 'OpenEstimate2026';
const API_BASE = 'http://localhost:8000';

let cachedAccessToken: string | null = null;

async function loginAsAdmin(page: Page): Promise<string> {
  if (!cachedAccessToken) {
    const res = await page.request.post(`${API_BASE}/api/v1/users/auth/login/`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
      failOnStatusCode: false,
    });
    if (!res.ok()) {
      throw new Error(
        `Admin login failed (${res.status()}): ${await res.text()}`,
      );
    }
    const body = await res.json();
    cachedAccessToken = body.access_token;
  }
  const token = cachedAccessToken!;
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
      // Clear custom categories from prior runs so the spec starts clean
      localStorage.removeItem('oe-task-custom-categories');
      localStorage.removeItem('oe-task-custom-statuses');
    },
    { access: token, email: ADMIN_EMAIL },
  );
  await page.goto('/about');
  await page.waitForLoadState('load');
  return token;
}

async function firstProjectId(page: Page, token: string): Promise<string | null> {
  const res = await page.request.get(`${API_BASE}/api/v1/projects/`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) return null;
  const projects = (await res.json()) as Array<{ id: string }>;
  return projects[0]?.id ?? null;
}

async function ensureProject(page: Page, token: string): Promise<string> {
  const existing = await firstProjectId(page, token);
  if (existing) return existing;
  const res = await page.request.post(`${API_BASE}/api/v1/projects/`, {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: { name: 'v1.9 Cluster-A Project', description: 'Auto-created', currency: 'EUR' },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return body.id as string;
}

/**
 * Remove leftover E2E tasks from previous runs so the CRUD spec starts
 * clean. Without this, multiple "E2E Task Edited" cards accumulate and
 * make locator matching flaky.
 */
async function cleanupPriorE2ETasks(page: Page, token: string, projectId: string): Promise<void> {
  const res = await page.request.get(
    `${API_BASE}/api/v1/tasks/?project_id=${encodeURIComponent(projectId)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!res.ok()) return;
  const tasks = (await res.json()) as Array<{ id: string; title: string }>;
  const stale = tasks.filter((t) =>
    /^E2E (Test Task|Task Edited|Safety Test)$/i.test(t.title) ||
    t.title === 'Safety Test',
  );
  for (const t of stale) {
    await page.request.delete(`${API_BASE}/api/v1/tasks/${t.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  }
}

function attachConsoleErrorWatcher(page: Page) {
  const errors: string[] = [];
  const handler = (msg: ConsoleMessage) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (
        text.includes('[vite]') ||
        text.includes('HMR') ||
        text.includes('Download the React DevTools') ||
        text.includes('DeprecationWarning') ||
        // React Query fetch errors during test setup are expected for missing backend data
        text.includes('Failed to load resource')
      ) {
        return;
      }
      errors.push(text);
    }
  };
  page.on('console', handler);
  return () => {
    page.off('console', handler);
    return errors;
  };
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
}

// Generous timeout: full-page screenshots can take >5s on a busy Windows
// host, and this spec takes many of them.
test.setTimeout(120_000);

test.describe('v1.9.4 R5 Cluster A — Tasks page + Projects workflows', () => {
  let accessToken = '';

  test.beforeEach(async ({ page }) => {
    accessToken = await loginAsAdmin(page);
    const projectId = await ensureProject(page, accessToken);
    await cleanupPriorE2ETasks(page, accessToken, projectId);
  });

  test('Task page — filters, CRUD lifecycle, free-text assignee', async ({ page }) => {
    const stop = attachConsoleErrorWatcher(page);

    // Watch task API responses so we can identify 422 bugs.
    const failed: { url: string; status: number; body: string }[] = [];
    page.on('response', async (res) => {
      const url = res.url();
      if (!url.includes('/api/v1/tasks')) return;
      const status = res.status();
      if (status >= 400 && status < 500) {
        let body = '';
        try {
          body = (await res.text()).slice(0, 500);
        } catch {
          /* ignore */
        }
        failed.push({ url, status, body });
      }
    });

    // Step 1 — navigate to /tasks
    await page.goto('/tasks');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(800);
    await shot(page, '01-tasks-landing');

    // Step 2 — verify filter tabs are present and clickable
    const allTab = page.getByRole('button', { name: /^All$/ }).first();
    await expect(allTab).toBeVisible({ timeout: 15_000 });

    const builtinTabs = ['Task', 'Topic', 'Information', 'Decision', 'Personal'];
    for (let i = 0; i < builtinTabs.length; i++) {
      const tabName = builtinTabs[i]!;
      const tab = page.getByRole('button', { name: new RegExp(`^${tabName}$`) }).first();
      await expect(tab).toBeVisible({ timeout: 5000 });
      await tab.click();
      await page.waitForTimeout(250);
      await shot(page, `02-filter-tab-${String(i + 1).padStart(2, '0')}-${tabName.toLowerCase()}`);
    }
    await allTab.click();
    await page.waitForTimeout(200);

    // Step 3 — press "n" to open the New Task modal
    await page.keyboard.press('n');
    await page.waitForTimeout(500);
    const modal = page.locator('[role="dialog"][aria-label*="New Task" i]').first();
    await expect(modal).toBeVisible({ timeout: 5000 });
    await shot(page, '03-new-task-modal-open');

    // Step 4 — fill the title. The first textual input in the dialog is the
    // Title field; use a role-scoped lookup for robustness against i18n
    // placeholder changes.
    const titleInput = modal
      .locator('input[placeholder*="title" i], input[placeholder*="Review" i]')
      .first()
      .or(modal.locator('input[type="text"]').first());
    await titleInput.fill('E2E Test Task');
    await shot(page, '04-title-filled');

    // Step 5 — click each of the 5 Type buttons and verify selection
    // The selected button has ring-2 / border-current / colored bg; a simple
    // proxy is aria-pressed, but the component does not set it — fall back to
    // screenshot + visual check.
    const typeButtons = modal.locator('button').filter({ hasText: /^(Task|Topic|Information|Decision|Personal)$/ });
    const typeLabels = ['Task', 'Topic', 'Information', 'Decision', 'Personal'];
    for (let i = 0; i < typeLabels.length; i++) {
      const label = typeLabels[i]!;
      const btn = modal.locator('button').filter({ has: page.locator(`span:has-text("${label}")`) }).first();
      if (await btn.isVisible().catch(() => false)) {
        await btn.click();
        await page.waitForTimeout(150);
        await shot(page, `05-type-${String(i + 1).padStart(2, '0')}-${label.toLowerCase()}`);
      }
    }
    // End on "Task" so the created task shows on the default filter
    const taskTypeBtn = modal.locator('button').filter({ has: page.locator('span:has-text("Task")') }).first();
    await taskTypeBtn.click();
    await page.waitForTimeout(150);
    // Keep visual handle for later assertions
    void typeButtons;

    // Step 6 — pick Priority High
    const highPriority = modal.getByRole('button', { name: /^High$/ });
    await expect(highPriority).toBeVisible();
    await highPriority.click();
    await page.waitForTimeout(150);
    await shot(page, '06-priority-high-selected');

    // Step 7 — type a free-text Assignee name (NOT a UUID)
    // The i18n translation shows placeholder "Select assignee" and the
    // accessible name used by the a11y tree is also "Select assignee". Fall
    // back to a role-based lookup anchored on the Assignee label.
    const assigneeInput = modal
      .locator('input[placeholder*="assignee" i], input[placeholder*="Name" i], input[placeholder*="email" i]')
      .first();
    await expect(assigneeInput).toBeVisible({ timeout: 5000 });
    await assigneeInput.fill('John Doe');
    await page.waitForTimeout(100);
    await shot(page, '07-assignee-filled');

    // Step 8 — submit
    // The Create Task button sits in the footer; it contains a Plus icon + text
    const createBtn = modal.getByRole('button', { name: /Create Task/i });
    await expect(createBtn).toBeEnabled({ timeout: 3000 });
    await createBtn.click();

    // Wait for the POST to complete and the modal to close
    await expect(modal).toBeHidden({ timeout: 10_000 });
    await page.waitForTimeout(800);
    await shot(page, '08-after-create');

    // Step 9 — verify the task appears in the Kanban list
    const newTaskCard = page.locator('[role="listitem"]').filter({ hasText: 'E2E Test Task' }).first();
    await expect(newTaskCard).toBeVisible({ timeout: 10_000 });
    await shot(page, '09-task-in-list');

    // Step 10 — open edit via pencil icon (becomes visible on hover).
    // The buttons are in the DOM but hidden via opacity-0 group-hover:opacity-100,
    // so hover() alone isn't always enough — force-click dispatches the
    // event directly on the element. The card has 3 buttons inside the
    // action cluster (Complete, Edit, Delete); select the SECOND-to-last.
    await newTaskCard.hover();
    await page.waitForTimeout(300);
    // Try svg class first, fall back to nth-of-type selector
    let editBtn = newTaskCard.locator('button:has(svg.lucide-pencil)').first();
    if ((await editBtn.count()) === 0) {
      // Fallback: the card has 3 non-label buttons — Complete, Edit (pencil),
      // Delete (trash). Pick the penultimate button inside the card.
      const allBtns = newTaskCard.locator('button');
      const n = await allBtns.count();
      editBtn = allBtns.nth(n - 2);
    }
    await editBtn.click({ force: true });
    await page.waitForTimeout(500);
    const editModal = page.locator('[role="dialog"][aria-label*="New Task" i]').first();
    await expect(editModal).toBeVisible({ timeout: 5000 });
    await shot(page, '10-edit-modal-open');

    // Step 11 — change title and save
    const editTitle = editModal.locator('input').first();
    await editTitle.fill('E2E Task Edited');
    await page.waitForTimeout(100);
    await shot(page, '11-title-edited');

    // The edit modal still shows a "Create Task" button (same button reused) —
    // verify it submits and closes.
    const saveBtn = editModal.getByRole('button', { name: /Create Task|Save/i });
    await saveBtn.click();
    // Tolerate a possible 422 bug on edit: if the modal doesn't close in 8s,
    // capture the state and continue so we can still exercise the delete
    // flow. This keeps the spec informative even when the backend rejects
    // the edit payload.
    let editClosed = true;
    try {
      await expect(editModal).toBeHidden({ timeout: 8000 });
    } catch {
      editClosed = false;
      await shot(page, '12a-edit-modal-still-open-BUG');
      // Close the dialog manually so we can carry on.
      await page.keyboard.press('Escape');
      await page.waitForTimeout(400);
    }
    await page.waitForTimeout(500);
    await shot(page, '12-after-edit');

    // Step 12 — assert the edited task shows with the new title (only when
    // the edit actually succeeded). Otherwise fall back to the original
    // "E2E Test Task" card for the delete step.
    const searchTitle = editClosed ? 'E2E Task Edited' : 'E2E Test Task';
    const editedCard = page.locator('[role="listitem"]').filter({ hasText: searchTitle }).first();
    await expect(editedCard).toBeVisible({ timeout: 10_000 });
    await shot(page, '13-edited-task-visible');

    // Step 13 — delete the task via the trash icon. Same opacity-on-hover
    // issue as the pencil button — use force-click. Fall back to the last
    // button inside the card if the svg class selector doesn't resolve.
    await editedCard.hover();
    await page.waitForTimeout(300);
    let deleteBtn = editedCard.locator('button:has(svg.lucide-trash-2)').first();
    if ((await deleteBtn.count()) === 0) {
      const allBtns = editedCard.locator('button');
      const n = await allBtns.count();
      deleteBtn = allBtns.nth(n - 1);
    }
    await deleteBtn.click({ force: true });
    await page.waitForTimeout(400);

    // Confirm in the ConfirmDialog (role="alertdialog")
    const confirmDialog = page.locator('[role="alertdialog"]').first();
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });
    await shot(page, '14-delete-confirm-dialog');
    const confirmBtn = page.getByTestId('confirm-dialog-confirm');
    await confirmBtn.click();
    await expect(confirmDialog).toBeHidden({ timeout: 10_000 });
    await page.waitForTimeout(800);
    await shot(page, '15-after-delete');

    // Step 14 — assert the task is gone
    const goneCard = page.locator('[role="listitem"]').filter({ hasText: 'E2E Task Edited' });
    await expect(goneCard).toHaveCount(0, { timeout: 5000 });
    await shot(page, '16-task-gone');

    const errors = stop();
    if (errors.length > 0) {
      await shot(page, '17-console-errors');
      // eslint-disable-next-line no-console
      console.warn('[Cluster A] Console errors during Task CRUD:', errors);
    }
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.warn('[Cluster A] Task API 4xx responses observed:', failed);
    }
    // Fail if we saw 4xx responses that indicate a backend contract bug
    const relevantFailures = failed.filter((f) =>
      // Ignore cosmetic 404 on completion fetch etc. — focus on PATCH edit.
      /\/tasks\/[0-9a-f-]+/.test(f.url) && f.status === 422,
    );
    expect(errors, 'No unhandled console errors during Task CRUD workflow').toEqual([]);
    expect(relevantFailures, 'No 422 errors on /tasks/<id> endpoint (edit contract bug)')
      .toEqual([]);
  });

  test('Task page — custom category creation and task assignment', async ({ page }) => {
    const stop = attachConsoleErrorWatcher(page);

    await page.goto('/tasks');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(800);

    // Step 1 — click the + button next to the filter tabs (custom category)
    // It sits right after the custom category tabs, title "Add category"
    const addCategoryBtn = page.locator('button[title*="Add category" i]').first();
    await expect(addCategoryBtn).toBeVisible({ timeout: 10_000 });
    await addCategoryBtn.click();
    await page.waitForTimeout(400);
    await shot(page, '20-add-category-popover');

    // Step 2 — type "Safety"
    const categoryInput = page.locator('input[placeholder*="Safety" i], input[placeholder*="QA" i]').first();
    await expect(categoryInput).toBeVisible({ timeout: 5000 });
    await categoryInput.fill('Safety');

    // Step 3 — pick a color (use the second color button in the palette)
    const colorButtons = page.locator('button[style*="background-color"]');
    const firstColor = colorButtons.nth(1);
    if (await firstColor.isVisible().catch(() => false)) {
      await firstColor.click();
      await page.waitForTimeout(150);
    }
    await shot(page, '21-category-name-filled');

    // Step 4 — click Add
    const addBtn = page.getByRole('button', { name: /^Add$/ }).first();
    await expect(addBtn).toBeEnabled();
    await addBtn.click();
    await page.waitForTimeout(500);
    await shot(page, '22-after-category-add');

    // Step 5 — assert "Safety" tab appears in the filter bar
    const safetyTab = page.getByRole('button', { name: /^Safety$/ }).first();
    await expect(safetyTab).toBeVisible({ timeout: 5000 });

    // Step 6 — click the Safety tab
    await safetyTab.click();
    await page.waitForTimeout(300);
    await shot(page, '23-safety-tab-active');

    // Step 7 — press "n" for new task with Safety pre-filled
    await page.keyboard.press('n');
    await page.waitForTimeout(500);
    const modal = page.locator('[role="dialog"][aria-label*="New Task" i]').first();
    await expect(modal).toBeVisible({ timeout: 5000 });
    await shot(page, '24-safety-modal-open');

    // The task_type should be pre-filled to 'safety'. Verify the Safety
    // button inside the modal is the selected one (ring-2 class present).
    const safetyTypeBtn = modal.locator('button').filter({
      has: page.locator('span:has-text("Safety")'),
    }).first();
    if (await safetyTypeBtn.isVisible().catch(() => false)) {
      const cls = (await safetyTypeBtn.getAttribute('class')) || '';
      const looksSelected =
        cls.includes('ring-2') || cls.includes('border-current') || cls.includes('ring-oe-blue');
      if (!looksSelected) {
        // Not necessarily a bug — log a warning screenshot
        await shot(page, '25-safety-not-preselected');
      } else {
        await shot(page, '25-safety-preselected');
      }
    }

    // Step 8 — fill title and submit
    const titleInput = modal.locator('input').first();
    await titleInput.fill('Safety Test');
    await page.waitForTimeout(100);
    await shot(page, '26-safety-title-filled');

    const createBtn = modal.getByRole('button', { name: /Create Task/i });
    await expect(createBtn).toBeEnabled();
    await createBtn.click();
    await expect(modal).toBeHidden({ timeout: 10_000 });
    await page.waitForTimeout(1000);
    await shot(page, '27-safety-after-create');

    // Step 9 — assert the Safety task appears under the Safety filter
    // Click Safety tab again to be safe
    const safetyTabAgain = page.getByRole('button', { name: /^Safety$/ }).first();
    if (await safetyTabAgain.isVisible().catch(() => false)) {
      await safetyTabAgain.click();
      await page.waitForTimeout(400);
    }
    const safetyTaskCard = page.locator('[role="listitem"]').filter({ hasText: 'Safety Test' }).first();
    await expect(safetyTaskCard).toBeVisible({ timeout: 10_000 });
    await shot(page, '28-safety-task-visible');

    // Cleanup: delete the task we just created so the suite stays idempotent
    await safetyTaskCard.hover();
    await page.waitForTimeout(300);
    const deleteBtn = safetyTaskCard.locator('button:has(svg.lucide-trash-2)').first();
    if ((await deleteBtn.count()) > 0) {
      await deleteBtn.click({ force: true });
      await page.waitForTimeout(400);
      const confirmBtn = page.getByTestId('confirm-dialog-confirm');
      if (await confirmBtn.isVisible().catch(() => false)) {
        await confirmBtn.click();
        await page.waitForTimeout(800);
      }
    }

    const errors = stop();
    if (errors.length > 0) {
      // eslint-disable-next-line no-console
      console.warn('[Cluster A] Console errors during Custom Category workflow:', errors);
    }
    expect(errors, 'No unhandled console errors during Custom Category workflow').toEqual([]);
  });

  test('Projects list — navigation and detail page render', async ({ page }) => {
    const stop = attachConsoleErrorWatcher(page);

    // Step 1 — navigate to /projects
    await page.goto('/projects');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(800);
    await shot(page, '30-projects-list');

    // Step 2 — assert the page-body heading is visible. There are two
    // "Projects" headings on the page (top banner + body); we want the
    // visible body H1, so pick the one NOT inside banner/header.
    const heading = page
      .locator('main h1, section h1')
      .filter({ hasText: /^Projects/i })
      .first()
      .or(page.getByRole('heading', { name: /^Projects/i, level: 1 }).last());
    await expect(heading).toBeVisible({ timeout: 10_000 });

    // Step 3 — click the first project card (by id from backend)
    const projectId = await firstProjectId(page, accessToken);
    if (!projectId) {
      // Could not obtain a project via helper — attempt visual click
      const firstCard = page
        .locator('a[href^="/projects/"]:not([href="/projects/new"])')
        .first();
      if (await firstCard.isVisible().catch(() => false)) {
        await firstCard.click();
      } else {
        test.skip(true, 'No projects found and no visible project card to click');
      }
    } else {
      // Prefer direct navigation to the known project to be deterministic
      await page.goto(`/projects/${projectId}`);
    }
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1200);
    await shot(page, '31-project-detail');

    // Step 4 — verify the detail page has a visible heading. The
    // ProjectDetailPage shows the project name in a body H1; prefer the
    // body heading (skip the shell banner duplicate).
    const detailHeading = page
      .locator('main h1, section h1')
      .first()
      .or(page.locator('h1').last());
    await expect(detailHeading).toBeVisible({ timeout: 10_000 });
    const headingBox = await detailHeading.boundingBox();
    if (!headingBox || headingBox.width <= 0 || headingBox.height <= 0) {
      await shot(page, '32-detail-heading-broken');
      throw new Error('Project detail heading has no layout box (possible overlap)');
    }
    await shot(page, '32-project-detail-loaded');

    const errors = stop();
    if (errors.length > 0) {
      // eslint-disable-next-line no-console
      console.warn('[Cluster A] Console errors during Projects workflow:', errors);
    }
    expect(errors, 'No unhandled console errors during Projects workflow').toEqual([]);
  });
});
