// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// The X31 dialog proposes and a person confirms. Pinned here: a file the
// editor hands over is read on the right tab without a click, unmatched OZ
// are listed with their reason, rows already measured that way start
// unticked, only the ticked rows are sent to apply, and the bill quantity is
// left alone unless the box is ticked. An X89 opens the check, which has no
// apply button at all.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('./gaebSiteExchangeApi', () => ({
  previewX31: vi.fn(),
  applyX31: vi.fn(),
  downloadX31: vi.fn(),
  checkX89: vi.fn(),
}));

import * as api from './gaebSiteExchangeApi';
import { GaebSiteExchangeDialog, tabForFile } from './GaebSiteExchangeDialog';

const previewMock = vi.mocked(api.previewX31);
const applyMock = vi.mocked(api.applyX31);
const checkMock = vi.mocked(api.checkX89);

function matched(oz: string, id: string, proposed: string, unchanged = false): api.X31MatchedItem {
  return {
    oz,
    quantity: proposed,
    row_count: 0,
    rows: [],
    position_id: id,
    ordinal: oz,
    description: `Position ${oz}`,
    unit: 'm3',
    matched_via: 'ordinal',
    current_quantity: '100.000',
    current_measured_quantity: unchanged ? proposed : null,
    proposed_quantity: proposed,
    difference_to_quantity: '0.000',
    unchanged,
  };
}

const PREVIEW: api.X31Preview = {
  file_name: 'aufmass.x31',
  method: 'REB23003-2009',
  project_name: 'Kita',
  boq_name: 'LV',
  items_in_file: 4,
  matched: [matched('01.0010', 'p1', '125.500'), matched('01.0020', 'p2', '42.000'), matched('01.0030', 'p3', '7.000', true)],
  unmatched: [{ oz: '09.0010', quantity: '7.000', row_count: 0, reason: 'unknown_oz' }],
  positions_not_in_file: 1,
};

beforeEach(() => {
  previewMock.mockReset();
  applyMock.mockReset();
  checkMock.mockReset();
});

describe('tabForFile', () => {
  it('sends an invoice to the check and everything else to the X31 reader', () => {
    expect(tabForFile('Rechnung.X89')).toBe('x89_check');
    expect(tabForFile('aufmass.x31')).toBe('x31_import');
    expect(tabForFile('export.xml')).toBe('x31_import');
  });
});

describe('GaebSiteExchangeDialog', () => {
  it('reads a handed-over X31, lists unmatched OZ, and applies only the ticked rows', async () => {
    previewMock.mockResolvedValue(PREVIEW);
    applyMock.mockResolvedValue({ applied: ['p1'], unchanged: [], errors: [], set_boq_quantity: false });
    const onApplied = vi.fn();
    const file = new File(['<GAEB/>'], 'aufmass.x31', { type: 'application/xml' });

    render(
      <GaebSiteExchangeDialog open boqId="b1" boqName="LV" initialFile={file} onClose={() => {}} onApplied={onApplied} />,
    );

    await waitFor(() => expect(previewMock).toHaveBeenCalledWith('b1', file));
    expect(await screen.findByText('09.0010')).toBeInTheDocument();
    expect(screen.getByText(/No position in this bill has this OZ/)).toBeInTheDocument();

    const boxes = {
      p1: screen.getByLabelText('01.0010') as HTMLInputElement,
      p2: screen.getByLabelText('01.0020') as HTMLInputElement,
      p3: screen.getByLabelText('01.0030') as HTMLInputElement,
    };
    expect(boxes.p1.checked).toBe(true);
    expect(boxes.p2.checked).toBe(true);
    // Already measured with this quantity: nothing to confirm.
    expect(boxes.p3.checked).toBe(false);

    fireEvent.click(boxes.p2);
    fireEvent.click(screen.getByRole('button', { name: 'Apply 1 measured quantity' }));

    await waitFor(() => expect(applyMock).toHaveBeenCalledTimes(1));
    const [boqId, body] = applyMock.mock.calls[0]!;
    expect(boqId).toBe('b1');
    expect(body.set_boq_quantity).toBe(false);
    expect(body.file_name).toBe('aufmass.x31');
    expect(body.items).toEqual([{ position_id: 'p1', quantity: '125.500', oz: '01.0010', rows: [] }]);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it('sends the bill quantity only when the box is ticked, and not at all on a locked bill', async () => {
    previewMock.mockResolvedValue(PREVIEW);
    applyMock.mockResolvedValue({ applied: ['p1', 'p2'], unchanged: [], errors: [], set_boq_quantity: true });
    const file = new File(['<GAEB/>'], 'aufmass.x31');

    const { rerender } = render(
      <GaebSiteExchangeDialog open boqId="b1" boqName="LV" initialFile={file} readOnly onClose={() => {}} />,
    );
    const apply = await screen.findByRole('button', { name: 'Apply 2 measured quantities' });
    expect(apply).toBeDisabled();

    rerender(<GaebSiteExchangeDialog open boqId="b1" boqName="LV" initialFile={file} onClose={() => {}} />);
    fireEvent.click(
      screen.getByLabelText('Also make the measured quantity the bill quantity (re-prices the positions)'),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Apply 2 measured quantities' }));
    await waitFor(() => expect(applyMock).toHaveBeenCalledTimes(1));
    expect(applyMock.mock.calls[0]![1].set_boq_quantity).toBe(true);
  });

  it('names a refused row in words and unticks the rows that were written', async () => {
    previewMock.mockResolvedValue(PREVIEW);
    applyMock.mockResolvedValue({
      applied: ['p1'],
      unchanged: [],
      errors: [{ position_id: 'p2', error: 'position_is_section' }],
      set_boq_quantity: false,
    });
    render(
      <GaebSiteExchangeDialog
        open
        boqId="b1"
        boqName="LV"
        initialFile={new File(['<GAEB/>'], 'aufmass.x31')}
        onClose={() => {}}
      />,
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Apply 2 measured quantities' }));

    expect(await screen.findByText('01.0020: A section row takes no quantity')).toBeInTheDocument();
    expect(screen.queryByText(/position_is_section/)).toBeNull();
    // Written: no longer offered. Refused: still ticked, so it can be retried.
    expect((screen.getByLabelText('01.0010') as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText('01.0020') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole('button', { name: 'Apply 1 measured quantity' })).toBeInTheDocument();
  });

  it('opens a handed-over X89 on the check, shows findings and offers no apply', async () => {
    checkMock.mockResolvedValue({
      file_name: 'r.x89',
      header: { InvoiceNo: 'R-17', InvoiceDate: '2026-10-01' },
      currency: 'EUR',
      items_in_file: 1,
      lines: [
        {
          oz: '01.0020',
          description: 'Stahl',
          unit: 't',
          bill_qty: '2.000',
          unit_price: '1400.000',
          amount: '2800.00',
          position_id: 'p2',
          expected_amount: '2680.00',
          difference: '120.00',
          issues: ['unit_price_differs'],
        },
      ],
      invoiced_total: '2800.00',
      expected_total: '2680.00',
      total_difference: '120.00',
      issue_counts: { unit_price_differs: 1 },
      totals_check: [{ key: 'items_total', stated: '2800.00', computed: '2800.00', matches: true }],
      positions_not_invoiced: 0,
    });
    const file = new File(['<GAEB/>'], 'r.x89');

    render(<GaebSiteExchangeDialog open boqId="b1" boqName="LV" initialFile={file} onClose={() => {}} />);

    await waitFor(() => expect(checkMock).toHaveBeenCalledWith('b1', file));
    expect(await screen.findByText('Unit price differs from bill')).toBeInTheDocument();
    expect(screen.getByText('Invoice R-17 of 2026-10-01')).toBeInTheDocument();
    expect(previewMock).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /Apply/ })).toBeNull();
  });

  it('shows the server refusal of a file instead of a table', async () => {
    previewMock.mockRejectedValue(new Error('This is a GAEB X83 file, not an X31 quantity determination.'));
    render(
      <GaebSiteExchangeDialog
        open
        boqId="b1"
        boqName="LV"
        initialFile={new File(['x'], 'lv.xml')}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByText('This is a GAEB X83 file, not an X31 quantity determination.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
