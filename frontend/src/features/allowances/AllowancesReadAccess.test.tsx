// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What a user may read never depends on what they may write: a viewer sees the
// same allowance actions as an editor, disabled with the reason.

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

vi.mock('./api', async (orig) => {
  const real = await orig<typeof import('./api')>();
  return {
    ...real,
    fetchAllowances: vi.fn().mockResolvedValue([]),
    fetchRegisterSummary: vi.fn().mockResolvedValue(null),
  };
});
vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: vi.fn().mockResolvedValue([{ id: 'p1', name: 'Project' }]),
}));

import { AllowancesPage } from './AllowancesPage';

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AllowancesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AllowancesPage read access', () => {
  beforeEach(() => {
    useProjectContextStore.setState({ activeProjectId: 'p1' } as never);
  });

  it('keeps New allowance on screen for a viewer, disabled, with the reason', () => {
    useAuthStore.setState({ userRole: 'viewer' } as never);
    renderPage();
    const button = screen.getByRole('button', { name: /New allowance/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Only an editor, manager or administrator can do this.');
  });

  it('enables it for an editor', () => {
    useAuthStore.setState({ userRole: 'editor' } as never);
    renderPage();
    const button = screen.getByRole('button', { name: /New allowance/ });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute('title');
  });
});
