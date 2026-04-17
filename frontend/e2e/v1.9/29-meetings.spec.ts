/**
 * v1.9 #29 -- Meetings: edit + attachments + description (RFC 29).
 *
 * End-to-end coverage for the Option A decision:
 *   - Create meeting with a dropped attachment -> attachment chip visible on the row
 *   - Download URL on the chip resolves to the Documents download endpoint
 *   - Edit an existing meeting's minutes -> PATCH persists, row re-renders
 *   - Delete meeting -> confirm dialog -> row disappears
 *   - Removing an attachment in edit mode persists across reload
 *
 * Keeps the suite focused. Uses the shared helpers in ./helpers-v19.
 */
import { test, expect } from '@playwright/test';
import { loginV19, ensureProject } from './helpers-v19';

async function createMeetingViaApi(
  page: import('@playwright/test').Page,
  token: string,
  projectId: string,
  payload: Record<string, unknown>,
): Promise<{ id: string; meeting_number: string }> {
  const res = await page.request.post('http://localhost:8000/api/v1/meetings/', {
    headers: { Authorization: `Bearer ${token}` },
    data: { project_id: projectId, ...payload },
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as { id: string; meeting_number: string };
}

async function uploadDocumentViaApi(
  page: import('@playwright/test').Page,
  token: string,
  projectId: string,
  filename: string,
  content: string,
): Promise<string> {
  const res = await page.request.post(
    `http://localhost:8000/api/v1/documents/upload/?project_id=${projectId}&category=meeting`,
    {
      headers: { Authorization: `Bearer ${token}` },
      multipart: {
        file: {
          name: filename,
          mimeType: 'text/plain',
          buffer: Buffer.from(content, 'utf8'),
        },
      },
    },
  );
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return String(body.id);
}

async function readAccessToken(
  page: import('@playwright/test').Page,
): Promise<string> {
  return page.evaluate(() => localStorage.getItem('oe_access_token') || '');
}

test.describe('v1.9 #29 -- Meetings overhaul', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  test('create meeting with attachment via API, row shows attachment chip', async ({
    page,
  }) => {
    const projectId = await ensureProject(page);
    const token = await readAccessToken(page);

    const docId = await uploadDocumentViaApi(
      page,
      token,
      projectId,
      'agenda-29a.txt',
      'Agenda v1.9.1 RFC 29 test',
    );

    const meeting = await createMeetingViaApi(page, token, projectId, {
      meeting_type: 'progress',
      title: 'RFC 29 attachment test',
      meeting_date: new Date().toISOString().slice(0, 10),
      minutes: 'Initial minutes with a dropped file.',
      document_ids: [docId],
    });
    expect(meeting.id).toBeTruthy();

    await page.goto(`/projects/${projectId}/meetings`);
    await page.waitForLoadState('networkidle');

    const row = page.locator('text=RFC 29 attachment test').first();
    await expect(row).toBeVisible({ timeout: 10_000 });

    // Expand the row so that the attachment chip renders.
    await row.click();

    const chip = page
      .locator('[data-testid="meeting-row-attachment-chip"]')
      .first();
    await expect(chip).toBeVisible({ timeout: 10_000 });
    const href = await chip.getAttribute('href');
    expect(href).toContain(`/api/v1/documents/${docId}/download`);
  });

  test('edit modal opens, saves minutes via PATCH', async ({ page }) => {
    const projectId = await ensureProject(page);
    const token = await readAccessToken(page);

    const meeting = await createMeetingViaApi(page, token, projectId, {
      meeting_type: 'progress',
      title: 'RFC 29 edit test',
      meeting_date: new Date().toISOString().slice(0, 10),
      minutes: 'Original minutes.',
    });

    await page.goto(`/projects/${projectId}/meetings`);
    await page.waitForLoadState('networkidle');

    const row = page.locator('text=RFC 29 edit test').first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();

    await page.locator('[data-testid="meeting-row-edit"]').first().click();

    const modal = page.locator('[data-testid="edit-meeting-modal"]');
    await expect(modal).toBeVisible();

    const minutesInput = page.locator('[data-testid="edit-meeting-minutes"]');
    await minutesInput.fill('Updated minutes via E2E.');

    await page.locator('[data-testid="edit-meeting-save"]').click();
    await expect(modal).toBeHidden({ timeout: 10_000 });

    // Verify PATCH landed in the DB.
    const getRes = await page.request.get(
      `http://localhost:8000/api/v1/meetings/${meeting.id}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(getRes.ok()).toBeTruthy();
    const fetched = await getRes.json();
    expect(fetched.minutes).toBe('Updated minutes via E2E.');
  });

  test('delete meeting removes it from the list', async ({ page }) => {
    const projectId = await ensureProject(page);
    const token = await readAccessToken(page);

    await createMeetingViaApi(page, token, projectId, {
      meeting_type: 'progress',
      title: 'RFC 29 delete test',
      meeting_date: new Date().toISOString().slice(0, 10),
    });

    await page.goto(`/projects/${projectId}/meetings`);
    await page.waitForLoadState('networkidle');

    const row = page.locator('text=RFC 29 delete test').first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();

    await page.locator('[data-testid="meeting-row-delete"]').first().click();

    // ConfirmDialog -> click the destructive confirm button. The dialog renders
    // the confirm label passed from useConfirm ('Delete').
    const confirmBtn = page
      .locator('button', { hasText: /^Delete$/ })
      .last();
    await confirmBtn.click();

    await expect(page.locator('text=RFC 29 delete test')).toHaveCount(0, {
      timeout: 10_000,
    });
  });

  test('edit mode: remove attachment persists after save', async ({ page }) => {
    const projectId = await ensureProject(page);
    const token = await readAccessToken(page);

    const docId = await uploadDocumentViaApi(
      page,
      token,
      projectId,
      'agenda-29b.txt',
      'Agenda for removal test',
    );

    const meeting = await createMeetingViaApi(page, token, projectId, {
      meeting_type: 'progress',
      title: 'RFC 29 remove attachment test',
      meeting_date: new Date().toISOString().slice(0, 10),
      document_ids: [docId],
    });

    await page.goto(`/projects/${projectId}/meetings`);
    await page.waitForLoadState('networkidle');

    const row = page.locator('text=RFC 29 remove attachment test').first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();

    await page.locator('[data-testid="meeting-row-edit"]').first().click();

    const modal = page.locator('[data-testid="edit-meeting-modal"]');
    await expect(modal).toBeVisible();

    // The attachment row renders inside the attachments list -- there should
    // be a single remove button at load time.
    const removeBtn = modal.locator('[data-testid="meeting-attachment-remove"]').first();
    await expect(removeBtn).toBeVisible({ timeout: 10_000 });
    await removeBtn.click();

    await page.locator('[data-testid="edit-meeting-save"]').click();
    await expect(modal).toBeHidden({ timeout: 10_000 });

    // Confirm that document_ids on the meeting is now empty.
    const getRes = await page.request.get(
      `http://localhost:8000/api/v1/meetings/${meeting.id}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(getRes.ok()).toBeTruthy();
    const fetched = await getRes.json();
    expect(fetched.document_ids).toEqual([]);
  });
});
