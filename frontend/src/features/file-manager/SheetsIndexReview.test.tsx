// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Confirming a machine-read drawing set.
 *
 * A sheet read by OCR, or from a text layer too thin to trust, is held until a
 * person confirms it. These drive the register against stubbed endpoints and
 * pin the three things the user sees: how each row says it was read, the
 * "Needs review" filter, and the bulk confirmation behind a dialog.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn() };
});

import { apiGet, apiPost } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { SheetsIndexPage } from './SheetsIndexPage';
import { bulkConfirmable, machineReadFields, needsReview } from './sheetExtraction';

function sheet(id: string, number: string, metadata: Record<string, unknown>, over = {}) {
  return {
    id,
    project_id: 'proj-1',
    sheet_number: number,
    sheet_title: `Title ${number}`,
    discipline: 'Architectural',
    revision: 'B',
    revision_date: null,
    scale: null,
    document_id: 'doc-1',
    page_number: 1,
    is_current: true,
    previous_version_id: null,
    thumbnail_path: null,
    metadata,
    created_at: '2026-03-14T10:00:00Z',
    updated_at: '2026-03-14T10:00:00Z',
    ...over,
  };
}

const TEXT_SHEET = sheet('s-text', 'A-101', {
  extraction: { source: 'text', confidence: 0.95, needs_review: false, reason: null },
});
const OCR_SHEET = sheet(
  's-ocr',
  'A-102',
  { extraction: { source: 'ocr', confidence: 0.72, needs_review: true, reason: 'ocr_read' }, status: 'pending_review' },
  { is_current: false },
);
const HIGH_OCR_SHEET = sheet('s-ocr-hi', 'A-103', {
  extraction: { source: 'ocr', confidence: 0.88, needs_review: true, reason: 'ocr_read' },
});
const UNREAD_SHEET = sheet('s-none', 'A-104', {
  extraction: { source: 'ocr', confidence: 0, needs_review: true, reason: 'ocr_unavailable' },
});
const SHEETS = [TEXT_SHEET, OCR_SHEET, HIGH_OCR_SHEET, UNREAD_SHEET];

function routeApi(sheets = SHEETS) {
  (apiGet as any).mockImplementation((url: string) => {
    if (url.startsWith('/v1/projects/')) return Promise.resolve([{ id: 'proj-1', name: 'Riverside HQ' }]);
    if (url.startsWith('/v1/documents/sheets/disciplines/')) return Promise.resolve(['Architectural']);
    if (/^\/v1\/documents\/sheets\/[^/]+\/versions\/$/.test(url)) {
      return Promise.resolve({ current: sheets[0], history: [] });
    }
    if (url.startsWith('/v1/documents/sheets/')) {
      return Promise.resolve({ items: sheets, total: sheets.length, offset: 0, limit: 500 });
    }
    return Promise.reject(new Error(`unexpected URL: ${url}`));
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/sheets']}>
        <SheetsIndexPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('sheet extraction helpers', () => {
  it('reads the extraction block and the hold', () => {
    expect(needsReview(TEXT_SHEET)).toBe(false);
    expect(needsReview(OCR_SHEET)).toBe(true);
    expect(needsReview(sheet('x', 'X', {}))).toBe(false);
  });

  it('bulk-confirms only held, numbered, readable sheets at or above the threshold', () => {
    expect(bulkConfirmable(SHEETS).map((s) => s.id)).toEqual(['s-ocr-hi']);
    expect(bulkConfirmable(SHEETS, 0.7).map((s) => s.id)).toEqual(['s-ocr', 's-ocr-hi']);
  });

  it('marks as machine read only the fields nobody has typed', () => {
    const edited = sheet('e', 'E-1', {
      extraction: { source: 'ocr', confidence: 0.7, needs_review: true, reason: 'ocr_read' },
      manually_edited: ['revision'],
    });
    expect([...machineReadFields(edited)].sort()).toEqual(['discipline', 'sheet_number', 'sheet_title']);
    expect(machineReadFields(TEXT_SHEET).size).toBe(0);
  });
});

describe('SheetsIndexPage review of machine-read sheets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ userRole: 'editor' });
    useProjectContextStore.getState().clearProject();
    useProjectContextStore.getState().setActiveProject('proj-1', 'Riverside HQ');
  });

  it('says on each row how the title block was read and how sure the reader was', async () => {
    routeApi();
    renderPage();

    expect(await screen.findByText('Read from text, 95%')).toBeInTheDocument();
    expect(screen.getByText('Read by OCR, 72%')).toBeInTheDocument();
    expect(screen.getByText('Not read: OCR unavailable')).toBeInTheDocument();
  });

  it('narrows the register to the sheets that need review with the chip', async () => {
    routeApi();
    renderPage();

    const chip = await screen.findByRole('button', { name: /Needs review/ });
    expect(chip).toHaveTextContent('3');
    expect(screen.getByText('A-101')).toBeInTheDocument();

    fireEvent.click(chip);

    await waitFor(() => expect(screen.queryByText('A-101')).not.toBeInTheDocument());
    expect(screen.getByText('A-102')).toBeInTheDocument();
    expect(screen.getByText('A-103')).toBeInTheDocument();
  });

  it('confirms one row from its own button', async () => {
    routeApi();
    (apiPost as any).mockResolvedValue(OCR_SHEET);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Confirm the reading of sheet A-102' }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/v1/documents/sheets/s-ocr/confirm-extraction/', undefined),
    );
  });

  it('offers no row confirmation for a page OCR could not read', async () => {
    routeApi();
    renderPage();

    await screen.findByText('A-104');
    expect(screen.queryByRole('button', { name: 'Confirm the reading of sheet A-104' })).not.toBeInTheDocument();
  });

  it('asks before confirming everything above 80% and posts the threshold', async () => {
    routeApi();
    (apiPost as any).mockResolvedValue({ confirmed: 1, below_threshold: 1, ocr_unavailable: 1, no_number: 0 });
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Confirm all above 80%' }));
    expect(apiPost).not.toHaveBeenCalled();

    const dialog = await screen.findByRole('alertdialog').catch(() => screen.findByRole('dialog'));
    expect(within(dialog).getByText(/Confirm all machine-read sheets above 80%/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/v1/documents/sheets/confirm-bulk/', {
        project_id: 'proj-1',
        min_confidence: 0.8,
      }),
    );
    expect(await screen.findByText(/^1 sheets? confirmed.$/)).toBeInTheDocument();
  });

  it('keeps the review controls away from a viewer', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    routeApi();
    renderPage();

    expect(await screen.findByText('A-102')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm all above 80%' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Confirm the reading of sheet/ })).not.toBeInTheDocument();
  });

  it('shows the install hint, not a raw error, for a sheet OCR could not read', async () => {
    routeApi();
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'A-104' }));
    const dialog = await screen.findByRole('dialog');

    expect(within(dialog).getByText('Title block not read')).toBeInTheDocument();
    expect(within(dialog).getByText(/installing tesseract-ocr/)).toBeInTheDocument();
  });

  it('names the sheet a held one would supersede', async () => {
    const held = sheet(
      's-held',
      'A-101',
      {
        extraction: { source: 'ocr', confidence: 0.72, needs_review: true, reason: 'ocr_read' },
        status: 'pending_review',
        would_supersede: ['s-text'],
      },
      { is_current: false, revision: 'C' },
    );
    routeApi([TEXT_SHEET, held]);
    renderPage();

    await screen.findByText('Read by OCR, 72%');
    const [, heldButton] = await screen.findAllByRole('button', { name: 'A-101' });
    fireEvent.click(heldButton);
    const dialog = await screen.findByRole('dialog');

    expect(within(dialog).getByText('Held: not yet superseding A-101 B')).toBeInTheDocument();
  });
});
