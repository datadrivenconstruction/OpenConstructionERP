// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The buyer reads in one card whether the bill still matches the file it was
// imported from, and why an award file is refused when it does not.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./awardExchange', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./awardExchange')>();
  return {
    ...actual,
    fetchBillSource: vi.fn(),
    listPackageDocuments: vi.fn(),
    listBidFiles: vi.fn(),
    downloadAwardX86: vi.fn(),
  };
});

import { AwardExportError, downloadAwardX86, fetchBillSource, listBidFiles, listPackageDocuments } from './awardExchange';
import type { BillSourceState } from './awardExchange';
import { ExchangePanel } from './ExchangePanel';

const PKG = { id: 'pkg1', name: 'Earthworks', project_id: 'prj1', status: 'evaluating', boq_id: 'boq1' };

function source(overrides: Partial<BillSourceState> = {}): BillSourceState {
  return {
    source: {
      id: 's1',
      format_id: 'gaeb_xml',
      variant: 'x83',
      file_name: 'tender.X83',
      file_sha256: 'a'.repeat(64),
      bill_sha256: 'b'.repeat(64),
      file_size: 1200,
      document_id: null,
      line_count: 2,
      imported_at: null,
    },
    changed: false,
    differences: [],
    awarded_bid_id: null,
    rule_results: [],
    ...overrides,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ExchangePanel pkg={PKG} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(listPackageDocuments).mockResolvedValue([]);
  vi.mocked(listBidFiles).mockResolvedValue([]);
  vi.mocked(downloadAwardX86).mockReset();
});

describe('ExchangePanel', () => {
  it('says the bill is unchanged and names the imported file', async () => {
    vi.mocked(fetchBillSource).mockResolvedValue(source());
    renderPanel();
    expect(await screen.findByTestId('exchange-unchanged')).toBeTruthy();
    expect(screen.getByTestId('exchange-source').textContent).toContain('tender.X83');
  });

  it('lists what changed since the import', async () => {
    vi.mocked(fetchBillSource).mockResolvedValue(
      source({ changed: true, differences: [{ ordinal: '01.0010', field: 'quantity', was: '120.5', now: '999' }] }),
    );
    renderPanel();
    expect(await screen.findByTestId('exchange-changed')).toBeTruthy();
    const table = screen.getByTestId('exchange-differences');
    expect(table.textContent).toContain('01.0010');
    expect(table.textContent).toContain('999');
  });

  it('offers no GAEB award file for a bill imported from another format', async () => {
    const base = source();
    vi.mocked(fetchBillSource).mockResolvedValue(source({ source: { ...base.source!, format_id: 'bc3', variant: '' } }));
    renderPanel();
    await screen.findByTestId('exchange-unchanged');
    expect(screen.queryByTestId('exchange-x86')).toBeNull();
  });

  it('explains a refused award file instead of failing silently', async () => {
    vi.mocked(fetchBillSource).mockResolvedValue(source());
    vi.mocked(downloadAwardX86).mockRejectedValue(new AwardExportError('no_awarded_bid'));
    renderPanel();
    await screen.findByTestId('exchange-unchanged');
    fireEvent.click(screen.getByTestId('exchange-x86'));
    await waitFor(() => expect(screen.getByTestId('exchange-refusal').textContent).toContain('Award a bid first'));
  });
});
