/**
 * Finding #19 - the ITP-plan "Export compliance (CSV)" download was a bare
 * <a href> to a Bearer-auth-only endpoint, so a top-level navigation sent no
 * Authorization header and the endpoint returned 401 (dead download).
 *
 * The fix replaces it with an authed blob fetch + triggerDownload. These tests
 * pin that contract: the request carries the Bearer token and the response
 * blob is handed to triggerDownload. They FAIL on the original code (no such
 * handler existed; the anchor never fetched).
 *
 * Run: npx vitest run src/features/qms/QMSPage.compliance-download.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

/* ── Mock the shared api helpers used by the download handler ─────────── */
const mocks = vi.hoisted(() => ({
  getAuthToken: vi.fn<() => string | null>(() => 'jwt-token-123'),
  triggerDownload: vi.fn(),
}));

vi.mock('@/shared/lib/api', () => ({
  getAuthToken: mocks.getAuthToken,
  triggerDownload: mocks.triggerDownload,
  // QMSPage imports these too; stub so the module loads under the test.
  apiGet: vi.fn(),
  getErrorMessage: (e: unknown) => String(e),
}));

import { downloadPlanComplianceCsv } from './QMSPage';

const PLAN_ID = '11111111-2222-3333-4444-555555555555';

describe('downloadPlanComplianceCsv (finding #19)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getAuthToken.mockReturnValue('jwt-token-123');
  });

  it('fetches the CSV with an Authorization: Bearer header and triggers a download', async () => {
    const blob = new Blob(['plan,compliance'], { type: 'text/csv' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: () => Promise.resolve(blob),
    });
    vi.stubGlobal('fetch', fetchMock);

    await downloadPlanComplianceCsv(PLAN_ID);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain(`/api/v1/qms/itp-plans/${PLAN_ID}/compliance-export`);
    expect(url).toContain('format=csv');
    // The auth header MUST be present - this is exactly what the bare anchor
    // could not send.
    expect((init as RequestInit).headers).toEqual({
      Authorization: 'Bearer jwt-token-123',
    });
    expect(mocks.triggerDownload).toHaveBeenCalledWith(
      blob,
      `itp_plan_${PLAN_ID}_compliance.csv`,
    );

    vi.unstubAllGlobals();
  });

  it('throws (and does not download) when the endpoint rejects', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      blob: () => Promise.resolve(new Blob()),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(downloadPlanComplianceCsv(PLAN_ID)).rejects.toThrow(/401/);
    expect(mocks.triggerDownload).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});
