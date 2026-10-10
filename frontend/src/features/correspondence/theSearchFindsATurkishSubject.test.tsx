// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The correspondence log filters on the subject, the reference number, the
// sender and every recipient, so its filter is the one that reads a list of
// values per row as well as single columns. It used `toLowerCase()` on each,
// which leaves the Turkish dotted capital and the dotless letter unreachable
// from a keyboard without them. These render the page whole and type into the
// real search box.
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
  apiDelete: vi.fn(),
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

vi.mock('@/features/tasks', () => ({ CreateTaskFromSourceDialog: () => null }));

import { CorrespondencePage } from './CorrespondencePage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const PROJECT = { id: 'p-1', name: 'Veri Merkezi' };

// "Isitma tesisati gecikme bildirimi" as written in Turkish.
const HEATING_SUBJECT = 'Isıtma tesisatı gecikme bildirimi';
// "Istanbul santiyesi erisim yazisi" with the dotted capital.
const ISTANBUL_SUBJECT = 'İstanbul şantiyesi erişim yazısı';
const OTHER_SUBJECT = 'Notice of delayed access to plant room';

function row(id: string, reference: string, subject: string, from: string | null, to: string[]) {
  return {
    id,
    project_id: 'p-1',
    reference_number: reference,
    subject,
    direction: 'outgoing',
    correspondence_type: 'letter',
    from_contact_id: from,
    to_contact_ids: to,
    date_sent: '2026-10-02',
    date_received: null,
    status: 'open',
    notes: null,
    created_by: null,
    created_at: '2026-10-02T08:00:00Z',
    updated_at: '2026-10-02T08:00:00Z',
  };
}

const ROWS = [
  row('c-1', 'COR-001', HEATING_SUBJECT, null, []),
  row('c-2', 'COR-002', ISTANBUL_SUBJECT, null, []),
  // The recipients are stored as given; one of them is a Turkish party name.
  row('c-3', 'COR-003', OTHER_SUBJECT, 'main-contractor', ['owner-rep', 'İşveren vekili']),
];

function renderPage() {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/correspondence/')) {
      return Promise.resolve({ items: ROWS, total: ROWS.length, offset: 0, limit: 100 });
    }
    if (path.startsWith('/v1/projects')) return Promise.resolve([PROJECT]);
    if (path.includes('?')) return Promise.resolve({ items: [], total: 0, offset: 0, limit: 100 });
    return Promise.resolve([]);
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/correspondence']}>
        <CorrespondencePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Type into the log's search box and return the subjects still listed. */
async function search(query: string): Promise<string[]> {
  const box = screen.getByLabelText(/search correspondence/i) as HTMLInputElement;
  fireEvent.change(box, { target: { value: query } });
  await waitFor(() => expect(box.value).toBe(query));
  return [HEATING_SUBJECT, ISTANBUL_SUBJECT, OTHER_SUBJECT].filter(
    (subject) => screen.queryByText(subject) !== null,
  );
}

beforeEach(() => {
  useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: PROJECT.name });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('searching the correspondence log for Turkish text', () => {
  it('finds the dotless spelling from a query in capitals', async () => {
    renderPage();
    await screen.findByText(HEATING_SUBJECT);
    expect(await search('ISITMA')).toEqual([HEATING_SUBJECT]);
  });

  it('finds the dotted capital from a plain lower-case query', async () => {
    renderPage();
    await screen.findByText(ISTANBUL_SUBJECT);
    expect(await search('istanbul')).toEqual([ISTANBUL_SUBJECT]);
  });

  it('finds an accented subject from a query typed without diacritics', async () => {
    renderPage();
    await screen.findByText(ISTANBUL_SUBJECT);
    expect(await search('santiyesi erisim yazisi')).toEqual([ISTANBUL_SUBJECT]);
  });

  it('finds a row by one of its recipients, typed without diacritics', async () => {
    renderPage();
    await screen.findByText(OTHER_SUBJECT);
    // The second recipient of the third row, as a phone keyboard types it.
    expect(await search('isveren')).toEqual([OTHER_SUBJECT]);
  });

  it('skips a row with no sender and no recipients instead of failing on it', async () => {
    renderPage();
    await screen.findByText(OTHER_SUBJECT);
    expect(await search('main-contractor')).toEqual([OTHER_SUBJECT]);
    expect(await search('no such record')).toEqual([]);
  });
});
