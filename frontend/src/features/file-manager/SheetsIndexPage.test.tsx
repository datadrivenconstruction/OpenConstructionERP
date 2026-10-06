// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tests for the drawing-sheet index.
 *
 * The page was written complete but never routed, so nothing had ever
 * rendered it against a response. These drive it through the real endpoints
 * it calls - /v1/documents/sheets/, .../disciplines/ and .../{id}/versions/ -
 * with the network stubbed at ``apiGet``, and cover what a user depends on:
 * the discipline chips, the free-text search, and the way out of the table
 * into the modules that open a drawing.
 *
 * The split control is covered against a stubbed ``fetch`` rather than a
 * stubbed ``./api``, so the endpoint URL and the multipart body stay under
 * test - mocking the module would leave nothing to check but that a function
 * was called.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

// Partial mock - only ``apiGet`` is faked. ``./api`` reaches for
// ``extractErrorMessageFromBody`` on the failure path, and replacing the whole
// module would make it undefined, so the split-failure test would blow up on a
// missing helper instead of surfacing the backend's message.
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: vi.fn(),
    apiPost: vi.fn(),
  };
});

import { apiGet, apiPost } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { SheetsIndexPage } from './SheetsIndexPage';

const SHEETS = [
  {
    id: 'sheet-1',
    project_id: 'proj-1',
    sheet_number: 'A-101',
    sheet_title: 'Ground Floor Plan',
    discipline: 'Architectural',
    revision: 'C',
    revision_date: null,
    scale: '1:100',
    document_id: 'doc-1',
    page_number: 1,
    is_current: true,
    previous_version_id: null,
    thumbnail_path: null,
    metadata: {},
    created_at: '2026-03-14T10:00:00Z',
    updated_at: '2026-03-14T10:00:00Z',
  },
  {
    id: 'sheet-2',
    project_id: 'proj-1',
    sheet_number: 'S-201',
    sheet_title: 'Foundation Details',
    discipline: 'Structural',
    revision: 'A',
    revision_date: null,
    scale: '1:50',
    document_id: 'doc-2',
    page_number: 4,
    is_current: false,
    previous_version_id: null,
    thumbnail_path: null,
    metadata: {},
    created_at: '2026-02-01T10:00:00Z',
    updated_at: '2026-02-01T10:00:00Z',
  },
];

const DISCIPLINES = ['Architectural', 'Structural'];

/** The revision that replaced S-201, as /versions/ reports it. `current` is
 *  the sheet that was asked about, not the newest one. */
const VERSIONS_SHEET_2 = {
  current: SHEETS[1],
  history: [
    {
      ...SHEETS[1],
      id: 'sheet-2b',
      revision: 'D',
      is_current: true,
      previous_version_id: 'sheet-2',
      created_at: '2026-06-02T10:00:00Z',
    },
  ],
};

/** Route each stubbed URL to its payload, so a wrong URL fails loudly.
 *
 *  Order matters: every sheet URL starts with `/v1/documents/sheets/`, so the
 *  two longer paths have to be matched before the list branch swallows them
 *  and hands a version lookup the whole sheet array. */
function routeApi(sheets = SHEETS, disciplines = DISCIPLINES, versions = VERSIONS_SHEET_2) {
  (apiGet as any).mockImplementation((url: string) => {
    if (url.startsWith('/v1/projects/')) {
      return Promise.resolve([{ id: 'proj-1', name: 'Riverside HQ' }]);
    }
    if (url.startsWith('/v1/documents/sheets/disciplines/')) {
      return Promise.resolve(disciplines);
    }
    if (/^\/v1\/documents\/sheets\/[^/]+\/versions\/$/.test(url)) {
      return Promise.resolve(versions);
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

/** Open the detail drawer for one sheet and return its dialog element. */
async function openDrawer(sheetNumber: string) {
  fireEvent.click(await screen.findByRole('button', { name: sheetNumber }));
  return screen.findByRole('dialog');
}

/** The hidden native input both split triggers proxy their click to. */
function pdfInput(): HTMLInputElement {
  return screen.getByLabelText(/Drawing set PDF/i) as HTMLInputElement;
}

function pdfFile(name = 'drawing-set.pdf'): File {
  return new File(['%PDF-1.7'], name, { type: 'application/pdf' });
}

/** The EmptyState block, scoped from its own heading, so "the empty state
 *  offers the action" cannot be satisfied by the copy of the button that
 *  lives up beside the search box. */
function emptyStateBlock(title: string): HTMLElement {
  return screen.getByText(title).parentElement as HTMLElement;
}

describe('SheetsIndexPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectContextStore.getState().clearProject();
    useProjectContextStore.getState().setActiveProject('proj-1', 'Riverside HQ');
  });

  afterEach(() => {
    // Hand `fetch` back to the wrapper in test/setup.ts.
    vi.unstubAllGlobals();
  });

  it('lists the sheets returned for the active project', async () => {
    routeApi();

    renderPage();

    expect(await screen.findByText('A-101')).toBeInTheDocument();
    expect(screen.getByText('Ground Floor Plan')).toBeInTheDocument();
    expect(screen.getByText('S-201')).toBeInTheDocument();
    expect(screen.getByText('Foundation Details')).toBeInTheDocument();
  });

  it('scopes the request to the active project', async () => {
    routeApi();

    renderPage();

    // Asserted as an anchored shape rather than a quoted route: it pins the
    // project scoping more tightly than a substring would, and it keeps the
    // envelope gate from reading a test expectation as a call site.
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith(
        expect.stringMatching(/^\/v1\/documents\/sheets\/\?project_id=proj-1(&|$)/),
      ),
    );
  });

  it('filters to one discipline when its chip is clicked', async () => {
    routeApi();

    renderPage();

    // Wait for both rows before filtering, so a chip that does nothing
    // cannot pass by virtue of the list not having rendered yet.
    expect(await screen.findByText('A-101')).toBeInTheDocument();
    expect(screen.getByText('S-201')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Structural/ }));

    await waitFor(() => expect(screen.queryByText('A-101')).not.toBeInTheDocument());
    expect(screen.getByText('S-201')).toBeInTheDocument();
  });

  it('searches across number, title, discipline and revision', async () => {
    routeApi();

    renderPage();

    expect(await screen.findByText('A-101')).toBeInTheDocument();

    const box = screen.getByPlaceholderText(/search/i);
    fireEvent.change(box, { target: { value: 'foundation' } });

    await waitFor(() => expect(screen.queryByText('A-101')).not.toBeInTheDocument());
    expect(screen.getByText('S-201')).toBeInTheDocument();
  });

  it('shows an empty state rather than a bare table when there are no sheets', async () => {
    routeApi([], []);

    renderPage();

    // Assert on what the empty branch actually renders. Checking only that
    // 'A-101' is absent would pass just as happily if the page rendered
    // nothing at all, which is the failure this test exists to catch.
    expect(await screen.findByText('No sheets indexed yet')).toBeInTheDocument();
    expect(
      screen.getByText(/every page becomes a sheet here/),
    ).toBeInTheDocument();
    // The "nothing indexed" copy, not the "your filter matched nothing" copy -
    // they are different branches and telling a user to adjust a filter they
    // never set would send them looking for a control that changes nothing.
    expect(screen.queryByText('No matching sheets')).not.toBeInTheDocument();
  });

  it('carries the explainer that says where sheets come from', async () => {
    routeApi();

    renderPage();

    expect(
      await screen.findByText(/How the Drawing Sheet register fits together/),
    ).toBeInTheDocument();
    expect(screen.getByText(/A multi-page PDF is uploaded to Project files/)).toBeInTheDocument();
  });

  it('offers the insights panel toggle', async () => {
    routeApi();

    renderPage();

    expect(await screen.findByRole('button', { name: /Insights/ })).toBeInTheDocument();
  });

  it('opens a detail panel for the sheet whose number is clicked', async () => {
    routeApi();

    renderPage();

    const dialog = await openDrawer('A-101');
    // The heading pins which sheet was opened - clicking S-201's number and
    // getting A-101's panel is exactly the mix-up worth catching. The title
    // appears twice (drawer subtitle and the Title field), hence getAllByText.
    expect(within(dialog).getByRole('heading', { name: 'A-101' })).toBeInTheDocument();
    expect(within(dialog).getAllByText('Ground Floor Plan').length).toBeGreaterThan(0);
    expect(within(dialog).queryByText('Foundation Details')).not.toBeInTheDocument();
  });

  it('links the sheet into the plan room at its own document and page', async () => {
    routeApi();

    renderPage();

    const dialog = await openDrawer('S-201');
    const link = within(dialog).getByRole('link', { name: /Plan room/ });
    // The page number is the whole point: S-201 is page 4 of doc-2, and a link
    // that dropped it would open the drawing set on its cover sheet.
    expect(link).toHaveAttribute('href', '/plan-room?doc=doc-2&page=4');
  });

  it('links the sheet into PDF takeoff as a documents-module source', async () => {
    routeApi();

    renderPage();

    const dialog = await openDrawer('S-201');
    const href = within(dialog)
      .getByRole('link', { name: /takeoff/i })
      .getAttribute('href');
    // `source=document` is what makes takeoff resolve a documents-module id
    // into a takeoff document; without it the viewer opens on nothing.
    expect(href).toContain('source=document');
    expect(href).toContain('doc=doc-2');
    expect(href).toContain('page=4');
    expect(href).toContain('tab=measurements');
  });

  it('links back to the drawing set the sheet was lifted from', async () => {
    routeApi();

    renderPage();

    const dialog = await openDrawer('A-101');
    expect(within(dialog).getByRole('link', { name: /drawing set it came from/ })).toHaveAttribute(
      'href',
      '/files?file=doc-1',
    );
  });

  it('names the revision that superseded an out-of-date sheet', async () => {
    routeApi();

    renderPage();

    const dialog = await openDrawer('S-201');
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith('/v1/documents/sheets/sheet-2/versions/'),
    );
    expect(await within(dialog).findByText(/Replaced by revision D/)).toBeInTheDocument();
  });

  it('says nothing about a replacement for a sheet that is still current', async () => {
    // The chain for A-101 is A-101 alone, so there is no successor to name and
    // claiming one would be worse than the silence.
    routeApi(SHEETS, DISCIPLINES, { current: SHEETS[0], history: [] });

    renderPage();

    const dialog = await openDrawer('A-101');
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith('/v1/documents/sheets/sheet-1/versions/'),
    );
    expect(within(dialog).queryByText(/Replaced by revision/)).not.toBeInTheDocument();
    expect(within(dialog).getByText('Current revision')).toBeInTheDocument();
  });

  /* The "Current?" column answered no with an em-dash, which is the same glyph
     the revision date and scale columns print when they hold nothing. Both
     fixture rows carry `revision_date: null`, so a superseded row printed one
     dash meaning "a later upload replaced this" beside another meaning "nobody
     typed a date", and the two were the same mark. The word was in the markup
     the whole time, but only inside an aria-label, so it reached the part of
     the audience that was not the one being misled. `getByText` reads rendered
     text and cannot be satisfied by an aria-label, so reverting the span to the
     dash turns this red.

     What this does NOT prove: `test/setup.ts` mocks `react-i18next` and its
     `t` returns `defaultValue`, so a passing assertion here says nothing about
     `sheets.is_current_no` existing in the 29 locale files. That was checked
     separately and it is present in all of them. */
  it('says superseded in words, not with the glyph an empty column uses', async () => {
    routeApi();

    renderPage();

    expect(await screen.findByText('S-201')).toBeInTheDocument();
    const row = screen.getByText('S-201').closest('tr');
    expect(row).not.toBeNull();

    expect(within(row as HTMLElement).getByText('Superseded')).toBeInTheDocument();

    // The dash is still in that row, on the columns that genuinely hold
    // nothing. The fix is that the two states stopped looking alike, not that
    // the table lost its way of printing an absent value.
    expect(within(row as HTMLElement).getAllByText('—').length).toBeGreaterThan(0);
  });

  it('leaves a current sheet unlabelled rather than calling it superseded', async () => {
    routeApi();

    renderPage();

    expect(await screen.findByText('A-101')).toBeInTheDocument();
    const row = screen.getByText('A-101').closest('tr');

    expect(within(row as HTMLElement).queryByText('Superseded')).not.toBeInTheDocument();
  });

  it('does not pretend to show a drawing preview it cannot fetch', async () => {
    routeApi();

    renderPage();

    const dialog = await openDrawer('A-101');
    expect(within(dialog).getByText(/No preview available for this sheet yet/)).toBeInTheDocument();
    expect(within(dialog).queryByRole('img')).not.toBeInTheDocument();
  });

  /* ── Splitting a drawing set into the register ─────────────────────── */

  it('offers the split action inside the empty state', async () => {
    routeApi([], []);

    renderPage();
    await screen.findByText('No sheets indexed yet');

    // An empty register is the one place a person has to be told how to fill
    // it, so the action has to be in the empty state itself - not only in the
    // toolbar the eye skips past when the middle of the page says "nothing".
    const empty = emptyStateBlock('No sheets indexed yet');
    expect(
      within(empty).getByRole('button', { name: /Split a PDF into sheets/i }),
    ).toBeInTheDocument();
    expect(pdfInput()).toBeInTheDocument();
  });

  it('leaves the split action out of a filter miss', async () => {
    routeApi();

    renderPage();

    expect(await screen.findByText('A-101')).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/search/i), {
      target: { value: 'nothing matches this' },
    });

    // A search that matched nothing is not fixed by uploading, and an upload
    // button there reads as if the filter had eaten the register.
    const empty = emptyStateBlock('No matching sheets');
    expect(
      within(empty).queryByRole('button', { name: /Split a PDF into sheets/i }),
    ).not.toBeInTheDocument();
  });

  it('posts the picked PDF to the split endpoint for the active project', async () => {
    routeApi([], []);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => [],
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();
    await screen.findByText('No sheets indexed yet');

    const file = pdfFile();
    fireEvent.change(pdfInput(), { target: { files: [file] } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    // The project id is the whole request: without it the endpoint 422s, and
    // with the wrong one the sheets land in somebody else's register.
    expect(url).toBe('/api/v1/documents/sheets/split-pdf/?project_id=proj-1');
    expect(init.method).toBe('POST');
    expect((init.body as FormData).get('file')).toBe(file);
  });

  it('surfaces the backend detail when the split fails', async () => {
    routeApi([], []);
    const detail = 'Failed to process PDF file: page 3 has no text layer';
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail }),
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();
    await screen.findByText('No sheets indexed yet');

    fireEvent.change(pdfInput(), { target: { files: [pdfFile()] } });

    // The backend's own words, verbatim. A generic "upload failed" would send
    // somebody back to re-pick a file that will fail again for the same
    // reason, and silence would be worse still.
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(detail);
  });

  it('repopulates the register from the server once the split lands', async () => {
    // The list starts empty and the server has the rows only after the split,
    // so a table that fills up proves the query was invalidated - a static
    // fixture would fill up whether or not anything was refetched.
    let listed: typeof SHEETS = [];
    (apiGet as any).mockImplementation((url: string) => {
      if (url.startsWith('/v1/projects/')) {
        return Promise.resolve([{ id: 'proj-1', name: 'Riverside HQ' }]);
      }
      if (url.startsWith('/v1/documents/sheets/disciplines/')) {
        return Promise.resolve(listed.length ? DISCIPLINES : []);
      }
      if (url.startsWith('/v1/documents/sheets/')) {
        return Promise.resolve({ items: listed, total: listed.length, offset: 0, limit: 500 });
      }
      return Promise.reject(new Error(`unexpected URL: ${url}`));
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async () => {
        listed = SHEETS;
        return { ok: true, status: 201, json: async () => SHEETS };
      }),
    );

    renderPage();
    await screen.findByText('No sheets indexed yet');

    fireEvent.change(pdfInput(), { target: { files: [pdfFile()] } });

    expect(await screen.findByText('A-101')).toBeInTheDocument();
    expect(screen.getByText('Foundation Details')).toBeInTheDocument();
    // The chip row comes from its own query and goes stale in exactly the
    // same way, so it has to be invalidated too.
    expect(screen.getByRole('button', { name: /Structural/ })).toBeInTheDocument();
  });
});

describe('SheetsIndexPage - re-reading title blocks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectContextStore.getState().clearProject();
    useProjectContextStore.getState().setActiveProject('proj-1', 'Riverside HQ');
    useAuthStore.setState({ userRole: 'editor' });
  });

  afterEach(() => {
    useAuthStore.setState({ userRole: null });
  });

  it('asks before re-reading, then posts for the active project and reports the outcome', async () => {
    routeApi();
    (apiPost as any).mockResolvedValue({
      sheets_checked: 2,
      sheets_updated: 1,
      fields_updated: 3,
      files_missing: 1,
      current_conflicts: ['sheet-1'],
    });
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Re-read title blocks/ }));
    // Nothing is sent until the confirmation is accepted.
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Fields you corrected by hand are not changed');
    expect(apiPost).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Re-read' }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith(
        '/v1/documents/sheets/reread-title-blocks/?project_id=proj-1',
      ),
    );
    expect(await screen.findByText(/Sheets updated: 1 of 2\./)).toBeInTheDocument();
    // The plural form depends on whether the test i18n loaded en.ts, the reason does not.
    expect(screen.getByRole('status')).toHaveTextContent(/PDF could not be read/);
    // A current state set by hand that the revisions contradict is kept and named, not resolved.
    expect(screen.getByRole('alert')).toHaveTextContent(/set by hand/);
  });

  it('sends nothing when the confirmation is cancelled', async () => {
    routeApi();
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Re-read title blocks/ }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('is not offered to a viewer', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    routeApi();
    renderPage();

    expect(await screen.findByText('A-101')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Re-read title blocks/ })).not.toBeInTheDocument();
  });
});
