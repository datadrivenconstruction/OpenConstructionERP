// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ importCodeList: vi.fn() }));
const toast = vi.hoisted(() => ({ addToast: vi.fn() }));
vi.mock('./structureApi', async (importOriginal) => {
  const real = await importOriginal<typeof import('./structureApi')>();
  return { ...real, costStructureApi: api };
});
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign((selector: (s: typeof toast) => unknown) => selector(toast), { getState: () => toast }),
}));

import { ApiError } from '@/shared/lib/api';
import { CodeListImportModal, suggestKey } from './CodeListImportModal';

function renderModal() {
  const onClose = vi.fn();
  const onImported = vi.fn();
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CodeListImportModal open projectId="p1" onClose={onClose} onImported={onImported} />
    </QueryClientProvider>,
  );
  return { onClose, onImported };
}

function fill() {
  const file = new File(['code,title\n1,A\n'], 'codes.csv', { type: 'text/csv' });
  fireEvent.change(screen.getByTestId('code-list-file'), { target: { files: [file] } });
  fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Company Codes 2026' } });
  return file;
}

const base = { key: 'company-codes-2026', name: 'Company Codes 2026', entry_count: 2, depth: 2, code_list: null };

beforeEach(() => {
  api.importCodeList.mockReset();
  toast.addToast.mockReset();
});

describe('suggestKey', () => {
  it('turns a name into a key that starts with a letter', () => {
    expect(suggestKey('Company Codes 2026')).toBe('company-codes-2026');
    expect(suggestKey('2026 list')).toBe('list-2026-list');
    expect(suggestKey('')).toBe('');
  });
});

describe('<CodeListImportModal>', () => {
  it('checks the file first and lists the row problems, keeping import locked', async () => {
    api.importCodeList.mockResolvedValueOnce({
      ...base,
      ok: false,
      dry_run: true,
      issues: [{ row: 3, code: '11', problem: 'duplicate_code', params: { first_row: 2 } }],
      preview: [],
    });
    renderModal();
    const file = fill();
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }));
    await waitFor(() =>
      expect(api.importCodeList).toHaveBeenCalledWith('p1', { file, key: 'company-codes-2026', name: 'Company Codes 2026', dryRun: true }),
    );
    expect(await screen.findByText('This code already appears on row 2.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled();
  });

  it('imports after a clean check and reports the stored list', async () => {
    api.importCodeList
      .mockResolvedValueOnce({ ...base, ok: true, dry_run: true, issues: [], preview: [{ code: '1', title: 'Shell', parent: null, level: 1 }] })
      .mockResolvedValueOnce({ ...base, ok: true, dry_run: false, issues: [], preview: [] });
    const { onClose, onImported } = renderModal();
    fill();
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }));
    expect(await screen.findByText('Shell')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(onImported).toHaveBeenCalledWith('company-codes-2026'));
    expect(api.importCodeList.mock.calls[1]![1].dryRun).toBe(false);
    expect(onClose).toHaveBeenCalled();
    expect(toast.addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }));
  });

  it('counts codes and levels with plural forms', async () => {
    api.importCodeList
      .mockResolvedValueOnce({ ...base, entry_count: 1, depth: 1, ok: true, dry_run: true, issues: [], preview: [] })
      .mockResolvedValueOnce({ ...base, entry_count: 12, depth: 3, ok: true, dry_run: false, issues: [], preview: [] });
    renderModal();
    fill();
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }));
    expect(await screen.findByText('The file is fine: 1 code in 1 level.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(toast.addToast).toHaveBeenCalled());
    expect(toast.addToast.mock.calls[0]![0].message).toBe('Company Codes 2026 is stored with 12 codes in 3 levels.');
  });

  it('shows a file-level refusal as a sentence', async () => {
    api.importCodeList.mockRejectedValueOnce(
      new ApiError(400, 'Bad Request', { detail: { problem: 'missing_code_column', message: 'x', params: {} } }),
    );
    renderModal();
    fill();
    fireEvent.click(screen.getByRole('button', { name: 'Check file' }));
    expect(await screen.findByText('The file has no column named code.')).toBeInTheDocument();
  });
});
