// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Correcting a sheet from its detail panel.
 *
 * The backend has accepted `PATCH /v1/documents/sheets/{id}` all along, but the
 * panel only displayed fields, so a title block read wrongly (a revision of
 * "ole" off an Italian drawing) stayed wrong. These tests drive the edit form
 * against the real `updateSheet` call with the network stubbed at `apiPatch`,
 * so the URL and the body the backend receives stay under test.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPatch: vi.fn() };
});

import { apiGet, apiPatch } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { SheetDetailDrawer } from './SheetDetailDrawer';
import { orderStack } from './sheetStack';
import { buildSheetPatch, validateSheetForm } from './SheetEditForm';

const SHEET = {
  id: 'sheet-1',
  project_id: 'proj-1',
  document_id: 'doc-1',
  page_number: 1,
  sheet_number: null,
  sheet_title: 'Pianta piano terra',
  discipline: null,
  revision: 'ole',
  revision_date: null,
  scale: '1:100',
  is_current: true,
  previous_version_id: null,
  thumbnail_path: null,
  metadata: {},
  created_by: 'u',
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
};

function routeApi() {
  (apiGet as any).mockImplementation((url: string) => {
    if (url.startsWith('/v1/documents/sheets/disciplines/')) return Promise.resolve(['Architectural']);
    if (/\/versions\/$/.test(url)) return Promise.resolve({ current: SHEET, history: [] });
    return Promise.reject(new Error(`unexpected URL: ${url}`));
  });
}

function renderDrawer(sheet = SHEET, onSheetChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SheetDetailDrawer sheet={sheet} onClose={() => {}} onSheetChange={onSheetChange} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onSheetChange, invalidate };
}

describe('SheetDetailDrawer editing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ userRole: 'editor' });
    routeApi();
  });

  it('patches only the changed fields and hands the saved row back', async () => {
    const saved = { ...SHEET, sheet_number: 'TAV_01', revision: '02', revision_date: '2025-03-12T00:00:00Z' };
    (apiPatch as any).mockResolvedValue(saved);
    const { onSheetChange, invalidate } = renderDrawer();

    fireEvent.click(await screen.findByRole('button', { name: /Edit details/ }));
    fireEvent.change(screen.getByLabelText('Sheet #'), { target: { value: ' TAV_01 ' } });
    fireEvent.change(screen.getByLabelText('Rev'), { target: { value: '02' } });
    fireEvent.change(screen.getByLabelText('Issue Date'), { target: { value: '2025-03-12' } });
    fireEvent.change(screen.getByLabelText('Scale'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(apiPatch).toHaveBeenCalledTimes(1));
    expect(apiPatch).toHaveBeenCalledWith('/v1/documents/sheets/sheet-1', {
      sheet_number: 'TAV_01',
      revision: '02',
      revision_date: '2025-03-12',
      // A cleared field goes as null, never as an empty string.
      scale: null,
    });
    await waitFor(() => expect(onSheetChange).toHaveBeenCalledWith(saved));
    // The restack can move other rows, so the register and the stack refetch.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['sheets', 'proj-1'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['sheet-versions'] });
    // Back in view mode once saved.
    expect(await screen.findByRole('button', { name: /Edit details/ })).toBeInTheDocument();
  });

  it('refuses a value longer than the backend accepts without calling it', async () => {
    renderDrawer();

    fireEvent.click(await screen.findByRole('button', { name: /Edit details/ }));
    fireEvent.change(screen.getByLabelText('Rev'), { target: { value: 'X'.repeat(51) } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('At most 50 characters.')).toBeInTheDocument();
    expect(apiPatch).not.toHaveBeenCalled();
  });

  it('keeps the form open and says why when the save fails', async () => {
    (apiPatch as any).mockRejectedValue(new Error('Sheet not found'));
    renderDrawer();

    fireEvent.click(await screen.findByRole('button', { name: /Edit details/ }));
    fireEvent.change(screen.getByLabelText('Rev'), { target: { value: '02' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The changes could not be saved.');
    expect(alert).toHaveTextContent('Sheet not found');
    expect(screen.getByLabelText('Rev')).toHaveValue('02');
  });

  it('offers no edit to a role the PATCH would refuse', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderDrawer();

    expect(await screen.findByText('Pianta piano terra', { selector: 'dd' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Edit details/ })).not.toBeInTheDocument();
  });

  it('flags a revision whose order against the one it replaced is unclear', async () => {
    renderDrawer({ ...SHEET, metadata: { revision_order_unclear: true } });

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Revision order unclear, check')).toBeInTheDocument();
  });
});

describe('sheet edit helpers', () => {
  const t = (_key: string, opts: any) => opts.defaultValue.replace('{{max}}', String(opts.max));

  it('builds an empty patch when nothing changed', () => {
    const values = {
      sheet_number: '',
      sheet_title: 'Pianta piano terra',
      revision: 'ole',
      discipline: '',
      scale: '1:100',
      revision_date: '',
    };
    expect(buildSheetPatch(SHEET, values)).toEqual({});
  });

  it('rejects a partial date', () => {
    const values = {
      sheet_number: '',
      sheet_title: '',
      revision: '',
      discipline: '',
      scale: '',
      revision_date: '2025-3',
    };
    expect(validateSheetForm(values, t).revision_date).toBe('Enter a complete date.');
  });
});

describe('orderStack', () => {
  const row = (id: string, prev: string | null, created: string, revision: string) => ({
    ...SHEET,
    id,
    previous_version_id: prev,
    created_at: created,
    revision,
  });

  it('puts an older revision uploaded late beneath the newer one', () => {
    // A uploaded last but filed beneath B: B names A as the one it replaced.
    const a = row('a', null, '2026-10-03T00:00:00Z', 'A');
    const b = row('b', 'a', '2026-10-01T00:00:00Z', 'B');
    expect(orderStack([a, b]).map((r) => r.revision)).toEqual(['B', 'A']);
  });
});
