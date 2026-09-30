// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The column mapping dropdowns in the import preview reach the server.
//
// The dropdowns were decorative: whatever the user picked, the import posted
// the file alone and the bill was read with the importer's own guess. A header
// the importer did not know imported nothing, and the one control that could
// fix it did nothing. The dialog now previews again with the columns the user
// changed and sends the same mapping with the import, and sends nothing when
// nothing changed, so a file the importer reads well is read exactly as before.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

import { ImportPreviewDialog } from '../ImportPreviewDialog';

const HEADINGS = ['Sor', 'Kód', 'Munka', 'Darab', 'ME', 'Ár'];

function preview(overrides: Record<string, unknown> = {}) {
  return {
    positions: [],
    total_positions: 0,
    total_sections: 0,
    currency: 'HUF',
    source_format: 'xlsx',
    warnings: [],
    errors: [
      {
        severity: 'error',
        code: 'header_not_recognised',
        missing: ['description'],
        unrecognised: ['Sor', 'Kód', 'Munka', 'Darab', 'Ár'],
        recognised: { ME: 'unit' },
      },
    ],
    skipped: 0,
    truncated: false,
    metadata: { original_columns: HEADINGS, column_mapping: { '4': 'unit' }, header_row: 5 },
    ...overrides,
  };
}

const MAPPED = preview({
  positions: [
    {
      ordinal: '1',
      code: '',
      description: 'Földkiemelés',
      unit: 'm3',
      quantity: 125.5,
      unit_rate: 1850,
      total: 232175,
      is_section: false,
      classification: {},
      metadata: {},
    },
  ],
  total_positions: 1,
  errors: [],
  metadata: {
    original_columns: HEADINGS,
    column_mapping: { '2': 'description', '3': 'quantity', '4': 'unit', '5': 'unit_rate' },
    header_row: 5,
  },
});

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

/** Every request the dialog made: its URL and the column_mapping it sent, if any. */
function sent(spy: { mock: { calls: unknown[][] } }) {
  return spy.mock.calls.map(([url, init]) => ({
    url: String(url),
    mapping: ((init as RequestInit | undefined)?.body as FormData | undefined)?.get('column_mapping') ?? null,
  }));
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function open() {
  render(<ImportPreviewDialog open onClose={() => {}} boqId="boq-1" onImported={() => {}} />);
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['x'], 'koltsegvetes.xlsx')] } });
}

describe('import preview column mapping', () => {
  it('opens the mapping for a header the importer could not read, and previews again with what the user chose', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(preview()))
      .mockResolvedValueOnce(json(MAPPED))
      .mockResolvedValueOnce(json({ imported: 1, warnings: [] }));
    open();

    const quantity = await screen.findByRole('combobox', { name: 'Darab' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Munka' }), { target: { value: 'description' } });
    fireEvent.change(quantity, { target: { value: 'quantity' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Ár' }), { target: { value: 'unit_rate' } });

    fireEvent.click(screen.getByTestId('import-preview-apply-mapping'));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    const expected = JSON.stringify({ '2': 'description', '3': 'quantity', '5': 'unit_rate' });
    expect(sent(fetchSpy)[1]).toEqual({ url: '/api/v1/boq/import/preview/', mapping: expected });

    const next = await screen.findByRole('button', { name: 'Continue' });
    await waitFor(() => expect(next).not.toBeDisabled());
    fireEvent.click(next);
    fireEvent.click(await screen.findByRole('button', { name: 'Import' }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(3));
    expect(sent(fetchSpy)[2]).toEqual({ url: '/api/v1/boq/boqs/boq-1/import/auto/', mapping: expected });
  });

  it('sends no mapping when the user left the importer reading alone', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(MAPPED))
      .mockResolvedValueOnce(json({ imported: 1, warnings: [] }));
    open();

    const next = await screen.findByRole('button', { name: 'Continue' });
    await waitFor(() => expect(next).not.toBeDisabled());
    fireEvent.click(next);
    fireEvent.click(await screen.findByRole('button', { name: 'Import' }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    expect(sent(fetchSpy).map((call) => call.mapping)).toEqual([null, null]);
    expect(screen.queryByTestId('import-preview-apply-mapping')).toBeNull();
  });

  it('holds Continue until a changed mapping has been previewed, so the counts confirmed are the bill imported', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(MAPPED));
    open();

    const next = await screen.findByRole('button', { name: 'Continue' });
    await waitFor(() => expect(next).not.toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: /Column mapping/ }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Sor' }), { target: { value: 'ordinal' } });

    expect(next).toBeDisabled();
    expect(screen.getByTestId('import-preview-apply-mapping')).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it('does not offer a field the importer refuses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(preview()));
    open();
    const select = await screen.findByRole('combobox', { name: 'Sor' });
    const values = Array.from((select as HTMLSelectElement).options).map((o) => o.value);
    expect(values).toEqual(['', 'ordinal', 'description', 'unit', 'quantity', 'unit_rate', 'total', 'classification']);
  });
});
