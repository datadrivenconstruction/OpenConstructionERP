// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The register filter lower-cased both sides with `toLowerCase()`, which does
// not bring the Turkish dotted capital or the dotless letter to anything a
// keyboard without them can type. A submittal for a project in Istanbul was
// therefore not found by typing "istanbul", and a title in capitals was not
// found by its lower-case spelling. These render the page whole and type into
// the real search box. The rows carry no spec section and no ball-in-court
// name on purpose: the filter reads optional columns, and a missing one must
// be skipped, not thrown on.
//
// Turkish letters are written as escapes so the four i's cannot be swapped by
// an editor or a formatter.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  downloadWithAuth: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), setOpen: vi.fn(), custom: [] }),
}));

vi.mock('@/features/approval-routes', () => ({
  ApprovalInstanceCard: () => null,
  ApprovalTargetBadge: () => null,
}));

import { SubmittalsPage } from './SubmittalsPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const PROJECT = { id: 'p-1', name: 'Veri Merkezi' };

// "Istanbul" with the dotted capital, and "isitma" with two dotless letters.
const ISTANBUL_TITLE = 'İstanbul soğutma grubu çizimleri';
const HEATING_TITLE = 'Kat ısıtma kolektörü';
const CAPITALS_TITLE = 'YANGIN POMPASI TEST RAPORU';
const OTHER_TITLE = 'Cable tray shop drawings';

function row(id: string, number: string, title: string) {
  return {
    id,
    project_id: 'p-1',
    submittal_number: number,
    title,
    spec_section: null,
    submittal_type: 'shop_drawing',
    status: 'submitted',
    ball_in_court: null,
    ball_in_court_name: null,
    revision: 1,
    date_submitted: '2026-10-01',
    date_required: '2026-10-15',
    description: null,
    linked_boq_item_ids: [],
    metadata: {},
    created_by: null,
    created_at: '2026-10-01T08:00:00Z',
    updated_at: '2026-10-01T08:00:00Z',
  };
}

const ROWS = [
  row('s-1', 'SUB-001', ISTANBUL_TITLE),
  row('s-2', 'SUB-002', HEATING_TITLE),
  row('s-3', 'SUB-003', CAPITALS_TITLE),
  row('s-4', 'SUB-004', OTHER_TITLE),
];

function renderPage() {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/submittals/')) return Promise.resolve(ROWS);
    if (path.startsWith('/v1/projects')) return Promise.resolve([PROJECT]);
    return Promise.resolve([]);
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/submittals']}>
        <SubmittalsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Type into the register's search box and return the titles still listed. */
async function search(query: string): Promise<string[]> {
  const box = screen.getByLabelText(/search submittals/i) as HTMLInputElement;
  fireEvent.change(box, { target: { value: query } });
  await waitFor(() => expect(box.value).toBe(query));
  return [ISTANBUL_TITLE, HEATING_TITLE, CAPITALS_TITLE, OTHER_TITLE].filter(
    (title) => screen.queryByText(title) !== null,
  );
}

beforeEach(() => {
  useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: PROJECT.name });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('searching the submittal register for Turkish titles', () => {
  it('finds the dotted capital from a plain lower-case query', async () => {
    renderPage();
    await screen.findByText(ISTANBUL_TITLE);
    expect(await search('istanbul')).toEqual([ISTANBUL_TITLE]);
  });

  it('finds the dotless spelling from a query in capitals', async () => {
    renderPage();
    await screen.findByText(HEATING_TITLE);
    expect(await search('ISITMA')).toEqual([HEATING_TITLE]);
  });

  it('finds a title written in capitals from its lower-case Turkish spelling', async () => {
    renderPage();
    await screen.findByText(CAPITALS_TITLE);
    // "yangin pompasi" typed correctly, with dotless letters.
    expect(await search('yangın pompası')).toEqual([CAPITALS_TITLE]);
  });

  it('finds an accented title from a query typed without diacritics', async () => {
    renderPage();
    await screen.findByText(ISTANBUL_TITLE);
    expect(await search('sogutma grubu cizimleri')).toEqual([ISTANBUL_TITLE]);
  });

  it('still narrows the list, and still finds by number', async () => {
    renderPage();
    await screen.findByText(OTHER_TITLE);
    expect(await search('cable tray')).toEqual([OTHER_TITLE]);
    expect(await search('sub-002')).toEqual([HEATING_TITLE]);
    expect(await search('no such record')).toEqual([]);
  });
});
