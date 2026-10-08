// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The settings door to the encoder: off until the user flips it, and flipping
// it is the one request that starts the download.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const { embeddingModelStatus, installEmbeddingModel } = vi.hoisted(() => ({
  embeddingModelStatus: vi.fn(),
  installEmbeddingModel: vi.fn(),
}));

vi.mock('@/features/ai-estimator/api', () => ({
  aiEstimatorApi: { embeddingModelStatus, installEmbeddingModel },
}));

import SemanticModelSettings from '../SemanticModelSettings';

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SemanticModelSettings />
    </QueryClientProvider>,
  );
}

describe('SemanticModelSettings', () => {
  beforeEach(() => {
    embeddingModelStatus.mockReset();
    installEmbeddingModel.mockReset();
    embeddingModelStatus.mockResolvedValue({ state: 'not_requested', enabled: false, locked: false });
    installEmbeddingModel.mockResolvedValue({});
  });

  it('downloads nothing until the switch is flipped, then asks once', async () => {
    renderIt();
    const toggle = await screen.findByRole('switch');
    await waitFor(() => expect(embeddingModelStatus).toHaveBeenCalled());
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(installEmbeddingModel).not.toHaveBeenCalled();

    fireEvent.click(toggle);

    await waitFor(() => expect(installEmbeddingModel).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('true');
  });
});
