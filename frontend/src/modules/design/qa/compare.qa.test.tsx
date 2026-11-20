// UI QA: comparing two revisions must not report invented changes when a model was only partly loaded.
import { describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { RevisionView } from '../data/revisions';

vi.mock('@/features/bim/api', () => ({
  // the server answers with a page of 2 elements out of 60 000 (the viewer asks for at most 50 000)
  fetchBIMElements: vi.fn(async (id: string) => ({
    items: id === 'm1' ? [{ stable_id: 'a' }, { stable_id: 'b' }] : [{ stable_id: 'a' }, { stable_id: 'c' }],
    total: 60000,
  })),
}));

import { useRevisionCompare } from '../useRevisionCompare';

const rev = (n: number): RevisionView => ({
  revision_id: `r${n}`, project_id: 'p', number: n, parent_revision_id: null, status: 'shared', source_kind: 'editor',
  depth_level: 'D2', message: '', bim_model_id: `m${n}`, decided_by: null, decided_at: null, decision_comment: null, created_at: '',
});

describe('revision comparison', () => {
  it('reports a failure instead of counts when a model came back truncated', async () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useRevisionCompare(rev(1), rev(2)), { wrapper });
    await waitFor(() => expect(result.current.cmp !== null || result.current.failed).toBe(true));
    expect(result.current.cmp).toBeNull();
    expect(result.current.failed).toBe(true);
  });
});
