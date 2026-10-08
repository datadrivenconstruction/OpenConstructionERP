// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The one switch for semantic search: off by default, says what it costs in
// memory before it is flipped, and flipping it is the one request that turns
// it on (and fetches the model when it is missing).
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const { embeddingModelStatus, setSemanticSearchEnabled } = vi.hoisted(() => ({
  embeddingModelStatus: vi.fn(),
  setSemanticSearchEnabled: vi.fn(),
}));

vi.mock('@/features/ai-estimator/api', () => ({
  aiEstimatorApi: { embeddingModelStatus, setSemanticSearchEnabled },
}));

import SemanticModelSettings from '../SemanticModelSettings';
import { SemanticSearchOffHint } from '../SemanticSearchOffHint';

const OFF = {
  state: 'disabled',
  semantic_enabled: false,
  semantic_locked: false,
  available_memory_mb: 700,
  required_memory_mb: 1024,
  memory_low: true,
};

function renderIt(ui = <SemanticModelSettings />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SemanticModelSettings', () => {
  beforeEach(() => {
    embeddingModelStatus.mockReset();
    setSemanticSearchEnabled.mockReset();
    embeddingModelStatus.mockResolvedValue(OFF);
    setSemanticSearchEnabled.mockImplementation(async () => {
      const on = { ...OFF, state: 'downloading', semantic_enabled: true };
      embeddingModelStatus.mockResolvedValue(on);
      return on;
    });
  });

  it('is off by default, shows the memory it needs, and turns on with one request', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByRole('switch').hasAttribute('disabled')).toBe(false));
    const toggle = screen.getByRole('switch');
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(screen.getByText(/1024 MB/)).toBeTruthy();
    expect(screen.getByText(/700 MB/)).toBeTruthy();
    expect(setSemanticSearchEnabled).not.toHaveBeenCalled();

    fireEvent.click(toggle);

    await waitFor(() => expect(setSemanticSearchEnabled).toHaveBeenCalledWith(true));
    await waitFor(() => expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('true'));
  });

  it('offers no switch when an operator fixed it', async () => {
    embeddingModelStatus.mockResolvedValue({ ...OFF, semantic_locked: true });
    renderIt();
    await screen.findByText(/administrator/);
    expect(screen.queryByRole('switch')).toBeNull();
  });
});

describe('SemanticSearchOffHint', () => {
  beforeEach(() => embeddingModelStatus.mockReset());

  it('points to Settings while semantic search is off', async () => {
    embeddingModelStatus.mockResolvedValue(OFF);
    renderIt(<SemanticSearchOffHint />);
    const link = await screen.findByRole('link');
    expect(link.getAttribute('href')).toBe('/settings?tab=ai');
  });

  it('renders its fallback when semantic search is on', async () => {
    embeddingModelStatus.mockResolvedValue({ ...OFF, state: 'ready', semantic_enabled: true });
    renderIt(<SemanticSearchOffHint>fallback</SemanticSearchOffHint>);
    await screen.findByText('fallback');
    expect(screen.queryByRole('link')).toBeNull();
  });
});
