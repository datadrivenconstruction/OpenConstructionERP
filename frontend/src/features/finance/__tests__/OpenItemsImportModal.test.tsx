// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Carrying open invoices over from another system.
 *
 * Pins the order of the dialog: the file is checked first and nothing can be
 * imported before that, a file with errors shows why in the reader's words
 * and cannot be imported, and a clean file shows its control totals and then
 * imports with the same cut-over date.
 *
 * Run:  npx vitest run src/features/finance/__tests__/OpenItemsImportModal.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { OpenItemsImportModal } from '../OpenItemsImportModal';
import type { OpenItemRow, OpenItemsImportResult } from '../api';

const mocks = vi.hoisted(() => ({
  importOpenItems: vi.fn(),
  downloadOpenItemsTemplate: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (_key: string, opts?: Record<string, unknown>) => {
      const text = String(opts?.defaultValue ?? _key);
      return text.replace(/\{\{(\w+)\}\}/g, (_m, name: string) => String(opts?.[name] ?? ''));
    },
    i18n: { language: 'en' },
  }),
}));

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  importOpenItems: mocks.importOpenItems,
  downloadOpenItemsTemplate: mocks.downloadOpenItemsTemplate,
}));

function row(over: Partial<OpenItemRow>): OpenItemRow {
  return {
    row: 2,
    status: 'ready',
    message: null,
    code: null,
    params: {},
    direction: 'receivable',
    invoice_number: 'INV-1042',
    counterparty: 'Lakeview Homes',
    contact_id: 'c-1',
    contact_name: 'Lakeview Homes Inc.',
    invoice_date: '2026-08-15',
    due_date: '2026-09-14',
    currency_code: 'CAD',
    total: '11300.00',
    retention_held: '1000.00',
    open: '6300.00',
    paid: '4000.00',
    invoice_id: null,
    ...over,
  };
}

function result(over: Partial<OpenItemsImportResult>): OpenItemsImportResult {
  return {
    project_id: 'proj-1',
    cutover_date: '2026-09-30',
    dry_run: true,
    missing_columns: [],
    imported: 0,
    ready: 1,
    exists: 0,
    errors: 0,
    rows: [row({})],
    control_totals: [
      { direction: 'receivable', currency_code: 'CAD', count: 1, total: '11300.00', retention_held: '1000.00', open: '6300.00' },
    ],
    ...over,
  };
}

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OpenItemsImportModal projectId="proj-1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

function chooseFile() {
  const file = new File(['direction,invoice_number\n'], 'open.csv', { type: 'text/csv' });
  fireEvent.change(screen.getByLabelText('File (CSV or Excel)'), { target: { files: [file] } });
  fireEvent.change(screen.getByDisplayValue(/^\d{4}-\d{2}-\d{2}$/), { target: { value: '2026-09-30' } });
  return file;
}

beforeEach(() => {
  mocks.importOpenItems.mockReset();
  mocks.downloadOpenItemsTemplate.mockReset().mockResolvedValue(undefined);
});

describe('OpenItemsImportModal', () => {
  it('checks the file before anything can be imported', () => {
    renderModal();
    expect(screen.getByRole('button', { name: 'Check file' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Import (0)' })).toBeDisabled();
  });

  it('shows why rows fail in the reader\'s words and keeps the import closed', async () => {
    mocks.importOpenItems.mockResolvedValue(
      result({
        ready: 0,
        errors: 2,
        control_totals: [],
        rows: [
          row({ row: 2 }),
          row({
            row: 3,
            status: 'error',
            code: 'contact_name_unknown',
            params: { name: 'Nobody Ltd' },
            message: 'server wording',
            contact_id: null,
            contact_name: null,
            counterparty: 'Nobody Ltd',
          }),
          row({
            row: 4,
            status: 'error',
            code: 'amount_invalid',
            params: { column: 'retention_held', value: '1,234' },
            message: 'server wording',
          }),
        ],
      }),
    );
    renderModal();
    const file = chooseFile();
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }));
    expect(await screen.findByText('No contact named Nobody Ltd. Add or import the contacts first.')).toBeInTheDocument();
    expect(
      screen.getByText("Retention held '1,234' is not an amount that reads one way only (write it as 1234.56)."),
    ).toBeInTheDocument();
    expect(screen.getByTestId('open-items-summary')).toHaveTextContent('Rows with errors: 2.');
    expect(mocks.importOpenItems).toHaveBeenCalledWith('proj-1', file, '2026-09-30', true);
    expect(screen.getByRole('button', { name: 'Import (0)' })).toBeDisabled();
  });

  it('shows the control totals of a clean file and imports it with the same cut-over', async () => {
    mocks.importOpenItems
      .mockResolvedValueOnce(result({}))
      .mockResolvedValueOnce(result({ dry_run: false, imported: 1, ready: 0, rows: [row({ status: 'imported' })] }));
    renderModal();
    const file = chooseFile();
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }));
    expect(await screen.findByTestId('open-items-totals')).toHaveTextContent('Receivable · CAD');
    fireEvent.click(screen.getByRole('button', { name: 'Import (1)' }));
    await waitFor(() => expect(mocks.importOpenItems).toHaveBeenLastCalledWith('proj-1', file, '2026-09-30', false));
    expect(await screen.findByText('Imported: 1. They now show in ageing and statements of account.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check file' })).not.toBeInTheDocument();
  });

  it('names the columns a file does not have', async () => {
    mocks.importOpenItems.mockResolvedValue(
      result({ missing_columns: ['direction', 'invoice_date'], rows: [], control_totals: [], ready: 0 }),
    );
    renderModal();
    chooseFile();
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }));
    expect(await screen.findByText('The file does not name these columns: direction, invoice_date')).toBeInTheDocument();
  });

  it('a new file or cut-over date asks for a new check', async () => {
    mocks.importOpenItems.mockResolvedValue(result({}));
    renderModal();
    chooseFile();
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }));
    await screen.findByTestId('open-items-totals');
    fireEvent.change(screen.getByDisplayValue('2026-09-30'), { target: { value: '2026-09-29' } });
    expect(screen.queryByTestId('open-items-totals')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import (0)' })).toBeDisabled();
  });
});
