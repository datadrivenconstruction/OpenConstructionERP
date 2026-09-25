// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A new estimate opened without a project named by its caller started on an
// empty project picker, even with a project chosen in the top-bar switcher.
// It now starts in that project; a project the caller names still wins.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: () =>
    Promise.resolve([
      { id: 'proj-a', name: 'Alpha Tower' },
      { id: 'proj-b', name: 'Bravo Bridge' },
    ]),
}));

import { CreateBOQModal } from '../CreateBOQPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

function renderModal(defaultProjectId?: string) {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CreateBOQModal open onClose={() => {}} defaultProjectId={defaultProjectId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useProjectContextStore.getState().setActiveProject('proj-b', 'Bravo Bridge');
});

afterEach(() => {
  cleanup();
});

describe('New estimate', () => {
  it('starts in the project chosen in the switcher', async () => {
    renderModal();
    await waitFor(() => expect(screen.getByRole('option', { name: 'Bravo Bridge' })).toBeInTheDocument());
    expect(screen.getByRole('combobox')).toHaveValue('proj-b');
  });

  it('keeps the project its caller names', async () => {
    renderModal('proj-a');
    await waitFor(() => expect(screen.getByRole('option', { name: 'Alpha Tower' })).toBeInTheDocument());
    expect(screen.getByRole('combobox')).toHaveValue('proj-a');
  });
});
