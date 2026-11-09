import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PdfDetailsPanel } from './PdfDetailsPanel';
import { boqApi, type PdfDetails } from './api';

const t = (key: string, options?: Record<string, string | number>) => String(options?.defaultValue ?? key);

const stored: PdfDetails = {
  client_name: 'Acme',
  client_address: '1 Main St',
  project_number: 'P-7',
  site_address: '',
  payment_terms: '30 days net',
  hidden_columns: [],
};

function renderPanel(readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PdfDetailsPanel t={t} projectId="p1" readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

describe('PdfDetailsPanel', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('loads the stored details and saves an edit with a hidden column', async () => {
    vi.spyOn(boqApi, 'getPdfDetails').mockResolvedValue(stored);
    const put = vi.spyOn(boqApi, 'putPdfDetails').mockImplementation(async (_id, body) => body);
    renderPanel();
    await waitFor(() => expect((screen.getByTestId('pdf-details-client_name') as HTMLInputElement).value).toBe('Acme'));
    fireEvent.change(screen.getByTestId('pdf-details-payment_terms'), { target: { value: '14 days' } });
    fireEvent.click(screen.getByTestId('pdf-details-col-rate'));
    fireEvent.click(screen.getByTestId('pdf-details-save'));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith('p1', { ...stored, payment_terms: '14 days', hidden_columns: ['rate'] }),
    );
  });

  it('offers no save button on a read-only bill', async () => {
    vi.spyOn(boqApi, 'getPdfDetails').mockResolvedValue(stored);
    renderPanel(true);
    await waitFor(() => expect((screen.getByTestId('pdf-details-client_name') as HTMLInputElement).value).toBe('Acme'));
    expect(screen.queryByTestId('pdf-details-save')).toBeNull();
  });
});
