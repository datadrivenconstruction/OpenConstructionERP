// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Path and shape tests for the approval request client.
//
// Listing, submitting, approving and rejecting requests were written without
// the trailing slash the routes declare, and the application does not redirect
// slashes, so all four answered 404. The list was worse than a 404: without
// the slash GET /enterprise-workflows/requests is read as a workflow whose id
// is "requests". Both list routes also answer with a page envelope, which the
// page reads as an array, so the unwrapping is pinned here with the paths.

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn(() => Promise.resolve({ items: [], total: 0, offset: 0, limit: 50 })),
  apiPost: vi.fn(() => Promise.resolve({})),
  apiPatch: vi.fn(() => Promise.resolve({})),
  apiDelete: vi.fn(() => Promise.resolve(undefined)),
}));

import { apiGet, apiPost } from '@/shared/lib/api';
import {
  fetchWorkflows,
  fetchApprovalRequests,
  submitApprovalRequest,
  approveRequest,
  rejectRequest,
} from './api';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('approval request routes', () => {
  it('lists requests under /requests/ and returns the items of the page', async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({ items: [{ id: 'q-1' }], total: 1, offset: 0, limit: 50 });
    const rows = await fetchApprovalRequests({ status: 'pending' });
    expect(apiGet).toHaveBeenCalledWith('/v1/enterprise-workflows/requests/?status=pending');
    expect(rows).toEqual([{ id: 'q-1' }]);
  });

  it('lists workflows and returns the items of the page', async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({ items: [{ id: 'w-1' }], total: 1, offset: 0, limit: 50 });
    const rows = await fetchWorkflows();
    expect(apiGet).toHaveBeenCalledWith('/v1/enterprise-workflows/');
    expect(rows).toEqual([{ id: 'w-1' }]);
  });

  it('submits, approves and rejects with the trailing slash', async () => {
    await submitApprovalRequest({ workflow_id: 'w-1', entity_type: 'boq', entity_id: 'e-1' });
    expect(apiPost).toHaveBeenCalledWith('/v1/enterprise-workflows/requests/', expect.anything());
    await approveRequest('q-1');
    expect(apiPost).toHaveBeenCalledWith('/v1/enterprise-workflows/requests/q-1/approve/', undefined);
    await rejectRequest('q-1');
    expect(apiPost).toHaveBeenCalledWith('/v1/enterprise-workflows/requests/q-1/reject/', undefined);
  });
});
