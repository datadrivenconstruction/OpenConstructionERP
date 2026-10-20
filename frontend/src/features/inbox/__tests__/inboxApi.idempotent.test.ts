// A second dismiss of a row that is already gone must read as success.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiPost = vi.fn();
const apiDelete = vi.fn();
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  apiPost: (...a: unknown[]) => apiPost(...a),
  apiDelete: (...a: unknown[]) => apiDelete(...a),
  apiGet: vi.fn(),
}));

import { ApiError } from '@/shared/lib/api';
import { acknowledgeInboxItem, dismissInboxItem, restoreInboxItem } from '../api';

const notFound = () => new ApiError(404, 'Not Found', { detail: 'Inbox item not found' });

describe('inbox row actions are idempotent', () => {
  beforeEach(() => {
    apiPost.mockReset();
    apiDelete.mockReset();
  });

  it('treats a 404 on dismiss as dismissed', async () => {
    apiPost.mockRejectedValue(notFound());
    await expect(dismissInboxItem('notification:1')).resolves.toEqual({
      item_id: 'notification:1',
      state: 'dismissed',
      findings: [],
    });
  });

  it('treats a 404 on acknowledge and on undo as done', async () => {
    apiPost.mockRejectedValue(notFound());
    apiDelete.mockRejectedValue(notFound());
    await expect(acknowledgeInboxItem('a')).resolves.toMatchObject({ state: 'acknowledged' });
    await expect(restoreInboxItem('a')).resolves.toMatchObject({ state: null });
  });

  it('still raises other failures', async () => {
    apiPost.mockRejectedValue(new ApiError(500, 'Server Error', {}));
    await expect(dismissInboxItem('a')).rejects.toBeInstanceOf(ApiError);
  });
});
