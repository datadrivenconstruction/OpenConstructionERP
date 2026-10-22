// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The recipient import shows every row checked before anything is stored, and
// only the confirm click sends the second (storing) request.

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { RecipientImportDialog } from './RecipientImportDialog';
import * as api from './api';

vi.mock('./api', async (orig) => ({ ...(await orig<typeof api>()), importRecipients: vi.fn() }));

const row = (line: number, email: string, issues: string[] = []) => ({
  line,
  company: `Firm ${line}`,
  contact_name: '',
  email,
  trade: 'Steel',
  vat_id: '',
  issues,
  valid: issues.length === 0,
});

function setup(onImported = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <RecipientImportDialog open onClose={vi.fn()} packageId="p1" onImported={onImported} />
    </QueryClientProvider>,
  );
  return onImported;
}

const pickFile = () =>
  fireEvent.change(screen.getByTestId('recipient-import-file'), {
    target: { files: [new File(['x'], 'firms.csv', { type: 'text/csv' })] },
  });

describe('recipient import dialog', () => {
  beforeEach(() => vi.mocked(api.importRecipients).mockReset());

  it('previews rows with their issues and stores only after confirm', async () => {
    vi.mocked(api.importRecipients).mockImplementation(async (_p, _f, confirm) =>
      (confirm
        ? { added: [{ id: 'r1' }], skipped: [row(3, 'bad', ['email_invalid'])], contacts_created: 1, contacts_linked: 0 }
        : { total: 2, valid: 1, rows: [row(2, 'a@a.io'), row(3, 'bad', ['email_invalid'])] }) as never,
    );
    const onImported = setup();
    pickFile();

    await waitFor(() => expect(screen.getAllByTestId('recipient-import-row')).toHaveLength(2));
    expect(screen.getByText('Invalid email')).toBeTruthy();
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(vi.mocked(api.importRecipients)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.importRecipients).mock.calls[0]![2]).toBe(false);

    fireEvent.click(screen.getByText('Add valid rows'));
    await waitFor(() => expect(onImported).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.importRecipients).mock.calls[1]![2]).toBe(true);
  });

  it('keeps the confirm button off when no row is valid', async () => {
    vi.mocked(api.importRecipients).mockResolvedValue({
      total: 1,
      valid: 0,
      rows: [row(2, 'bad', ['email_invalid'])],
    } as never);
    setup();
    pickFile();
    await waitFor(() => expect(screen.getAllByTestId('recipient-import-row')).toHaveLength(1));
    expect((screen.getByText('Add valid rows').closest('button') as HTMLButtonElement).disabled).toBe(true);
  });
});
