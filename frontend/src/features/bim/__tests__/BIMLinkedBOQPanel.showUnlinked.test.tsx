// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', () => ({
  fetchBIMModelBOQLinks: vi.fn(),
  fetchBIMLinkCheck: vi.fn(),
  fetchBIMUnlinkedElementIds: vi.fn(),
}));

import { fetchBIMLinkCheck, fetchBIMModelBOQLinks, fetchBIMUnlinkedElementIds } from '../api';
import BIMLinkedBOQPanel from '../BIMLinkedBOQPanel';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mount(onHighlightElements = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <BIMLinkedBOQPanel modelId="m1" elements={[]} onHighlightElements={onHighlightElements} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  return onHighlightElements;
}

describe('BIMLinkedBOQPanel link check', () => {
  it('highlights the unlinked elements in the viewer', async () => {
    vi.mocked(fetchBIMModelBOQLinks).mockResolvedValue({ items: [] } as never);
    vi.mocked(fetchBIMLinkCheck).mockResolvedValue({
      model_id: 'm1',
      element_total: 3,
      unlinked_total: 2,
      unlinked_by_type: [{ element_type: 'Door', count: 2 }],
      positions: [],
      findings: [{ rule_id: 'bim_link.elements_linked', severity: 'warning', message: '2 elements are not linked', params: {}, element_ref: '', suggestion: null }],
    });
    vi.mocked(fetchBIMUnlinkedElementIds).mockResolvedValue(['e2', 'e3']);
    const onHighlight = mount();
    fireEvent.click(await screen.findByTestId('bim-link-check-show-3d'));
    await waitFor(() => expect(onHighlight).toHaveBeenCalledWith(['e2', 'e3']));
    expect(fetchBIMUnlinkedElementIds).toHaveBeenCalledWith('m1');
  });

  it('offers no 3D button when every element is linked', async () => {
    vi.mocked(fetchBIMModelBOQLinks).mockResolvedValue({ items: [] } as never);
    vi.mocked(fetchBIMLinkCheck).mockResolvedValue({
      model_id: 'm1',
      element_total: 3,
      unlinked_total: 0,
      unlinked_by_type: [],
      positions: [],
      findings: [{ rule_id: 'bim_link.unit_supplied', severity: 'warning', message: 'unit', params: {}, element_ref: '', suggestion: null }],
    });
    mount();
    await screen.findByTestId('bim-link-check');
    expect(screen.queryByTestId('bim-link-check-show-3d')).toBeNull();
  });
});
