// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The global search opens over everything, the AI dock included. The dock
// keeps Tab inside itself in overlay mode and answers Alt+A, and both yield
// only to another open `aria-modal="true"` dialog (`isAnotherModalOpen`).
// Unmarked, the search would open visibly on top while Tab and Alt+A kept
// working the dock underneath it. So the mark is the contract checked here,
// together with the dock's own reading of it, open and closed.
//
// Run:  npx vitest run src/features/search/__tests__/globalSearchModalIsAModal.test.tsx

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// No search runs here: the facet list never answers, so nothing settles
// after an assertion.
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  fetchSearchTypes: () => new Promise(() => {}),
  unifiedSearch: () => new Promise(() => {}),
}));

import GlobalSearchModal from '../GlobalSearchModal';
import { useGlobalSearchStore } from '@/stores/useGlobalSearchStore';
import { isAnotherModalOpen } from '@/features/erp-chat/useFloatingChat';

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <GlobalSearchModal />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useGlobalSearchStore.setState({ open: false, query: '' });
});

afterEach(() => {
  cleanup();
});

describe('the global search', () => {
  it('is a labelled modal dialog while it is open', () => {
    mount();
    act(() => useGlobalSearchStore.getState().openModal());
    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.getAttribute('aria-modal')).toBe('true');
    expect(dialog!.getAttribute('aria-label')).toBe('Search');
  });

  it('is what the dock yields to while it is open, and only then', () => {
    mount();
    expect(isAnotherModalOpen(null)).toBe(false);
    act(() => useGlobalSearchStore.getState().openModal());
    expect(isAnotherModalOpen(null)).toBe(true);
    act(() => useGlobalSearchStore.getState().closeModal());
    // It unmounts when closed, so the mark never outlives it.
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(isAnotherModalOpen(null)).toBe(false);
  });
});
