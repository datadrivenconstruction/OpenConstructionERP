// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The preview endpoint serialises money as decimal strings. The dialog used to
// hand them to a number formatter and crash the moment a priced row appeared.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ImportPreviewDialog } from '../ImportPreviewDialog';

const PREVIEW = {
  positions: [
    {
      ordinal: '1',
      code: '',
      description: 'Excavation',
      unit: 'm3',
      quantity: 125.5,
      unit_rate: '1850.00',
      total: '232175.00',
      is_section: false,
      classification: {},
      metadata: {},
    },
  ],
  total_positions: 1,
  total_sections: 0,
  currency: 'EUR',
  source_format: 'xlsx',
  warnings: [],
  errors: [],
  skipped: 0,
  truncated: false,
  metadata: { original_columns: ['A', 'B'], column_mapping: {}, header_row: 1 },
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('import preview money', () => {
  it('renders unit rate and total that arrive as decimal strings', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(PREVIEW), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ImportPreviewDialog open onClose={() => {}} boqId="boq-1" onImported={() => {}} />
      </QueryClientProvider>,
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['x'], 'bill.xlsx')] } });

    expect(await screen.findByText(/1[\s,.\u00a0\u202f]?850[.,]00/)).toBeTruthy();
    expect(screen.getByText(/232[\s,.\u00a0\u202f]?175[.,]00/)).toBeTruthy();
  });

  it('previews a file handed in by the caller without a second pick', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(PREVIEW), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ImportPreviewDialog
          open
          onClose={() => {}}
          boqId="boq-1"
          onImported={() => {}}
          initialFile={new File(['x'], 'bill.xlsx')}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/1[\s,.  ]?850[.,]00/)).toBeTruthy();
    expect(String(fetchSpy.mock.calls[0]![0])).toBe('/api/v1/boq/import/preview/');
  });
});
