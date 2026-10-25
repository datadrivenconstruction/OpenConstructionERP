import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ExportEmbeddingPanel } from './ExportEmbeddingPanel';
import { boqApi, type EmbeddingPreview } from './api';

const t = (key: string, options?: Record<string, string | number>) => {
  let text = String(options?.defaultValue ?? key);
  for (const [k, v] of Object.entries(options ?? {})) text = text.replace(`{{${k}}}`, String(v));
  return text;
};

const preview: EmbeddingPreview = {
  buckets: [
    { scope_position_ids: [], direct_cost: '10.59', embedded_amount: '0.74', k: '1.070000', sale_net: '10.50', position_count: 30 },
  ],
  editor_net: '10.59',
  sale_net: '10.50',
  rounding_gap: '-0.09',
  tolerance: '0.05',
  within_tolerance: false,
  visible_markups: [{ id: 'vat', name: 'VAT', category: 'tax', amount: '2.10' }],
  grand_total: '12.60',
  markups: [
    { id: 'oh', name: 'Overhead', category: 'overhead', include_in_unit_rates: true },
    { id: 'vat', name: 'VAT', category: 'tax', include_in_unit_rates: false },
  ],
};

function renderPanel(enabled: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ExportEmbeddingPanel t={t} boqId="b1" enabled={enabled} currency="EUR" />
    </QueryClientProvider>,
  );
}

describe('ExportEmbeddingPanel', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('does not fetch a preview while the mode is off, and the toggle saves the bill setting', async () => {
    const get = vi.spyOn(boqApi, 'embeddingPreview').mockResolvedValue(preview);
    const update = vi.spyOn(boqApi, 'update').mockResolvedValue({} as never);
    renderPanel(false);
    expect(get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('export-embed-toggle'));
    await waitFor(() => expect(update).toHaveBeenCalledWith('b1', { metadata: { export_embed_markups: true } }));
  });

  it('shows k, the sale net and warns on a rounding gap above tolerance', async () => {
    vi.spyOn(boqApi, 'embeddingPreview').mockResolvedValue(preview);
    renderPanel(true);
    expect(await screen.findByText(/^k = 1[.,]0700$/)).toBeInTheDocument();
    expect(screen.getByText(/10[.,]50/)).toBeInTheDocument();
    expect(screen.getByTestId('export-embedding-gap')).toHaveTextContent(/0[.,]09/);
    expect(screen.getByRole('status')).toHaveTextContent('0.05');
  });

  it('saves the rounding tolerance on the bill and refuses a negative one', async () => {
    vi.spyOn(boqApi, 'embeddingPreview').mockResolvedValue(preview);
    const update = vi.spyOn(boqApi, 'update').mockResolvedValue({} as never);
    renderPanel(true);
    const input = await screen.findByTestId('export-embed-tolerance');
    expect(input).toHaveValue('0.05');
    fireEvent.change(input, { target: { value: '-1' } });
    fireEvent.blur(input);
    expect(update).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: '0,10' } });
    fireEvent.blur(input);
    await waitFor(() => expect(update).toHaveBeenCalledWith('b1', { metadata: { export_embed_tolerance: '0.10' } }));
  });

  it('flips a markup line in or out of the unit rates', async () => {
    vi.spyOn(boqApi, 'embeddingPreview').mockResolvedValue(preview);
    const updateMarkup = vi.spyOn(boqApi, 'updateMarkup').mockResolvedValue({} as never);
    renderPanel(true);
    fireEvent.click(await screen.findByLabelText('Include VAT in unit rates'));
    await waitFor(() =>
      expect(updateMarkup).toHaveBeenCalledWith('b1', 'vat', { metadata: { include_in_unit_rates: true } }),
    );
  });
});
