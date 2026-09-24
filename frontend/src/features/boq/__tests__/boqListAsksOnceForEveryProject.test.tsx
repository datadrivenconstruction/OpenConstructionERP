// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The bill register used to ask `GET /boqs/?project_id=` once per project. The
// browser runs six requests to a host at a time, so on a workspace of forty
// projects most of the page's wait was queueing. It now asks once, for every
// project, and this pins that it does.
//
// The old page also caught each project's failure and listed the rest, so a
// project archived or unshared under the reader's feet vanished from the list
// and from every total above it, with nothing on screen to say so. The batched
// call now leaves such a project out of its answer, and the page names it
// above the totals, with a Refresh that clears the notice once the project
// list no longer carries it. An id that names no project at all still refuses
// the whole request; what is pinned for that case is what the reader sees:
// the names, no estimates, no count and no totals, and a Retry that recovers
// once the project list no longer carries the project.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: (url: string) => api.get(url),
    apiPost: (url: string, body: unknown) => api.post(url, body),
  };
});

vi.mock('@/modules/collaboration/components/PresenceAvatars', () => ({
  PresenceAvatars: () => null,
}));

vi.mock('../CreateBOQPage', () => ({
  CreateBOQModal: () => null,
}));

import { BOQListPage } from '../BOQListPage';
import { ApiError } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const BATCH_URL = '/v1/boq/boqs/by-projects/';

const ALPHA = { id: 'proj-a', name: 'Alpha Tower', currency: 'EUR', classification_standard: 'din276' };
const BRAVO = { id: 'proj-b', name: 'Bravo Bridge', currency: 'EUR', classification_standard: 'din276' };
const CHARLIE = { id: 'proj-c', name: 'Charlie Centre', currency: 'EUR', classification_standard: 'din276' };

const BILLS: Record<string, string[]> = {
  'proj-a': ['Alpha shell and core'],
  'proj-b': ['Bravo deck works', 'Bravo abutments'],
  'proj-c': ['Charlie fit out'],
};

function rows(projectId: string) {
  return (BILLS[projectId] ?? []).map((name, i) => ({
    id: `${projectId}-boq-${i}`,
    project_id: projectId,
    name,
    description: '',
    status: 'draft',
    created_at: `2026-0${i + 1}-01T00:00:00Z`,
    updated_at: `2026-0${i + 1}-01T00:00:00Z`,
    direct_cost_total: '1000.00',
    markups_total: '0.00',
    grand_total: '1000.00',
    position_count: 10,
  }));
}

/** The register the server answers for the ids it was asked about. */
function register(body: { project_ids: string[] }) {
  return Object.fromEntries(body.project_ids.map((id) => [id, rows(id)]));
}

/** The server's refusal when one project in the batch is gone. */
function refusal(missing: string) {
  return new ApiError(404, 'Not Found', {
    detail: {
      error: 'projects_not_found',
      message: `Project not found: ${missing}.`,
      project_ids: [missing],
      not_found: [missing],
      forbidden: [],
    },
  });
}

let projects = [ALPHA, BRAVO, CHARLIE];

beforeEach(() => {
  localStorage.clear();
  useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
  projects = [ALPHA, BRAVO, CHARLIE];
  api.get.mockImplementation((url: string) => {
    if (url.startsWith('/v1/projects/')) return Promise.resolve(projects);
    if (url === '/v1/documents/file-types-by-project/') return Promise.resolve({});
    return Promise.resolve([]);
  });
  api.post.mockImplementation((url: string, body: { project_ids: string[] }) => {
    if (url === BATCH_URL) return Promise.resolve(register(body));
    return Promise.resolve({});
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mountList() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BOQListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function billRequests(): string[] {
  return api.get.mock.calls.map(([url]) => url as string).filter((url) => url.includes('/boq/boqs/'));
}

describe('BOQListPage asks for every project\'s bills in one request', () => {
  it('sends one batched request naming every project, and no request per project', async () => {
    mountList();
    await waitFor(() => expect(screen.getByText('Charlie fit out')).toBeTruthy());

    const batches = api.post.mock.calls.filter(([url]) => url === BATCH_URL);
    expect(batches).toHaveLength(1);
    expect((batches[0]![1] as { project_ids: string[] }).project_ids).toEqual(['proj-a', 'proj-b', 'proj-c']);
    expect(billRequests()).toEqual([]);

    for (const name of Object.values(BILLS).flat()) {
      expect(screen.getByText(name)).toBeTruthy();
    }
    expect(screen.getByText('4 estimates across 3 projects')).toBeTruthy();
  });

  it('lists the rest and names a project the answer left out, above the totals', async () => {
    // Bravo was archived after the project list loaded: the server answers
    // for the other two and leaves Bravo out of the register.
    api.post.mockImplementation((url: string, body: { project_ids: string[] }) => {
      if (url !== BATCH_URL) return Promise.resolve({});
      return Promise.resolve(register({ project_ids: body.project_ids.filter((id) => id !== 'proj-b') }));
    });
    mountList();

    await waitFor(() => expect(screen.getByText('Charlie fit out')).toBeTruthy());
    expect(screen.getByText('Alpha shell and core')).toBeTruthy();
    expect(screen.queryByText('Bravo deck works')).toBeNull();
    const notice = screen.getByRole('status');
    expect(notice.textContent).toMatch(/Not included: Bravo Bridge\./);
    // The count covers what is listed, not what was asked for.
    expect(screen.getByText('2 estimates across 2 projects')).toBeTruthy();
    expect(screen.queryByText('Estimates could not be loaded')).toBeNull();

    // A project with no bills is a key with an empty list, not a skipped one.
    expect(notice.textContent).not.toMatch(/Alpha Tower|Charlie Centre/);

    projects = [ALPHA, CHARLIE];
    fireEvent.click(screen.getByRole('button', { name: /Refresh/ }));
    // Charlie is on screen before the refresh too, so wait for both at once.
    await waitFor(() => {
      expect(screen.queryByText(/Not included:/)).toBeNull();
      expect(screen.getByText('Charlie fit out')).toBeTruthy();
    });
    expect(screen.getByText('2 estimates across 2 projects')).toBeTruthy();
  });

  it('shows no notice when a project answers with no bills', async () => {
    projects = [ALPHA, BRAVO, CHARLIE, { ...ALPHA, id: 'proj-empty', name: 'Empty Yard' }];
    mountList();
    await waitFor(() => expect(screen.getByText('Charlie fit out')).toBeTruthy());
    expect(screen.queryByText(/Not included:/)).toBeNull();
    expect(screen.getByText('4 estimates across 4 projects')).toBeTruthy();
  });

  it('names the project it could not read and lists nothing, rather than a short list', async () => {
    api.post.mockImplementation(() => Promise.reject(refusal('proj-b')));
    mountList();

    await waitFor(() => expect(screen.getByText('Estimates could not be loaded')).toBeTruthy());
    expect(screen.getByText(/These projects could not be read: Bravo Bridge\./)).toBeTruthy();

    // Not one estimate, not the empty state, and no count that could be read
    // as the size of the register.
    for (const name of Object.values(BILLS).flat()) {
      expect(screen.queryByText(name)).toBeNull();
    }
    expect(screen.queryByText('No BOQs yet')).toBeNull();
    expect(screen.queryByText(/estimates across/)).toBeNull();
  });

  it('recovers on Retry once the project list no longer carries the project', async () => {
    // Bravo is gone on the server, so any batch that names it is refused.
    api.post.mockImplementation((url: string, body: { project_ids: string[] }) => {
      if (url !== BATCH_URL) return Promise.resolve({});
      if (body.project_ids.includes('proj-b')) return Promise.reject(refusal('proj-b'));
      return Promise.resolve(register(body));
    });
    mountList();
    await waitFor(() => expect(screen.getByText('Estimates could not be loaded')).toBeTruthy());

    // Bravo was archived while the page was open: the next project list
    // leaves it out, and the bills are asked for under the new set.
    projects = [ALPHA, CHARLIE];
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }));

    await waitFor(() => expect(screen.getByText('Charlie fit out')).toBeTruthy());
    expect(screen.getByText('Alpha shell and core')).toBeTruthy();
    expect(screen.queryByText('Estimates could not be loaded')).toBeNull();
    expect(screen.getByText('2 estimates across 2 projects')).toBeTruthy();
    const last = api.post.mock.calls.filter(([url]) => url === BATCH_URL).at(-1);
    expect((last![1] as { project_ids: string[] }).project_ids).toEqual(['proj-a', 'proj-c']);
  });
});
