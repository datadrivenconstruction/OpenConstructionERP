/**
 * Hook test for ``useMarkups``.
 *
 * What we verify here:
 *   1. The hook hits the correct ``/v1/markups/?project_id=&document_id=&page=``
 *      endpoint when given a full triple.
 *   2. It stays disabled (no network) when any of the three args is missing.
 *   3. It collapses per-markup ``GET /comments/`` responses into a count map
 *      keyed by markup id.
 *
 * All network calls are mocked at the ``@/shared/lib/api`` boundary so the
 * test stays pure (no real React-Query background).
 */

import { type ReactNode } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useMarkups } from '../useMarkups';

const apiGet = vi.fn();

vi.mock('@/shared/lib/api', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: { getState: () => ({ accessToken: 'test-token' }) },
}));

function wrapper(): (props: { children: ReactNode }) => JSX.Element {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return ({ children }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  apiGet.mockReset();
});

describe('useMarkups', () => {
  it('calls /v1/markups/ with project_id, document_id, and page when ready', async () => {
    apiGet.mockImplementationOnce(async () => [
      {
        id: 'm-1',
        project_id: 'p-1',
        document_id: 'd-1',
        page: 3,
        type: 'rectangle',
        geometry: {},
        text: null,
        color: '#3b82f6',
        line_width: 2,
        opacity: 1,
        author_id: 'u-1',
        status: 'active',
        label: null,
        measurement_value: null,
        measurement_unit: null,
        stamp_template_id: null,
        linked_boq_position_id: null,
        metadata: {},
        created_by: 'u-1',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
      },
    ]);
    // Second call: comments for m-1
    apiGet.mockImplementationOnce(async () => [
      {
        id: 'c-1',
        markup_id: 'm-1',
        user_id: 'u-1',
        body: 'first comment',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
      },
      {
        id: 'c-2',
        markup_id: 'm-1',
        user_id: 'u-2',
        body: 'second comment',
        created_at: '2026-05-12T00:00:01Z',
        updated_at: '2026-05-12T00:00:01Z',
      },
    ]);

    const { result } = renderHook(
      () =>
        useMarkups({
          projectId: 'p-1',
          documentId: 'd-1',
          pageNumber: 3,
        }),
      { wrapper: wrapper() },
    );

    await waitFor(() => expect(result.current.markups.length).toBe(1));

    // First call must be the per-page markups endpoint with all three filters.
    const firstCall = apiGet.mock.calls[0];
    expect(firstCall).toBeTruthy();
    const firstUrl = firstCall?.[0] as string;
    expect(firstUrl).toContain('/v1/markups/');
    expect(firstUrl).toContain('project_id=p-1');
    expect(firstUrl).toContain('document_id=d-1');
    expect(firstUrl).toContain('page=3');

    // Wait for the per-markup comment count to land.
    await waitFor(() => expect(result.current.commentCounts['m-1']).toBe(2));
  });

  it('stays disabled (zero network calls) when any arg is null', () => {
    renderHook(
      () => useMarkups({ projectId: null, documentId: 'd-1', pageNumber: 1 }),
      { wrapper: wrapper() },
    );
    expect(apiGet).not.toHaveBeenCalled();

    renderHook(
      () => useMarkups({ projectId: 'p-1', documentId: null, pageNumber: 1 }),
      { wrapper: wrapper() },
    );
    expect(apiGet).not.toHaveBeenCalled();

    renderHook(
      () =>
        useMarkups({ projectId: 'p-1', documentId: 'd-1', pageNumber: null }),
      { wrapper: wrapper() },
    );
    expect(apiGet).not.toHaveBeenCalled();
  });

  it('returns 0 in commentCounts for markups whose comments are still loading', async () => {
    apiGet.mockImplementationOnce(async () => [
      {
        id: 'm-1',
        project_id: 'p-1',
        document_id: 'd-1',
        page: 1,
        type: 'rectangle',
        geometry: {},
        text: null,
        color: '#3b82f6',
        line_width: 2,
        opacity: 1,
        author_id: 'u-1',
        status: 'active',
        label: null,
        measurement_value: null,
        measurement_unit: null,
        stamp_template_id: null,
        linked_boq_position_id: null,
        metadata: {},
        created_by: 'u-1',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
      },
    ]);
    // Make the comments fetch hang forever for this test.
    apiGet.mockImplementationOnce(
      () => new Promise(() => {}),
    );

    const { result } = renderHook(
      () =>
        useMarkups({ projectId: 'p-1', documentId: 'd-1', pageNumber: 1 }),
      { wrapper: wrapper() },
    );

    await waitFor(() => expect(result.current.markups.length).toBe(1));
    expect(result.current.commentCounts['m-1']).toBe(0);
  });

  it('flags markups in commentCountErrors when the comments fetch fails', async () => {
    apiGet.mockImplementationOnce(async () => [
      {
        id: 'm-1',
        project_id: 'p-1',
        document_id: 'd-1',
        page: 1,
        type: 'rectangle',
        geometry: {},
        text: null,
        color: '#3b82f6',
        line_width: 2,
        opacity: 1,
        author_id: 'u-1',
        status: 'active',
        label: null,
        measurement_value: null,
        measurement_unit: null,
        stamp_template_id: null,
        linked_boq_position_id: null,
        metadata: {},
        created_by: 'u-1',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
      },
    ]);
    // The comments fetch rejects: the count must fall back to 0 AND the id
    // must surface in commentCountErrors so the badge is not silently 0.
    apiGet.mockImplementationOnce(async () => {
      throw new Error('comments fetch failed');
    });

    const { result } = renderHook(
      () =>
        useMarkups({ projectId: 'p-1', documentId: 'd-1', pageNumber: 1 }),
      { wrapper: wrapper() },
    );

    await waitFor(() =>
      expect(result.current.commentCountErrors.has('m-1')).toBe(true),
    );
    expect(result.current.commentCounts['m-1']).toBe(0);
    expect(result.current.error).toBeTruthy();
  });
});
