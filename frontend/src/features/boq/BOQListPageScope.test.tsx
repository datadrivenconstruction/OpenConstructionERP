// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for the project scope of <BOQListPage />.
//
// The page is mounted by two routes, /boq and /projects/:projectId/boq, and it
// keeps a persisted filter store (`oe_boq_filters`) for the choices a user
// makes in the toolbar. A scope the route pins, or the project that happens to
// be active in the top bar, is not such a choice, and must not end up in that
// store or outlive the page that imposed it.
//
// Every case below is a SEQUENCE of two mounts, because that is the shape of
// the defect: one visit proves nothing, it takes visiting one project and then
// going somewhere the first project no longer applies. Asserting the shape of
// the filter store alone would pass against the broken code, so the assertions
// are on what the list actually renders.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

/* ── Route params ─────────────────────────────────────────────────────
   The global setup mocks react-router-dom with a fixed empty `useParams`.
   Override it here with a mutable holder so a test can move between
   /projects/:projectId/boq and /boq the way navigation does. */

const routerState = vi.hoisted(() => ({ params: {} as { projectId?: string } }));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => routerState.params,
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

/* ── API ──────────────────────────────────────────────────────────────
   Only `apiGet` is replaced; the rest of the module stays real so the
   feature-local `./api` keeps its imports. */

const api = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: (url: string) => api.get(url) };
});

/* ── Inner components that carry their own data or canvas ─────────── */

vi.mock('@/modules/collaboration/components/PresenceAvatars', () => ({
  PresenceAvatars: () => null,
}));

vi.mock('./CreateBOQPage', () => ({
  CreateBOQModal: () => null,
}));

import { BOQListPage } from './BOQListPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/* ── Fixture: three projects, four estimates ──────────────────────── */

const PROJECTS = [
  { id: 'proj-a', name: 'Alpha Tower', currency: 'EUR', classification_standard: 'din276' },
  { id: 'proj-b', name: 'Bravo Bridge', currency: 'EUR', classification_standard: 'din276' },
  { id: 'proj-c', name: 'Charlie Centre', currency: 'EUR', classification_standard: 'din276' },
];

const BOQS: Record<string, { id: string; name: string }[]> = {
  'proj-a': [{ id: 'boq-a1', name: 'Alpha shell and core' }],
  'proj-b': [
    { id: 'boq-b1', name: 'Bravo deck works' },
    { id: 'boq-b2', name: 'Bravo abutments' },
  ],
  'proj-c': [{ id: 'boq-c1', name: 'Charlie fit out' }],
};

const TOTAL_BOQS = Object.values(BOQS).reduce((n, list) => n + list.length, 0);

function boqPayload(projectId: string) {
  return (BOQS[projectId] ?? []).map((b, i) => ({
    id: b.id,
    project_id: projectId,
    name: b.name,
    description: '',
    status: 'draft',
    created_at: `2026-0${i + 1}-01T00:00:00Z`,
    position_count: 10,
    grand_total: '1000.00',
  }));
}

beforeEach(() => {
  localStorage.clear();
  routerState.params = {};
  useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
  api.get.mockImplementation((url: string) => {
    if (url === '/v1/projects/') return Promise.resolve(PROJECTS);
    if (url === '/v1/documents/file-types-by-project/') return Promise.resolve({});
    const match = /\/v1\/boq\/boqs\/\?project_id=(.+)$/.exec(url);
    if (match) return Promise.resolve(boqPayload(match[1]!));
    return Promise.resolve([]);
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/* ── Helpers ──────────────────────────────────────────────────────── */

function mountList(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BOQListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
}

/** Estimate names currently on screen, in no particular order. */
function visibleEstimates(): string[] {
  return Object.values(BOQS)
    .flat()
    .filter((b) => screen.queryByText(b.name) !== null)
    .map((b) => b.name);
}

/** The "1–4 of 4 estimates" footer, which is the table's own denominator. */
function footerText(): string {
  const el = screen.getByText(/of \d+ estimates/);
  return el.textContent ?? '';
}

/* ── The two sequences ────────────────────────────────────────────── */

describe('BOQListPage project scope', () => {
  it('shows every estimate on /boq after a visit to one project\'s estimates', async () => {
    // Carrier under test is the persisted store alone: no project is active,
    // so anything that survives the first mount got there by being written.
    const client = newClient();

    routerState.params = { projectId: 'proj-a' };
    const scoped = mountList(client);
    await waitFor(() => expect(screen.getByText('Alpha shell and core')).toBeTruthy());
    scoped.unmount();

    routerState.params = {};
    mountList(client);
    await waitFor(() => expect(screen.getByText('Charlie fit out')).toBeTruthy());

    expect(visibleEstimates().sort()).toEqual(
      Object.values(BOQS).flat().map((b) => b.name).sort(),
    );
    expect(footerText()).toContain(`of ${TOTAL_BOQS} estimates`);
    expect(footerText()).not.toContain('filtered from');
  });

  it('lists the estimates of the project in the URL after another project was opened first', async () => {
    // Carrier under test is the active-project context that opening a project
    // leaves behind. The route pins Bravo; nothing about Alpha may reach it.
    const client = newClient();

    useProjectContextStore.setState({ activeProjectId: 'proj-a', activeProjectName: 'Alpha Tower' });
    routerState.params = { projectId: 'proj-a' };
    const first = mountList(client);
    await waitFor(() => expect(screen.getByText('Alpha shell and core')).toBeTruthy());
    first.unmount();

    routerState.params = { projectId: 'proj-b' };
    mountList(client);

    await waitFor(() => expect(screen.getByText('Bravo deck works')).toBeTruthy());
    expect(screen.getByText('Bravo abutments')).toBeTruthy();
    expect(screen.queryByText('No matching estimates')).toBeNull();
    // The dropdown must never offer Alpha as the value of a Bravo page.
    expect(screen.queryByDisplayValue('Alpha Tower')).toBeNull();
  });

  /* ── The invariant behind both ──────────────────────────────────── */

  it('never counts more estimates in the header than the table can show', async () => {
    // The visible symptom was a header reading "4 estimates across 3 projects"
    // over a table reading "1-1 of 1 (filtered from 4)". With no filter the
    // user chose, those two numbers are the same number.
    const client = newClient();

    routerState.params = { projectId: 'proj-a' };
    const scoped = mountList(client);
    await waitFor(() => expect(screen.getByText('Alpha shell and core')).toBeTruthy());
    scoped.unmount();

    routerState.params = {};
    mountList(client);
    await waitFor(() => expect(screen.getByText('Charlie fit out')).toBeTruthy());

    const header = screen.getByText(/estimates across \d+ projects/).textContent ?? '';
    const headerCount = Number(/(\d+) estimates across/.exec(header)?.[1]);
    const tableTotal = Number(/of (\d+) estimates/.exec(footerText())?.[1]);
    expect(headerCount).toBe(tableTotal);
  });

  /* ── The write site itself ──────────────────────────────────────── */

  it('does not write a route-imposed project into the persisted filter store', async () => {
    routerState.params = { projectId: 'proj-a' };
    mountList(newClient());
    await waitFor(() => expect(screen.getByText('Alpha shell and core')).toBeTruthy());

    const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
    expect(saved.project ?? '').toBe('');
  });

  it('does not write the active project into the persisted filter store', async () => {
    useProjectContextStore.setState({ activeProjectId: 'proj-a', activeProjectName: 'Alpha Tower' });
    mountList(newClient());
    await waitFor(() => expect(screen.getByText('Charlie fit out')).toBeTruthy());

    const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
    expect(saved.project ?? '').toBe('');
  });
});
